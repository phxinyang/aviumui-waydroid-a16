#!/usr/bin/env python3
"""Apply the locked A16 windowing series from exact input trees."""

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
import tempfile
from typing import Any


SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SERIES_FIELDS = {"schema_version", "projects"}
PROJECT_FIELDS = {"path", "base_tree", "expected_tree", "patches"}
PATCH_FIELDS = {"path", "sha256"}
IDENTITY = {
    "GIT_AUTHOR_NAME": "Avium Window Reproducer",
    "GIT_AUTHOR_EMAIL": "avium-window-reproducer@example.invalid",
    "GIT_COMMITTER_NAME": "Avium Window Reproducer",
    "GIT_COMMITTER_EMAIL": "avium-window-reproducer@example.invalid",
}


class ConfigError(ValueError):
    pass


class ApplyError(RuntimeError):
    pass


def relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise ConfigError(f"{field} must stay inside its root: {value!r}")
    normalized = path.as_posix()
    if normalized in ("", "."):
        raise ConfigError(f"{field} must name a path")
    return normalized


def digest(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ConfigError(f"{field} has an invalid digest")
    return value.lower()


def load_series(path: Path) -> dict[str, Any]:
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
        raise ConfigError(f"cannot read series {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != SERIES_FIELDS:
        raise ConfigError("series must contain exactly schema_version and projects")
    if (
        not isinstance(value["schema_version"], int)
        or isinstance(value["schema_version"], bool)
        or value["schema_version"] != 1
        or not isinstance(value["projects"], list)
    ):
        raise ConfigError("series schema_version must be 1 and projects must be an array")
    if not value["projects"]:
        raise ConfigError("series projects must not be empty")

    projects: list[dict[str, Any]] = []
    project_paths: set[str] = set()
    patch_paths: set[str] = set()
    for index, project in enumerate(value["projects"]):
        if not isinstance(project, dict) or set(project) != PROJECT_FIELDS:
            raise ConfigError(
                f"projects[{index}] must contain path, base_tree, expected_tree and patches"
            )
        project_path = relative_path(project["path"], f"projects[{index}].path")
        if project_path in project_paths:
            raise ConfigError(f"duplicate project path: {project_path}")
        project_paths.add(project_path)
        patches = project["patches"]
        if not isinstance(patches, list) or not patches:
            raise ConfigError(f"projects[{index}].patches must be a non-empty array")
        normalized_patches: list[dict[str, str]] = []
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, dict) or set(patch) != PATCH_FIELDS:
                raise ConfigError(
                    f"projects[{index}].patches[{patch_index}] must contain path and sha256"
                )
            patch_path = relative_path(
                patch["path"], f"projects[{index}].patches[{patch_index}].path"
            )
            if patch_path in patch_paths:
                raise ConfigError(f"duplicate patch path: {patch_path}")
            patch_paths.add(patch_path)
            normalized_patches.append(
                {
                    "path": patch_path,
                    "sha256": digest(
                        patch["sha256"],
                        SHA256_RE,
                        f"projects[{index}].patches[{patch_index}].sha256",
                    ),
                }
            )
        projects.append(
            {
                "path": project_path,
                "base_tree": digest(project["base_tree"], SHA40_RE, "base_tree"),
                "expected_tree": digest(
                    project["expected_tree"], SHA40_RE, "expected_tree"
                ),
                "patches": normalized_patches,
            }
        )
    return {"schema_version": 1, "projects": projects}


def resolve_inside(root: Path, relative: str, field: str) -> Path:
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"{field} escapes its root: {relative}") from exc
    return path


def run_git(project: Path, *arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(project), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )
    if check and result.returncode != 0:
        raise ApplyError(result.stdout.strip() or f"git {' '.join(arguments)} failed")
    return result


def git_value(project: Path, *arguments: str) -> str:
    return run_git(project, *arguments, check=True).stdout.strip()


def git_status(project: Path) -> list[str]:
    return run_git(
        project,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
        check=True,
    ).stdout.splitlines()


