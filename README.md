# AviumUI × Waydroid A16

[简体中文](README_CN.md)

A Waydroid arm64 build recipe for AviumUI (LineageOS 23.2 / Android 16).
This repository contains no Android source code — only a locked manifest,
patch series, and build entrypoint that produce a paired
`system.img` / `vendor.img` from the official AviumUI manifest from scratch.

## Layout

```text
manifests/   waydroid.lock.xml (locked local manifest, pins every project revision)
upstream/    Waydroid upstream repos as git submodules (pinned to the locked revisions)
patches/
  a16/       A16 Waydroid porting patches (upstream / local fixes / manual)
  windowing/ Multi-window patch series (per-task Wayland windows)
scripts/     avium-a16.sh build entrypoint + patch apply/verify helpers + self-tests
docker/      Ubuntu 24.04 build environment (pinned base image)
docs/        Sources, porting, window architecture, fix ledger
```

## Build

Inside the Docker environment (or an equivalent Ubuntu 24.04 environment):

```bash
repo init -u https://github.com/AviumUI/android_manifests \
  -b 981823afd5a1c3fcf740cd3b4eeeb61331ca8304 \
  --manifest-upstream-branch avium-16.2 --git-lfs
mkdir -p .repo/local_manifests
cp manifests/waydroid.lock.xml .repo/local_manifests/waydroid.xml
repo sync
scripts/avium-a16.sh --root "$PWD" all
```

Outputs land in `out/target/product/waydroid_arm64_only/system.img` and
`vendor.img`; provenance is recorded in `out/avium-a16/provenance.json`.

## Source sourcing

This project fetches all Android source from upstream at build time:

- **AviumUI** (`github.com/AviumUI/android_manifests`, branch `avium-16.2`):
  LineageOS 23.2 / Android 16 base source, ~1085 projects.
- **Waydroid components** (`waydroid.lock.xml`, layered as a local manifest):
  33 projects from waydroid / WayDroid-ATV / intel / android-generic and
  others, covering device trees, HALs, media stack, and GApps.

The core Waydroid repositories are also referenced as git submodules under
`upstream/`, pinned to the same revisions as the manifest:

```bash
git submodule update --init --recursive
```

`manifests/a16-recipe-lock.json` pins the AviumUI manifest HEAD, local
manifest SHA-256, every project revision, and LFS file hashes. The patch
series (`patches/`) is applied on the locked source; final trees are
verified against the series.

## Docs

- [docs/SOURCES.md](docs/SOURCES.md): sources and input locks
- [docs/PORTING-A16.md](docs/PORTING-A16.md): A16 porting notes
- [docs/WINDOW-ARCHITECTURE.md](docs/WINDOW-ARCHITECTURE.md): multi-window architecture
- [docs/FIX-LEDGER.md](docs/FIX-LEDGER.md): fix ledger

## License

This repository is released under Apache-2.0 (see [LICENSE](LICENSE)).
Patches retain the licenses of the upstream projects they modify; patches
for GPL-licensed Waydroid components follow GPL-3.0. See [NOTICE](NOTICE).
