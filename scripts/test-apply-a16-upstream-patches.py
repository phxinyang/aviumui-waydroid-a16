#!/usr/bin/env python3
"""Semantic tests for the isolated A16 patch applier."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Iterator


ROOT = Path(__file__).resolve().parent.parent
APPLIER = ROOT / "scripts/apply-a16-upstream-patches.py"


def run_git(directory: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(directory), *arguments],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def init_project(root: Path, relative: str) -> tuple[Path, str]:
    project = root / relative
    project.mkdir(parents=True)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Patch Test")
    run_git(project, "config", "user.email", "patch@example.invalid")
    (project / "state.txt").write_text("base\n", encoding="utf-8")
    run_git(project, "add", "state.txt")
    run_git(project, "commit", "-qm", "base")
    return project, run_git(project, "rev-parse", "HEAD").strip()


def make_patch(project: Path, patch_root: Path, name: str, content: str) -> tuple[str, str]:
    (project / "state.txt").write_text(content, encoding="utf-8")
    run_git(project, "add", "state.txt")
    run_git(project, "commit", "-qm", name)
    commit = run_git(project, "rev-parse", "HEAD").strip()
    expected_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
    patch_root.mkdir(parents=True, exist_ok=True)
    patch = patch_root / f"{name}.patch"
    patch.write_text(run_git(project, "format-patch", "-1", "--stdout"), encoding="utf-8")
    base = run_git(project, "rev-parse", "HEAD~1").strip()
    run_git(project, "reset", "--hard", base)
    return expected_tree, commit


def snapshot_project(project: Path) -> tuple[str, str, str]:
    return (
        run_git(project, "rev-parse", "HEAD"),
        run_git(project, "status", "--porcelain=v1"),
        (project / "state.txt").read_text(encoding="utf-8"),
    )


def worktree_snapshot(project: Path) -> str:
    return run_git(project, "worktree", "list", "--porcelain")


def run_apply(
    root: Path,
    series: Path,
    local_root: Path,
    upstream_root: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(APPLIER),
            str(root),
            "--series",
            str(series),
            "--local-patch-root",
            str(local_root),
            "--upstream-patch-root",
            str(upstream_root),
            *extra,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


@contextmanager
def fixture() -> Iterator[tuple[Path, Path, Path, Path, Path, Path, str, str, str, str]]:
    with tempfile.TemporaryDirectory(prefix="apply-a16-patches-") as directory:
        root = Path(directory)
        project_one, base_one = init_project(root, "frameworks/base")
        project_two, base_two = init_project(root, "hardware/waydroid")
        local_root = root / "local-patches"
        upstream_root = root / "upstream-patches"
        tree_one, _ = make_patch(project_one, upstream_root, "framework-one", "framework\n")
        tree_two, _ = make_patch(project_two, local_root, "hardware-two", "hardware\n")
        skips = [
            {
                "patch": "optional.patch",
                "reason": "optional project absent",
                "predicate": "missing_project:optional/project",
            },
            {
                "patch": "noop.patch",
                "reason": "anchor is already absent",
                "predicate": "file_not_contains:frameworks/base:state.txt:never-present",
            },
        ]
        series = root / "series.json"
        series.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": [
                        {
                            "path": "frameworks/base",
                            "base_head": base_one,
                            "expected_tree": tree_one,
                            "patches": [{"source": "upstream", "path": "framework-one.patch"}],
                        },
                        {
                            "path": "hardware/waydroid",
                            "base_head": base_two,
                            "expected_tree": tree_two,
                            "patches": [{"source": "local", "path": "hardware-two.patch"}],
                        },
                    ],
                    "skips": skips,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        yield (
            root,
            series,
            local_root,
            upstream_root,
            project_one,
            project_two,
            base_one,
            base_two,
            tree_one,
            tree_two,
        )


def assert_check_only_and_idempotence() -> None:
    with fixture() as fixture_data:
        (
            root,
            series,
            local_root,
            upstream_root,
            project_one,
            project_two,
            base_one,
            base_two,
            tree_one,
            tree_two,
        ) = fixture_data
        before = (snapshot_project(project_one), snapshot_project(project_two))
        worktrees_before = (worktree_snapshot(project_one), worktree_snapshot(project_two))
        output = root.parent / "check-only.json"
        result = run_apply(
            root,
            series,
            local_root,
            upstream_root,
            "--check-only",
            "--output",
            str(output),
        )
        if result.returncode != 0 or result.stdout:
            raise AssertionError(result.stderr or result.stdout)
        state = json.loads(output.read_text(encoding="utf-8"))
        if not state["ok"] or not state["check_only"] or len(state["skips"]) != 2:
            raise AssertionError(f"unexpected check-only result: {state}")
        if (snapshot_project(project_one), snapshot_project(project_two)) != before:
            raise AssertionError("check-only changed a real project")
        if (worktree_snapshot(project_one), worktree_snapshot(project_two)) != worktrees_before:
            raise AssertionError("check-only left a worktree registration")

        result = run_apply(root, series, local_root, upstream_root)
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        state = json.loads(result.stdout)
        if not state["ok"] or {entry["status"] for entry in state["projects"]} != {"applied"}:
            raise AssertionError(f"unexpected apply result: {state}")
        if run_git(project_one, "rev-parse", "HEAD^{tree}").strip() != tree_one:
            raise AssertionError("first project tree was not applied")
        if run_git(project_two, "rev-parse", "HEAD^{tree}").strip() != tree_two:
            raise AssertionError("second project tree was not applied")

        heads_after_apply = (run_git(project_one, "rev-parse", "HEAD"), run_git(project_two, "rev-parse", "HEAD"))
        result = run_apply(root, series, local_root, upstream_root)
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        state = json.loads(result.stdout)
        if {entry["status"] for entry in state["projects"]} != {"completed"}:
            raise AssertionError(f"second apply was not idempotent: {state}")
        if (run_git(project_one, "rev-parse", "HEAD"), run_git(project_two, "rev-parse", "HEAD")) != heads_after_apply:
            raise AssertionError("second apply changed completed projects")
        if base_one == heads_after_apply[0].strip() or base_two == heads_after_apply[1].strip():
            raise AssertionError("apply did not advance project heads")


def assert_bad_series_is_atomic() -> None:
    with fixture() as (root, series, local_root, upstream_root, project_one, project_two, *_):
        before = (snapshot_project(project_one), snapshot_project(project_two))
        worktrees_before = (worktree_snapshot(project_one), worktree_snapshot(project_two))
        bad_patch = upstream_root / "bad.patch"
        bad_patch.write_text("this is not a mail patch\n", encoding="utf-8")
        value = json.loads(series.read_text(encoding="utf-8"))
        value["projects"][1]["patches"] = [{"source": "upstream", "path": "bad.patch"}]
        bad_series = root / "bad-series.json"
        bad_series.write_text(json.dumps(value), encoding="utf-8")
        result = run_apply(root, bad_series, local_root, upstream_root)
        if result.returncode != 1:
            raise AssertionError("bad second patch did not fail")
        state = json.loads(result.stdout)
        if state["ok"] or not state["errors"]:
            raise AssertionError("bad patch did not produce failure JSON")
        if (snapshot_project(project_one), snapshot_project(project_two)) != before:
            raise AssertionError("failed phase one modified a real project")
        if (worktree_snapshot(project_one), worktree_snapshot(project_two)) != worktrees_before:
            raise AssertionError("failed phase one left a worktree")


def assert_state_guards() -> None:
    with fixture() as (root, series, local_root, upstream_root, project_one, project_two, *_):
        before_head = snapshot_project(project_one)[0]
        (project_one / "state.txt").write_text("dirty\n", encoding="utf-8")
        result = run_apply(root, series, local_root, upstream_root)
        if result.returncode != 1 or "dirty" not in json.loads(result.stdout)["errors"][0]:
            raise AssertionError("dirty project was not rejected")
        run_git(project_one, "checkout", "--", "state.txt")

        value = json.loads(series.read_text(encoding="utf-8"))
        value["projects"][0]["base_head"] = "0" * 40
        wrong_base = root / "wrong-base.json"
        wrong_base.write_text(json.dumps(value), encoding="utf-8")
        result = run_apply(root, wrong_base, local_root, upstream_root)
        if result.returncode != 1:
            raise AssertionError("wrong base was not rejected")
        if snapshot_project(project_one)[0] != before_head:
            raise AssertionError("wrong base changed the real project")

        value = json.loads(series.read_text(encoding="utf-8"))
        value["projects"][0]["expected_tree"] = "0" * 40
        wrong_tree = root / "wrong-tree.json"
        wrong_tree.write_text(json.dumps(value), encoding="utf-8")
        result = run_apply(root, wrong_tree, local_root, upstream_root)
        if result.returncode != 1 or "tree mismatch" not in result.stdout:
            raise AssertionError("expected tree mismatch was not reported")

        value = json.loads(series.read_text(encoding="utf-8"))
        value["skips"][0]["predicate"] = "missing_project:frameworks/base"
        false_skip = root / "false-skip.json"
        false_skip.write_text(json.dumps(value), encoding="utf-8")
        result = run_apply(root, false_skip, local_root, upstream_root)
        if result.returncode != 1 or "skip predicate is false" not in result.stdout:
            raise AssertionError("false skip predicate was accepted")


def assert_config_error() -> None:
    with fixture() as (root, series, local_root, upstream_root, *_):
        value = json.loads(series.read_text(encoding="utf-8"))
        value["projects"][0]["base_head"] = "/absolute/not-a-head"
        invalid = root / "invalid.json"
        invalid.write_text(json.dumps(value), encoding="utf-8")
        result = run_apply(root, invalid, local_root, upstream_root)
        if result.returncode != 2 or result.stdout or not result.stderr:
            raise AssertionError("invalid series did not return rc=2 on stderr")


def main() -> int:
    assert_check_only_and_idempotence()
    assert_bad_series_is_atomic()
    assert_state_guards()
    assert_config_error()
    print("apply-a16-upstream-patches semantic tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
