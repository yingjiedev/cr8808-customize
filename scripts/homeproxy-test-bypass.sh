#!/bin/sh
# Temporary IPv4 test-PC bypass. No UCI or persistent firewall changes.
set -eu
action="${1:-}"
address="${2:-}"
tag="${3:-}"
case "$tag" in cr8808-node-test-*) ;; *) echo 'A unique cr8808-node-test- tag is required' >&2; exit 1 ;; esac
case "$tag" in *[!a-zA-Z0-9_-]*) echo 'Invalid tag' >&2; exit 1 ;; esac
printf '%s\n' "$address" | awk -F. '
NF != 4 { exit 1 }
{ for (i=1; i<=4; i++) if ($i !~ /^[0-9]+$/ || $i < 0 || $i > 255) exit 1 }
' || { echo 'A single IPv4 address is required' >&2; exit 1; }

remove_rules() {
	for chain in homeproxy_redirect_lanac homeproxy_mangle_lanac; do
		handles="$(nft -a list chain inet fw4 "$chain" 2>/dev/null |
			awk -v tag="$tag" 'index($0, "comment \"" tag "\"") { print $NF }')"
		for handle in $handles; do
			case "$handle" in *[!0-9]*|'') return 1 ;; esac
			nft delete rule inet fw4 "$chain" handle "$handle" || return 1
		done
	done
}

case "$action" in
add)
	remove_rules
	nft -f - <<EOF
insert rule inet fw4 homeproxy_redirect_lanac ip saddr $address counter return comment "$tag"
insert rule inet fw4 homeproxy_mangle_lanac ip saddr $address counter return comment "$tag"
EOF
	;;
remove)
	remove_rules
	;;
status)
	for chain in homeproxy_redirect_lanac homeproxy_mangle_lanac; do
		nft -a list chain inet fw4 "$chain" |
			awk -v tag="$tag" 'index($0, "comment \"" tag "\"") { print }'
	done
	;;
watchdog)
	# Stop a manually cancelled watchdog without leaving its sleep child behind.
	sleep 900 &
	child=$!
	trap 'kill "$child" 2>/dev/null || true; exit 0' INT TERM
	wait "$child" || exit 0
	remove_rules
	;;
*)
	echo 'Usage: homeproxy-test-bypass.sh add|remove|status|watchdog IPv4 unique_tag' >&2
	exit 1
	;;
esac
