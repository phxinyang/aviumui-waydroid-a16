#!/usr/bin/env python3
"""Static guardrails for the reproducible A16 build container definition."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "docker/Dockerfile"
BASE_DIGEST = (
    "ubuntu:24.04@sha256:"
    "4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90"
)
REPO_URL = "https://storage.googleapis.com/git-repo-downloads/repo"
REPO_DIGEST = "1211b57b57e4122a9c546295a59b37d24068f1164d0e87bef096d5323c413e4f"


def main() -> int:
    text = DOCKERFILE.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not re.search(rf"^FROM {re.escape(BASE_DIGEST)}\s*$", text, re.MULTILINE):
        raise AssertionError("Ubuntu 24.04 base image must use the approved digest")
    if text.count(REPO_URL) != 1:
        raise AssertionError("repo must have exactly one fixed download URL")
    if text.count(REPO_DIGEST) != 1:
        raise AssertionError("repo must have exactly one pinned SHA-256")

    download = next(i for i, line in enumerate(lines) if REPO_URL in line)
    checksum = next(i for i, line in enumerate(lines) if "sha256sum -c" in line)
    chmod = next(i for i, line in enumerate(lines) if "chmod +x /usr/local/bin/repo" in line)
    if not download < checksum < chmod:
        raise AssertionError("repo checksum must be checked before chmod")
    if "curl -fsSL" not in lines[download]:
        raise AssertionError("repo download must fail on HTTP errors")
    if "-o /usr/local/bin/repo" not in lines[download + 1]:
        raise AssertionError("repo download must target the installed launcher")

    required = {
        "python3": "python 3 support",
        "python3.12": "python 3.12 support",
        "git-lfs": "git LFS support",
        "glslang-tools": "glslang support",
        "meson==1.7.2": "Meson 1.7.2",
    }
    for token, description in required.items():
        if token not in text:
            raise AssertionError(f"missing {description}: {token}")

    print("Dockerfile static checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
