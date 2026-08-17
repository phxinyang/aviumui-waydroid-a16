#!/usr/bin/env python3
"""Semantic tests for the single Avium A16 build entrypoint."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "scripts/avium-a16.sh"


def run(command: list[str], *, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@contextmanager
def fixture():
    temporary = tempfile.TemporaryDirectory(prefix="avium-a16-entry-")
    root = Path(temporary.name) / "aosp"
    root.mkdir()
    (root / ".repo/manifests").mkdir(parents=True)
    (root / "out/host/linux-x86/bin/lib64").mkdir(parents=True)
    ncurses_dir = root / "prebuilts/clang/host/linux-x86/clang-3289846/lib64"
    tinfo_dir = (
        root
        / "prebuilts/gcc/linux-x86/host/x86_64-linux-glibc2.17-4.8/sysroot/usr/lib"
    )
    ncurses_dir.mkdir(parents=True)
    tinfo_dir.mkdir(parents=True)
    (ncurses_dir / "libncurses.so.5").write_text("ncurses\n", encoding="utf-8")
    (tinfo_dir / "libtinfo.so.5").write_text("tinfo\n", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build/envsetup.sh").write_text(
        "case $- in *u*) printf 'envsetup received nounset\\n' >&2; return 19;; esac\n"
        "envsetup_seen=1\n"
        "lunch() { printf 'lunch %s\\n' \"$*\" >> \"$AVIUM_A16_TEST_LOG\"; }\n"
        "m() { printf 'm %s\\n' \"$*\" >> \"$AVIUM_A16_TEST_LOG\"; return \"${AVIUM_A16_M_RC:-0}\"; }\n",
        encoding="utf-8",
    )
    helper = Path(temporary.name) / "helpers"
    helper.mkdir()
    try:
        yield temporary, root, helper
    finally:
        temporary.cleanup()


def helper_scripts(helper: Path) -> None:
    write_executable(
        helper / "check-repro-inputs.py",
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "with open(os.environ['AVIUM_A16_TEST_CALLS'], 'a', encoding='utf-8') as f:\n"
        "    f.write('preflight ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(int(os.environ.get('AVIUM_A16_PREFLIGHT_RC', '0')))\n",
    )
    write_executable(
        helper / "apply-a16-upstream-patches.py",
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "with open(os.environ['AVIUM_A16_TEST_CALLS'], 'a', encoding='utf-8') as f:\n"
        "    f.write('apply ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(int(os.environ.get('AVIUM_A16_APPLY_RC', '0')))\n",
    )
    write_executable(
        helper / "apply-a16-windowing-patches.py",
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "mode = 'inputs' if '--inputs-only' in sys.argv else "
        "('check' if '--check-only' in sys.argv else 'apply')\n"
        "with open(os.environ['AVIUM_A16_TEST_CALLS'], 'a', encoding='utf-8') as f:\n"
        "    f.write('window ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "key = {'inputs': 'AVIUM_A16_WINDOW_INPUTS_RC', "
        "'check': 'AVIUM_A16_WINDOW_CHECK_RC', "
        "'apply': 'AVIUM_A16_WINDOW_APPLY_RC'}[mode]\n"
        "raise SystemExit(int(os.environ.get(key, '0')))\n",
    )
    write_executable(
        helper / "verify-a16-images.py",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['AVIUM_A16_TEST_CALLS'], 'a', encoding='utf-8') as f:\n"
        "    f.write('verify ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "args = iter(sys.argv[1:])\n"
        "values = dict(zip(args, args))\n"
        "out = sys.argv[sys.argv.index('--output') + 1]\n"
        "with open(out, 'w', encoding='utf-8') as f: json.dump({'ok': True}, f)\n",
    )


def environment(root: Path, helper: Path, calls: Path, log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AVIUM_A16_TESTING": "1",
            "AVIUM_A16_HELPER_ROOT": str(helper),
            "AVIUM_A16_MANIFEST_EPOCH": "1786061200",
            "AVIUM_A16_TEST_CALLS": str(calls),
            "AVIUM_A16_TEST_LOG": str(log),
            "PATH": f"{ROOT / 'scripts'}:{env['PATH']}",
        }
    )
    return env


def invoke(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return run([str(ENTRY), "--root", str(root), "--jobs", "3", *args], env=env, cwd=ROOT)


def assert_calls(calls: Path, expected: list[str]) -> None:
    actual = calls.read_text(encoding="utf-8").splitlines()
    if actual != expected:
        raise AssertionError(f"unexpected helper order:\n{actual}\nexpected:\n{expected}")


def main() -> int:
    with fixture() as (temporary, root, helper):
        helper_scripts(helper)
        calls = Path(temporary.name) / "calls.log"
        build_log = Path(temporary.name) / "pipeline.log"
        env = environment(root, helper, calls, build_log)

        result = invoke(root, env, "preflight")
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        preflight = (
            f"preflight {root} --lock {ROOT / 'manifests/a16-recipe-lock.json'} "
            f"--series {ROOT / 'patches/a16/release-series.json'} "
            f"--window-series {ROOT / 'patches/windowing/a16/series.json'}"
        )
        window_prefix = (
            f"window {root} --series {ROOT / 'patches/windowing/a16/series.json'} "
            f"--patch-root {ROOT / 'patches/windowing'}"
        )
        upstream_apply = (
            f"apply {root} --series {ROOT / 'patches/a16/release-series.json'} "
            f"--local-patch-root {ROOT / 'patches/a16'} "
            f"--upstream-patch-root {ROOT / 'patches/a16/upstream'}"
        )
        assert_calls(calls, [preflight, f"{window_prefix} --inputs-only"])

        calls.write_text("", encoding="utf-8")
        lock_path = root / ".repo/avium-a16.lock"
        with lock_path.open("w", encoding="utf-8") as held_lock:
            fcntl.flock(held_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = invoke(root, env, "apply")
        if result.returncode != 2 or "another Avium A16 operation" not in result.stderr:
            raise AssertionError("concurrent operation was not rejected immediately")
        if calls.read_text(encoding="utf-8"):
            raise AssertionError("locked apply ran helpers before rejecting concurrency")

        calls.write_text("", encoding="utf-8")
        env["AVIUM_A16_WINDOW_INPUTS_RC"] = "13"
        result = invoke(root, env, "apply")
        if result.returncode != 13:
            raise AssertionError("window input failure was not propagated")
        assert_calls(calls, [preflight, f"{window_prefix} --inputs-only"])
        del env["AVIUM_A16_WINDOW_INPUTS_RC"]

        calls.write_text("", encoding="utf-8")
        env["AVIUM_A16_WINDOW_APPLY_RC"] = "14"
        result = invoke(root, env, "apply")
        if result.returncode != 14:
            raise AssertionError("window apply failure was not propagated")
        assert_calls(
            calls,
            [
                preflight,
                f"{window_prefix} --inputs-only",
                upstream_apply,
                window_prefix,
            ],
        )
        del env["AVIUM_A16_WINDOW_APPLY_RC"]

        calls.write_text("", encoding="utf-8")
        env["AVIUM_A16_WINDOW_CHECK_RC"] = "15"
        result = invoke(root, env, "build")
        if result.returncode != 15:
            raise AssertionError("window final-tree check failure was not propagated")
        assert_calls(
            calls,
            [f"{preflight} --require-prepared", f"{window_prefix} --check-only"],
        )
        if build_log.exists():
            raise AssertionError("build ran after a failed window final-tree check")
        del env["AVIUM_A16_WINDOW_CHECK_RC"]

        calls.write_text("", encoding="utf-8")
        result = invoke(root, env, "apply")
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert_calls(
            calls,
            [
                preflight,
                f"{window_prefix} --inputs-only",
                upstream_apply,
                window_prefix,
            ],
        )

        calls.write_text("", encoding="utf-8")
        result = invoke(root, env, "build")
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        calls_text = calls.read_text(encoding="utf-8").splitlines()
        if (
            calls_text[:2]
            != [f"{preflight} --require-prepared", f"{window_prefix} --check-only"]
            or not calls_text[-1].startswith("verify ")
        ):
            raise AssertionError(f"build call order missing strict preflight/verify: {calls_text}")
        pipeline = build_log.read_text(encoding="utf-8").splitlines()
        if pipeline != ["lunch lineage_waydroid_arm64_only bp4a userdebug", "m -j3 systemimage vendorimage"]:
            raise AssertionError(f"wrong build pipeline: {pipeline}")
        context = json.loads((root / "out/avium-a16/build-context.json").read_text(encoding="utf-8"))
        if context["build_command"] != "m -j3 systemimage vendorimage":
            raise AssertionError("build context command mismatch")
        if context.get("status") != "complete":
            raise AssertionError("successful build context is not complete")
        if not context["started_at"].endswith("Z") or not context["finished_at"].endswith("Z"):
            raise AssertionError("build context timestamps are not UTC")
        verify_call = next(line for line in calls_text if line.startswith("verify "))
        for needle in (
            "--build-command m -j3 systemimage vendorimage",
            "--started-at ",
            "--finished-at ",
            f"--output {root / 'out/avium-a16/provenance.json'}",
            f"--window-series {ROOT / 'patches/windowing/a16/series.json'}",
            f"--window-patch-root {ROOT / 'patches/windowing'}",
        ):
            if needle not in verify_call:
                raise AssertionError(f"verifier provenance argument missing: {needle}")
        if (root / "out/host/linux-x86/bin/lib64/libncurses.so.5").read_text() != "ncurses\n":
            raise AssertionError("ncurses host library was not installed")
        if (root / "out/host/linux-x86/bin/lib64/libtinfo.so.5").read_text() != "tinfo\n":
            raise AssertionError("tinfo host library was not installed")

        calls.write_text("", encoding="utf-8")
        result = invoke(root, env, "verify")
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        verify_calls = calls.read_text(encoding="utf-8").splitlines()
        if len(verify_calls) != 1 or not verify_calls[0].startswith("verify "):
            raise AssertionError(f"verify unexpectedly ran build preflight: {verify_calls}")

        calls.write_text("", encoding="utf-8")
        (root / "out/avium-a16/build-context.json").write_text(
            json.dumps(
                {
                    "status": "complete",
                    "started_at": "2000-01-01T00:00:00Z",
                    "finished_at": "2000-01-01T00:00:01Z",
                    "build_command": "stale build",
                }
            ),
            encoding="utf-8",
        )
        env["AVIUM_A16_M_RC"] = "17"
        result = invoke(root, env, "all")
        if result.returncode == 0:
            raise AssertionError("all did not propagate the build failure")
        failed_calls = calls.read_text(encoding="utf-8").splitlines()
        if any(line.startswith("verify ") for line in failed_calls):
            raise AssertionError("all continued to verify after a failed build")
        failed_context = json.loads(
            (root / "out/avium-a16/build-context.json").read_text(encoding="utf-8")
        )
        if failed_context.get("status") != "building" or failed_context.get("finished_at") is not None:
            raise AssertionError("failed build left a stale complete build context")
        calls.write_text("", encoding="utf-8")
        result = invoke(root, env, "verify")
        if result.returncode == 0 or calls.read_text(encoding="utf-8"):
            raise AssertionError("verify accepted an incomplete build context")

    for retired in (
        ROOT / "scripts/build-system.sh",
        ROOT / "scripts/resume-build.sh",
        ROOT / "scripts/set-window-mode.sh",
        ROOT / "scripts/deploy-a16-framework-race.sh",
        ROOT / "scripts/deploy-b021.sh",
        ROOT / "scripts/deploy-flag-on.sh",
    ):
        result = run([str(retired)], env=os.environ.copy(), cwd=ROOT)
        if result.returncode != 2 or not any(
            marker in result.stderr
            for marker in ("avium-a16.sh", "per-task routing", "paired-image workflow")
        ):
            raise AssertionError(f"retired entrypoint is not fail-closed: {retired}")

    executable_scripts = sorted(ROOT.joinpath("scripts").glob("*.sh"))
    historical_tablet = "<lan-ip>" + "132"
    for script in executable_scripts:
        if historical_tablet in script.read_text(encoding="utf-8"):
            raise AssertionError(f"historical tablet address remains executable: {script}")
    topology = (ROOT / "docs/TOPOLOGY.md").read_text(encoding="utf-8")
    if "| 平板 | `<tablet-ip>` |" not in topology:
        raise AssertionError("current topology does not identify <tablet-ip>")
    print("avium-a16 entry semantic tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
