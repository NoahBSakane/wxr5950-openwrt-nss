# Time stamp helpers, sourced by /usr/sbin/notify and /usr/sbin/config-backup-mail.
#   ts_long   2026-10-09(Fri)15:55:50.609+09:00   yyyy-MM-dd(DoW)hh:mm:ss.sss+09:00
#   ts_short  20261009(5)155550609JST              yyyyMMdd(D)hhmmsssssJST   (D = ISO 8601 weekday digit: Mon=1 ... Sun=7)
#   ts_file   20261009155550609JST                 same as ts_short without "(D)" (safe in file names)
# Milliseconds need GNU date (package coreutils-date). With BusyBox date they fall back to 000.
_ts() {
  set -- $(LC_ALL=C date '+%Y %m %d %a %u %H %M %S %N %z %Z' 2>/dev/null)
  if [ $# -ge 11 ]; then _ms=$(printf '%s' "$9" | cut -c1-3); _z=${10}; _zn=${11}
  else _ms=000; _z=$9; _zn=${10}; fi
  _Y=$1; _m=$2; _d=$3; _a=$4; _u=$5; _H=$6; _M=$7; _S=$8
  _k=$_u   # ISO 8601 weekday: 1 (Mon) .. 7 (Sun); one character, no collisions
}
ts_long()  { _ts; printf '%s-%s-%s(%s)%s:%s:%s.%s%s:%s' "$_Y" "$_m" "$_d" "$_a" "$_H" "$_M" "$_S" "$_ms" "$(printf '%s' "$_z" | cut -c1-3)" "$(printf '%s' "$_z" | cut -c4-5)"; }
ts_short() { _ts; printf '%s%s%s(%s)%s%s%s%s%s' "$_Y" "$_m" "$_d" "$_k" "$_H" "$_M" "$_S" "$_ms" "$_zn"; }
ts_file()  { _ts; printf '%s%s%s%s%s%s%s%s' "$_Y" "$_m" "$_d" "$_H" "$_M" "$_S" "$_ms" "$_zn"; }
