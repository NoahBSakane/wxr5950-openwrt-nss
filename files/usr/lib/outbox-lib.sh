#!/bin/sh
# Shared queue helpers. USB route is not yet verified on the router.
. "${FAULTLOG_LIB:-/usr/lib/faultlog-lib.sh}" || return 1
: "${OUTBOX_NAND_DIR:=/root/outbox}"
: "${OUTBOX_USB_SUBDIR:=outbox}"
: "${OUTBOX_LOCK:=/tmp/outbox.lock}"
outbox_dir() { faultlog_storage_dir "$OUTBOX_NAND_DIR" "$OUTBOX_USB_SUBDIR"; }
outbox_lock() {
  _ob_wait=0
  while [ "$_ob_wait" -lt 30 ]; do
    mkdir "$OUTBOX_LOCK" 2>/dev/null && return 0
    if [ -r "$OUTBOX_LOCK/pid" ]; then
      read -r _ob_pid < "$OUTBOX_LOCK/pid"
      case "$_ob_pid" in ''|*[!0-9]*) ;; *)
        if ! kill -0 "$_ob_pid" 2>/dev/null; then
          rm -f "$OUTBOX_LOCK/pid"
          rmdir "$OUTBOX_LOCK" 2>/dev/null || :
          continue
        fi;;
      esac
    fi
    sleep 1
    _ob_wait=$((_ob_wait + 1))
  done
  return 1
}
outbox_unlock() { rm -f "$OUTBOX_LOCK/pid"; rmdir "$OUTBOX_LOCK" 2>/dev/null || :; }
outbox_prune() {
  # notify accepts one message argument; bound the aggregate below exec limits.
  faultlog_prune_files "$1" 10000 65536
}
outbox_migrate() {
  faultlog_usb_ready || return 1
  _ob_dest=$FAULTLOG_USB_MOUNT/$OUTBOX_USB_SUBDIR
  [ -d "$OUTBOX_NAND_DIR" ] || return 0
  mkdir -p "$_ob_dest" || return 1
  find "$OUTBOX_NAND_DIR" -type f | while IFS= read -r _ob_file; do
    _ob_name=${_ob_file##*/}
    _ob_target=$_ob_dest/$_ob_name
    if [ -f "$_ob_target" ] && ! cmp -s "$_ob_file" "$_ob_target"; then
      _ob_hash=$(sha256sum "$_ob_file" | cut -d' ' -f1)
      _ob_target=$_ob_target-migrated-$_ob_hash
    fi
    faultlog_migrate_one "$_ob_file" "$_ob_dest" "$_ob_target" || exit 1
  done || return 1
  rmdir "$OUTBOX_NAND_DIR" 2>/dev/null || :
  outbox_prune "$_ob_dest"
}
