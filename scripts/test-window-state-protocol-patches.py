#!/usr/bin/env python3
"""Verify that the three window-state patches invert and replay exactly."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT_PATCHES = (
    (
        "hardware/waydroid",
        "hardware-waydroid/0001-a16-task-window-state-protocol.patch",
    ),
    (
        "frameworks/base",
        "frameworks-base/0001-waydroid-task-window-state-bridge.patch",
    ),
    (
        "device/waydroid/waydroid",
        "device-waydroid/0001-window-hal-1.3.patch",
    ),
)


def run(*command: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else ""


def patch_paths(patch: Path) -> tuple[str, ...]:
    output = run("git", "apply", "--numstat", str(patch), capture=True)
    paths = []
    for line in output.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            raise RuntimeError(f"unexpected numstat line in {patch}: {line}")
        paths.append(fields[2])
    if not paths:
        raise RuntimeError(f"patch has no paths: {patch}")
    return tuple(paths)


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} AOSP_ROOT", file=sys.stderr)
        return 2

    source_root = Path(sys.argv[1]).resolve()
    scripts = Path(__file__).resolve().parent
    patch_root = scripts.parent / "patches/windowing"
    apply_script = scripts / "apply-window-state-protocol.sh"
    out = source_root / "out"
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="window-state-patches-", dir=out
    ) as directory:
        fixture_root = Path(directory)
        expected: dict[tuple[str, str], str | None] = {}

        for project_name, patch_name in PROJECT_PATCHES:
            source_project = source_root / project_name
            fixture_project = fixture_root / project_name
            patch = patch_root / patch_name
            fixture_project.mkdir(parents=True)
            for relative in patch_paths(patch):
                source = source_project / relative
                if not source.is_file():
                    raise RuntimeError(f"current source is missing {project_name}/{relative}")
                destination = fixture_project / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                expected[(project_name, relative)] = digest(source)

            run("git", "init", "-q", cwd=fixture_project)
            run("git", "add", "-A", cwd=fixture_project)
            run(
                "git",
                "-c",
                "user.name=Window State Patch Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "current state",
                cwd=fixture_project,
            )

        run(str(apply_script), "--check", str(fixture_root))

        for project_name, patch_name in PROJECT_PATCHES:
            run(
                "git",
                "apply",
                "--reverse",
                str(patch_root / patch_name),
                cwd=fixture_root / project_name,
            )

        run(str(apply_script), "--check", str(fixture_root))
        run(str(apply_script), str(fixture_root))
        run(str(apply_script), str(fixture_root))

        for (project_name, relative), expected_digest in expected.items():
            actual = digest(fixture_root / project_name / relative)
            if actual != expected_digest:
                raise RuntimeError(
                    f"patch replay differs for {project_name}/{relative}: "
                    f"expected {expected_digest}, got {actual}"
                )

    print("window-state protocol patches invert and replay exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
