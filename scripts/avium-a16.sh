#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat >&2 <<'EOF'
usage: avium-a16.sh [--root AOSP_ROOT] [--jobs N] [--provenance PATH] \
    preflight|apply|build|verify|all
EOF
}

die() {
    printf 'avium-a16: %s\n' "$*" >&2
    exit 2
}

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
root=/build
jobs=8
provenance=
testing=${AVIUM_A16_TESTING:-0}

while (( $# )); do
    case $1 in
        --root)
            (( $# >= 2 )) || die "--root requires a value"
            root=$2
            shift 2
            ;;
        --jobs)
            (( $# >= 2 )) || die "--jobs requires a value"
            jobs=$2
            shift 2
            ;;
        --provenance)
            (( $# >= 2 )) || die "--provenance requires a value"
            provenance=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -* )
            die "unknown option: $1"
            ;;
        *)
            break
            ;;
    esac
done

(( $# == 1 )) || { usage; exit 2; }
command=$1
case $command in
    preflight|apply|build|verify|all) ;;
    *) die "unknown command: $command" ;;
esac

[[ $jobs =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
if [[ ! -d $root ]]; then
    die "AOSP root is not a directory: $root"
fi
root=$(cd -- "$root" && pwd -P)

if [[ -z $provenance ]]; then
    provenance="$root/out/avium-a16/provenance.json"
fi
if [[ $provenance != /* ]]; then
    provenance=$(readlink -m -- "$provenance")
else
    provenance=$(readlink -m -- "$provenance")
fi

lock=$repo_root/manifests/a16-recipe-lock.json
series=$repo_root/patches/a16/release-series.json
upstream_patch_root=$repo_root/patches/a16/upstream
window_series=$repo_root/patches/windowing/a16/series.json
window_patch_root=$repo_root/patches/windowing
check_helper=$repo_root/scripts/check-repro-inputs.py
apply_helper=$repo_root/scripts/apply-a16-upstream-patches.py
window_apply_helper=$repo_root/scripts/apply-a16-windowing-patches.py
verify_helper=$repo_root/scripts/verify-a16-images.py
envsetup=$root/build/envsetup.sh
if [[ $testing == 1 ]]; then
    helper_root=${AVIUM_A16_HELPER_ROOT:-$repo_root/scripts}
    check_helper=${AVIUM_A16_CHECK_HELPER:-$helper_root/check-repro-inputs.py}
    apply_helper=${AVIUM_A16_APPLY_HELPER:-$helper_root/apply-a16-upstream-patches.py}
    window_apply_helper=${AVIUM_A16_WINDOW_APPLY_HELPER:-$helper_root/apply-a16-windowing-patches.py}
    verify_helper=${AVIUM_A16_VERIFY_HELPER:-$helper_root/verify-a16-images.py}
    envsetup=${AVIUM_A16_ENVSETUP:-$envsetup}
fi

lock_file=$root/.repo/avium-a16.lock
build_dir=$root/out/avium-a16
build_log=$build_dir/build.log
build_context=$build_dir/build-context.json

require_file() {
    [[ -f $1 ]] || die "missing file: $1"
}

run_preflight() {
    local prepared=$1
    local -a args=(
        "$root"
        --lock "$lock"
        --series "$series"
        --window-series "$window_series"
    )
    if [[ $prepared == 1 ]]; then
        args+=(--require-prepared)
    fi
    python3 "$check_helper" "${args[@]}"
}

run_apply() {
    python3 "$apply_helper" "$root" \
        --series "$series" \
        --local-patch-root "$repo_root/patches/a16" \
        --upstream-patch-root "$upstream_patch_root"
}

run_window_inputs() {
    python3 "$window_apply_helper" "$root" \
        --series "$window_series" \
        --patch-root "$window_patch_root" \
        --inputs-only
}

run_window_apply() {
    python3 "$window_apply_helper" "$root" \
        --series "$window_series" \
        --patch-root "$window_patch_root"
}

run_window_check() {
    python3 "$window_apply_helper" "$root" \
        --series "$window_series" \
        --patch-root "$window_patch_root" \
        --check-only
}

find_host_library() {
    local source_dir=$1
    local library=$2
    local candidate
    candidate=$(find "$source_dir" -maxdepth 1 \( -type f -o -type l \) -name "$library*" -print | sort | head -n 1)
    [[ -n $candidate ]] || die "missing host library $library in $source_dir"
    readlink -f -- "$candidate"
}

prepare_host_libraries() {
    local target=$root/out/host/linux-x86/bin/lib64
    local ncurses_dir=$root/prebuilts/clang/host/linux-x86/clang-3289846/lib64
    local tinfo_dir=$root/prebuilts/gcc/linux-x86/host/x86_64-linux-glibc2.17-4.8/sysroot/usr/lib
    if [[ $testing == 1 ]]; then
        local override=${AVIUM_A16_HOST_LIB_SOURCE:-${AVIUM_A16_HOST_LIB_DIR:-}}
        if [[ -n $override ]]; then
            ncurses_dir=$override
            tinfo_dir=$override
        fi
        ncurses_dir=${AVIUM_A16_NCURSES_SOURCE_DIR:-$ncurses_dir}
        tinfo_dir=${AVIUM_A16_TINFO_SOURCE_DIR:-$tinfo_dir}
    fi
    local ncurses_source
    local tinfo_source
    ncurses_source=$(find_host_library "$ncurses_dir" libncurses.so.5)
    tinfo_source=$(find_host_library "$tinfo_dir" libtinfo.so.5)
    mkdir -p -- "$target"
    install -m 0644 -- "$ncurses_source" "$target/libncurses.so.5"
    install -m 0644 -- "$tinfo_source" "$target/libtinfo.so.5"
}

manifest_epoch() {
    if [[ $testing == 1 && -n ${AVIUM_A16_MANIFEST_EPOCH:-} ]]; then
        printf '%s\n' "$AVIUM_A16_MANIFEST_EPOCH"
        return
    fi
    git --no-optional-locks -C "$root/.repo/manifests" show -s --format=%ct HEAD
}

write_build_context() {
    local started=$1
    local finished=$2
    local temporary=$build_context.tmp.$$
    mkdir -p -- "$build_dir"
    printf '{\n  "build_command": "m -j%s systemimage vendorimage",\n  "finished_at": "%s",\n  "started_at": "%s",\n  "status": "complete"\n}\n' \
        "$jobs" "$finished" "$started" > "$temporary"
    mv -f -- "$temporary" "$build_context"
}

write_incomplete_build_context() {
    local started=$1
    local temporary=$build_context.tmp.$$
    mkdir -p -- "$build_dir"
    printf '{\n  "build_command": "m -j%s systemimage vendorimage",\n  "finished_at": null,\n  "started_at": "%s",\n  "status": "building"\n}\n' \
        "$jobs" "$started" > "$temporary"
    mv -f -- "$temporary" "$build_context"
}

read_build_context() {
    require_file "$build_context"
    python3 - "$build_context" <<'PY'
import json
import sys

value = json.loads(open(sys.argv[1], encoding="utf-8").read())
if value.get("status") != "complete":
    raise SystemExit("build context is not complete")
for key in ("started_at", "finished_at", "build_command"):
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise SystemExit(f"build context missing {key}")
    print(item)
PY
}

run_verify() {
    local -a context
    mapfile -t context < <(read_build_context)
    (( ${#context[@]} == 3 )) || die "build context must contain three values"
    python3 "$verify_helper" "$root" \
        --lock "$lock" \
        --series "$series" \
        --window-series "$window_series" \
        --window-patch-root "$window_patch_root" \
        --output "$provenance" \
        --build-command "${context[2]}" \
        --started-at "${context[0]}" \
        --finished-at "${context[1]}"
}

run_build() {
    local started
    started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    write_incomplete_build_context "$started"
    require_file "$envsetup"
    prepare_host_libraries
    cd -- "$root"
    export CCACHE_DIR="$root/.ccache"
    export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
    export LC_ALL=C
    export BUILD_USERNAME=avium
    export BUILD_HOSTNAME=avium-a16
    # Waydroid userdebug runs the debug ART runtime (read barrier/CMC), which
    # does not match a preopted boot image compiled by the release dex2oat.
    # Disable dexpreopt so the device generates a matching boot image on first
    # boot instead of crashing zygote with a read-barrier mismatch.
    export WITH_DEXPREOPT=false
    local build_datetime
    build_datetime=$(manifest_epoch)
    export BUILD_DATETIME="$build_datetime"
    local finished
    mkdir -p -- "$build_dir"
    : > "$build_log"

    build_pipeline() {
        set +u
        # shellcheck source=/dev/null
        source "$envsetup" || return $?
        lunch lineage_waydroid_arm64_only bp4a userdebug || return $?
        m "-j$jobs" systemimage vendorimage || return $?
    }

    set +e
    build_pipeline 2>&1 | tee "$build_log"
    local -a pipeline_status=("${PIPESTATUS[@]}")
    set -e
    (( pipeline_status[0] == 0 )) || return "${pipeline_status[0]}"
    (( pipeline_status[1] == 0 )) || die "failed to write build log: $build_log"

    finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    write_build_context "$started" "$finished"
    run_verify
}

run_locked() {
    local action=$1
    mkdir -p -- "$(dirname -- "$lock_file")"
    exec {lock_fd}>"$lock_file"
    flock -n "$lock_fd" || die "another Avium A16 operation holds $lock_file"
    "$action"
}

preflight_action() {
    run_preflight 0
    run_window_inputs
}

apply_action() {
    run_preflight 0
    run_window_inputs
    run_apply
    run_window_apply
}

build_action() {
    run_preflight 1
    run_window_check
    run_build
}

verify_action() {
    run_verify
}

all_action() {
    run_preflight 0
    run_window_inputs
    run_apply
    run_window_apply
    run_preflight 1
    run_window_check
    run_build
}

case $command in
    preflight)
        preflight_action
        ;;
    apply)
        run_locked apply_action
        ;;
    build)
        run_locked build_action
        ;;
    verify)
        run_locked verify_action
        ;;
    all)
        run_locked all_action
        ;;
esac
