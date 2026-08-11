#!/usr/bin/env python3
"""Run a read-only reproducibility preflight for an AOSP checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
from typing import Any


DEFAULT_PROCESS_PATTERNS = (
    r"(?:^|/)ninja$",
    r"(?:^|/)soong_ui$",
    r"(?:^|/)ckati$",
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
GIT_HEAD_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ALLOWED_LOCK_KEYS = {
    "schema_version",
    "manifest_repository_head",
    "local_manifests",
    "min_free_bytes",
    "min_free_bytes_with_out_base",
    "out_base_snapshot",
    "required_commands",
    "projects",
    "lfs_files",
    "process_patterns",
}
ALLOWED_SERIES_KEYS = {"schema_version", "projects", "skips"}
ALLOWED_WINDOW_SERIES_KEYS = {"schema_version", "projects"}
ALLOWED_WINDOW_PROJECT_KEYS = {"path", "base_tree", "expected_tree", "patches"}
ALLOWED_WINDOW_PATCH_KEYS = {"path", "sha256"}


class ConfigError(ValueError):
    """The lock or command-line configuration is invalid."""


class CheckError(RuntimeError):
    """An internal check could not be completed."""


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if "\x00" in value:
        raise ConfigError(f"{field} contains NUL")
    if path.is_absolute() or PureWindowsPath(value).is_absolute():
        raise ConfigError(f"{field} must be relative: {value!r}")
    if ".." in path.parts:
        raise ConfigError(f"{field} must not contain '..': {value!r}")
    normalized = path.as_posix()
    if normalized in ("", "."):
        raise ConfigError(f"{field} must name a file or project: {value!r}")
    return normalized


def validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ConfigError(f"{field} must be a 64-digit SHA-256 value")
    return value.lower()


def validate_git_head(value: Any, field: str) -> str:
    if not isinstance(value, str) or not GIT_HEAD_RE.fullmatch(value):
        raise ConfigError(f"{field} must be a 40-digit Git object ID")
    return value.lower()


def load_lock(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read lock JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("lock JSON must contain an object")
    unknown = sorted(set(value) - ALLOWED_LOCK_KEYS)
    if unknown:
        raise ConfigError(f"unknown lock fields: {', '.join(unknown)}")
    required = {
        "schema_version",
        "manifest_repository_head",
        "local_manifests",
        "min_free_bytes",
        "required_commands",
        "projects",
        "lfs_files",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ConfigError(f"missing lock fields: {', '.join(missing)}")
    if value["schema_version"] != 1:
        raise ConfigError("lock schema_version must be 1")
    manifest_repository_head = validate_git_head(
        value["manifest_repository_head"], "manifest_repository_head"
    )
    if not is_integer(value["min_free_bytes"]) or value["min_free_bytes"] < 0:
        raise ConfigError("min_free_bytes must be a non-negative integer")
    if "min_free_bytes_with_out_base" in value:
        with_base = value["min_free_bytes_with_out_base"]
        if not is_integer(with_base) or with_base < 0:
            raise ConfigError("min_free_bytes_with_out_base must be a non-negative integer")
        if with_base > value["min_free_bytes"]:
            raise ConfigError(
                "min_free_bytes_with_out_base must not exceed min_free_bytes"
            )
    if "out_base_snapshot" in value:
        snapshot = value["out_base_snapshot"]
        if not is_integer(snapshot) or snapshot <= 0:
            raise ConfigError("out_base_snapshot must be a positive integer")

    local_manifests = value["local_manifests"]
    if not isinstance(local_manifests, dict):
        raise ConfigError("local_manifests must be an object mapping paths to hashes")
    normalized_manifests: dict[str, str] = {}
    for raw_path, digest in local_manifests.items():
        path = relative_path(raw_path, "local_manifests path")
        if path in normalized_manifests:
            raise ConfigError(f"duplicate local_manifests path after normalization: {path}")
        normalized_manifests[path] = validate_sha256(
            digest, f"local_manifests[{raw_path!r}]"
        )

    commands = value["required_commands"]
    if not isinstance(commands, list) or any(
        not isinstance(command, str) or not command for command in commands
    ):
        raise ConfigError("required_commands must be an array of non-empty strings")
    if len(set(commands)) != len(commands):
        raise ConfigError("required_commands must not contain duplicates")

    projects = value["projects"]
    if not isinstance(projects, list):
        raise ConfigError("projects must be an array")
    normalized_projects: list[dict[str, str]] = []
    project_paths: set[str] = set()
    for index, project in enumerate(projects):
        if not isinstance(project, dict) or set(project) != {"path", "base_head"}:
            raise ConfigError(f"projects[{index}] must contain only path and base_head")
        path = relative_path(project["path"], f"projects[{index}].path")
        if path in project_paths:
            raise ConfigError(f"duplicate project path: {path}")
        project_paths.add(path)
        normalized_projects.append(
            {
                "path": path,
                "base_head": validate_git_head(
                    project["base_head"], f"projects[{index}].base_head"
                ),
            }
        )

    lfs_files = value["lfs_files"]
    if not isinstance(lfs_files, list):
        raise ConfigError("lfs_files must be an array")
    normalized_lfs: list[dict[str, Any]] = []
    lfs_paths: set[str] = set()
    for index, item in enumerate(lfs_files):
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise ConfigError(f"lfs_files[{index}] must contain path, sha256 and size")
        path = relative_path(item["path"], f"lfs_files[{index}].path")
        if path in lfs_paths:
            raise ConfigError(f"duplicate LFS path: {path}")
        if not is_integer(item["size"]) or item["size"] < 0:
            raise ConfigError(f"lfs_files[{index}].size must be a non-negative integer")
        lfs_paths.add(path)
        normalized_lfs.append(
            {
                "path": path,
                "sha256": validate_sha256(item["sha256"], f"lfs_files[{index}].sha256"),
                "size": item["size"],
            }
        )

    patterns = value.get("process_patterns")
    if patterns is not None:
        if not isinstance(patterns, list) or any(
            not isinstance(pattern, str) or not pattern for pattern in patterns
        ):
            raise ConfigError("process_patterns must be an array of non-empty strings")
        if not patterns:
            raise ConfigError("process_patterns must not be empty")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"invalid process pattern {pattern!r}: {exc}") from exc
        normalized_patterns = list(patterns)
    else:
        normalized_patterns = list(DEFAULT_PROCESS_PATTERNS)

    return {
        "schema_version": 1,
        "manifest_repository_head": manifest_repository_head,
        "local_manifests": normalized_manifests,
        "min_free_bytes": value["min_free_bytes"],
        "min_free_bytes_with_out_base": value.get("min_free_bytes_with_out_base"),
        "out_base_snapshot": value.get("out_base_snapshot"),
        "required_commands": list(commands),
        "projects": normalized_projects,
        "lfs_files": normalized_lfs,
        "process_patterns": normalized_patterns,
    }


def load_prepared_trees(path: Path, lock: dict[str, Any]) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read series JSON {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != ALLOWED_SERIES_KEYS:
        raise ConfigError("series JSON must contain only schema_version, projects and skips")
    if value["schema_version"] != 1 or not isinstance(value["projects"], list):
        raise ConfigError("series schema_version/projects are invalid")
    lock_paths = {project["path"] for project in lock["projects"]}
    prepared: dict[str, str] = {}
    for index, project in enumerate(value["projects"]):
        if not isinstance(project, dict):
            raise ConfigError(f"series projects[{index}] must be an object")
        if "path" not in project or "expected_tree" not in project:
            raise ConfigError(
                f"series projects[{index}] must contain path and expected_tree"
            )
        project_path = relative_path(project["path"], f"series projects[{index}].path")
        if project_path not in lock_paths:
            raise ConfigError(f"series project is absent from input lock: {project_path}")
        if project_path in prepared:
            raise ConfigError(f"duplicate series project path: {project_path}")
        prepared[project_path] = validate_git_head(
            project["expected_tree"], f"series projects[{index}].expected_tree"
        )
    return prepared


def load_window_series(path: Path, lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ConfigError(f"duplicate JSON field: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read window series JSON {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != ALLOWED_WINDOW_SERIES_KEYS:
        raise ConfigError(
            "window series JSON must contain only schema_version and projects"
        )
    if (
        not is_integer(value["schema_version"])
        or value["schema_version"] != 1
        or not isinstance(value["projects"], list)
    ):
        raise ConfigError(
            "window series schema_version must be 1 and projects must be an array"
        )
    if not value["projects"]:
        raise ConfigError("window series projects must not be empty")

    lock_paths = {project["path"] for project in lock["projects"]}
    projects: dict[str, dict[str, Any]] = {}
    patch_paths: set[str] = set()
    for index, project in enumerate(value["projects"]):
        if not isinstance(project, dict) or set(project) != ALLOWED_WINDOW_PROJECT_KEYS:
            raise ConfigError(
                "window series projects[{}] must contain path, base_tree, "
                "expected_tree and patches".format(index)
            )
        project_path = relative_path(
            project["path"], f"window series projects[{index}].path"
        )
        if project_path not in lock_paths:
            raise ConfigError(
                f"window series project is absent from input lock: {project_path}"
            )
        if project_path in projects:
            raise ConfigError(f"duplicate window series project path: {project_path}")
        patches = project["patches"]
        if not isinstance(patches, list) or not patches:
            raise ConfigError(
                f"window series projects[{index}].patches must be a non-empty array"
            )
        normalized_patches: list[dict[str, str]] = []
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, dict) or set(patch) != ALLOWED_WINDOW_PATCH_KEYS:
                raise ConfigError(
                    "window series projects[{}].patches[{}] must contain "
                    "path and sha256".format(index, patch_index)
                )
            patch_path = relative_path(
                patch["path"],
                f"window series projects[{index}].patches[{patch_index}].path",
            )
            if patch_path in patch_paths:
                raise ConfigError(f"duplicate window series patch path: {patch_path}")
            patch_paths.add(patch_path)
            normalized_patches.append(
                {
                    "path": patch_path,
                    "sha256": validate_sha256(
                        patch["sha256"],
                        f"window series projects[{index}].patches[{patch_index}].sha256",
                    ),
                }
            )
        projects[project_path] = {
            "path": project_path,
            "base_tree": validate_git_head(
                project["base_tree"], f"window series projects[{index}].base_tree"
            ),
            "expected_tree": validate_git_head(
                project["expected_tree"],
                f"window series projects[{index}].expected_tree",
            ),
            "patches": normalized_patches,
        }
        if projects[project_path]["base_tree"] == projects[project_path]["expected_tree"]:
            raise ConfigError(
                f"window series project has identical base and expected tree: {project_path}"
            )
    return projects


def run_git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(project), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def git_head(project: Path) -> str:
    result = run_git(project, "rev-parse", "HEAD")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckError(detail or "git rev-parse failed")
    return result.stdout.strip()


def git_value(project: Path, *arguments: str) -> str:
    result = run_git(project, *arguments)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _under_nested_git_repo(project: Path, relative: str) -> bool:
    parts = Path(relative).parts
    for index in range(1, len(parts) + 1):
        candidate = project.joinpath(*parts[:index])
        if candidate.is_dir() and (candidate / ".git").exists():
            return True
    return False


def git_status(project: Path) -> list[str]:
    result = run_git(
        project,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckError(detail or "git status failed")
    tokens = result.stdout.split("\0")
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


def resolve_inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CheckError(f"path escapes AOSP_ROOT: {relative}") from exc
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_manifest_files(directory: Path) -> tuple[dict[str, str], list[str]]:
    if not directory.exists():
        return {}, []
    if not directory.is_dir() or directory.is_symlink():
        return {}, ["local_manifests is not a regular directory"]
    files: dict[str, str] = {}
    special: list[str] = []
    for path in sorted(directory.rglob("*")):
        mode = path.stat(follow_symlinks=False).st_mode
        relative = path.relative_to(directory).as_posix()
        if stat.S_ISREG(mode):
            files[relative] = sha256_file(path)
        else:
            special.append(relative)
    return files, special


def check_manifest(root: Path, lock: dict[str, Any], errors: list[str]) -> bool:
    manifests = root / ".repo/manifests"
    if not manifests.is_dir() or manifests.is_symlink() or not (manifests / ".git").exists():
        errors.append("manifest repository is missing or is not a Git checkout")
        return False
    try:
        actual = git_head(manifests)
    except CheckError as exc:
        errors.append(f"manifest repository HEAD: {exc}")
        return False
    if actual != lock["manifest_repository_head"]:
        errors.append(
            "manifest repository HEAD mismatch: "
            f"expected {lock['manifest_repository_head']}, got {actual}"
        )
        return False
    try:
        status = git_status(manifests)
    except CheckError as exc:
        errors.append(f"manifest repository status: {exc}")
        return False
    if status:
        errors.append("manifest repository is dirty: " + "; ".join(status))
        return False
    return True


def check_local_manifests(root: Path, lock: dict[str, Any], errors: list[str]) -> bool:
    actual, special = local_manifest_files(root / ".repo/local_manifests")
    if special:
        errors.append("local_manifests contains non-regular entries: " + ", ".join(special))
    expected = lock["local_manifests"]
    if actual != expected:
        expected_paths = set(expected)
        actual_paths = set(actual)
        for path in sorted(expected_paths - actual_paths):
            errors.append(f"missing local manifest: {path}")
        for path in sorted(actual_paths - expected_paths):
            errors.append(f"unexpected local manifest: {path}")
        for path in sorted(expected_paths & actual_paths):
            if actual[path] != expected[path]:
                errors.append(f"local manifest hash mismatch: {path}")
    return not special and actual == expected


def read_out_base_marker(root: Path, lock: dict[str, Any]) -> tuple[bool, bool]:
    """Return (valid_marker, marker_present) for the restored-out base."""
    if (
        lock.get("min_free_bytes_with_out_base") is None
        or lock.get("out_base_snapshot") is None
    ):
        return False, False
    marker = root / "out/avium-a16/base-provenance.json"
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, False
    valid = (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and value.get("restored_from_snapshot") == lock["out_base_snapshot"]
        and isinstance(value.get("restored_at"), str)
        and bool(value.get("restored_at"))
        and isinstance(value.get("base_system_sha256"), str)
        and SHA256_RE.fullmatch(value["base_system_sha256"]) is not None
        and isinstance(value.get("base_vendor_sha256"), str)
        and SHA256_RE.fullmatch(value["base_vendor_sha256"]) is not None
    )
    return valid, True


def check_disk(root: Path, lock: dict[str, Any], errors: list[str]) -> bool:
    testing = os.environ.get("AVIUM_PREFLIGHT_TESTING") == "1"
    injected = os.environ.get("AVIUM_FREE_BYTES") if testing else None
    if injected is not None:
        try:
            free = int(injected, 10)
        except ValueError:
            errors.append("AVIUM_FREE_BYTES is not an integer")
            return False
        if free < 0:
            errors.append("AVIUM_FREE_BYTES is negative")
            return False
    else:
        try:
            free = shutil.disk_usage(root).free
        except OSError as exc:
            errors.append(f"disk usage failed: {exc}")
            return False
    valid_base, marker_present = read_out_base_marker(root, lock)
    if valid_base:
        minimum = lock["min_free_bytes_with_out_base"]
    else:
        if marker_present:
            errors.append("out base marker is invalid")
            return False
        minimum = lock["min_free_bytes"]
    if free < minimum:
        errors.append(f"free disk bytes {free} below required minimum {minimum}")
        return False
    return True


def check_commands(lock: dict[str, Any], errors: list[str]) -> bool:
    missing = [command for command in lock["required_commands"] if shutil.which(command) is None]
    if missing:
        errors.append("required commands are not executable: " + ", ".join(missing))
    return not missing


def check_projects(
    root: Path,
    lock: dict[str, Any],
    errors: list[str],
    prepared_trees: dict[str, str],
    window_projects: dict[str, dict[str, Any]],
    require_prepared: bool,
) -> bool:
    passed = True
    for project in lock["projects"]:
        relative = project["path"]
        try:
            path = resolve_inside(root, relative)
        except CheckError as exc:
            errors.append(f"project {relative}: {exc}")
            passed = False
            continue
        if not path.is_dir() or path.is_symlink() or not (path / ".git").exists():
            errors.append(f"project {relative} is not a Git checkout")
            passed = False
            continue
        try:
            actual_head = git_head(path)
            actual_tree = git_value(path, "rev-parse", "HEAD^{tree}")
            status = git_status(path)
            window = window_projects.get(relative)
            if window is not None:
                release_tree = prepared_trees.get(relative)
                if release_tree is None:
                    release_tree = git_value(
                        path, "rev-parse", f"{project['base_head']}^{{tree}}"
                    )
                if window["base_tree"] != release_tree:
                    errors.append(
                        f"project {relative} window base tree mismatch: "
                        f"expected {release_tree}, got {window['base_tree']}"
                    )
                    passed = False
        except CheckError as exc:
            errors.append(f"project {relative}: {exc}")
            passed = False
            continue
        release_tree = prepared_trees.get(relative)
        window = window_projects.get(relative)
        window_tree = window["expected_tree"] if window is not None else None
        if require_prepared:
            if window_tree is not None:
                if actual_tree != window_tree:
                    errors.append(
                        f"project {relative} prepared tree mismatch: "
                        f"expected {window_tree}, got {actual_tree}"
                    )
                    passed = False
            elif release_tree is not None:
                if actual_tree != release_tree:
                    errors.append(
                        f"project {relative} prepared tree mismatch: "
                        f"expected {release_tree}, got {actual_tree}"
                    )
                    passed = False
            elif actual_head != project["base_head"]:
                errors.append(
                    f"project {relative} HEAD mismatch: "
                    f"expected {project['base_head']}, got {actual_head}"
                )
                passed = False
        elif release_tree is None and window_tree is None:
            if actual_head != project["base_head"]:
                errors.append(
                    f"project {relative} HEAD mismatch: "
                    f"expected {project['base_head']}, got {actual_head}"
                )
                passed = False
        elif (
            actual_head != project["base_head"]
            and (release_tree is None or actual_tree != release_tree)
            and (window_tree is None or actual_tree != window_tree)
        ):
            errors.append(
                f"project {relative} is neither base HEAD, release tree, nor window tree"
            )
            passed = False
        if status:
            errors.append(f"project {relative} is dirty: {'; '.join(status)}")
            passed = False
    return passed


def is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as stream:
        prefix = stream.read(128)
    return prefix.startswith(b"version https://git-lfs.github.com/spec/v1")


def check_lfs_files(root: Path, lock: dict[str, Any], errors: list[str]) -> bool:
    passed = True
    for item in lock["lfs_files"]:
        relative = item["path"]
        try:
            path = resolve_inside(root, relative)
        except CheckError as exc:
            errors.append(f"LFS file {relative}: {exc}")
            passed = False
            continue
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError:
            errors.append(f"LFS file missing: {relative}")
            passed = False
            continue
        if not stat.S_ISREG(mode) or path.is_symlink():
            errors.append(f"LFS file is not a regular non-symlink file: {relative}")
            passed = False
            continue
        size = path.stat(follow_symlinks=False).st_size
        if size != item["size"]:
            errors.append(
                f"LFS file size mismatch: {relative} (expected {item['size']}, got {size})"
            )
            passed = False
        if is_lfs_pointer(path):
            errors.append(f"LFS pointer is not expanded: {relative}")
            passed = False
            continue
        actual_hash = sha256_file(path)
        if actual_hash != item["sha256"]:
            errors.append(f"LFS file hash mismatch: {relative}")
            passed = False
    return passed


def check_processes(lock: dict[str, Any], errors: list[str]) -> bool:
    testing = os.environ.get("AVIUM_PREFLIGHT_TESTING") == "1"
    proc_root = Path(os.environ.get("AVIUM_PROC_ROOT", "/proc") if testing else "/proc")
    if not proc_root.is_dir():
        errors.append(f"process scan root is not a directory: {proc_root}")
        return False
    patterns = [re.compile(pattern) for pattern in lock["process_patterns"]]
    ignored = {os.getpid(), os.getppid()}
    collisions: list[str] = []
    try:
        entries = sorted(proc_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        errors.append(f"process scan failed: {exc}")
        return False
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) in ignored:
            continue
        try:
            raw_command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        arguments = [part for part in raw_command.split(b"\x00") if part]
        if not arguments:
            continue
        executable = arguments[0].decode("utf-8", errors="replace")
        command = b" ".join(arguments).decode("utf-8", errors="replace")
        for pattern in patterns:
            if pattern.search(executable):
                collisions.append(f"pid {entry.name}: {command.strip() or '<empty>'}")
                break
    if collisions:
        errors.append("concurrent build processes detected: " + "; ".join(collisions))
    return not collisions


def run_checks(
    root: Path,
    lock: dict[str, Any],
    prepared_trees: dict[str, str] | None = None,
    require_prepared: bool = False,
    window_projects: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prepared_trees = prepared_trees or {}
    window_projects = window_projects or {}
    errors: list[str] = []
    repo_ok = root.is_dir() and (root / ".repo").is_dir()
    if not repo_ok:
        errors.append(f"missing AOSP repo directory: {root / '.repo'}")
    checks = {
        "aosp_root_repo": repo_ok,
        "manifest_repository_head": False,
        "local_manifests": False,
        "disk_free": False,
        "required_commands": False,
        "projects": False,
        "lfs_files": False,
        "concurrent_build": False,
    }

    def safe_check(name: str, function: Any) -> bool:
        try:
            return bool(function())
        except (CheckError, OSError, UnicodeError) as exc:
            errors.append(f"{name} check failed: {exc}")
            return False

    if repo_ok:
        checks["manifest_repository_head"] = safe_check(
            "manifest repository", lambda: check_manifest(root, lock, errors)
        )
        checks["local_manifests"] = safe_check(
            "local manifests", lambda: check_local_manifests(root, lock, errors)
        )
    else:
        errors.append("manifest and local manifest checks skipped because .repo is missing")
    checks["disk_free"] = (
        safe_check("disk", lambda: check_disk(root, lock, errors))
        if root.is_dir()
        else False
    )
    checks["required_commands"] = safe_check(
        "required commands", lambda: check_commands(lock, errors)
    )
    checks["projects"] = (
        safe_check(
            "projects",
            lambda: check_projects(
                root, lock, errors, prepared_trees, window_projects, require_prepared
            ),
        )
        if root.is_dir()
        else False
    )
    checks["lfs_files"] = (
        safe_check("LFS files", lambda: check_lfs_files(root, lock, errors))
        if root.is_dir()
        else False
    )
    checks["concurrent_build"] = safe_check(
        "process scan", lambda: check_processes(lock, errors)
    )
    return {
        "schema_version": 1,
        "ok": not errors,
        "checks": checks,
        "errors": errors,
    }


def emit(result: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aosp_root", metavar="AOSP_ROOT")
    parser.add_argument("--lock", required=True, type=Path, metavar="LOCK_JSON")
    parser.add_argument("--output", type=Path, metavar="PATH")
    parser.add_argument("--series", type=Path, metavar="SERIES_JSON")
    parser.add_argument("--window-series", type=Path, metavar="PATH")
    parser.add_argument("--require-prepared", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        root = Path(args.aosp_root).expanduser().resolve(strict=False)
        output = args.output.expanduser().resolve(strict=False) if args.output else None
        if output is not None:
            try:
                output.relative_to(root)
            except ValueError:
                pass
            else:
                raise ConfigError("--output must not be inside AOSP_ROOT")
        lock = load_lock(args.lock.expanduser().resolve(strict=False))
        if args.require_prepared and args.series is None and args.window_series is None:
            raise ConfigError("--require-prepared requires --series or --window-series")
        prepared_trees = (
            load_prepared_trees(args.series.expanduser().resolve(strict=False), lock)
            if args.series
            else {}
        )
        window_projects = (
            load_window_series(
                args.window_series.expanduser().resolve(strict=False), lock
            )
            if args.window_series
            else {}
        )
    except (ConfigError, OSError, UnicodeError) as exc:
        print(f"check-repro-inputs: {exc}", file=sys.stderr)
        return 2

    try:
        result = run_checks(
            root,
            lock,
            prepared_trees,
            args.require_prepared,
            window_projects,
        )
        emit(result, output)
    except (OSError, UnicodeError, CheckError) as exc:
        print(f"check-repro-inputs: {exc}", file=sys.stderr)
        return 1
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
