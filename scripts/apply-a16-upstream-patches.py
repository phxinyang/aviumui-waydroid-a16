#!/usr/bin/env python3
"""Apply an A16 patch series through isolated worktrees before fast-forwarding."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
DEFAULT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Avium A16 Reproducer",
    "GIT_AUTHOR_EMAIL": "avium-a16-reproducer@example.invalid",
    "GIT_COMMITTER_NAME": "Avium A16 Reproducer",
    "GIT_COMMITTER_EMAIL": "avium-a16-reproducer@example.invalid",
}
REQUIRED_LOCK_FIELDS = {"schema_version", "projects", "skips"}
ALLOWED_PROJECT_FIELDS = {"path", "base_head", "expected_tree", "patches"}
ALLOWED_PATCH_FIELDS = {"source", "path"}
ALLOWED_SKIP_FIELDS = {"patch", "reason", "predicate"}


class ConfigError(ValueError):
    """Invalid CLI or series configuration."""


class ApplyError(RuntimeError):
    """A patch series could not be verified or applied."""


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
        raise ConfigError(f"{field} must name a path: {value!r}")
    return normalized


def sha40(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA40_RE.fullmatch(value):
        raise ConfigError(f"{field} must be a 40-digit Git object ID")
    return value.lower()


def load_series(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read series JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("series JSON must contain an object")
    if set(value) != REQUIRED_LOCK_FIELDS:
        missing = sorted(REQUIRED_LOCK_FIELDS - set(value))
        unknown = sorted(set(value) - REQUIRED_LOCK_FIELDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ConfigError("invalid series fields: " + "; ".join(details))
    if value["schema_version"] != 1:
        raise ConfigError("series schema_version must be 1")
    if not isinstance(value["projects"], list):
        raise ConfigError("projects must be an array")
    if not isinstance(value["skips"], list):
        raise ConfigError("skips must be an array")

    projects: list[dict[str, Any]] = []
    project_paths: set[str] = set()
    for index, project in enumerate(value["projects"]):
        if not isinstance(project, dict) or set(project) != ALLOWED_PROJECT_FIELDS:
            raise ConfigError(
                f"projects[{index}] must contain exactly path, base_head, expected_tree and patches"
            )
        path = relative_path(project["path"], f"projects[{index}].path")
        if path in project_paths:
            raise ConfigError(f"duplicate project path: {path}")
        project_paths.add(path)
        patches = project["patches"]
        if not isinstance(patches, list):
            raise ConfigError(f"projects[{index}].patches must be an array")
        normalized_patches: list[dict[str, str]] = []
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, dict) or set(patch) != ALLOWED_PATCH_FIELDS:
                raise ConfigError(
                    f"projects[{index}].patches[{patch_index}] must contain source and path"
                )
            source = patch["source"]
            if source not in ("upstream", "local"):
                raise ConfigError(
                    f"projects[{index}].patches[{patch_index}].source must be upstream or local"
                )
            normalized_patches.append(
                {
                    "source": source,
                    "path": relative_path(
                        patch["path"], f"projects[{index}].patches[{patch_index}].path"
                    ),
                }
            )
        projects.append(
            {
                "path": path,
                "base_head": sha40(project["base_head"], f"projects[{index}].base_head"),
                "expected_tree": sha40(
                    project["expected_tree"], f"projects[{index}].expected_tree"
                ),
                "patches": normalized_patches,
            }
        )

    skips: list[dict[str, str]] = []
    for index, skip in enumerate(value["skips"]):
        if not isinstance(skip, dict) or set(skip) != ALLOWED_SKIP_FIELDS:
            raise ConfigError(
                f"skips[{index}] must contain exactly patch, reason and predicate"
            )
        patch = relative_path(skip["patch"], f"skips[{index}].patch")
        if not isinstance(skip["reason"], str) or not skip["reason"]:
            raise ConfigError(f"skips[{index}].reason must be a non-empty string")
        predicate = skip["predicate"]
        if not isinstance(predicate, str) or not predicate:
            raise ConfigError(f"skips[{index}].predicate must be a non-empty string")
        validate_predicate_syntax(predicate, f"skips[{index}].predicate")
        skips.append({"patch": patch, "reason": skip["reason"], "predicate": predicate})

    return {"schema_version": 1, "projects": projects, "skips": skips}


def validate_predicate_syntax(predicate: str, field: str) -> None:
    if predicate.startswith("missing_project:"):
        relative_path(predicate.removeprefix("missing_project:"), field + " project")
        return
    if predicate.startswith("file_not_contains:"):
        payload = predicate.removeprefix("file_not_contains:")
        pieces = payload.split(":", 2)
        if len(pieces) != 3:
            pieces = payload.split(",", 2)
        if len(pieces) != 3 or not pieces[2]:
            raise ConfigError(
                f"{field} must be file_not_contains:project:path:needle"
            )
        relative_path(pieces[0], field + " project")
        relative_path(pieces[1], field + " file")
        return
    raise ConfigError(
        f"{field} must be missing_project:path or file_not_contains:project:path:needle"
    )


def run_git(project: Path, *arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(project), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ApplyError(detail or f"git {' '.join(arguments)} failed")
    return result


def git_value(project: Path, *arguments: str) -> str:
    result = run_git(project, *arguments)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ApplyError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def git_status(project: Path) -> list[str]:
    result = run_git(project, "status", "--porcelain=v1")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ApplyError(detail or "git status failed")
    return result.stdout.splitlines()


def resolve_inside(root: Path, relative: str, field: str) -> Path:
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"{field} escapes its root: {relative}") from exc
    return path


def patch_id(patch: dict[str, str]) -> str:
    return f"{patch['source']}:{patch['path']}"


def skip_matches(skip_patch: str, patch: dict[str, str]) -> bool:
    return skip_patch in (patch["path"], patch_id(patch))


def predicate_holds(root: Path, predicate: str) -> bool:
    if predicate.startswith("missing_project:"):
        path = resolve_inside(root, predicate.removeprefix("missing_project:"), "predicate")
        return not path.exists()
    payload = predicate.removeprefix("file_not_contains:")
    pieces = payload.split(":", 2)
    if len(pieces) != 3:
        pieces = payload.split(",", 2)
    project, relative_file, needle = pieces
    project_root = resolve_inside(root, project, "predicate project")
    if not project_root.is_dir():
        return False
    path = resolve_inside(project_root, relative_file, "predicate file")
    if not path.exists():
        return True
    if path.is_symlink() or not path.is_file():
        return False
    return needle.encode("utf-8") not in path.read_bytes()


def evaluate_skips(root: Path, series: dict[str, Any], errors: list[str]) -> list[dict[str, str]]:
    applied: list[dict[str, str]] = []
    for skip in series["skips"]:
        try:
            holds = predicate_holds(root, skip["predicate"])
        except (ApplyError, OSError, UnicodeError) as exc:
            errors.append(f"skip {skip['patch']} predicate failed: {exc}")
            holds = False
        if not holds:
            errors.append(f"skip predicate is false: {skip['patch']} ({skip['predicate']})")
        else:
            applied.append(skip)
    return applied


def project_complete(project: Path, specification: dict[str, Any]) -> bool:
    if git_status(project):
        raise ApplyError(f"project is dirty: {specification['path']}")
    head = git_value(project, "rev-parse", "HEAD")
    tree = git_value(project, "rev-parse", "HEAD^{tree}")
    if head == specification["base_head"]:
        return False
    if tree == specification["expected_tree"]:
        return True
    raise ApplyError(
        f"project {specification['path']} is neither base HEAD nor expected completed tree"
    )


def patch_path(
    patch: dict[str, str],
    upstream_root: Path,
    local_root: Path,
) -> Path:
    root = upstream_root if patch["source"] == "upstream" else local_root
    path = resolve_inside(root, patch["path"], f"{patch_id(patch)} patch")
    if path.is_symlink() or not path.is_file():
        raise ApplyError(f"patch is not a regular file: {path}")
    return path


def apply_in_worktree(
    worktree: Path,
    specification: dict[str, Any],
    patches: list[dict[str, str]],
    upstream_root: Path,
    local_root: Path,
) -> str:
    environment = os.environ.copy()
    environment.update(DEFAULT_IDENTITY)
    for patch in patches:
        path = patch_path(patch, upstream_root, local_root)
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(worktree),
                "-c",
                "user.name=Avium A16 Reproducer",
                "-c",
                "user.email=avium-a16-reproducer@example.invalid",
                "am",
                "--3way",
                str(path),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        if result.returncode != 0:
            run_git(worktree, "am", "--abort")
            detail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown git am error"
            raise ApplyError(f"{specification['path']} {patch_id(patch)}: {detail}")
    tree = git_value(worktree, "rev-parse", "HEAD^{tree}")
    if tree != specification["expected_tree"]:
        raise ApplyError(
            f"project {specification['path']} tree mismatch: "
            f"expected {specification['expected_tree']}, got {tree}"
        )
    return git_value(worktree, "rev-parse", "HEAD")


def cleanup_worktrees(worktrees: list[tuple[Path, Path]]) -> None:
    for project, worktree in reversed(worktrees):
        run_git(project, "worktree", "remove", "--force", str(worktree))
        run_git(project, "worktree", "prune")


def run_series(
    root: Path,
    series: dict[str, Any],
    local_root: Path,
    upstream_root: Path,
    check_only: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    skips = evaluate_skips(root, series, errors)
    skip_list = [dict(skip) for skip in series["skips"]]
    projects_output: list[dict[str, Any]] = []
    worktrees: list[tuple[Path, Path]] = []
    staged: list[tuple[Path, dict[str, Any], str]] = []
    temporary_root = Path(tempfile.mkdtemp(prefix="a16-patch-worktrees-"))
    try:
        if errors:
            return {
                "schema_version": 1,
                "ok": False,
                "check_only": check_only,
                "projects": projects_output,
                "skips": skip_list,
                "errors": errors,
            }
        for specification in series["projects"]:
            project = resolve_inside(root, specification["path"], "project")
            if not project.is_dir() or project.is_symlink() or not (project / ".git").exists():
                raise ApplyError(f"project is not a Git checkout: {specification['path']}")
            complete = project_complete(project, specification)
            if complete:
                projects_output.append({"path": specification["path"], "status": "completed"})
                continue
            active_patches = [
                patch
                for patch in specification["patches"]
                if not any(skip_matches(skip["patch"], patch) for skip in skips)
            ]
            worktree = temporary_root / specification["path"]
            worktree.parent.mkdir(parents=True, exist_ok=True)
            run_git(project, "worktree", "add", "--detach", str(worktree), specification["base_head"], check=True)
            worktrees.append((project, worktree))
            head = apply_in_worktree(
                worktree, specification, active_patches, upstream_root, local_root
            )
            staged.append((project, specification, head))
            projects_output.append(
                {
                    "path": specification["path"],
                    "status": "verified",
                    "head": head,
                }
            )

        if not check_only:
            for project, specification, head in staged:
                if project_complete(project, specification):
                    continue
                run_git(project, "merge", "--ff-only", head, check=True)
                if (
                    git_value(project, "rev-parse", "HEAD^{tree}")
                    != specification["expected_tree"]
                    or git_status(project)
                ):
                    raise ApplyError(f"post-merge verification failed: {specification['path']}")
                for result in projects_output:
                    if result["path"] == specification["path"]:
                        result["status"] = "applied"
        return {
            "schema_version": 1,
            "ok": True,
            "check_only": check_only,
            "projects": projects_output,
            "skips": skip_list,
            "errors": [],
        }
    except (ApplyError, OSError, UnicodeError) as exc:
        errors.append(str(exc))
        return {
            "schema_version": 1,
            "ok": False,
            "check_only": check_only,
            "projects": projects_output,
            "skips": skip_list,
            "errors": errors,
        }
    finally:
        cleanup_worktrees(worktrees)
        shutil.rmtree(temporary_root, ignore_errors=True)


def emit(result: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aosp_root", metavar="AOSP_ROOT")
    parser.add_argument("--series", required=True, type=Path, metavar="SERIES_JSON")
    parser.add_argument("--local-patch-root", type=Path, metavar="PATH")
    parser.add_argument("--upstream-patch-root", type=Path, metavar="PATH")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path, metavar="PATH")
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
        series = load_series(args.series.expanduser().resolve(strict=False))
        local_root = (
            args.local_patch_root.expanduser().resolve(strict=False)
            if args.local_patch_root
            else (Path(__file__).resolve().parent.parent / "patches/a16").resolve()
        )
        upstream_root = (
            args.upstream_patch_root.expanduser().resolve(strict=False)
            if args.upstream_patch_root
            else (root / "vendor/extra/waydroid-patches/base-patches-36").resolve()
        )
        for patch_root, field in ((local_root, "local-patch-root"), (upstream_root, "upstream-patch-root")):
            if not patch_root.is_dir():
                raise ConfigError(f"{field} is not a directory: {patch_root}")
    except (ConfigError, OSError, UnicodeError) as exc:
        print(f"apply-a16-upstream-patches: {exc}", file=sys.stderr)
        return 2

    result = run_series(root, series, local_root, upstream_root, args.check_only)
    try:
        emit(result, output)
    except (OSError, UnicodeError) as exc:
        print(f"apply-a16-upstream-patches: {exc}", file=sys.stderr)
        return 1
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
