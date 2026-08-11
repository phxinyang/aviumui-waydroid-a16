#!/usr/bin/env python3
"""Semantic tests for check-repro-inputs.py."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Iterator


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts/check-repro-inputs.py"


def run_git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(directory), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def init_repo(path: Path, filename: str = "source.txt") -> tuple[Path, str]:
    path.mkdir(parents=True)
    run_git(path, "init", "-q")
    run_git(path, "config", "user.name", "Preflight Test")
    run_git(path, "config", "user.email", "preflight@example.invalid")
    (path / filename).write_text(f"{path.name}\n", encoding="utf-8")
    run_git(path, "add", filename)
    run_git(path, "commit", "-qm", "initial")
    return path, run_git(path, "rev-parse", "HEAD").strip()


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_lock(path: Path, root: Path, project: Path, project_head: str, lfs: Path) -> dict:
    manifest = root / ".repo/manifests"
    local = root / ".repo/local_manifests/waydroid.xml"
    lock = {
        "schema_version": 1,
        "manifest_repository_head": run_git(manifest, "rev-parse", "HEAD").strip(),
        "local_manifests": {
            "waydroid.xml": hash_file(local),
        },
        "min_free_bytes": 0,
        "required_commands": ["preflight-tool"],
        "projects": [{"path": str(project.relative_to(root)), "base_head": project_head}],
        "lfs_files": [
            {
                "path": str(lfs.relative_to(root)),
                "sha256": hash_file(lfs),
                "size": lfs.stat().st_size,
            }
        ],
    }
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return lock


def proc_fixture(root: Path, command: bytes | None = None) -> Path:
    proc = root / "proc-fixture"
    proc.mkdir()
    if command is not None:
        pid = proc / "999999"
        pid.mkdir()
        (pid / "cmdline").write_bytes(command)
    return proc


def run_check(root: Path, lock: Path, *, env: dict[str, str] | None = None, output: Path | None = None):
    child_env = os.environ.copy()
    child_env["AVIUM_PREFLIGHT_TESTING"] = "1"
    child_env["AVIUM_PROC_ROOT"] = str(root / "proc-fixture")
    command_bin = root / "command-bin"
    if command_bin.is_dir():
        child_env["PATH"] = f"{command_bin}{os.pathsep}{child_env['PATH']}"
    if env:
        child_env.update(env)
    command = [sys.executable, str(CHECK), str(root), "--lock", str(lock)]
    if output is not None:
        command.extend(["--output", str(output)])
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=child_env,
    )


def run_prepared_check(
    root: Path,
    lock: Path,
    series: Path,
    *,
    window_series: Path | None = None,
    require_prepared: bool = False,
):
    child_env = os.environ.copy()
    child_env["AVIUM_PREFLIGHT_TESTING"] = "1"
    child_env["AVIUM_PROC_ROOT"] = str(root / "proc-fixture")
    command_bin = root / "command-bin"
    child_env["PATH"] = f"{command_bin}{os.pathsep}{child_env['PATH']}"
    command = [
        sys.executable,
        str(CHECK),
        str(root),
        "--lock",
        str(lock),
        "--series",
        str(series),
    ]
    if window_series is not None:
        command.extend(["--window-series", str(window_series)])
    if require_prepared:
        command.append("--require-prepared")
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=child_env,
    )


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def status_snapshot(root: Path, project: Path) -> tuple[str, str]:
    return (
        run_git(project, "status", "--porcelain=v1"),
        run_git(project, "rev-parse", "HEAD"),
    )


@contextmanager
def fixture() -> Iterator[tuple[Path, Path, Path, Path, Path]]:
    with tempfile.TemporaryDirectory(prefix="check-repro-inputs-") as directory:
        root = Path(directory)
        repo = root / ".repo"
        repo.mkdir()
        manifest, _ = init_repo(repo / "manifests", "default.xml")
        local = repo / "local_manifests"
        local.mkdir()
        (local / "waydroid.xml").write_text("<manifest/>\n", encoding="utf-8")
        project, head = init_repo(root / "hardware/waydroid")
        lfs = root / "prebuilts/mesa-tools/libLLVM.so.20.1"
        lfs.parent.mkdir(parents=True)
        lfs.write_bytes(b"real binary contents\n")
        command_bin = root / "command-bin"
        command_bin.mkdir()
        command = command_bin / "preflight-tool"
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)
        proc_fixture(root, b"safe-process\x00")
        lock_path = root.parent / "preflight-lock.json"
        write_lock(lock_path, root, project, head, lfs)
        yield root, lock_path, project, lfs, manifest


def assert_green_and_unchanged() -> None:
    with tempfile.TemporaryDirectory(prefix="check-green-parent-") as directory:
        with fixture() as (root, lock_path, project, _, _):
            ignored_pid = root / "proc-fixture" / str(os.getpid())
            ignored_pid.mkdir()
            (ignored_pid / "cmdline").write_bytes(b"ninja\x00-C\x00out\x00")
            before_tree = tree_snapshot(root)
            before_status = status_snapshot(root, project)
            result = run_check(root, lock_path)
            if result.returncode != 0:
                raise AssertionError(result.stderr or result.stdout)
            state = json.loads(result.stdout)
            if state["schema_version"] != 1 or not state["ok"]:
                raise AssertionError("green preflight was not successful")
            if not all(state["checks"].values()) or state["errors"]:
                raise AssertionError("green preflight has failed checks")

            output = Path(directory) / "state.json"
            output_result = run_check(root, lock_path, output=output)
            if output_result.returncode != 0 or output_result.stdout:
                raise AssertionError("--output did not produce the expected result")
            if json.loads(output.read_text(encoding="utf-8"))["ok"] is not True:
                raise AssertionError("--output result was not successful")
            if tree_snapshot(root) != before_tree or status_snapshot(root, project) != before_status:
                raise AssertionError("green preflight modified the input checkout")


def assert_failure(root: Path, lock_path: Path, expected: str, *, env: dict[str, str] | None = None) -> None:
    result = run_check(root, lock_path, env=env)
    if result.returncode != 1:
        raise AssertionError(f"expected preflight rc=1, got {result.returncode}: {result.stderr}")
    state = json.loads(result.stdout)
    if state["ok"] or not any(expected in error for error in state["errors"]):
        raise AssertionError(f"missing expected failure {expected!r}: {state}")


def assert_semantic_failures() -> None:
    with fixture() as (root, lock_path, project, lfs, manifest):
        lock = json.loads(lock_path.read_text(encoding="utf-8"))

        dirty_lock = root.parent / "dirty-lock.json"
        # Reuse the fixture and restore the source after each independent mutation.
        (project / "source.txt").write_text("dirty\n", encoding="utf-8")
        assert_failure(root, lock_path, "is dirty")
        run_git(project, "checkout", "--", "source.txt")

        lock["projects"][0]["base_head"] = "0" * 40
        dirty_lock.write_text(json.dumps(lock), encoding="utf-8")
        assert_failure(root, dirty_lock, "HEAD mismatch")
        lock["projects"][0]["base_head"] = run_git(project, "rev-parse", "HEAD").strip()

        lock["manifest_repository_head"] = "0" * 40
        manifest_lock = root.parent / "manifest-mismatch.json"
        manifest_lock.write_text(json.dumps(lock), encoding="utf-8")
        assert_failure(root, manifest_lock, "manifest repository HEAD")
        lock["manifest_repository_head"] = run_git(manifest, "rev-parse", "HEAD").strip()

        (root / ".repo/local_manifests/waydroid.xml").write_text("changed\n", encoding="utf-8")
        assert_failure(root, lock_path, "local manifest hash mismatch")
        (root / ".repo/local_manifests/waydroid.xml").write_text("<manifest/>\n", encoding="utf-8")

        (manifest / "default.xml").write_text("dirty manifest\n", encoding="utf-8")
        assert_failure(root, lock_path, "manifest repository is dirty")
        run_git(manifest, "checkout", "--", "default.xml")

        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:deadbeef\nsize 9\n"
        lfs.write_bytes(pointer)
        pointer_lock = root.parent / "pointer.json"
        pointer_data = json.loads(lock_path.read_text(encoding="utf-8"))
        pointer_data["lfs_files"][0]["sha256"] = hash_file(lfs)
        pointer_data["lfs_files"][0]["size"] = lfs.stat().st_size
        pointer_lock.write_text(json.dumps(pointer_data), encoding="utf-8")
        assert_failure(root, pointer_lock, "pointer is not expanded")
        lfs.write_bytes(b"wrong contents\n")
        assert_failure(root, lock_path, "hash mismatch")
        lfs.write_bytes(b"real binary contents\n")

        low_disk_lock = root.parent / "low-disk.json"
        lock["min_free_bytes"] = 1
        low_disk_lock.write_text(json.dumps(lock), encoding="utf-8")
        assert_failure(root, low_disk_lock, "free disk bytes", env={"AVIUM_FREE_BYTES": "0"})
        missing_command_lock = root.parent / "missing-command.json"
        lock["required_commands"] = ["command-that-does-not-exist"]
        missing_command_lock.write_text(json.dumps(lock), encoding="utf-8")
        assert_failure(root, missing_command_lock, "required commands")

        proc = root / "proc-fixture/999999/cmdline"
        proc.write_bytes(b"ninja\x00-C\x00out\x00")
        assert_failure(root, lock_path, "concurrent build processes")
        proc.write_bytes(b"grep logs mentioning ninja and soong_ui\x00")
        clean_search = run_check(root, lock_path)
        if clean_search.returncode != 0:
            raise AssertionError("process-name matching rejected a non-build log search")
        proc.write_bytes(b"custom-builder\x00")
        custom_lock = root.parent / "custom-pattern.json"
        custom_data = json.loads(lock_path.read_text(encoding="utf-8"))
        custom_data["process_patterns"] = ["custom-builder"]
        custom_lock.write_text(json.dumps(custom_data), encoding="utf-8")
        assert_failure(root, custom_lock, "concurrent build processes")


def assert_out_base_marker() -> None:
    with fixture() as (root, lock_path, _, _, _):
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["min_free_bytes"] = 100
        lock["min_free_bytes_with_out_base"] = 1
        lock["out_base_snapshot"] = 987
        marker_lock = lock_path.parent / "marker-lock.json"
        marker_lock.write_text(json.dumps(lock), encoding="utf-8")

        marker = root / "out/avium-a16/base-provenance.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "restored_from_snapshot": 987,
                    "restored_at": "2026-08-11T00:00:00Z",
                    "base_system_sha256": "0" * 64,
                    "base_vendor_sha256": "0" * 64,
                }
            ),
            encoding="utf-8",
        )
        result = run_check(root, marker_lock, env={"AVIUM_FREE_BYTES": "50"})
        if result.returncode != 0:
            raise AssertionError(
                f"valid out base marker should pass: {result.stderr}\n{result.stdout}"
            )
        state = json.loads(result.stdout)
        if not state["checks"]["disk_free"] or state["errors"]:
            raise AssertionError("valid out base marker did not enable the lower floor")

        marker.write_text('{"schema_version": 2}\n', encoding="utf-8")
        result = run_check(root, marker_lock, env={"AVIUM_FREE_BYTES": "50"})
        if result.returncode != 1 or "out base marker is invalid" not in result.stdout:
            raise AssertionError("invalid out base marker was not rejected")

        marker.unlink()
        result = run_check(root, marker_lock, env={"AVIUM_FREE_BYTES": "50"})
        if result.returncode != 1 or "free disk bytes" not in result.stdout:
            raise AssertionError("missing out base marker did not apply the full floor")


def assert_config_errors() -> None:
    with fixture() as (root, lock_path, _, _, _):
        invalid = json.loads(lock_path.read_text(encoding="utf-8"))
        invalid["schema_version"] = 2
        bad_lock = lock_path.parent / "bad-schema.json"
        bad_lock.write_text(json.dumps(invalid), encoding="utf-8")
        result = run_check(root, bad_lock)
        if result.returncode != 2 or result.stdout or not result.stderr:
            raise AssertionError("invalid lock schema did not return rc=2 on stderr")

        missing_root = root.parent / "missing-aosp-root"
        result = run_check(missing_root, lock_path)
        if result.returncode != 1:
            raise AssertionError("missing AOSP_ROOT did not return rc=1")
        state = json.loads(result.stdout)
        if state["ok"] or not state["errors"]:
            raise AssertionError("missing AOSP_ROOT did not produce failure JSON")


def assert_prepared_state() -> None:
    with fixture() as (root, lock_path, project, _, _):
        base = run_git(project, "rev-parse", "HEAD").strip()
        (project / "source.txt").write_text("prepared\n", encoding="utf-8")
        run_git(project, "add", "source.txt")
        run_git(project, "commit", "-qm", "prepared")
        prepared_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
        run_git(project, "reset", "--hard", base)
        series = root.parent / "prepared-series.json"
        series.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": [
                        {
                            "path": "hardware/waydroid",
                            "expected_tree": prepared_tree,
                        }
                    ],
                    "skips": [],
                }
            ),
            encoding="utf-8",
        )
        either_base = run_prepared_check(root, lock_path, series)
        if either_base.returncode != 0:
            raise AssertionError(either_base.stderr or either_base.stdout)
        require_base = run_prepared_check(
            root, lock_path, series, require_prepared=True
        )
        if require_base.returncode != 1 or "prepared tree mismatch" not in require_base.stdout:
            raise AssertionError("strict prepared state accepted the base tree")
        run_git(project, "cherry-pick", "HEAD@{1}")
        prepared = run_prepared_check(root, lock_path, series, require_prepared=True)
        if prepared.returncode != 0:
            raise AssertionError(prepared.stderr or prepared.stdout)


def assert_window_prepared_state() -> None:
    with fixture() as (root, lock_path, project, _, _):
        base = run_git(project, "rev-parse", "HEAD").strip()
        (project / "source.txt").write_text("release\n", encoding="utf-8")
        run_git(project, "add", "source.txt")
        run_git(project, "commit", "-qm", "release")
        release_head = run_git(project, "rev-parse", "HEAD").strip()
        release_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()

        (project / "source.txt").write_text("window\n", encoding="utf-8")
        run_git(project, "add", "source.txt")
        run_git(project, "commit", "-qm", "window")
        window_head = run_git(project, "rev-parse", "HEAD").strip()
        window_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
        run_git(project, "reset", "--hard", base)

        release_series = root.parent / "window-release-series.json"
        release_series.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": [
                        {
                            "path": "hardware/waydroid",
                            "expected_tree": release_tree,
                        }
                    ],
                    "skips": [],
                }
            ),
            encoding="utf-8",
        )
        window_series = root.parent / "window-series.json"
        window_value = {
            "schema_version": 1,
            "projects": [
                {
                    "path": "hardware/waydroid",
                    "base_tree": release_tree,
                    "expected_tree": window_tree,
                    "patches": [
                        {"path": "a16/test.patch", "sha256": "1" * 64}
                    ],
                }
            ],
        }
        window_series.write_text(json.dumps(window_value), encoding="utf-8")

        base_allowed = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if base_allowed.returncode != 0:
            raise AssertionError(base_allowed.stderr or base_allowed.stdout)
        base_strict = run_prepared_check(
            root,
            lock_path,
            release_series,
            window_series=window_series,
            require_prepared=True,
        )
        if base_strict.returncode != 1 or window_tree not in base_strict.stdout:
            raise AssertionError("strict window state accepted the base checkout")

        run_git(project, "cherry-pick", release_head)
        release_allowed = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if release_allowed.returncode != 0:
            raise AssertionError(release_allowed.stderr or release_allowed.stdout)
        release_strict = run_prepared_check(
            root,
            lock_path,
            release_series,
            window_series=window_series,
            require_prepared=True,
        )
        if release_strict.returncode != 1:
            raise AssertionError("strict window state accepted the release-only tree")

        run_git(project, "cherry-pick", window_head)
        final = run_prepared_check(
            root,
            lock_path,
            release_series,
            window_series=window_series,
            require_prepared=True,
        )
        if final.returncode != 0:
            raise AssertionError(final.stderr or final.stdout)

        wrong_base = json.loads(json.dumps(window_value))
        wrong_base["projects"][0]["base_tree"] = "0" * 40
        window_series.write_text(json.dumps(wrong_base), encoding="utf-8")
        mismatch = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if mismatch.returncode != 1 or "window base tree mismatch" not in mismatch.stdout:
            raise AssertionError("window base tree was not linked to the release tree")

        invalid = json.loads(json.dumps(window_value))
        invalid["projects"][0]["patches"][0]["path"] = "../escape.patch"
        window_series.write_text(json.dumps(invalid), encoding="utf-8")
        escaped = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if escaped.returncode != 2 or "must not contain '..'" not in escaped.stderr:
            raise AssertionError("window patch path escape was accepted")

        invalid = json.loads(json.dumps(window_value))
        invalid["projects"][0]["patches"][0]["sha256"] = "invalid"
        window_series.write_text(json.dumps(invalid), encoding="utf-8")
        digest = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if digest.returncode != 2 or "SHA-256" not in digest.stderr:
            raise AssertionError("invalid window patch digest was accepted")

        duplicate = json.dumps(window_value).replace(
            '"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1
        )
        window_series.write_text(duplicate, encoding="utf-8")
        duplicate_result = run_prepared_check(
            root, lock_path, release_series, window_series=window_series
        )
        if duplicate_result.returncode != 2 or "duplicate JSON field" not in duplicate_result.stderr:
            raise AssertionError("duplicate window series field was accepted")


def main() -> int:
    assert_green_and_unchanged()
    assert_semantic_failures()
    assert_out_base_marker()
    assert_config_errors()
    assert_prepared_state()
    assert_window_prepared_state()
    print("check-repro-inputs semantic tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
