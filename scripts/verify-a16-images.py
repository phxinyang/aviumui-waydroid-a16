#!/usr/bin/env python3
"""Verify A16 source provenance and a paired system/vendor image build."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import subprocess
import sys
import tempfile
from typing import Any


SHA40 = set("0123456789abcdefABCDEF")
REQUIRED_LOCK = {"schema_version", "manifest_repository_head", "local_manifests", "projects"}
REQUIRED_SERIES = {"schema_version", "projects", "skips"}
REQUIRED_WINDOW_SERIES = {"schema_version", "projects"}


class ConfigError(ValueError):
    pass


class VerifyError(RuntimeError):
    pass


def path_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if "\x00" in value or path.is_absolute() or PureWindowsPath(value).is_absolute():
        raise ConfigError(f"{field} must be a relative path")
    if ".." in path.parts:
        raise ConfigError(f"{field} must not contain '..'")
    normalized = path.as_posix()
    if normalized in ("", "."):
        raise ConfigError(f"{field} must name a path")
    return normalized


def object_json(path: Path, label: str, *, reject_duplicates: bool = False) -> dict[str, Any]:
    def pairs(value: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value:
            if reject_duplicates and key in result:
                raise ConfigError(f"{label} JSON contains duplicate field: {key}")
            result[key] = item
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=pairs if reject_duplicates else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {label} JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{label} JSON must contain an object")
    return value


def validate_lock(value: dict[str, Any]) -> dict[str, Any]:
    if not REQUIRED_LOCK <= set(value):
        raise ConfigError("lock is missing required fields")
    if value["schema_version"] != 1:
        raise ConfigError("lock schema_version must be 1")
    if (
        not isinstance(value["manifest_repository_head"], str)
        or len(value["manifest_repository_head"]) != 40
        or not all(c in SHA40 for c in value["manifest_repository_head"])
    ):
        raise ConfigError("lock manifest_repository_head must be a 40-digit Git object ID")
    local = value["local_manifests"]
    if not isinstance(local, dict):
        raise ConfigError("lock local_manifests must be an object")
    local_normalized: dict[str, str] = {}
    for raw_path, digest in local.items():
        path = path_value(raw_path, "lock local_manifests path")
        if not isinstance(digest, str) or len(digest) != 64 or not all(c in SHA40 for c in digest):
            raise ConfigError(f"lock local manifest hash is invalid: {raw_path}")
        if path in local_normalized:
            raise ConfigError(f"duplicate lock local manifest path: {path}")
        local_normalized[path] = digest.lower()
    projects = value["projects"]
    if not isinstance(projects, list):
        raise ConfigError("lock projects must be an array")
    project_paths: set[str] = set()
    normalized_projects: list[dict[str, str]] = []
    for index, project in enumerate(projects):
        if not isinstance(project, dict) or "path" not in project or "base_head" not in project:
            raise ConfigError(f"lock projects[{index}] is invalid")
        path = path_value(project["path"], f"lock projects[{index}].path")
        base = project["base_head"]
        if not isinstance(base, str) or len(base) != 40 or not all(c in SHA40 for c in base):
            raise ConfigError(f"lock projects[{index}].base_head is invalid")
        if path in project_paths:
            raise ConfigError(f"duplicate lock project path: {path}")
        project_paths.add(path)
        normalized_projects.append({"path": path, "base_head": base.lower()})
    return {
        "schema_version": 1,
        "manifest_repository_head": value["manifest_repository_head"].lower(),
        "local_manifests": local_normalized,
        "projects": normalized_projects,
    }


def validate_series(value: dict[str, Any]) -> dict[str, Any]:
    if not REQUIRED_SERIES <= set(value):
        raise ConfigError("series is missing required fields")
    if value["schema_version"] != 1 or not isinstance(value["projects"], list):
        raise ConfigError("series schema_version or projects is invalid")
    if not isinstance(value["skips"], list):
        raise ConfigError("series skips must be an array")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, project in enumerate(value["projects"]):
        if not isinstance(project, dict) or not {
            "path",
            "base_head",
            "expected_tree",
            "patches",
        } <= set(project):
            raise ConfigError(f"series projects[{index}] is invalid")
        path = path_value(project["path"], f"series projects[{index}].path")
        base = project["base_head"]
        tree = project["expected_tree"]
        for field, value_to_check in (("base_head", base), ("expected_tree", tree)):
            if (
                not isinstance(value_to_check, str)
                or len(value_to_check) != 40
                or not all(c in SHA40 for c in value_to_check)
            ):
                raise ConfigError(f"series projects[{index}].{field} is invalid")
        if not isinstance(project["patches"], list):
            raise ConfigError(f"series projects[{index}].patches is invalid")
        if path in seen:
            raise ConfigError(f"duplicate series project path: {path}")
        seen.add(path)
        normalized.append(
            {
                "path": path,
                "base_head": base.lower(),
                "expected_tree": tree.lower(),
            }
        )
    return {"schema_version": 1, "projects": normalized, "skips": value["skips"]}


def validate_window_series(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != REQUIRED_WINDOW_SERIES:
        raise ConfigError("window series must contain exactly schema_version and projects")
    if (
        not isinstance(value["schema_version"], int)
        or isinstance(value["schema_version"], bool)
        or value["schema_version"] != 1
    ):
        raise ConfigError("window series schema_version must be 1")
    projects = value["projects"]
    if not isinstance(projects, list) or not projects:
        raise ConfigError("window series projects must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen_projects: set[str] = set()
    seen_patches: set[str] = set()
    for index, project in enumerate(projects):
        if not isinstance(project, dict) or set(project) != {
            "path",
            "base_tree",
            "expected_tree",
            "patches",
        }:
            raise ConfigError(f"window series projects[{index}] has an invalid schema")
        path = path_value(project["path"], f"window series projects[{index}].path")
        if path in seen_projects:
            raise ConfigError(f"duplicate window series project path: {path}")
        seen_projects.add(path)
        trees: dict[str, str] = {}
        for field in ("base_tree", "expected_tree"):
            tree = project[field]
            if (
                isinstance(tree, bool)
                or not isinstance(tree, str)
                or len(tree) != 40
                or not all(c in SHA40 for c in tree)
            ):
                raise ConfigError(f"window series projects[{index}].{field} is invalid")
            trees[field] = tree.lower()
        if trees["base_tree"] == trees["expected_tree"]:
            raise ConfigError(
                f"window series projects[{index}] has identical base and expected tree"
            )
        patches = project["patches"]
        if not isinstance(patches, list) or not patches:
            raise ConfigError(f"window series projects[{index}].patches must be a non-empty array")
        normalized_patches: list[dict[str, str]] = []
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, dict) or set(patch) != {"path", "sha256"}:
                raise ConfigError(
                    f"window series projects[{index}].patches[{patch_index}] has an invalid schema"
                )
            patch_path = path_value(
                patch["path"],
                f"window series projects[{index}].patches[{patch_index}].path",
            )
            if patch_path in seen_patches:
                raise ConfigError(f"duplicate window patch path: {path}/{patch_path}")
            seen_patches.add(patch_path)
            digest = patch["sha256"]
            if (
                isinstance(digest, bool)
                or not isinstance(digest, str)
                or len(digest) != 64
                or not all(c in SHA40 for c in digest)
            ):
                raise ConfigError(
                    f"window series projects[{index}].patches[{patch_index}].sha256 is invalid"
                )
            normalized_patches.append({"path": patch_path, "sha256": digest.lower()})
        normalized.append(
            {
                "path": path,
                "base_tree": trees["base_tree"],
                "expected_tree": trees["expected_tree"],
                "patches": normalized_patches,
            }
        )
    return {"schema_version": 1, "projects": normalized}


def run_git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(project), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def git_value(project: Path, *args: str) -> str:
    result = run_git(project, *args)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VerifyError(detail or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _under_nested_git_repo(project: Path, relative: str) -> bool:
    parts = Path(relative).parts
    for index in range(1, len(parts) + 1):
        candidate = project.joinpath(*parts[:index])
        if candidate.is_dir() and (candidate / ".git").exists():
            return True
    return False


def git_status(project: Path) -> list[str]:
    raw = git_value(
        project,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    tokens = raw.split("\0")
    entries: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue
        status = token[:2]
        path = token[3:]
        if status.startswith("R"):
            index += 1
            if index < len(tokens):
                path = tokens[index]
        if status == "??" and _under_nested_git_repo(project, path):
            index += 1
            continue
        entries.append(token)
        index += 1
    return entries


def resolve_inside(root: Path, relative: str, field: str, root_label: str = "AOSP_ROOT") -> Path:
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VerifyError(f"{field} escapes {root_label}: {relative}") from exc
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_image_digest(path: Path, label: str) -> tuple[str, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerifyError(f"{label} cannot be opened as a regular non-symlink file: {exc}") from exc
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size == 0:
            raise VerifyError(f"{label} is not a non-empty regular file")
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    try:
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise VerifyError(f"{label} changed while it was hashed: {exc}") from exc
    if identity(before) != identity(after) or identity(after) != identity(current):
        raise VerifyError(f"{label} changed while it was hashed")
    return digest.hexdigest(), after


def manifest_state(root: Path, lock: dict[str, Any]) -> tuple[str, dict[str, str]]:
    manifests = root / ".repo/manifests"
    if not manifests.is_dir() or manifests.is_symlink() or not (manifests / ".git").exists():
        raise VerifyError("manifest repository is missing or is not a Git checkout")
    head = git_value(manifests, "rev-parse", "HEAD")
    if head.lower() != lock["manifest_repository_head"].lower():
        raise VerifyError(
            f"manifest repository HEAD mismatch: expected {lock['manifest_repository_head']}, got {head}"
        )
    status = git_value(manifests, "status", "--porcelain=v1")
    if status:
        raise VerifyError(f"manifest repository is dirty: {status}")
    local_root = root / ".repo/local_manifests"
    actual: dict[str, str] = {}
    if local_root.exists():
        if local_root.is_symlink() or not local_root.is_dir():
            raise VerifyError("local_manifests is not a regular directory")
        for path in sorted(local_root.rglob("*")):
            mode = path.stat(follow_symlinks=False).st_mode
            relative = path.relative_to(local_root).as_posix()
            if not stat.S_ISREG(mode):
                raise VerifyError(f"local_manifests contains non-regular entry: {relative}")
            actual[relative] = sha256_file(path)
    if actual != lock["local_manifests"]:
        raise VerifyError("local_manifests set or hash does not match lock")
    return head, actual


def window_patch_state(
    patch_root: Path, window_series: dict[str, Any]
) -> list[dict[str, str]]:
    if patch_root.is_symlink() or not patch_root.is_dir():
        raise VerifyError("window patch root is missing, not a directory, or is a symlink")
    patches: list[dict[str, str]] = []
    for project in window_series["projects"]:
        project_path = project["path"]
        for patch in project["patches"]:
            relative = patch["path"]
            raw_path = patch_root
            for component in Path(relative).parts:
                raw_path /= component
                try:
                    mode = raw_path.lstat().st_mode
                except OSError as exc:
                    raise VerifyError(
                        f"cannot inspect window patch {relative}: {exc}"
                    ) from exc
                if stat.S_ISLNK(mode):
                    raise VerifyError(f"window patch is a symlink: {relative}")
            path = resolve_inside(patch_root, relative, "window patch", "window patch root")
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise VerifyError(f"window patch is missing or not a regular file: {relative}")
            actual = sha256_file(path)
            if actual != patch["sha256"]:
                raise VerifyError(f"window patch sha256 mismatch: {relative}")
            patches.append(
                {"project": project_path, "path": relative, "sha256": patch["sha256"]}
            )
    return sorted(patches, key=lambda item: (item["project"], item["path"]))


def source_state(
    root: Path,
    lock: dict[str, Any],
    series: dict[str, Any],
    window_series: dict[str, Any],
) -> list[dict[str, str]]:
    series_by_path = {project["path"]: project for project in series["projects"]}
    lock_by_path = {project["path"]: project for project in lock["projects"]}
    window_by_path = {project["path"]: project for project in window_series["projects"]}
    extra = sorted(set(series_by_path) - set(lock_by_path))
    if extra:
        raise VerifyError("series contains projects absent from lock: " + ", ".join(extra))
    extra_window = sorted(set(window_by_path) - set(lock_by_path))
    if extra_window:
        raise VerifyError("window series contains projects absent from lock: " + ", ".join(extra_window))
    mismatched_bases = sorted(
        path
        for path, project in series_by_path.items()
        if project["base_head"] != lock_by_path[path]["base_head"]
    )
    if mismatched_bases:
        raise VerifyError(
            "series base HEAD does not match input lock: " + ", ".join(mismatched_bases)
        )
    for path, project in window_by_path.items():
        if path in series_by_path:
            expected_base_tree = series_by_path[path]["expected_tree"]
        else:
            project_path = resolve_inside(root, path, "project")
            expected_base_tree = git_value(
                project_path, "rev-parse", f"{lock_by_path[path]['base_head']}^{{tree}}"
            )
        if project["base_tree"] != expected_base_tree.lower():
            raise VerifyError(f"window base tree mismatch: {path}")
    result: list[dict[str, str]] = []
    for project in lock["projects"]:
        path_value_string = project["path"]
        raw_project_path = root / path_value_string
        if raw_project_path.is_symlink():
            raise VerifyError(f"project path is a symlink: {path_value_string}")
        project_path = resolve_inside(root, path_value_string, "project")
        if project_path.is_symlink() or not project_path.is_dir() or not (project_path / ".git").exists():
            raise VerifyError(f"project is not a Git checkout: {path_value_string}")
        status = git_status(project_path)
        if status:
            raise VerifyError(f"project is dirty: {path_value_string}: {status}")
        head = git_value(project_path, "rev-parse", "HEAD")
        tree = git_value(project_path, "rev-parse", "HEAD^{tree}")
        if path_value_string in window_by_path:
            if tree.lower() != window_by_path[path_value_string]["expected_tree"]:
                raise VerifyError(f"window expected tree mismatch: {path_value_string}")
        elif path_value_string in series_by_path:
            if tree.lower() != series_by_path[path_value_string]["expected_tree"]:
                raise VerifyError(f"series expected tree mismatch: {path_value_string}")
        elif head.lower() != project["base_head"]:
            raise VerifyError(f"lock base HEAD mismatch: {path_value_string}")
        result.append({"path": path_value_string, "head": head, "tree": tree})
    return result


def image_state(root: Path, product: str) -> dict[str, dict[str, Any]]:
    product_path = path_value(product, "product")
    if "/" in product_path:
        raise ConfigError("product must be a single path component")
    output: dict[str, dict[str, Any]] = {}
    for name in ("system", "vendor"):
        relative = f"out/target/product/{product_path}/{name}.img"
        raw_path = root / relative
        if raw_path.is_symlink():
            raise VerifyError(f"{relative} is a symlink")
        path = resolve_inside(root, relative, f"{name}.img")
        if path.is_symlink() or not path.is_file():
            raise VerifyError(f"{relative} is missing or is a symlink")
        digest, stat_result = stable_image_digest(path, relative)
        output[name] = {
            "path": relative,
            "sha256": digest,
            "size": stat_result.st_size,
            "mtime_ns": stat_result.st_mtime_ns,
        }
    return output


def utc_value(value: str, field: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{field} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ConfigError(f"{field} must include UTC timezone")
    return value, parsed


def emit_atomic(output: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aosp_root", metavar="AOSP_ROOT")
    parser.add_argument("--lock", required=True, type=Path, metavar="LOCK_JSON")
    parser.add_argument("--series", required=True, type=Path, metavar="SERIES_JSON")
    parser.add_argument("--window-series", required=True, type=Path, metavar="WINDOW_SERIES_JSON")
    parser.add_argument("--window-patch-root", required=True, type=Path, metavar="WINDOW_PATCH_ROOT")
    parser.add_argument("--output", required=True, type=Path, metavar="OUTPUT_JSON")
    parser.add_argument("--build-command", required=True, metavar="TEXT")
    parser.add_argument("--started-at", required=True, metavar="UTC")
    parser.add_argument("--finished-at", required=True, metavar="UTC")
    parser.add_argument("--product", default="waydroid_arm64_only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        root = Path(args.aosp_root).expanduser().resolve(strict=False)
        output = args.output.expanduser().resolve(strict=False)
        out_root = (root / "out").resolve(strict=False)
        try:
            output.relative_to(out_root)
        except ValueError as exc:
            raise ConfigError("OUTPUT_JSON must be inside AOSP_ROOT/out") from exc
        if output.exists() and output.is_symlink():
            raise ConfigError("OUTPUT_JSON must not be a symlink")
        product_name = path_value(args.product, "product")
        if "/" in product_name:
            raise ConfigError("product must be a single path component")
        image_outputs = {
            (root / f"out/target/product/{product_name}/{name}.img").resolve(strict=False)
            for name in ("system", "vendor")
        }
        if output in image_outputs:
            raise ConfigError("OUTPUT_JSON must not replace system.img or vendor.img")
        if not isinstance(args.build_command, str) or not args.build_command:
            raise ConfigError("build command must be non-empty")
        started, started_datetime = utc_value(args.started_at, "started-at")
        finished, finished_datetime = utc_value(args.finished_at, "finished-at")
        if finished_datetime < started_datetime:
            raise ConfigError("finished-at must not be earlier than started-at")
        lock_path = args.lock.expanduser().resolve(strict=False)
        lock = validate_lock(object_json(lock_path, "lock"))
        lock_digest = sha256_file(lock_path)
        series_path = args.series.expanduser().resolve(strict=False)
        series = validate_series(object_json(series_path, "series"))
        series_digest = sha256_file(series_path)
        window_series_path = args.window_series.expanduser().resolve(strict=False)
        window_series = validate_window_series(
            object_json(window_series_path, "window series", reject_duplicates=True)
        )
        window_series_digest = sha256_file(window_series_path)
        window_patch_root_input = args.window_patch_root.expanduser()
        if window_patch_root_input.is_symlink():
            raise ConfigError("WINDOW_PATCH_ROOT must not be a symlink")
        window_patch_root = window_patch_root_input.resolve(strict=False)
        if not root.is_dir():
            raise VerifyError(f"AOSP_ROOT is not a directory: {root}")
        manifest_head, local_manifests = manifest_state(root, lock)
        window_patches = window_patch_state(window_patch_root, window_series)
        projects = source_state(root, lock, series, window_series)
        images = image_state(root, product_name)
        # build-context timestamps are second-precision; allow the image mtime
        # to land within that final second without accepting an older context.
        finished_ns = int(finished_datetime.timestamp() * 1_000_000_000) + 1_000_000_000
        for name, image in images.items():
            if image["mtime_ns"] > finished_ns:
                raise VerifyError(
                    f"{name}.img is newer than finished-at; build provenance is stale"
                )
        payload = {
            "schema_version": 1,
            "product": args.product,
            "build_command": args.build_command,
            "started_at": started,
            "finished_at": finished,
            "manifest": {"head": manifest_head},
            "local_manifests": local_manifests,
            "recipe_lock_sha256": lock_digest,
            "series_sha256": series_digest,
            "window_series_sha256": window_series_digest,
            "window_patches": window_patches,
            "source_projects": projects,
            "images": images,
        }
        emit_atomic(output, payload)
        return 0
    except ConfigError as exc:
        print(f"verify-a16-images: {exc}", file=sys.stderr)
        return 2
    except (VerifyError, OSError, UnicodeError) as exc:
        print(f"verify-a16-images: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
