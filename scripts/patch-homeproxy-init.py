"""Apply CR8808 memory settings and conditional TUN cleanup to pinned HomeProxy."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--gogc', type=int, choices=(50, 100), default=50,
                        help='100 reduces collection frequency for the smaller GFWList profile')
    args = parser.parse_args()
    source = args.input.read_text(encoding='utf-8')
    anchor = '\t\tuname -r | grep -Eq "^6\\.6" && procd_set_param env "QUIC_GO_DISABLE_GSO"="true"'
    memory = f'\t\tprocd_append_param env "GOMEMLIMIT=24MiB" "GOGC={args.gogc}"'
    if source.count(anchor) != 2:
        raise SystemExit('Unexpected HomeProxy version: environment anchors do not match')
    memory_pattern = r'\t\tprocd_append_param env "GOMEMLIMIT=24MiB" "GOGC=(?:50|100)"'
    configured = re.findall(memory_pattern, source)
    if len(configured) == 2:
        source = re.sub(memory_pattern, memory, source)
    elif not configured:
        source = source.replace(anchor, anchor + '\n' + memory)
    else:
        raise SystemExit('Unexpected partial memory configuration')
    # The native validation process also needs the limit during a cold start.
    check_pattern = r'elif ! (?:env GOMEMLIMIT=24MiB GOGC=(?:50|100) )?"\$PROG" check'
    if len(re.findall(check_pattern, source)) != 2:
        raise SystemExit('Unexpected HomeProxy version: config checks do not match')
    source = re.sub(check_pattern,
                    f'elif ! env GOMEMLIMIT=24MiB GOGC={args.gogc} "$PROG" check', source)
    old = ('\t# TUN\n'
           '\tip link set "$tun_name" down 2>"/dev/null"\n'
           '\tip tuntap del mode tun name "$tun_name" 2>"/dev/null"\n')
    new = ('\t# TUN: redirect/tproxy mode does not create a TUN interface.\n'
           '\tif ip link show "$tun_name" >/dev/null 2>&1; then\n'
           '\t\tip link set "$tun_name" down 2>"/dev/null"\n'
           '\t\tip tuntap del mode tun name "$tun_name" 2>"/dev/null"\n'
           '\tfi\n'
           '\treturn 0\n')
    if source.count(old) == 1:
        source = source.replace(old, new)
    elif new not in source:
        raise SystemExit('Unexpected HomeProxy version: TUN cleanup does not match')
    args.output.write_bytes(source.encode('utf-8'))
    print('Applied memory settings and conditional TUN cleanup')


if __name__ == '__main__':
    main()
