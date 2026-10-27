#!/bin/sh
# Read-only compatibility check. Does not print UCI configuration or run sing-box.
set -eu

fail() { echo "INCOMPATIBLE: $*" >&2; exit 1; }
version_of() { opkg status "$1" 2>/dev/null | sed -n 's/^Version: //p'; }

[ "$(cat /tmp/sysinfo/board_name)" = 'redmi,ax3000' ] || fail 'board name'
[ "$(uname -r)" = '6.6.137' ] || fail 'kernel version'
[ "$(version_of kernel)" = '6.6.137~20a052f3c3e98b3a9ba1a095f81e2725-r1' ] || fail 'full kernel ABI'
grep -q "DISTRIB_REVISION='r0-9a11bb8'" /etc/openwrt_release || fail 'firmware revision'
grep -q squashfs /proc/filesystems || fail 'SquashFS support'
[ -c /dev/loop-control ] || fail 'loop device support'
for package in firewall4 dnsmasq-full rpcd rpcd-mod-ucode ucode ucode-mod-fs ucode-mod-uci ca-bundle; do
    [ -n "$(version_of "$package")" ] || fail "missing base package: $package"
done
echo 'Compatible with the frozen CR8808 firmware/kernel baseline.'
echo 'Installation additionally requires free flash/RAM checks and matching package hashes.'
