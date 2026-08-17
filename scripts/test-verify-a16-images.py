#!/usr/bin/env python3
"""Semantic tests for verify-a16-images.py."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Iterator


ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "scripts/verify-a16-images.py"


def run_git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(directory), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def init_project(root: Path, relative: str) -> tuple[Path, str, str]:
    project = root / relative
    project.mkdir(parents=True)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Image Verify Test")
    run_git(project, "config", "user.email", "image@example.invalid")
    (project / "source.txt").write_text("base\n", encoding="utf-8")
    run_git(project, "add", "source.txt")
    run_git(project, "commit", "-qm", "base")
    base = run_git(project, "rev-parse", "HEAD").strip()
    base_tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
    return project, base, base_tree


def advance_project(project: Path) -> str:
    (project / "source.txt").write_text("series-complete\n", encoding="utf-8")
    run_git(project, "add", "source.txt")
    run_git(project, "commit", "-qm", "series")
    tree = run_git(project, "rev-parse", "HEAD^{tree}").strip()
    return tree


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_verify(
    root: Path,
    lock: Path,
    series: Path,
    window_series: Path,
    window_patch_root: Path,
    output: Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            str(root),
            "--lock",
            str(lock),
            "--series",
            str(series),
            "--window-series",
            str(window_series),
            "--window-patch-root",
            str(window_patch_root),
            "--output",
            str(output),
            "--build-command",
            "m -j8 systemimage vendorimage",
            "--started-at",
            "2026-08-10T00:00:00Z",
            "--finished-at",
            "2026-08-10T01:00:00Z",
            *extra,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


@contextmanager
def fixture() -> Iterator[
    tuple[Path, Path, Path, Path, Path, Path, Path, str, str, str]
]:
    with tempfile.TemporaryDirectory(prefix="verify-a16-images-") as directory:
        root = Path(directory)
        repo = root / ".repo"
        repo.mkdir()
        manifests, manifest_head, _ = init_project(repo, "manifests")
        local = repo / "local_manifests"
        local.mkdir()
        local_file = local / "waydroid.xml"
        local_file.write_text("<manifest/>\n", encoding="utf-8")
        series_project, base_head, _ = init_project(root, "frameworks/base")
        base_project, base_project_head, _ = init_project(root, "hardware/waydroid")
        release_tree = advance_project(series_project)
        (series_project / "source.txt").write_text(
            "window-complete\n", encoding="utf-8"
        )
        run_git(series_project, "add", "source.txt")
        run_git(series_project, "commit", "-qm", "window")
        window_tree = run_git(series_project, "rev-parse", "HEAD^{tree}").strip()
        product = root / "out/target/product/waydroid_arm64_only"
        product.mkdir(parents=True)
        system = product / "system.img"
        vendor = product / "vendor.img"
        system.write_bytes(b"system image\n")
        vendor.write_bytes(b"vendor image\n")
        image_mtime = 1786321800
        os.utime(system, (image_mtime, image_mtime))
        os.utime(vendor, (image_mtime, image_mtime))
        lock = root / "lock.json"
        lock.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "manifest_repository_head": manifest_head,
                    "local_manifests": {"waydroid.xml": digest(local_file)},
                    "projects": [
                        {"path": "frameworks/base", "base_head": base_head},
                        {"path": "hardware/waydroid", "base_head": base_project_head},
                    ],
                }
            ),
            encoding="utf-8",
        )
        series = root / "series.json"
        series.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": [
                        {
                            "path": "frameworks/base",
                            "base_head": base_head,
                            "expected_tree": release_tree,
                            "patches": [],
                        }
                    ],
                    "skips": [],
                }
            ),
            encoding="utf-8",
        )
        window_patch_root = root / "recipe-window-patches"
        window_patch = window_patch_root / "a16/frameworks-base/0001.patch"
        window_patch.parent.mkdir(parents=True, exist_ok=True)
        window_patch.write_bytes(b"window patch contents\n")
        window_series = root / "window-series.json"
        window_series.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "projects": [
                        {
                            "path": "frameworks/base",
                            "base_tree": release_tree,
                            "expected_tree": window_tree,
                            "patches": [
                                {
                                    "path": "a16/frameworks-base/0001.patch",
                                    "sha256": digest(window_patch),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        output = product / "provenance.json"
        yield (
            root,
            lock,
            series,
            window_series,
            window_patch_root,
            output,
            system,
            release_tree,
            window_tree,
            base_project_head,
        )


def assert_green() -> None:
    with fixture() as (
        root,
        lock,
        series,
        window_series,
        window_patch_root,
        output,
        system,
        _,
        window_tree,
        base_project_head,
    ):
        before = {
            "project": run_git(root / "frameworks/base", "status", "--porcelain=v1"),
            "head": run_git(root / "frameworks/base", "rev-parse", "HEAD"),
            "image": system.read_bytes(),
        }
        result = run_verify(
            root, lock, series, window_series, window_patch_root, output
        )
        if result.returncode != 0 or result.stderr:
            raise AssertionError(result.stderr or result.stdout)
        state = json.loads(output.read_text(encoding="utf-8"))
        if state["schema_version"] != 1 or state["product"] != "waydroid_arm64_only":
            raise AssertionError("output metadata is incorrect")
        if state["manifest"]["head"] != run_git(root / ".repo/manifests", "rev-parse", "HEAD").strip():
            raise AssertionError("manifest head is missing")
        if state["series_sha256"] != digest(series):
            raise AssertionError("series digest is incorrect")
        if state["window_series_sha256"] != digest(window_series):
            raise AssertionError("window series digest is incorrect")
        expected_patches = [
            {
                "project": "frameworks/base",
                "path": "a16/frameworks-base/0001.patch",
                "sha256": digest(window_patch_root / "a16/frameworks-base/0001.patch"),
            }
        ]
        if state["window_patches"] != expected_patches:
            raise AssertionError("window patch provenance is incorrect")
        if state["recipe_lock_sha256"] != digest(lock):
            raise AssertionError("recipe lock digest is incorrect")
        projects = {item["path"]: item for item in state["source_projects"]}
        if projects["frameworks/base"]["tree"] != window_tree:
            raise AssertionError("window project tree is incorrect")
        if projects["hardware/waydroid"]["head"] != base_project_head:
            raise AssertionError("lock-only project head is incorrect")
        for name in ("system", "vendor"):
            image = state["images"][name]
            image_path = root / image["path"]
            if image["sha256"] != digest(image_path) or image["size"] != image_path.stat().st_size:
                raise AssertionError(f"image metadata is incorrect: {name}")
        if run_git(root / "frameworks/base", "status", "--porcelain=v1") != before["project"]:
            raise AssertionError("green verification dirtied source")
        if run_git(root / "frameworks/base", "rev-parse", "HEAD") != before["head"]:
            raise AssertionError("green verification changed source HEAD")
        if system.read_bytes() != before["image"]:
            raise AssertionError("green verification changed image")


def assert_failure(mutator, expected: str, *, preserve_output: bool = True) -> None:
    with fixture() as (
        root,
        lock,
        series,
        window_series,
        window_patch_root,
        output,
        system,
        *_
    ):
        output.write_text("sentinel\n", encoding="utf-8")
        mutator(root, lock, series, window_series, window_patch_root, system)
        before = output.read_bytes()
        result = run_verify(
            root, lock, series, window_series, window_patch_root, output
        )
        if result.returncode == 0 or expected not in result.stderr:
            raise AssertionError(f"expected {expected!r}: rc={result.returncode}, stderr={result.stderr}")
        if preserve_output and output.read_bytes() != before:
            raise AssertionError("verification failure replaced output")


def dirty(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    (root / "frameworks/base/source.txt").write_text("dirty\n", encoding="utf-8")


def wrong_series_tree(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(series.read_text(encoding="utf-8"))
    value["projects"][0]["expected_tree"] = "0" * 40
    series.write_text(json.dumps(value), encoding="utf-8")


def missing_system(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    system.unlink()


def empty_system(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    system.write_bytes(b"")


def image_newer_than_finished(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    os.utime(system, (1786325400, 1786325400))


def symlink_system(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    target = root / "outside-system.img"
    target.write_bytes(b"outside")
    system.unlink()
    system.symlink_to(target)


def wrong_manifest(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(lock.read_text(encoding="utf-8"))
    value["manifest_repository_head"] = "0" * 40
    lock.write_text(json.dumps(value), encoding="utf-8")


def dirty_manifest(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    (root / ".repo/manifests/source.txt").write_text("dirty\n", encoding="utf-8")


def wrong_series_base(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(series.read_text(encoding="utf-8"))
    value["projects"][0]["base_head"] = "0" * 40
    series.write_text(json.dumps(value), encoding="utf-8")


def wrong_local_manifest(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    (root / ".repo/local_manifests/waydroid.xml").write_text("changed\n", encoding="utf-8")


def wrong_window_tree(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(window_series.read_text(encoding="utf-8"))
    value["projects"][0]["expected_tree"] = "0" * 40
    window_series.write_text(json.dumps(value), encoding="utf-8")


def wrong_window_base(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(window_series.read_text(encoding="utf-8"))
    value["projects"][0]["base_tree"] = "0" * 40
    window_series.write_text(json.dumps(value), encoding="utf-8")


def tamper_window_patch(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    patch = patch_root / "a16/frameworks-base/0001.patch"
    patch.write_bytes(patch.read_bytes() + b"tampered\n")


def symlink_window_patch(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    patch = patch_root / "a16/frameworks-base/0001.patch"
    target = patch.with_name("target.patch")
    patch.rename(target)
    patch.symlink_to(target.name)


def escape_window_patch(root: Path, lock: Path, series: Path, window_series: Path, patch_root: Path, system: Path) -> None:
    value = json.loads(window_series.read_text(encoding="utf-8"))
    value["projects"][0]["patches"][0]["path"] = "../escape.patch"
    window_series.write_text(json.dumps(value), encoding="utf-8")


def assert_failures() -> None:
    assert_failure(dirty, "project is dirty")
    assert_failure(wrong_series_tree, "window base tree mismatch")
    assert_failure(missing_system, "system.img")
    assert_failure(empty_system, "non-empty")
    assert_failure(image_newer_than_finished, "provenance is stale")
    assert_failure(symlink_system, "symlink")
    assert_failure(wrong_manifest, "manifest repository HEAD mismatch")
    assert_failure(dirty_manifest, "manifest repository is dirty")
    assert_failure(wrong_series_base, "series base HEAD does not match input lock")
    assert_failure(wrong_local_manifest, "local_manifests")
    assert_failure(wrong_window_tree, "window expected tree mismatch")
    assert_failure(wrong_window_base, "window base tree mismatch")
    assert_failure(tamper_window_patch, "window patch sha256 mismatch")
    assert_failure(symlink_window_patch, "window patch is a symlink")
    assert_failure(escape_window_patch, "must not contain '..'")


def assert_output_escape_is_config_error() -> None:
    with fixture() as (
        root,
        lock,
        series,
        window_series,
        window_patch_root,
        *_
    ):
        result = run_verify(
            root,
            lock,
            series,
            window_series,
            window_patch_root,
            root / "outside.json",
        )
        if result.returncode != 2 or result.stdout or not result.stderr:
            raise AssertionError("output escape was not rejected as a config error")


def assert_timestamp_order_is_config_error() -> None:
    with fixture() as (
        root,
        lock,
        series,
        window_series,
        window_patch_root,
        output,
        *_,
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(root),
                "--lock",
                str(lock),
                "--series",
                str(series),
                "--window-series",
                str(window_series),
                "--window-patch-root",
                str(window_patch_root),
                "--output",
                str(output),
                "--build-command",
                "m -j8 systemimage vendorimage",
                "--started-at",
                "2026-08-10T02:00:00Z",
                "--finished-at",
                "2026-08-10T01:00:00Z",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 2 or "finished-at" not in result.stderr:
            raise AssertionError("reverse build timestamps were not rejected")


def main() -> int:
    assert_green()
    assert_failures()
    assert_output_escape_is_config_error()
    assert_timestamp_order_is_config_error()
    print("verify-a16-images semantic tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
