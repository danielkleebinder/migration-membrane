#!/usr/bin/env bash

set -Eeuo pipefail

readonly upstream_repository="git@github.com:wasm-micro-runtime/wasm-micro-runtime.git"
readonly upstream_commit="c6fbf20d17d36b1fb5bdf75c8ef7273475daa206"

usage() {
    printf 'Usage: %s PATH_TO_PATCH [DESTINATION]\n' "$(basename "$0")"
    printf 'Example: %s ./wamr.patch ./runtime\n' "$(basename "$0")"
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage >&2
    exit 2
fi

patch_argument="${1:-${script_directory}/wamr.patch}"
destination="${2:-./runtime}"

if [[ ! -f "$patch_argument" ]]; then
    printf 'Error: patch file does not exist: %s\n' "$patch_argument" >&2
    exit 1
fi

patch_path="$(realpath "$patch_argument")"

if [[ -e "$destination" ]]; then
    printf 'Error: destination already exists: %s\n' "$destination" >&2
    printf 'Choose a new destination; this script will not overwrite it.\n' >&2
    exit 1
fi

printf 'Cloning upstream WAMR into %s\n' "$destination"
git clone --no-checkout "$upstream_repository" "$destination"

printf 'Checking out upstream revision %s\n' "$upstream_commit"
git -C "$destination" checkout --detach "$upstream_commit"

printf 'Validating patch applicability\n'
git -C "$destination" apply --check --index "$patch_path"

printf 'Applying patch\n'
git -C "$destination" apply --index "$patch_path"

printf 'Checking the reconstructed source tree\n'
git -C "$destination" diff --cached --check
git -C "$destination" apply --reverse --check --index "$patch_path"

printf '\nReconstruction completed successfully.\n'
printf 'The contribution is staged for inspection in: %s\n' "$destination"
printf 'Inspect it with:\n'
printf '  git -C %q diff --cached --stat\n' "$destination"
printf '  git -C %q diff --cached\n' "$destination"
printf 'Build it with:\n'
printf '  (cd %q && bash build.sh)\n' "$destination"
