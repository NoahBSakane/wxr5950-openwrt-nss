#!/usr/bin/env bash
set -euo pipefail
if (( $# != 2 )); then
  printf 'usage: %s SOURCE_FILES TARGET_FILES\n' "$0" >&2
  exit 2
fi
[[ -d "$1" ]] || { printf 'Missing files overlay: %s\n' "$1" >&2; exit 1; }
mkdir -p -- "$2"
while IFS= read -r -d '' source; do
  relative=${source#"$1"/}
  if [[ -e "$2/$relative" || -L "$2/$relative" ]]; then
    printf 'Builder file collision: %s\n' "$relative" >&2
    exit 1
  fi
done < <(find "$1" \( -type f -o -type l \) -print0)
rsync -a -- "$1/" "$2/"
