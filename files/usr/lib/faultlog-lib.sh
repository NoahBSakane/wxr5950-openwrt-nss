#!/bin/sh
# Shared storage policy for faultlog and later evidence tools. USB path is NOT live-tested.
# Source this file; do not execute it. Mount/label checks must pass before any NAND deletion.
: "${FAULTLOG_NAND_DIR:=/root/faultlog}"
: "${FAULTLOG_USB_MOUNT:=/mnt/maha-log}"
: "${FAULTLOG_USB_SUBDIR:=faultlog}"
: "${FAULTLOG_MOUNTS:=/proc/mounts}"
: "${FAULTLOG_PSTORE_DIR:=/root/pstore}"

faultlog_usb_ready() {
  [ -r "$FAULTLOG_MOUNTS" ] || return 1
  _fl_source=$(awk -v p="$FAULTLOG_USB_MOUNT" '$2 == p && $3 == "ext4" {print $1; exit}' "$FAULTLOG_MOUNTS")
  [ -n "$_fl_source" ] || return 1
  case "$_fl_source" in
    LABEL=MAHALOG) return 0 ;;
  esac
  [ "$(blkid -s LABEL -o value "$_fl_source" 2>/dev/null)" = MAHALOG ] && return 0
  block info "$_fl_source" 2>/dev/null | grep -q 'LABEL="MAHALOG"'
}
faultlog_usb_dir() { printf '%s/%s\n' "$FAULTLOG_USB_MOUNT" "$FAULTLOG_USB_SUBDIR"; }
faultlog_storage_dir() {
  # Usage: faultlog_storage_dir <NAND path> <USB relative path>.
  # Future outbox/state/capture tools can share the same verified switch.
  if faultlog_usb_ready; then printf '%s/%s\n' "$FAULTLOG_USB_MOUNT" "$2"; else printf '%s\n' "$1"; fi
}
faultlog_dir() {
  faultlog_storage_dir "$FAULTLOG_NAND_DIR" "$FAULTLOG_USB_SUBDIR"
}
faultlog_is_usb() { faultlog_usb_ready; }
faultlog_size() { [ -f "$1" ] && wc -c < "$1" || printf '0\n'; }
faultlog_tree_size() {
  [ -d "$1" ] || { printf '0\n'; return; }
  find "$1" -type f -exec wc -c {} + 2>/dev/null | awk '$2 != "total" {s += $1} END {printf "%.0f\n", s}'
}
faultlog_oldest_file() {
  _fl_oldest_path=
  _fl_oldest_epoch=
  # The router's BusyBox has no stat(1); ls -t (newest first) reversed gives oldest first.
  _fl_oldest_path=$(ls -1trd -- "$@" 2>/dev/null | while IFS= read -r _fl_candidate; do
    [ -f "$_fl_candidate" ] && { printf '%s\n' "$_fl_candidate"; break; }
  done)
  printf '%s\n' "$_fl_oldest_path"
}
faultlog_prune_files() {
  # Usage: faultlog_prune_files <flat directory> <max files> <max bytes>.
  # Caller keeps per-record and aggregate limits; works for later outbox/pcap.
  _fl_flat_dir=$1; _fl_flat_count=$2; _fl_flat_bytes=$3
  [ -d "$_fl_flat_dir" ] || return 0
  while :; do
    _fl_count=$(find "$_fl_flat_dir" -type f | wc -l | tr -d ' ')
    _fl_bytes=$(faultlog_tree_size "$_fl_flat_dir")
    [ "$_fl_count" -le "$_fl_flat_count" ] && [ "$_fl_bytes" -le "$_fl_flat_bytes" ] && break
    _fl_old=$(faultlog_oldest_file "$_fl_flat_dir"/*)
    [ -n "$_fl_old" ] || break
    rm -f "$_fl_old"
  done
}
faultlog_redact() {
  sed -E \
    -e 's/("[Tt][Oo][Kk][Ee][Nn]"|"[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]"|"[Pp][Aa][Ss][Ss][Pp][Hh][Rr][Aa][Ss][Ee]"|"[Tt][Oo][Pp][Ii][Cc]")[[:space:]]*:[[:space:]]*"[^"]*"/\1:"[REDACTED]"/g' \
    -e 's/([Tt][Oo][Kk][Ee][Nn]|[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|[Pp][Aa][Ss][Ss][Pp][Hh][Rr][Aa][Ss][Ee]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Kk][Ee][Yy]|[Pp][Ss][Kk]|[Pp][Rr][Ii][Vv][Aa][Tt][Ee]_[Kk][Ee][Yy])[[:space:]]*[:=][[:space:]]*[^[:space:]|,;]+/\1=[REDACTED]/g' \
    -e 's/([Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn][[:space:]]*[:=][[:space:]]*).*/\1[REDACTED]/g' \
    -e 's#https?://[^/[:space:]]*ntfy[^/[:space:]]*/[^[:space:]|]+#[REDACTED_URL]#g' \
    -e 's/([Nn][Tt][Ff][Yy][_ -]?[Tt][Oo][Pp][Ii][Cc]|[Tt][Oo][Pp][Ii][Cc])[[:space:]]*[:=][[:space:]]*[^[:space:]|,;]+/\1=[REDACTED]/g'
}
faultlog_clean_field() {
  printf '%s' "$1" | tr '\r\n|' '   ' | faultlog_redact | cut -c1-500
}
faultlog_rotate() {
  _fl_dir=$1; _fl_limit=$2; _fl_generations=$3
  _fl_log=$_fl_dir/events.log
  [ -f "$_fl_log" ] || return 0
  [ "$(faultlog_size "$_fl_log")" -le "$_fl_limit" ] && return 0
  # Keep at most N generations including the active file. Oldest is removed first.
  rm -f "$_fl_log.$((_fl_generations - 1))"
  _fl_i=$((_fl_generations - 2))
  while [ "$_fl_i" -ge 1 ]; do
    [ ! -f "$_fl_log.$_fl_i" ] || mv "$_fl_log.$_fl_i" "$_fl_log.$((_fl_i + 1))"
    _fl_i=$((_fl_i - 1))
  done
  mv "$_fl_log" "$_fl_log.1"
}
faultlog_prune() {
  _fl_dir=$1
  if faultlog_usb_ready && [ "$_fl_dir" = "$(faultlog_usb_dir)" ]; then
    _fl_snap_count=200; _fl_snap_bytes=268435456; _fl_total=268435456
  else
    _fl_snap_count=12; _fl_snap_bytes=131072; _fl_total=262144
  fi
  _fl_snaps=$_fl_dir/snapshots
  faultlog_prune_files "$_fl_snaps" "$_fl_snap_count" "$_fl_snap_bytes"
  # The 256 KB NAND aggregate cap takes priority over four possible 64 KB generations.
  while [ "$(faultlog_tree_size "$_fl_dir")" -gt "$_fl_total" ]; do
    _fl_old=$(faultlog_oldest_file "$_fl_snaps"/* "$_fl_dir"/events.log.* \
      "$_fl_dir/migrated/snapshots"/* "$_fl_dir/pstore"/* "$_fl_dir/migrated/events"/* "$_fl_dir/migrated/misc"/*)
    if [ -n "$_fl_old" ]; then rm -f "$_fl_old"; continue; fi
    break
  done
}
# Content-addressed copies make migration restartable after a power cut. Keep source
# until cmp proves the destination complete. USB mount absence is never a delete signal.
faultlog_migrate_one() {
  _fl_src=$1; _fl_dest=$2
  _fl_hash=$(sha256sum "$_fl_src" 2>/dev/null | awk '{print $1}') || return 1
  [ -n "$_fl_hash" ] || return 1
  # An explicit target keeps a directory tree intact for state archives.
  _fl_target=${3:-$_fl_dest/$_fl_hash}
  mkdir -p "$_fl_dest" || return 1
  if [ -f "$_fl_target" ]; then
    cmp -s "$_fl_src" "$_fl_target" || return 1
  else
    _fl_tmp=$_fl_target.tmp.$$
    cp -p "$_fl_src" "$_fl_tmp" || { rm -f "$_fl_tmp"; return 1; }
    if [ "$(faultlog_size "$_fl_src")" != "$(faultlog_size "$_fl_tmp")" ] || ! cmp -s "$_fl_src" "$_fl_tmp"; then
      rm -f "$_fl_tmp"
      return 1
    fi
    mv "$_fl_tmp" "$_fl_target" || { rm -f "$_fl_tmp"; return 1; }
  fi
  sync || return 1
  cmp -s "$_fl_src" "$_fl_target" || return 1
  faultlog_usb_ready || return 1
  rm -f "$_fl_src"
}
faultlog_migrate() {
  faultlog_usb_ready || return 1
  _fl_usb=$(faultlog_usb_dir)
  _fl_needed=$(( $(faultlog_tree_size "$_fl_usb") + $(faultlog_tree_size "$FAULTLOG_NAND_DIR") + $(faultlog_tree_size "$FAULTLOG_PSTORE_DIR") ))
  # Do not start deleting NAND if the USB cannot hold all existing evidence.
  [ "$_fl_needed" -le 268435456 ] || return 1
  mkdir -p "$_fl_usb/migrated/events" "$_fl_usb/migrated/snapshots" "$_fl_usb/migrated/misc" "$_fl_usb/pstore" || return 1
  if [ -d "$FAULTLOG_NAND_DIR" ]; then
    find "$FAULTLOG_NAND_DIR" -type f | while IFS= read -r _fl_file; do
      case "$_fl_file" in
        "$FAULTLOG_NAND_DIR"/events.log*) _fl_dest=$_fl_usb/migrated/events;;
        "$FAULTLOG_NAND_DIR"/snapshots/*) _fl_dest=$_fl_usb/migrated/snapshots;;
        *) _fl_dest=$_fl_usb/migrated/misc;;
      esac
      faultlog_migrate_one "$_fl_file" "$_fl_dest" || exit 1
    done || return 1
  fi
  if [ -d "$FAULTLOG_PSTORE_DIR" ]; then
    find "$FAULTLOG_PSTORE_DIR" -type f | while IFS= read -r _fl_file; do
      faultlog_migrate_one "$_fl_file" "$_fl_usb/pstore" || exit 1
    done || return 1
  fi
  for _fl_tree in "$FAULTLOG_NAND_DIR" "$FAULTLOG_PSTORE_DIR"; do
    [ -d "$_fl_tree" ] && find "$_fl_tree" -depth -type d -exec rmdir {} \; 2>/dev/null || :
  done
  faultlog_prune "$_fl_usb"
}
