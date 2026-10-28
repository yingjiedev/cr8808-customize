"""Stage a pinned Linux NSS build tree; never connect to or flash a device."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import dependency_lib as deps

ROOT = Path(__file__).resolve().parents[1]
NSS = ROOT / 'firmware/nss'
CPU_PATCH = 'target/linux/qualcommax/patches-6.18/0974-arm64-dts-qcom-ipq5018-let-the-CPU-boost-to-1296-MHz.patch'


def load_lock():
    lock = json.loads((NSS / 'source-lock.json').read_text(encoding='utf-8'))
    if lock.get('schema_version') != 1 or lock.get('cpu_max_khz') != 1008000:
        raise ValueError('Unexpected NSS policy')
    if lock.get('wifi_offload') is not False or lock.get('software_flow_offload') is not False:
        raise ValueError('Candidate must keep wireless NSS and software flowtable disabled')
    for item in [lock['source'], *lock['feeds']]:
        if not re.fullmatch('[0-9a-f]{40}', item['commit']):
            raise ValueError('All sources require exact commit IDs')
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', item['repository']):
            raise ValueError('Unexpected source repository')
    names = [feed['name'] for feed in lock['feeds']]
    if sorted(names) != ['luci', 'nss', 'packages', 'routing', 'telephony', 'video']:
        raise ValueError('Unexpected feed set')
    return lock


def write(path, data, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.replace('\r\n', '\n').encode())
    path.chmod(0o755 if executable else 0o644)


def verify_config(path):
    actual = set(path.read_text(encoding='utf-8').splitlines())
    requested = [line for line in (NSS / 'cr8808.config').read_text().splitlines() if line.startswith('CONFIG_')]
    missing = [line for line in requested if line not in actual]
    if missing:
        raise ValueError('defconfig dropped requested settings: ' + ', '.join(missing))
    if 'CONFIG_PACKAGE_sing-box=y' in actual:
        raise ValueError('Unpinned sing-box must not replace the frozen core')
    if 'CONFIG_PACKAGE_dnsmasq=y' in actual or 'CONFIG_PACKAGE_dnsmasq-dhcpv6=y' in actual:
        raise ValueError('Use dnsmasq-full with nftset for HomeProxy GFWList')
    if 'CONFIG_NSS_MEM_PROFILE_MEDIUM=y' in actual or 'CONFIG_ATH11K_MEM_PROFILE_1G=y' in actual:
        raise ValueError('Wrong memory profile for 256 MiB')
    return {'requested_settings_verified': len(requested)}


def remove_cpu_boost(source):
    path = source / CPU_PATCH
    text = path.read_text(encoding='utf-8')
    if text.count('+\t\topp-1296000000 {') != 1 or 'above the rated 1008 MHz' not in text:
        raise ValueError('CPU boost patch changed: inspect instead of silently removing')
    digest = deps.sha256(path.read_bytes())
    path.unlink()
    return digest


def package_makefile(name, title, dependencies, provides=''):
    return f'''# SPDX-License-Identifier: GPL-2.0-or-later
include $(TOPDIR)/rules.mk
PKG_NAME:={name}
PKG_VERSION:=1.12.25
PKG_RELEASE:=4
PKG_LICENSE:=GPL-3.0-or-later
include $(INCLUDE_DIR)/package.mk
define Package/{name}
  SECTION:=net
  CATEGORY:=Network
  TITLE:={title}
  DEPENDS:={dependencies}
  PROVIDES:={provides}
endef
define Build/Compile
endef
define Package/{name}/install
\t$(CP) ./files/. $(1)/
endef
$(eval $(call BuildPackage,{name}))
'''


def stage_packages(source, baseline):
    frozen = deps.load_lock()
    entry = deps.by_id(frozen, 'sing-box-squashfs')
    _, files = deps.package_parts(ROOT / entry['path'])
    core = source / 'package/cr8808/sing-box-squashfs'
    if core.exists():
        raise ValueError('Refusing to overwrite staged core package')
    for name, data in files.items():
        if name.endswith('.ko') or name.startswith('lib/modules/'):
            raise ValueError('Legacy kernel modules are forbidden in the new image')
        executable = name.startswith('etc/init.d/') or name.startswith('usr/bin/')
        write(core / 'files' / name, data, executable)
    recipe = package_makefile('sing-box-squashfs', 'Frozen sing-box 1.12.25 compressed core',
                              '+ca-bundle +kmod-inet-diag', 'sing-box')
    recipe = recipe.replace('  PROVIDES:=sing-box', '  USERID:=sing-box=5566:sing-box=5566\n  PROVIDES:=sing-box')
    write(core / 'Makefile', recipe)

    app = source / 'package/cr8808/luci-app-homeproxy'
    shutil.copytree(ROOT / 'upstream/homeproxy', app)
    recipe = (app / 'Makefile').read_text(encoding='utf-8')
    if recipe.count('+sing-box \\') != 1 or recipe.count('include ../../luci.mk') != 1:
        raise ValueError('HomeProxy recipe changed')
    recipe = recipe.replace('+sing-box \\', '+sing-box-squashfs \\\n\t+dnsmasq-full \\')
    recipe = recipe.replace('include ../../luci.mk', 'include $(TOPDIR)/feeds/luci/luci.mk')
    recipe = recipe.replace('LUCI_TITLE:=', 'PKG_VERSION:=26.236.50592\nPKG_RELEASE:=1\n\nLUCI_TITLE:=', 1)
    write(app / 'Makefile', recipe)

    policy = source / 'package/cr8808/cr8808-nss-policy'
    shutil.copytree(NSS / 'files', policy / 'files')
    # base-files owns this path. Override after APK installation via the
    # image overlay, rather than making two packages claim the same file.
    repository_list = 'etc/apk/repositories.d/distfeeds.list'
    repository_override = policy / 'files' / repository_list
    write(source / 'files' / repository_list, repository_override.read_bytes().replace(b'\r\n', b'\n'))
    repository_override.unlink()
    for path in (baseline / 'overlay').rglob('*'):
        if not path.is_file():
            continue
        name = path.relative_to(baseline / 'overlay').as_posix()
        if 'cr8808-proxy-wan' in name:
            target = policy / 'files' / name
        elif name.startswith('www/'):
            target = app / 'htdocs' / name[4:]
        else:
            target = app / 'root' / name
        executable = name.startswith('etc/init.d/') or name.startswith('etc/hotplug.d/')
        write(target, path.read_bytes(), executable)
    for path in (policy / 'files').rglob('*'):
        if path.is_file():
            executable = path.relative_to(policy / 'files').parts[:2] in [('etc', 'uci-defaults'), ('usr', 'sbin')]
            write(path, path.read_bytes().replace(b'\r\n', b'\n'), executable)
    recipe = package_makefile('cr8808-nss-policy', 'CR8808 wired NSS candidate policy',
                              '+nss-tools-dwmac +sing-box-squashfs')
    recipe = recipe.replace('PKG_VERSION:=1.12.25', 'PKG_VERSION:=2026.10.28').replace('PKG_LICENSE:=GPL-3.0-or-later', 'PKG_LICENSE:=GPL-2.0-or-later')
    write(policy / 'Makefile', recipe)
    return {'core_image_sha256': frozen['build']['core_image_sha256'],
            'core_binary_sha256': frozen['build']['core_binary_sha256'],
            'homeproxy_overlay_files': sum(path.is_file() for path in (baseline / 'overlay').rglob('*'))}


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    if source == ROOT or ROOT.is_relative_to(source) or output == ROOT or ROOT.is_relative_to(output):
        raise ValueError('Build directories cannot contain the project')
    if source.is_relative_to(ROOT) and source.relative_to(ROOT).parts[0] != 'tmp':
        raise ValueError('In-repository source must be under tmp/')
    if output.is_relative_to(ROOT) and output.relative_to(ROOT).parts[0] != 'tmp':
        raise ValueError('In-repository output must be under tmp/')
    lock = load_lock()
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != lock['source']['commit']:
        raise ValueError('NSS source commit mismatch')
    subprocess.run(['git', '-C', str(source), 'diff', '--quiet', 'HEAD', '--'], check=True)
    dts = (source / 'target/linux/qualcommax/dts/ipq5018-cr8806.dts').read_text()
    if dts.count('qcom,ath11k-fw-memory-mode = <2>') != 2 or 'coherent_pool=512K' not in dts or '0x800000' not in dts:
        raise ValueError('Unexpected 256 MiB board configuration')
    output.mkdir(parents=True, exist_ok=False)
    baseline = output / 'baseline'
    deps.build(deps.load_lock(), baseline)
    digest = remove_cpu_boost(source)
    application = stage_packages(source, baseline)
    feeds = ''.join(f"src-git {item['name']} {item['repository']}^{item['commit']}\n" for item in lock['feeds'])
    write(source / 'feeds.conf', feeds)
    write(source / '.config', (NSS / 'cr8808.config').read_bytes())
    # The legacy application's inner SquashFS uses XZ regardless of rootfs compression.
    config = source / 'target/linux/qualcommax/config-6.18'
    text = config.read_text()
    if not re.search(r'^CONFIG_BLK_DEV_LOOP=y$', text, re.M):
        raise ValueError('Loop devices must be built into the candidate kernel')
    text = re.sub(r'^# CONFIG_SQUASHFS_XZ is not set\n', '', text, flags=re.M)
    if not re.search(r'^CONFIG_SQUASHFS_XZ=y$', text, re.M):
        text += '\nCONFIG_SQUASHFS_XZ=y\n'
    write(config, text)
    report = {'status': 'prepared-not-built-not-device-validated', 'source_lock': lock,
              'removed_cpu_patch_sha256': digest, 'application': application,
              'private_configuration_included': False, 'legacy_kernel_packages_included': False}
    write(source / 'package/cr8808/cr8808-nss-policy/files/etc/cr8808-nss/candidate.json', json.dumps(report, indent=2)+'\n')
    write(output / 'preparation-report.json', json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-config', type=Path)
    args = parser.parse_args()
    if args.verify_config:
        print(json.dumps(verify_config(args.verify_config), indent=2))
    elif args.source and args.output:
        print(json.dumps(prepare(args.source, args.output), indent=2))
    else:
        parser.error('Specify --source and --output, or --verify-config')


if __name__ == '__main__':
    main()
