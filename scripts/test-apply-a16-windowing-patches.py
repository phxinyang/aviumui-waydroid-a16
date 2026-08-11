#!/usr/bin/env python3
"""Semantic tests for the locked A16 windowing patch applier."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
APPLIER = ROOT / "scripts/apply-a16-windowing-patches.py"


def run_git(directory: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(directory), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


def init_project(root: Path, relative: str) -> tuple[Path, str]:
    project = root / relative
    project.mkdir(parents=True)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Window Applier Test")
    run_git(project, "config", "user.email", "window-test@example.invalid")
    (project / "state.txt").write_text("base\n", encoding="utf-8")
    run_git(project, "add", "state.txt")
    run_git(project, "commit", "-qm", "base")
    return project, run_git(project, "rev-parse", "HEAD^{tree}").strip()


def make_patch(project: Path, patch: Path, content: str) -> str:
    (project / "state.txt").write_text(content, encoding="utf-8")
    run_git(project, "add", "state.txt")
    run_git(project, "commit", "-qm", patch.stem)
    expected_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(
        run_git(project, "format-patch", "-1", "--stdout"), encoding="utf-8"
    )
    run_git(project, "reset", "--hard", "HEAD~1")
    return expected_tree


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_series(path: Path, projects: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "projects": projects}, indent=2) + "\n",
        encoding="utf-8",
    )


def run_apply(
    root: Path,
    series: Path,
    patch_root: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(APPLIER),
            str(root),
            "--series",
            str(series),
            "--patch-root",
            str(patch_root),
            *extra,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def project_snapshot(project: Path) -> tuple[str, str, str, str]:
    return (
        run_git(project, "rev-parse", "HEAD").strip(),
        run_git(project, "rev-parse", "HEAD^{tree}").strip(),
        run_git(project, "status", "--porcelain=v1"),
        run_git(project, "worktree", "list", "--porcelain"),
    )


@contextmanager
def fixture() -> Iterator[
    tuple[Path, Path, Path, Path, Path, dict[str, Any], dict[str, Any]]
]:
    with tempfile.TemporaryDirectory(prefix="apply-a16-windowing-") as directory:
        container = Path(directory)
        root = container / "aosp"
        patch_root = container / "patches"
        series = container / "series.json"
        first, first_base = init_project(root, "frameworks/base")
        second, second_base = init_project(root, "hardware/waydroid")
        first_patch = patch_root / "a16/frameworks-base/0001.patch"
        second_patch = patch_root / "a16/hardware-waydroid/0001.patch"
        first_expected = make_patch(first, first_patch, "framework\n")
        second_expected = make_patch(second, second_patch, "hardware\n")
        first_specification = {
            "path": "frameworks/base",
            "base_tree": first_base,
            "expected_tree": first_expected,
            "patches": [
                {
                    "path": "a16/frameworks-base/0001.patch",
                    "sha256": sha256(first_patch),
                }
            ],
        }
        second_specification = {
            "path": "hardware/waydroid",
            "base_tree": second_base,
            "expected_tree": second_expected,
            "patches": [
                {
                    "path": "a16/hardware-waydroid/0001.patch",
                    "sha256": sha256(second_patch),
                }
            ],
        }
        write_series(series, [first_specification, second_specification])
        yield (
            root,
            series,
            patch_root,
            first,
            second,
            first_specification,
            second_specification,
        )


def result_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"applier did not emit JSON (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        ) from exc


def assert_success_and_idempotence() -> None:
    with fixture() as (root, series, patch_root, first, second, *_):
        before = (project_snapshot(first), project_snapshot(second))
        result = run_apply(root, series, patch_root, "--inputs-only")
        state = result_json(result)
        if (
            result.returncode != 0
            or not state["ok"]
            or not state["inputs_only"]
            or {item["status"] for item in state["projects"]}
            != {"inputs-verified"}
        ):
            raise AssertionError(f"input-only verification failed: {state}")
        if (project_snapshot(first), project_snapshot(second)) != before:
            raise AssertionError("input-only verification changed a checkout")

        output = root.parent / "check-only.json"
        result = run_apply(
            root,
            series,
            patch_root,
            "--check-only",
            "--output",
            str(output),
        )
        if result.returncode != 0 or result.stdout:
            raise AssertionError(result.stderr or result.stdout)
        state = json.loads(output.read_text(encoding="utf-8"))
        if not state["ok"] or not state["check_only"]:
            raise AssertionError(f"check-only failed: {state}")
        if [item["status"] for item in state["projects"]] != [
            "verified",
            "verified",
        ]:
            raise AssertionError(f"unexpected check-only statuses: {state}")
        if (project_snapshot(first), project_snapshot(second)) != before:
            raise AssertionError("check-only changed a checkout or worktree registration")

        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 0 or not state["ok"]:
            raise AssertionError(result.stderr or result.stdout)
        if {item["status"] for item in state["projects"]} != {"applied"}:
            raise AssertionError(f"apply did not report applied: {state}")
        applied = (project_snapshot(first), project_snapshot(second))
        if applied == before:
            raise AssertionError("apply did not advance the projects")

        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 0 or {item["status"] for item in state["projects"]} != {
            "completed"
        }:
            raise AssertionError(f"completed state was not idempotent: {state}")
        if (project_snapshot(first), project_snapshot(second)) != applied:
            raise AssertionError("completed apply changed a checkout")


def assert_failed_verification_is_atomic() -> None:
    with fixture() as (root, series, patch_root, first, second, *_):
        before = (project_snapshot(first), project_snapshot(second))
        value = json.loads(series.read_text(encoding="utf-8"))
        value["projects"][1]["expected_tree"] = "0" * 40
        write_series(series, value["projects"])
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or state["ok"] or "tree mismatch" not in state["errors"][0]:
            raise AssertionError(f"bad second project was not rejected: {state}")
        if (project_snapshot(first), project_snapshot(second)) != before:
            raise AssertionError("phase-one failure changed a real checkout")


def assert_state_guards() -> None:
    with fixture() as (
        root,
        series,
        patch_root,
        first,
        second,
        first_specification,
        second_specification,
    ):
        before = (project_snapshot(first), project_snapshot(second))
        (first / "state.txt").write_text("dirty\n", encoding="utf-8")
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "dirty" not in state["errors"][0]:
            raise AssertionError(f"dirty checkout was not rejected: {state}")
        run_git(first, "checkout", "--", "state.txt")

        wrong_base = dict(first_specification)
        wrong_base["base_tree"] = "0" * 40
        write_series(series, [wrong_base, second_specification])
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "unexpected tree" not in state["errors"][0]:
            raise AssertionError(f"wrong base tree was not rejected: {state}")
        if (project_snapshot(first), project_snapshot(second)) != before:
            raise AssertionError("state guard changed a checkout")

        run_git(first, "config", "status.showUntrackedFiles", "no")
        untracked = first / "hidden-by-config.txt"
        untracked.write_text("dirty\n", encoding="utf-8")
        write_series(series, [first_specification, second_specification])
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "dirty" not in state["errors"][0]:
            raise AssertionError(
                f"status.showUntrackedFiles hid a dirty checkout: {state}"
            )
        untracked.unlink()
        run_git(first, "config", "--unset", "status.showUntrackedFiles")


def assert_digest_is_always_checked() -> None:
    with fixture() as (root, series, patch_root, first, second, *_):
        result = run_apply(root, series, patch_root)
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        applied = (project_snapshot(first), project_snapshot(second))
        patch = patch_root / "a16/frameworks-base/0001.patch"
        patch.write_bytes(patch.read_bytes() + b"tampered\n")
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "digest mismatch" not in state["errors"][0]:
            raise AssertionError(f"completed project skipped patch digest validation: {state}")
        if (project_snapshot(first), project_snapshot(second)) != applied:
            raise AssertionError("digest rejection changed a checkout")


def assert_path_and_symlink_guards() -> None:
    with fixture() as (
        root,
        series,
        patch_root,
        first,
        second,
        first_specification,
        second_specification,
    ):
        before = (project_snapshot(first), project_snapshot(second))
        escaped = json.loads(json.dumps(first_specification))
        escaped["patches"][0]["path"] = "../outside.patch"
        write_series(series, [escaped, second_specification])
        result = run_apply(root, series, patch_root)
        if result.returncode != 2 or result.stdout or "stay inside" not in result.stderr:
            raise AssertionError("lexical patch path escape was not a config error")

        original = patch_root / first_specification["patches"][0]["path"]
        target = original.with_name("target.patch")
        original.rename(target)
        original.symlink_to(target.name)
        linked = json.loads(json.dumps(first_specification))
        linked["patches"][0]["sha256"] = sha256(target)
        write_series(series, [linked, second_specification])
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "regular file" not in state["errors"][0]:
            raise AssertionError(f"symlink patch was not rejected: {state}")
        if (project_snapshot(first), project_snapshot(second)) != before:
            raise AssertionError("path guard changed a checkout")


def assert_external_git_metadata_is_rejected() -> None:
    with fixture() as (root, series, patch_root, first, *_):
        external = root.parent / "external-framework-git"
        (first / ".git").rename(external)
        (first / ".git").write_text(f"gitdir: {external}\n", encoding="utf-8")
        result = run_apply(root, series, patch_root)
        state = result_json(result)
        if result.returncode != 1 or "metadata escapes" not in state["errors"][0]:
            raise AssertionError(f"external Git metadata was not rejected: {state}")


def assert_config_guards() -> None:
    with fixture() as (root, series, patch_root, *_):
        series.write_text(
            json.dumps({"schema_version": 1, "projects": [], "extra": True}),
            encoding="utf-8",
        )
        result = run_apply(root, series, patch_root)
        if result.returncode != 2 or result.stdout or not result.stderr:
            raise AssertionError("unknown series field was not rejected as configuration")

        series.write_text(
            '{"schema_version": true, "projects": []}\n', encoding="utf-8"
        )
        result = run_apply(root, series, patch_root)
        if result.returncode != 2 or "schema_version" not in result.stderr:
            raise AssertionError("boolean schema_version was accepted")

        series.write_text(
            '{"schema_version": 1, "schema_version": 1, "projects": []}\n',
            encoding="utf-8",
        )
        result = run_apply(root, series, patch_root)
        if result.returncode != 2 or "duplicate JSON field" not in result.stderr:
            raise AssertionError("duplicate JSON fields were accepted")


def main() -> int:
    assert_success_and_idempotence()
    assert_failed_verification_is_atomic()
    assert_state_guards()
    assert_digest_is_always_checked()
    assert_path_and_symlink_guards()
    assert_external_git_metadata_is_rejected()
    assert_config_guards()
    print("apply-a16-windowing-patches semantic tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
