#!/usr/bin/env python3
"""Permanently validate the A16 patch-series reproducibility inputs."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


EXPECTED_SKIP = {
    "upstream:device/google/atv/0001-Lift-maxUiWidth-restiction-on-ATV.patch",
    "upstream:lineage-sdk/0008-trust-Suppress-SELinux-warning.patch",
}


class Failure(RuntimeError):
    pass


def load_applier(repo: Path):
    path = repo / "scripts/apply-a16-upstream-patches.py"
    spec = importlib.util.spec_from_file_location("a16_applier", path)
    if spec is None or spec.loader is None:
        raise Failure(f"cannot load applier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Failure(f"{path}: cannot read JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise Failure(f"{path}: top-level value is not an object")
    return value


def manifest_revisions(path: Path) -> dict[str, str]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise Failure(f"{path}: cannot parse XML: {exc}") from exc
    result: dict[str, str] = {}
    for element in root.iter():
        if element.tag not in {"project", "extend-project"}:
            continue
        project_path = element.attrib.get("path")
        revision = element.attrib.get("revision")
        if project_path and revision:
            if project_path in result:
                raise Failure(f"{path}: duplicate project path: {project_path}")
            result[project_path] = revision.lower()
    return result


def patch_set(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*.patch") if p.is_file() and not p.is_symlink()}


def series_patches(series: dict) -> list[dict]:
    return [patch for project in series["projects"] for patch in project["patches"]]


def validate(repo: Path, applier) -> tuple[dict, dict, dict]:
    lock_path = repo / "manifests/a16-recipe-lock.json"
    manifest_path = repo / "manifests/waydroid.lock.xml"
    upstream_path = repo / "patches/a16/upstream-series.json"
    release_path = repo / "patches/a16/release-series.json"
    lock = read_json(lock_path)
    upstream = applier.load_series(upstream_path)
    release = applier.load_series(release_path)
    revisions = manifest_revisions(manifest_path)

    lock_projects = {p["path"]: p for p in lock.get("projects", [])}
    if len(lock_projects) != len(lock.get("projects", [])):
        raise Failure(f"{lock_path}: duplicate project paths")
    missing = sorted(set(lock_projects) - set(revisions))
    extra = sorted(set(revisions) - set(lock_projects))
    mismatched = sorted(p for p, item in lock_projects.items() if revisions.get(p) != item.get("base_head", "").lower())
    if missing:
        raise Failure(f"{manifest_path}: missing lock projects: {', '.join(missing[:8])}")
    if extra:
        raise Failure(f"{manifest_path}: projects absent from lock: {', '.join(extra[:8])}")
    if mismatched:
        raise Failure(f"manifest/lock base_head mismatch: {', '.join(mismatched[:8])}")
    upstream_by_path = {project["path"]: project for project in upstream["projects"]}
    release_by_path = {project["path"]: project for project in release["projects"]}
    for path, project in upstream_by_path.items():
        if path not in lock_projects:
            raise Failure(f"upstream series project absent from lock: {path}")
        if path in release_by_path and release_by_path[path]["base_head"] != project["base_head"]:
            raise Failure(f"upstream/release base_head mismatch: {path}")
    for path, project in release_by_path.items():
        lock_project = lock_projects.get(path)
        if lock_project is None:
            raise Failure(f"release series project absent from lock: {path}")
        if project["base_head"] != lock_project["base_head"].lower():
            raise Failure(f"release/lock base_head mismatch: {path}")

    up_patches = series_patches(upstream)
    rel_patches = series_patches(release)
    up_ids = [f"{p['source']}:{p['path']}" for p in up_patches]
    rel_ids = [f"{p['source']}:{p['path']}" for p in rel_patches]
    if len(set(up_ids)) != len(up_ids):
        raise Failure("upstream series contains duplicate patch declarations")
    if len(set(rel_ids)) != len(rel_ids):
        raise Failure("release series contains duplicate patch declarations")
    if len(upstream["skips"]) != 2 or len({s["patch"] for s in upstream["skips"]}) != 2 or set(s["patch"] for s in upstream["skips"]) != EXPECTED_SKIP:
        raise Failure("upstream series skips do not match the two required skips")
    if len(release["skips"]) != 2 or len({s["patch"] for s in release["skips"]}) != 2 or set(s["patch"] for s in release["skips"]) != EXPECTED_SKIP:
        raise Failure("release series skips do not match the two required skips")

    upstream_root = repo / "patches/a16/upstream"
    if not upstream_root.is_dir():
        raise Failure(f"{upstream_root}: formal upstream patch root is missing")
    local_root = repo / "patches/a16"
    actual_up = patch_set(upstream_root)
    actual_local = {
        path for path in patch_set(local_root) if not path.startswith("upstream/")
    }
    declared_up = {p["path"] for p in up_patches if p["source"] == "upstream"}
    declared_release_up = {p["path"] for p in rel_patches if p["source"] == "upstream"}
    skipped_up = {s["patch"].split(":", 1)[1] for s in release["skips"] if s["patch"].startswith("upstream:")}
    # Four upstream patches are intentionally replaced by four local/manual patches.
    replaced = actual_up - declared_up - skipped_up
    if len(actual_up) != 170 or len(replaced) != 4:
        raise Failure(f"upstream inventory must contain 170 patches and exactly 4 replacements (got {len(actual_up)} and {len(replaced)})")
    if actual_up - declared_release_up - skipped_up != replaced:
        raise Failure("upstream patch inventory differs between upstream and release series")
    if declared_release_up | skipped_up | replaced != actual_up:
        raise Failure(f"upstream patch inventory has unlisted files: {sorted(actual_up - (declared_release_up | skipped_up | replaced))[:8]}")
    declared_local = {p["path"] for p in rel_patches if p["source"] == "local"}
    expected_local = actual_local
    if declared_local != expected_local:
        raise Failure(f"local patch inventory mismatch: missing={sorted(expected_local - declared_local)} extra={sorted(declared_local - expected_local)}")

    if (len([p for p in up_patches if p["source"] == "upstream"]), len([p for p in up_patches if p["source"] == "local"])) != (164, 4):
        raise Failure("upstream series classification must be direct=164, manual=4")
    if (len(rel_patches), len(release["skips"])) != (185, 2):
        raise Failure("release series must contain 185 actual patches and 2 skips")
    return upstream, release, lock


def check_aosp(repo: Path, release: dict, root: Path, applier) -> None:
    command = [
        sys.executable,
        str(repo / "scripts/apply-a16-upstream-patches.py"),
        str(root),
        "--series",
        str(repo / "patches/a16/release-series.json"),
        "--local-patch-root",
        str(repo / "patches/a16"),
        "--upstream-patch-root",
        str(repo / "patches/a16/upstream"),
        "--check-only",
    ]
    import subprocess
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise Failure(f"check-only replay failed: {detail[-3000:]}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise Failure(f"check-only replay returned invalid JSON: {exc}") from exc
    statuses = {item.get("status") for item in output.get("projects", [])}
    if not output.get("ok") or statuses - {"verified", "completed"} or len(output.get("projects", [])) != len(release["projects"]):
        raise Failure("check-only replay did not verify/complete every release project")
    errors: list[str] = []
    applied = applier.evaluate_skips(root, release, errors)
    if errors or {item["patch"] for item in applied} != EXPECTED_SKIP:
        raise Failure("check-only replay skip predicates are not both true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aosp-root", type=Path, metavar="AOSP_ROOT")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    try:
        applier = load_applier(repo)
        _, release, _ = validate(repo, applier)
        if args.aosp_root:
            check_aosp(repo, release, args.aosp_root.expanduser().resolve(), applier)
        print("A16 series self-check passed: direct=164 manual=4 skip=2 release_patches=185")
        return 0
    except Exception as exc:
        print(f"test-a16-series: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
