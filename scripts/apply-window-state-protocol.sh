#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 [--check] [AOSP_ROOT]" >&2
}

check_only=false
if [[ ${1:-} == "--check" ]]; then
    check_only=true
    shift
fi
if (( $# > 1 )); then
    usage
    exit 2
fi

root=${1:-/build}
if [[ ! -d $root ]]; then
    echo "AOSP root does not exist: $root" >&2
    exit 1
fi
root=$(cd "$root" && pwd)
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
patch_root=$(cd "$script_dir/../patches/windowing" && pwd)

projects=(
    "hardware/waydroid"
    "frameworks/base"
    "device/waydroid/waydroid"
)
patches=(
    "$patch_root/hardware-waydroid/0001-a16-task-window-state-protocol.patch"
    "$patch_root/frameworks-base/0001-waydroid-task-window-state-bridge.patch"
    "$patch_root/device-waydroid/0001-window-hal-1.3.patch"
)
states=()

for index in "${!projects[@]}"; do
    project="$root/${projects[$index]}"
    patch_file=${patches[$index]}
    if [[ ! -e $project/.git ]]; then
        echo "missing Git project: $project" >&2
        exit 1
    fi
    if [[ ! -f $patch_file ]]; then
        echo "missing patch: $patch_file" >&2
        exit 1
    fi

    if git -C "$project" apply --check "$patch_file" >/dev/null 2>&1; then
        states[$index]=applicable
    elif git -C "$project" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
        states[$index]=applied
    else
        echo "patch does not match ${projects[$index]} in either direction" >&2
        git -C "$project" apply --check "$patch_file" || true
        exit 1
    fi
done

for index in "${!projects[@]}"; do
    project="$root/${projects[$index]}"
    if [[ ${states[$index]} == applied ]]; then
        echo "already applied: ${projects[$index]}"
        continue
    fi
    if $check_only; then
        echo "applicable: ${projects[$index]}"
        continue
    fi
    git -C "$project" apply "${patches[$index]}"
    git -C "$project" diff --check
    echo "applied: ${projects[$index]}"
done
