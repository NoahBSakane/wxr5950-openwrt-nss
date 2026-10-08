#!/usr/bin/env bash
# Adapted from Qualcommax_NSS_Builder/scripts/prepare-build.sh (edma-nss).
# Prune devices and apply package overrides BEFORE the first defconfig.
set -euo pipefail

: "${OPENWRT_DIR:?OPENWRT_DIR required}"
: "${BUILDER_REPO:?BUILDER_REPO required}"
: "${REQUIRED_CONFIG:?REQUIRED_CONFIG required}"
repo_dir="$(cd -- "$(dirname -- "$0")/.." && pwd)"
variant=edma-nss
common_dir="$BUILDER_REPO/devices/common"
device_dir="$BUILDER_REPO/devices/ipq807x-1g"

cd -- "$OPENWRT_DIR"
[[ -f feeds.conf ]] || cp feeds.conf.default feeds.conf
# Same-name replacement, as in the builder; this feed is required by NSS Wi-Fi.
sed -i -E '/^src-[^[:space:]]+[[:space:]]+nss[[:space:]]/d' feeds.conf
printf '%s\n' 'src-git nss https://github.com/JuliusBairaktaris/nss-packages.git;edma-nss' >> feeds.conf
./scripts/feeds update nss
./scripts/feeds install -a -p nss
./scripts/feeds update -a
./scripts/feeds install -a

# Feed patches first, then tree patches. Accept already-applied patches only
# when they reverse-apply cleanly; incompatible builder/fork pairs must fail.
apply_patch_file() {
  local directory="$1" patch_file="$2"
  if patch -p1 -d "$directory" --dry-run --forward < "$patch_file" >/dev/null 2>&1; then
    patch -p1 -d "$directory" --forward < "$patch_file"
  elif patch -p1 -d "$directory" --dry-run --reverse < "$patch_file" >/dev/null 2>&1; then
    printf 'Already applied: %s\n' "$patch_file"
  else
    printf 'Patch does not apply to %s: %s\n' "$directory" "$patch_file" >&2
    exit 1
  fi
}
shopt -s nullglob
for patch_file in "$BUILDER_REPO/patches/feeds/$variant"/*/*.patch; do
  apply_patch_file "feeds/$(basename -- "$(dirname -- "$patch_file")")" "$patch_file"
done
for patch_file in "$BUILDER_REPO/patches/tree/$variant"/*.patch; do
  apply_patch_file . "$patch_file"
done
shopt -u nullglob

python3 "$repo_dir/scripts/configure.py" prepare \
  --builder "$BUILDER_REPO" --packages "$repo_dir/config/packages.txt" \
  --config .config --required "$REQUIRED_CONFIG"
make defconfig

# Keep the builder's custom-feed distfeed exclusions; a replacement for an
# existing default feed keeps its distfeed entry.
if ! grep -qE '^src-[^[:space:]]+[[:space:]]+nss[[:space:]]' feeds.conf.default; then
  sed -i 's/^CONFIG_FEED_nss=.*/# CONFIG_FEED_nss is not set/' .config
fi
# This extra feed is not published as an image repository by the builder.
sed -i 's/^CONFIG_FEED_luci_extra=.*/# CONFIG_FEED_luci_extra is not set/' .config

# Common -> common variant -> device -> device variant, matching the builder.
mkdir -p files
for source in "$common_dir/files" "$common_dir/files.$variant" \
  "$device_dir/files" "$device_dir/files.$variant"; do
  if [[ -d "$source" ]]; then
    rsync -a "$source/" files/
  fi
done
if [[ -f files/etc/ssh/sshd_config ]]; then
  chmod 0600 files/etc/ssh/sshd_config
fi