def validate_checkout(root: Path, project: Path, relative: str) -> None:
    if not project.is_dir() or not (project / ".git").exists():
        raise ApplyError(f"project is not a Git checkout: {relative}")
    if git_value(project, "rev-parse", "--is-inside-work-tree") != "true":
        raise ApplyError(f"project is not a Git worktree: {relative}")
    top = Path(
        git_value(project, "rev-parse", "--path-format=absolute", "--show-toplevel")
    ).resolve(strict=False)
    if top != project:
        raise ApplyError(f"project worktree root mismatch: {relative}")
    common = Path(
        git_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve(strict=False)
    try:
        common.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"project Git metadata escapes AOSP_ROOT: {relative}") from exc


def reject_symlink_components(root: Path, relative: str, field: str) -> Path:
    current = root
    for component in Path(relative).parts:
        current /= component
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ApplyError(f"cannot inspect {field} {relative}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise ApplyError(f"{field} is not a regular file path: {relative}")
    return resolve_inside(root, relative, field)


def checked_patch(patch_root: Path, specification: dict[str, str]) -> bytes:
    path = reject_symlink_components(patch_root, specification["path"], "patch")
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise ApplyError(f"cannot inspect patch {specification['path']}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ApplyError(f"patch is not a regular file: {path}")
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise ApplyError(f"cannot read patch {specification['path']}: {exc}") from exc
    actual = hashlib.sha256(contents).hexdigest()
    if actual != specification["sha256"]:
        raise ApplyError(
            f"patch digest mismatch: {specification['path']} "
            f"expected {specification['sha256']}, got {actual}"
        )
    return contents


def apply_project(
    worktree: Path,
    project: dict[str, Any],
    patches: dict[str, bytes],
) -> str:
    environment = os.environ.copy()
    environment.update(IDENTITY)
    for specification in project["patches"]:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(worktree), "am", "--3way"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            input=patches[specification["path"]],
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            run_git(worktree, "am", "--abort")
            detail = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
            raise ApplyError(
                f"{project['path']} {specification['path']}: "
                f"{detail[-1] if detail else 'git am failed'}"
            )
    tree = git_value(worktree, "rev-parse", "HEAD^{tree}")
    if tree != project["expected_tree"]:
        raise ApplyError(
            f"{project['path']} tree mismatch: expected {project['expected_tree']}, got {tree}"
        )
    return git_value(worktree, "rev-parse", "HEAD")


def cleanup_worktrees(worktrees: list[tuple[Path, Path]]) -> list[str]:
    errors: list[str] = []
    for project, worktree in reversed(worktrees):
        remove = run_git(project, "worktree", "remove", "--force", str(worktree))
        if remove.returncode != 0:
            errors.append(
                f"failed to remove temporary worktree {worktree}: "
                f"{remove.stdout.strip() or 'git worktree remove failed'}"
            )
        prune = run_git(project, "worktree", "prune")
        if prune.returncode != 0:
            errors.append(
                f"failed to prune temporary worktrees for {project}: "
                f"{prune.stdout.strip() or 'git worktree prune failed'}"
            )
    return errors


def run_series(
    root: Path,
    series: dict[str, Any],
    patch_root: Path,
    check_only: bool,
) -> dict[str, Any]:
    temporary_root = Path(tempfile.mkdtemp(prefix="a16-window-worktrees-"))
    worktrees: list[tuple[Path, Path]] = []
    staged: list[tuple[Path, dict[str, Any], str]] = []
    output: list[dict[str, str]] = []
    result: dict[str, Any]
    try:
        patches = {
            patch["path"]: checked_patch(patch_root, patch)
            for project in series["projects"]
            for patch in project["patches"]
        }
        for specification in series["projects"]:
            project = reject_symlink_components(
                root, specification["path"], "project"
            )
            validate_checkout(root, project, specification["path"])
            if git_status(project):
                raise ApplyError(f"project is dirty: {specification['path']}")
            tree = git_value(project, "rev-parse", "HEAD^{tree}")
            if tree == specification["expected_tree"]:
                output.append(
                    {
                        "path": specification["path"],
                        "base_tree": specification["base_tree"],
                        "expected_tree": specification["expected_tree"],
                        "status": "completed",
                    }
                )
                continue
            if tree != specification["base_tree"]:
                raise ApplyError(
                    f"project {specification['path']} has unexpected tree: {tree}"
                )
            target = temporary_root / specification["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            run_git(project, "worktree", "add", "--detach", str(target), "HEAD", check=True)
            worktrees.append((project, target))
            head = apply_project(target, specification, patches)
            staged.append((project, specification, head))
            output.append(
                {
                    "path": specification["path"],
                    "base_tree": specification["base_tree"],
                    "expected_tree": specification["expected_tree"],
                    "status": "verified",
                }
            )

        if not check_only:
            for project, specification, _ in staged:
                if git_status(project):
                    raise ApplyError(
                        f"project changed during verification: {specification['path']}"
                    )
                tree = git_value(project, "rev-parse", "HEAD^{tree}")
                if tree != specification["base_tree"]:
                    raise ApplyError(
                        f"project changed during verification: {specification['path']}"
                    )
            for project, specification, head in staged:
                run_git(project, "merge", "--ff-only", head, check=True)
                if git_status(project) or git_value(project, "rev-parse", "HEAD^{tree}") != specification["expected_tree"]:
                    raise ApplyError(f"post-merge verification failed: {specification['path']}")
                next(item for item in output if item["path"] == specification["path"])[
                    "status"
                ] = "applied"
        result = {
            "schema_version": 1,
            "ok": True,
            "check_only": check_only,
            "projects": output,
            "errors": [],
        }
    except (ApplyError, OSError, UnicodeError) as exc:
        result = {
            "schema_version": 1,
            "ok": False,
            "check_only": check_only,
            "projects": output,
            "errors": [str(exc)],
        }
    cleanup_errors = cleanup_worktrees(worktrees)
    try:
        shutil.rmtree(temporary_root)
    except OSError as exc:
        cleanup_errors.append(f"failed to remove temporary root {temporary_root}: {exc}")
    if cleanup_errors:
        result["ok"] = False
        result["errors"].extend(cleanup_errors)
    return result


def check_inputs(series: dict[str, Any], patch_root: Path) -> dict[str, Any]:
    try:
        for project in series["projects"]:
            for patch in project["patches"]:
                checked_patch(patch_root, patch)
        return {
            "schema_version": 1,
            "ok": True,
            "check_only": True,
            "inputs_only": True,
            "projects": [
                {
                    "path": project["path"],
                    "base_tree": project["base_tree"],
                    "expected_tree": project["expected_tree"],
                    "status": "inputs-verified",
                }
                for project in series["projects"]
            ],
            "errors": [],
        }
    except (ApplyError, OSError, UnicodeError) as exc:
        return {
            "schema_version": 1,
            "ok": False,
            "check_only": True,
            "inputs_only": True,
            "projects": [],
            "errors": [str(exc)],
        }


def emit(result: dict[str, Any], output: Path | None) -> None:
    value = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(value)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, output)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aosp_root", metavar="AOSP_ROOT", type=Path)
    parser.add_argument("--series", required=True, type=Path)
    parser.add_argument("--patch-root", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--inputs-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.aosp_root.expanduser().resolve(strict=False)
        series = load_series(args.series.expanduser().resolve(strict=False))
        patch_root = (
            args.patch_root.expanduser().resolve(strict=False)
            if args.patch_root
            else (Path(__file__).resolve().parent.parent / "patches/windowing").resolve()
        )
        if not patch_root.is_dir():
            raise ConfigError(f"patch root is not a directory: {patch_root}")
        output = args.output.expanduser().resolve(strict=False) if args.output else None
        if output is not None:
            try:
                output.relative_to(root)
            except ValueError:
                pass
            else:
                raise ConfigError("--output must not be inside AOSP_ROOT")
    except (ConfigError, OSError, UnicodeError) as exc:
        print(f"apply-a16-windowing-patches: {exc}", file=sys.stderr)
        return 2

    result = (
        check_inputs(series, patch_root)
        if args.inputs_only
        else run_series(root, series, patch_root, args.check_only)
    )
    try:
        emit(result, output)
    except (OSError, UnicodeError) as exc:
        print(f"apply-a16-windowing-patches: {exc}", file=sys.stderr)
        return 1
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
