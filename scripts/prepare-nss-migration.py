"""Prepare a private configuration payload locally, without contacting a router."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shlex
import tarfile

import dependency_lib as deps

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'tmp/router-config/private'
TEMPLATES = ROOT / 'scripts/nss-migration'


def uci_sections(data):
    rows = []
    current = None
    for line in data.decode('utf-8').splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if words[0] == 'config' and len(words) in (2, 3):
            current = {'type': words[1], 'name': words[2] if len(words) == 3 else None, 'options': {}}
            rows.append(current)
        elif current is not None and words[0] in ('option', 'list') and len(words) == 3:
            if any(ord(c) < 32 for c in words[2]):
                raise ValueError('Control characters require manual UCI migration')
            if words[0] == 'list':
                current['options'].setdefault(words[1], []).append(words[2])
            else:
                current['options'][words[1]] = words[2]
        else:
            raise ValueError('Unsupported UCI structure; inspect the private backup locally')
    return rows


def subset(values, allowed):
    return {key: value for key, value in values.items() if key in allowed}


def settings(files):
    required = ['etc/config/network', 'etc/config/wireless', 'etc/config/homeproxy',
                'etc/config/dhcp', 'etc/config/firewall', 'etc/config/system', 'etc/shadow']
    if any(name not in files for name in required):
        raise ValueError('A complete fresh configuration backup including identity is required')
    network = uci_sections(files['etc/config/network'])
    interfaces = {s['name']:s['options'] for s in network if s['type'] == 'interface'}
    if set(interfaces) != {'loopback', 'lan', 'wan', 'wan6'} or any(s['type'] not in ('interface','device','globals') for s in network):
        raise ValueError('Additional network interfaces/routes require a separate migration review')
    if interfaces['wan'].get('proto') != 'dhcp' or interfaces['wan'].get('device') != 'wan' or interfaces['lan'].get('device') != 'br-lan':
        raise ValueError('This migration targets the reviewed DHCP WAN and br-lan topology')
    wireless = uci_sections(files['etc/config/wireless'])
    devices = [s for s in wireless if s['type'] == 'wifi-device']
    if len(devices) != 2 or {s['options'].get('band') for s in devices} != {'2g', '5g'}:
        raise ValueError('Expected one radio per band')
    radios = []
    for device in devices:
        aps = [s for s in wireless if s['type'] == 'wifi-iface' and s['options'].get('device') == device['name']]
        if len(aps) != 1 or aps[0]['options'].get('mode') != 'ap' or aps[0]['options'].get('network') != 'lan':
            raise ValueError('Additional SSIDs, mesh or guest networks require separate review')
        ap = aps[0]['options']
        if ap.get('encryption') not in ('psk2','psk-mixed','sae','sae-mixed') or not ap.get('key'):
            raise ValueError('Only existing encrypted personal-mode APs are migrated')
        radios.append({'band':device['options']['band'],
                       'device_options':subset(device['options'], {'channel','htmode','country','txpower','disabled','cell_density','legacy_rates'}),
                       'ap_options':subset(ap, {'ssid','encryption','key','disabled','hidden','isolate','ieee80211w','wpa_disable_eapol_key_retries','mode','network'})})
    system = next(s['options'] for s in uci_sections(files['etc/config/system']) if s['type'] == 'system')
    root_shadow = next((line for line in files['etc/shadow'].decode().splitlines() if line.startswith('root:')), None)
    if root_shadow is None or not root_shadow.split(':')[1].startswith('$'):
        raise ValueError('Expected an existing hashed administrator password')
    globals_options = next((s['options'] for s in network if s['type'] == 'globals'), {})
    return {'schema_version':1, 'radios':radios,
            'network':{
                'lan':subset(interfaces['lan'], {'proto','ipaddr','netmask','ip6assign','ip6hint','ip6ifaceid'}),
                'wan':subset(interfaces['wan'], {'proto','hostname','clientid','vendorid','peerdns','dns','defaultroute','metric','mtu'}),
                'wan6':subset(interfaces['wan6'], {'proto','disabled','reqaddress','reqprefix','peerdns','dns','defaultroute','metric'})},
            'globals':subset(globals_options, {'ula_prefix'}),
            'system':subset(system, {'hostname','timezone','zonename','log_size','conloglevel'}),
            'root_shadow':root_shadow}


def migration_files(backup_files):
    data = settings(backup_files)
    selected = {}
    for name, body in backup_files.items():
        if name in ('etc/config/homeproxy','etc/config/dhcp','etc/config/firewall'):
            selected[name] = (body, 0o600)
        elif name.startswith('etc/dropbear/') and name.rsplit('/',1)[-1] in (
                'dropbear_ed25519_host_key','dropbear_rsa_host_key','dropbear_ecdsa_host_key','authorized_keys'):
            selected[name] = (body, 0o600)
        elif name.startswith('etc/homeproxy/resources/') and name.endswith(('.txt','.ver')):
            selected[name] = (body, 0o600)
        elif name.startswith('etc/homeproxy/certs/'):
            selected[name] = (body, 0o600)
    if not any(name.endswith('_host_key') for name in selected):
        raise ValueError('SSH host keys must be included in the fresh backup')
    selected['etc/cr8808-nss/private-settings.json'] = (json.dumps(data, ensure_ascii=False).encode(), 0o600)
    selected['etc/cr8808-nss/apply-private.uc'] = ((TEMPLATES / 'apply-private.uc').read_bytes().replace(b'\r\n',b'\n'), 0o600)
    selected['etc/uci-defaults/zzzz-cr8808-private-migration'] = ((TEMPLATES / 'zzzz-cr8808-private-migration').read_bytes().replace(b'\r\n',b'\n'), 0o700)
    selected['etc/uci-defaults/00-cr8808-private-identity'] = ((TEMPLATES / '00-cr8808-private-identity').read_bytes().replace(b'\r\n',b'\n'), 0o700)
    return selected, data


def prepare(backup, output):
    output = output.resolve()
    if not output.is_relative_to(PRIVATE.resolve()) or output == PRIVATE.resolve():
        raise ValueError('Private migration output must be a new directory under tmp/router-config/private/')
    body = backup.read_bytes()
    files = deps.tar_files(body)
    selected, data = migration_files(files)
    output.mkdir(parents=True, exist_ok=False)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name,(content,mode) in sorted(selected.items()):
            member=tarfile.TarInfo(name);member.size=len(content);member.mode=mode
            member.uid=member.gid=0;member.mtime=0
            archive.addfile(member,io.BytesIO(content))
    payload=gzip.compress(raw.getvalue(),mtime=0)
    path=output/'private-migration.tar.gz';path.write_bytes(payload);path.chmod(0o600)
    report={'status':'prepared-from-backup-device-freshness-not-yet-verified',
            'backup_sha256':hashlib.sha256(body).hexdigest(),'payload_sha256':hashlib.sha256(payload).hexdigest(),
            'payload_bytes':len(payload),'files':len(selected),'bands':sorted(x['band'] for x in data['radios']),
            'copies_old_radio_paths':False,'copies_old_physical_network_devices':False,
            'changes_boot_environment':False,'initial_proxy_autostart':False,
            'on_device_ucode_validation_pending':True,'deployment_authorized':False}
    (output/'migration-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.backup,args.output),indent=2))


if __name__=='__main__':
    main()
