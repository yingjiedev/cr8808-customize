"""Build preparation and provenance checks for the pinned ARM32 QSDK candidate."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'firmware/qsdk'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, data, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.replace('\r\n', '\n').encode('utf-8'))
    path.chmod(0o755 if executable else 0o644)


def write_json(path, value):
    write(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def load_lock():
    lock = json.loads((POLICY / 'source-lock.json').read_text(encoding='utf-8'))
    if (lock.get('schema_version') != 1 or lock.get('target') != 'ipq50xx/arm'
            or lock.get('profile') != 'redmi_ax3000' or lock.get('slot_bytes') != 37748736
            or lock.get('maximum_factory_bytes') != 33554432
            or lock.get('cpu_max_hz') != 1008000000
            or lock.get('nand_ecc') != {'strength': 4, 'step_bytes': 512}
            or lock.get('minimum_sustained_nat_mbps') != 500):
        raise ValueError('Unexpected QSDK device policy')
    for item in [lock['source'], *lock['feeds']]:
        if not re.fullmatch(r'[0-9a-f]{40}', item['commit']):
            raise ValueError('Every source/feed requires a full commit ID')
        if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+\.git', item['repository']):
            raise ValueError('Unexpected source repository')
    if sorted(item['name'] for item in lock['feeds']) != ['luci', 'packages', 'routing', 'telephony']:
        raise ValueError('Unexpected QSDK feed set')
    cache = lock['reference']['download_archive']
    if not re.fullmatch(r'[0-9a-f]{64}', cache['sha256']):
        raise ValueError('Historical source cache requires a SHA256')
    return lock


def verify_config(path):
    actual = set(Path(path).read_text(encoding='utf-8').splitlines())
    requested = (POLICY / 'cr8808.config').read_text(encoding='utf-8').splitlines()
    missing = [line for line in requested if line.startswith('CONFIG_') and line not in actual]
    if missing:
        raise ValueError('defconfig dropped requested settings: ' + ', '.join(missing))
    forbidden = ['CONFIG_TARGET_MULTI_PROFILE', 'CONFIG_TARGET_ALL_PROFILES',
                 'CONFIG_ATH11K_MEM_PROFILE_512M', 'CONFIG_ATH11K_MEM_PROFILE_1G',
                 'CONFIG_PACKAGE_dnsmasq', 'CONFIG_PACKAGE_firewall4',
                 'CONFIG_PACKAGE_luci-app-homeproxy', 'CONFIG_PACKAGE_sing-box',
                 'CONFIG_VERSION_FILENAMES']
    if any(name + '=y' in actual for name in forbidden):
        raise ValueError('Wrong target, memory profile, ABI or application stack')
    devices = [line for line in actual if line.startswith('CONFIG_TARGET_')
               and '_DEVICE_' in line and line.endswith('=y')]
    if devices != ['CONFIG_TARGET_ipq50xx_arm_DEVICE_redmi_ax3000=y']:
        raise ValueError('Only the reviewed Redmi AX3000 profile may be selected')
    return {'requested_settings_verified': sum(line.startswith('CONFIG_') for line in requested)}


def check_source(source, lock):
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != lock['source']['commit']:
        raise ValueError('QSDK source commit mismatch')
    subprocess.run(['git', '-C', str(source), 'diff', '--quiet', 'HEAD', '--'], check=True)
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('QSDK preparation requires a clean source checkout')
    for name, expected in lock['reviewed_files'].items():
        if sha256(source / name) != expected:
            raise ValueError('Reviewed upstream file changed: ' + name)


def guarded_directory(path):
    path = Path(path).resolve()
    if path == ROOT or ROOT.is_relative_to(path):
        raise ValueError('Build directory cannot contain this repository')
    if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] != 'tmp':
        raise ValueError('In-repository build directories must be under tmp/')
    return path


def pin_cached_sources(source, lock):
    changes = []
    for item in lock['cached_sources']:
        path = source / item['recipe']
        text = path.read_text(encoding='utf-8')
        if item['kind'] == 'firmware-archive':
            # Upstream used a floating main branch. The release's archived
            # bytes are a binary/source input; no unverifiable commit is invented.
            for line in ['PKG_SOURCE_PROTO:=git\n', 'PKG_SOURCE_VERSION:=main\n', 'PKG_MIRROR_HASH:=skip\n']:
                if text.count(line) != 1:
                    raise ValueError('Unexpected firmware recipe')
                text = text.replace(line, '')
            text, count = re.subn(r'^PKG_SOURCE_URL:=.*$', 'PKG_SOURCE_URL:=file://$(DL_DIR)', text, flags=re.M)
            if count != 1:
                raise ValueError('Unexpected firmware source URL')
            marker = 'include $(INCLUDE_DIR)/package.mk'
            prefix = ('PKG_SOURCE:=' + item['file'] + '\nPKG_HASH:=' + item['sha256']
                      + '\nPKG_SOURCE_SUBDIR:=' + item['subdir'] + '\n\n')
            text = text.replace(marker, prefix + marker, 1)
        elif item['kind'] == 'git-kernel':
            marker = '  SUBDIR:=linux-$(LINUX_VERSION)\n'
            if text.count(marker) != 1:
                raise ValueError('Unexpected kernel download recipe')
            text = text.replace(marker, marker + '  MIRROR_HASH:=' + item['sha256'] + '\n')
        elif item['kind'] == 'git-or-generated':
            if text.count('PKG_MIRROR_HASH:=skip') != 1:
                raise ValueError('Unexpected QSDK mirror hash declaration')
            text = text.replace('PKG_MIRROR_HASH:=skip', 'PKG_MIRROR_HASH:=' + item['sha256'])
        else:
            raise ValueError('Unknown cache pin kind')
        write(path, text)
        changes.append({'path': item['recipe'], 'sha256': sha256(path),
                        'archive': item['file'], 'archive_sha256': item['sha256']})
    return changes


def stage_policy(source, lock, revision):
    package = source / 'package/cr8808/cr8808-qsdk-policy'
    if package.exists() or (source / 'files').exists():
        raise ValueError('Refusing to merge unknown image overlay or staged policy')
    shutil.copytree(POLICY / 'files', package / 'files')
    # base-files/opkg owns distfeeds.conf. The final image overlay overrides it
    # after package installation without two packages claiming the same path.
    feed = package / 'files/etc/opkg/distfeeds.conf'
    write(source / 'files/etc/opkg/distfeeds.conf', feed.read_bytes())
    feed.unlink()
    for path in (package / 'files').rglob('*'):
        if path.is_file():
            executable = path.suffix == '' and ('uci-defaults' in path.parts or 'sbin' in path.parts)
            write(path, path.read_bytes().replace(b'\r\n', b'\n'), executable)
    recipe = '''# SPDX-License-Identifier: GPL-2.0-or-later
include $(TOPDIR)/rules.mk
PKG_NAME:=cr8808-qsdk-policy
PKG_VERSION:=2026.10.31
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-or-later
include $(INCLUDE_DIR)/package.mk
define Package/cr8808-qsdk-policy
  SECTION:=base
  CATEGORY:=Base system
  TITLE:=CR8808 pinned QSDK candidate policy and read-only checks
  DEPENDS:=+kmod-qca-nss-ecm-standard +swconfig +iw
endef
define Build/Compile
endef
define Package/cr8808-qsdk-policy/install
\t$(CP) ./files/. $(1)/
\t$(INSTALL_DIR) $(1)/etc/rc.d
\t$(LN) ../init.d/qca-nss-ecm $(1)/etc/rc.d/S19qca-nss-ecm
endef
$(eval $(call BuildPackage,cr8808-qsdk-policy))
'''
    write(package / 'Makefile', recipe)
    report = {'status': 'prepared-not-built-not-device-validated', 'source_lock': lock,
              'customization_commit': revision, 'private_configuration_included': False,
              'legacy_kernel_packages_included': False, 'automatic_flash': False,
              'application_scope': 'NSS NAT, dual-band Wi-Fi, LuCI; HomeProxy migration pending'}
    write_json(package / 'files/etc/cr8808-qsdk/candidate.json', report)
    return report


def prepare(source, output):
    source, output = guarded_directory(source), guarded_directory(output)
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Source and preparation output must be separate directories')
    lock = load_lock()
    check_source(source, lock)
    output.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    changes = pin_cached_sources(source, lock)
    report = stage_policy(source, lock, revision)
    feeds = ''.join('src-git {} {}^{}\n'.format(item['name'], item['repository'], item['commit'])
                    for item in lock['feeds'])
    write(source / 'feeds.conf', feeds)
    write(source / '.config', (POLICY / 'cr8808.config').read_bytes().replace(b'\r\n', b'\n'))
    write(source / 'version', 'qsdk-{}-{}\n'.format(lock['source']['commit'][:8], revision[:12]))
    report['cached_source_pins'] = changes
    write_json(output / 'preparation-report.json', report)
    return report


def checkout_feeds(source):
    source = guarded_directory(source)
    lock = load_lock()
    for item in lock['feeds']:
        path = source / 'feeds' / item['name']
        if not path.exists():
            path.mkdir(parents=True)
            for args in [('init',), ('remote', 'add', 'origin', item['repository']),
                         ('fetch', '--depth', '1', 'origin', item['commit']),
                         ('checkout', '--detach', 'FETCH_HEAD')]:
                subprocess.run(['git', '-C', str(path), *args], check=True)
        actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != item['commit']:
            raise ValueError('Feed commit mismatch: ' + item['name'])
    return {'verified_feeds': len(lock['feeds'])}


def cache_member_name(item):
    path = PurePosixPath(item.name)
    if item.isdir() and path == PurePosixPath('.'):
        return None
    if (not item.isfile() or path.is_absolute() or len(path.parts) != 1
            or path.name in ('', '.', '..') or '\\' in item.name or ':' in item.name):
        raise ValueError('Unsafe source cache member: ' + item.name)
    return path.name


def restore_downloads(source, archive):
    source, archive = guarded_directory(source), Path(archive).resolve()
    lock = load_lock()
    expected = lock['reference']['download_archive']
    if archive.stat().st_size != expected['bytes'] or sha256(archive) != expected['sha256']:
        raise ValueError('Historical source cache size/hash mismatch')
    manifest = json.loads((POLICY / 'source-cache-manifest.json').read_text(encoding='utf-8'))
    if sha256(POLICY / 'source-cache-manifest.json') != expected['member_manifest_sha256']:
        raise ValueError('Source cache manifest mismatch')
    destination = source / 'dl'
    if destination.is_symlink():
        raise ValueError('Source cache directory is a symlink')
    destination.mkdir(parents=True, exist_ok=True)
    seen = set()
    with tarfile.open(archive, 'r:') as cached:
        for item in cached:
            name = cache_member_name(item)
            if name is None:
                continue
            if name in seen or name not in manifest or item.size != manifest[name]['bytes']:
                raise ValueError('Unexpected or duplicate source cache member: ' + name)
            seen.add(name)
            target = destination / name
            if target.is_symlink():
                raise ValueError('Source cache destination is a symlink')
            with cached.extractfile(item) as stream, target.open('wb') as out:
                shutil.copyfileobj(stream, out)
            if sha256(target) != manifest[name]['sha256']:
                raise ValueError('Source cache member hash mismatch: ' + name)
    if seen != set(manifest):
        raise ValueError('Incomplete source cache archive')
    return {'source_cache_sha256': expected['sha256'], 'verified_members': len(seen)}


def verify_downloads(source):
    source = guarded_directory(source)
    for item in load_lock()['cached_sources']:
        if sha256(source / 'dl' / item['file']) != item['sha256']:
            raise ValueError('QSDK source archive changed: ' + item['file'])
    return {'critical_cached_sources_verified': len(load_lock()['cached_sources'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--source', type=Path, required=True)
    prepare_parser.add_argument('--output', type=Path, required=True)
    for name in ('feeds', 'verify-downloads', 'finish'):
        sub = commands.add_parser(name)
        sub.add_argument('--source', type=Path, required=True)
        if name == 'finish':
            sub.add_argument('--output', type=Path, required=True)
    sub = commands.add_parser('restore-downloads')
    sub.add_argument('--source', type=Path, required=True)
    sub.add_argument('--archive', type=Path, required=True)
    sub = commands.add_parser('verify-config')
    sub.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.source, args.output)
        result = {key: value for key, value in result.items() if key != 'source_lock'}
    elif args.command == 'feeds':
        result = checkout_feeds(args.source)
    elif args.command == 'restore-downloads':
        result = restore_downloads(args.source, args.archive)
    elif args.command == 'verify-config':
        result = verify_config(args.path)
    elif args.command == 'verify-downloads':
        result = verify_downloads(args.source)
    else:
        from qsdk_candidate_image import finish
        result = finish(args.source, args.output)
        result = {key: value for key, value in result.items() if key not in ('source_lock', 'file_checksums')}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
