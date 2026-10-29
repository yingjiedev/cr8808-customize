"""Check and index candidate build outputs without executing firmware binaries."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import dependency_lib as deps
from nss_candidate_image import verify_nand_fit

spec = importlib.util.spec_from_file_location('nss_prepare', Path(__file__).with_name('prepare-nss-candidate.py'))
nss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nss)


def finish(source, output):
    source, output = source.resolve(), output.resolve()
    lock = nss.load_lock()
    config_report = nss.verify_config(source / '.config')
    target = source / 'bin/targets' / lock['target']
    prefix = 'openwrt-qualcommax-ipq50xx-xiaomi_cr8806'
    factory = target / (prefix + '-squashfs-factory.ubi')
    upgrade = target / (prefix + '-squashfs-sysupgrade.bin')
    initramfs = target / (prefix + '-initramfs-uImage.itb')
    for path in (factory, upgrade, initramfs):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Required image missing: ' + path.name)
    if factory.stat().st_size > lock['maximum_factory_bytes']:
        raise ValueError('Factory image leaves insufficient space in the 36 MiB slot')
    with factory.open('rb') as stream:
        if stream.read(4) != b'UBI#':
            raise ValueError('Factory image is not a UBI image')
    with initramfs.open('rb') as stream:
        if stream.read(4) != b'\xd0\x0d\xfe\xed':
            raise ValueError('Initramfs is not a FIT image')
    nand_report = verify_nand_fit(initramfs.read_bytes())
    manifest = (target / (prefix + '.manifest')).read_text(encoding='utf-8')
    required = ['sing-box-squashfs', 'luci-app-homeproxy', 'cr8808-nss-policy', 'nss-tools-dwmac',
                'kmod-qca-nss-ecm', 'kmod-qca-dwmac-nss', 'dnsmasq-full', 'ucode-mod-math']
    installed = {line.split(' - ', 1)[0] for line in manifest.splitlines()}
    missing = set(required) - installed
    if missing or 'sing-box' in installed or 'dnsmasq' in installed:
        raise ValueError('Unexpected application/driver package manifest: ' + ','.join(sorted(missing)))
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output / 'sysupgrade-metadata.json'
    subprocess.run([str(source / 'staging_dir/host/bin/fwtool'), '-i', str(metadata_path), str(upgrade)], check=True)
    metadata = json.loads(metadata_path.read_text())
    if 'xiaomi,cr8806' not in metadata.get('supported_devices', []):
        raise ValueError('Unexpected supported_devices metadata')
    # Include the exact installed package set/indexes for offline maintenance.
    # The tar contains only public bin outputs, never the build signing private key.
    paths = []
    for parent in (target, source / 'bin/packages'):
        for path in parent.rglob('*'):
            if path.is_file():
                if not path.resolve().is_relative_to(source):
                    raise ValueError('Artifact symlink escapes the source tree')
                paths.append(path)
    checksums = {path.relative_to(source).as_posix(): deps.sha256(path.read_bytes()) for path in sorted(set(paths))}
    for name in ('config.buildinfo', 'feeds.buildinfo', 'version.buildinfo'):
        path = target / name
        if path.is_file():
            shutil.copy2(path, output / name)
    for path in (factory, upgrade, initramfs, target / (prefix + '.manifest')):
        shutil.copy2(path, output / path.name)
    preparation = json.loads((source / 'package/cr8808/cr8808-nss-policy/files/etc/cr8808-nss/candidate.json').read_text())
    nss.write(output / 'preparation-report.json', json.dumps(preparation, indent=2)+'\n')
    report = {'status': ('build-complete-device-blocked' if lock.get('device_blockers')
                         else 'build-complete-device-validation-pending'), 'source_lock': lock,
              'config': config_report, 'factory_bytes': factory.stat().st_size,
              'nand_ecc': nand_report,
              'physical_slot_headroom_bytes': lock['slot_bytes']-factory.stat().st_size,
              'file_checksums': checksums, 'private_configuration_included': False,
              'automatic_flash': False, 'stable_500_mbps_validated': False}
    nss.write(output / 'build-report.json', json.dumps(report, indent=2)+'\n')
    nss.write(output / 'SHA256SUMS-bin', ''.join(f'{digest}  {name}\n' for name,digest in checksums.items()))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = finish(args.source, args.output)
    print(json.dumps({key:value for key,value in report.items() if key != 'file_checksums'}, indent=2))


if __name__ == '__main__':
    main()
