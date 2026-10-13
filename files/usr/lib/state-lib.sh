#!/bin/sh
# State archives contain sanitized configuration only. USB is not live-tested.
. "${FAULTLOG_LIB:-/usr/lib/faultlog-lib.sh}" || return 1
: "${STATE_NAND_DIR:=/root/states}"
: "${STATE_USB_SUBDIR:=states}"
: "${STATE_ROOT:=/}"
: "${STATE_SCRIPT_DIR:=/usr/sbin}"
state_dir() { faultlog_storage_dir "$STATE_NAND_DIR" "$STATE_USB_SUBDIR"; }
state_source() { printf '%s%s\n' "${STATE_ROOT%/}" "$1"; }
state_clean_tag() { printf '%s' "$1" | tr -cd 'A-Za-z0-9_-' | cut -c1-40; }
state_redact() {
  sed -E 's/^([[:space:]]*(option|list)[[:space:]]+[^[:space:]]*([Kk][Ee][Yy]|[Pp][Aa][Ss][Ss]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Tt][Oo][Kk][Ee][Nn]|[Pp][Ss][Kk]|[Aa][Uu][Tt][Hh])[^[:space:]]*[[:space:]]+).*/\1[REDACTED]/' | faultlog_redact
}
state_copy() {
  _st_src=$1; _st_rel=$2; _st_target=$3/$_st_rel
  [ -f "$_st_src" ] && [ -r "$_st_src" ] || return 0
  mkdir -p "${_st_target%/*}" || return 1
  state_redact < "$_st_src" > "$_st_target" || return 1
  chmod 600 "$_st_target" || return 1
}
state_prune() {
  _st_dir=$1
  if faultlog_usb_ready && [ "$_st_dir" = "$FAULTLOG_USB_MOUNT/$STATE_USB_SUBDIR" ]; then _st_max=30; _st_bytes=67108864
  else _st_max=2; _st_bytes=524288; fi  # one full set is ~210 KB; saved only before changes (rare writes)
  [ -d "$_st_dir" ] || return 0
  while :; do
    _st_count=$(find "$_st_dir" -maxdepth 1 -type d | sed '1d' | wc -l | tr -d ' ')
    _st_total=$(faultlog_tree_size "$_st_dir")
    [ "$_st_count" -le "$_st_max" ] && [ "$_st_total" -le "$_st_bytes" ] && break
    _st_old=$(ls -1d "$_st_dir"/* 2>/dev/null | sed -n '1p')  # names start with a timestamp: lexical == chronological (ls -t has 1 s resolution)
    [ -d "$_st_old" ] || break
    rm -rf "$_st_old" || return 1
  done
}
state_migrate() {
  faultlog_usb_ready || return 1
  [ -d "$STATE_NAND_DIR" ] || return 0
  _st_dest=$FAULTLOG_USB_MOUNT/$STATE_USB_SUBDIR
  [ "$(( $(faultlog_tree_size "$_st_dest") + $(faultlog_tree_size "$STATE_NAND_DIR") ))" -le 67108864 ] || return 1
  mkdir -p "$_st_dest" || return 1
  find "$STATE_NAND_DIR" -type f | while IFS= read -r _st_file; do
    _st_rel=${_st_file#"$STATE_NAND_DIR"/}
    _st_target=$_st_dest/$_st_rel
    faultlog_migrate_one "$_st_file" "${_st_target%/*}" "$_st_target" || exit 1
  done || return 1
  find "$STATE_NAND_DIR" -depth -type d -exec rmdir {} \; 2>/dev/null || :
  state_prune "$_st_dest"
}
