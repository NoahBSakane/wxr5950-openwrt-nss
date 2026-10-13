#!/bin/sh
set -eu
repo=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
script=$repo/files/etc/uci-defaults/90-wxr5950-bake
temp=$(mktemp -d "${TMPDIR:-/tmp}/wxr5950-bake-test.XXXXXX")
trap 'rm -rf "$temp"' EXIT HUP INT TERM
root=$temp/root
mkdir -p "$root/rom/usr/sbin" "$root/overlay/upper/usr/sbin" \
    "$root/rom/lib/adblock-fast" "$root/overlay/upper/lib/adblock-fast" \
    "$root/etc/crontabs" "$root/etc/init.d" "$root/root" "$temp/bin"
printf '#!/bin/sh\nexit 0\n' > "$temp/bin/logger"
chmod 755 "$temp/bin/logger"
cat > "$root/etc/init.d/adblock-cache-preload" <<'SH'
#!/bin/sh
[ "$1" = enable ] && touch "$ROOT/preload-enabled"
SH
chmod 755 "$root/etc/init.d/adblock-cache-preload"
printf 'same\n' > "$root/rom/usr/sbin/same"
printf 'different-rom\n' > "$root/rom/usr/sbin/different"
printf 'no-overlay\n' > "$root/rom/usr/sbin/no-overlay"
printf 'same\n' > "$root/overlay/upper/usr/sbin/same"
printf 'different-overlay\n' > "$root/overlay/upper/usr/sbin/different"
printf 'no-rom\n' > "$root/overlay/upper/usr/sbin/no-rom"
printf 'patched-rom\n' > "$root/rom/lib/adblock-fast/adblock-fast.uc"
printf 'old-overlay\n' > "$root/overlay/upper/lib/adblock-fast/adblock-fast.uc"
printf '%s\n' /usr/sbin/same /usr/sbin/different /usr/sbin/no-overlay /usr/sbin/no-rom > "$root/etc/wxr5950-baked-paths"
printf '%s\n' /usr/sbin/same /etc/notify.conf /usr/sbin/different /etc/config/network /root/keep /usr/sbin/no-rom /lib/adblock-fast/adblock-fast.uc > "$root/etc/sysupgrade.conf"
printf '%s\n' '# existing' > "$root/etc/crontabs/root"
printf '%s' '10 4 * * * /usr/sbin/adblock-update' >> "$root/etc/crontabs/root"
cp "$root/etc/crontabs/root" "$temp/cron-before"
ROOT=$root ROM=$root/rom OVERLAY=$root/overlay/upper TMPDIR=$temp PATH=$temp/bin:$PATH sh "$script"
[ ! -e "$root/overlay/upper/usr/sbin/same" ]
[ ! -e "$root/overlay/upper/usr/sbin/different" ]
[ -f "$root/preload-enabled" ]
[ ! -e "$root/overlay/upper/lib/adblock-fast/adblock-fast.uc" ]
[ -f "$root/overlay/upper/usr/sbin/no-rom" ]
backups=0
for backup in "$root"/root/overlay-shadow-backup-*; do
    [ -d "$backup" ] || continue
    backups=$((backups + 1))
    printf 'different-overlay\n' | cmp - "$backup/usr/sbin/different"
    printf 'old-overlay\n' | cmp - "$backup/lib/adblock-fast/adblock-fast.uc"
done
[ "$backups" -eq 1 ]
printf '%s\n' /etc/notify.conf /etc/config/network /root/keep /usr/sbin/no-rom > "$temp/expected-conf"
cmp "$temp/expected-conf" "$root/etc/sysupgrade.conf"
grep -Fqx '# existing' "$root/etc/crontabs/root"
head -n 2 "$root/etc/crontabs/root" > "$temp/cron-first-two"
printf '%s\n' '# existing' '10 4 * * * /usr/sbin/adblock-update' | \
    cmp - "$temp/cron-first-two"
[ "$(grep -Fxc '10 4 * * * /usr/sbin/adblock-update' "$root/etc/crontabs/root")" -eq 1 ]
[ "$(wc -l < "$root/etc/crontabs/root" | tr -d ' ')" -eq 6 ]
cp "$root/etc/crontabs/root" "$temp/cron-after"
cp "$root/etc/sysupgrade.conf" "$temp/conf-after"
ROOT=$root ROM=$root/rom OVERLAY=$root/overlay/upper TMPDIR=$temp PATH=$temp/bin:$PATH sh "$script"
cmp "$temp/cron-after" "$root/etc/crontabs/root"
cmp "$temp/conf-after" "$root/etc/sysupgrade.conf"
backups_after=0
for backup in "$root"/root/overlay-shadow-backup-*; do
    [ -d "$backup" ] || continue
    backups_after=$((backups_after + 1))
done
[ "$backups_after" -eq 1 ]

empty=$temp/empty
mkdir -p "$empty/etc/crontabs" "$empty/rom" "$empty/overlay/upper/usr/sbin"
printf '%s\n' /usr/sbin/same > "$empty/etc/wxr5950-baked-paths"
printf '%s\n' /usr/sbin/same > "$empty/etc/sysupgrade.conf"
printf '%s\n' 'existing cron' > "$empty/etc/crontabs/root"
printf 'old\n' > "$empty/overlay/upper/usr/sbin/same"
ROOT=$empty ROM=$empty/rom OVERLAY=$empty/overlay/upper TMPDIR=$temp PATH=$temp/bin:$PATH sh "$script"
printf '%s\n' /usr/sbin/same | cmp - "$empty/etc/sysupgrade.conf"
printf '%s\n' 'existing cron' | cmp - "$empty/etc/crontabs/root"
printf 'old\n' | cmp - "$empty/overlay/upper/usr/sbin/same"
printf 'bake shell tests: PASS\n'
