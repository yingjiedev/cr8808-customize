"""Stage the pinned fw3 subscription profile and build a static ARM32 core."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import urllib.request

import qsdk_candidate as base

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'firmware/qsdk/proxy'


def load_lock():
    lock = json.loads((POLICY / 'source-lock.json').read_text(encoding='utf-8'))
    for name in ('passwall2', 'core', 'tcping'):
        item = lock[name]
        if not re.fullmatch(r'[0-9a-f]{40}', item['commit']):
            raise ValueError('Proxy sources require complete commit IDs')
        if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+\.git', item['repository']):
            raise ValueError('Unexpected proxy source repository')
    if not re.fullmatch(r'[0-9a-f]{64}', lock['go']['sha256']):
        raise ValueError('Go requires a fixed SHA256')
    return lock


def checkout(item, path):
    if not path.exists():
        path.mkdir(parents=True)
        for args in [('init',), ('config', 'core.autocrlf', 'false'),
                     ('remote', 'add', 'origin', item['repository']),
                     ('fetch', '--depth', '1', 'origin', item['commit']),
                     ('checkout', '--detach', 'FETCH_HEAD')]:
            subprocess.run(['git', '-C', str(path), *args], check=True)
    head = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if head != item['commit']:
        raise ValueError('Proxy source commit mismatch')
    subprocess.run(['git', '-C', str(path), 'diff', '--quiet', 'HEAD', '--'], check=True)
    return path


def replace_exact(text, before, after, count=1):
    if text.count(before) != count:
        raise ValueError('Upstream changed at reviewed patch: ' + before[:90])
    return text.replace(before, after)


def normalise_translations(package):
    # Upstream publishes legacy directories and modern-name symlinks. Old
    # luci.mk aliases both to the same package. Keep one canonical input.
    root = (Path(package) / 'po').resolve()
    for legacy, modern in [('zh-cn', 'zh_Hans'), ('zh-tw', 'zh_Hant')]:
        old, new = root / legacy, root / modern
        if not old.is_dir():
            raise ValueError('Expected legacy translation directory missing')
        if not new.is_dir():
            if not new.is_file() or new.read_text().strip() != legacy:
                raise ValueError('Unexpected translation alias')
            new.unlink()
            shutil.copytree(old, new)
        if not old.resolve().is_relative_to(root) or old.resolve() == root:
            raise ValueError('Translation cleanup outside staged package')
        shutil.rmtree(old)


def verify_config(path):
    base.verify_config(path)
    actual = set(Path(path).read_text(encoding='utf-8').splitlines())
    required = [line for line in (POLICY / 'proxy.config').read_text().splitlines()
                if line.startswith('CONFIG_')]
    missing = [line for line in required if line not in actual]
    forbidden = ['CONFIG_PACKAGE_firewall4', 'CONFIG_PACKAGE_iptables-nft',
                 'CONFIG_PACKAGE_sing-box', 'CONFIG_PACKAGE_geoview',
                 'CONFIG_PACKAGE_v2ray-geoip', 'CONFIG_PACKAGE_v2ray-geosite',
                 'CONFIG_PACKAGE_chinadns-ng', 'CONFIG_PACKAGE_luci-app-passwall2_Basic_Core_All',
                 'CONFIG_PACKAGE_luci-app-passwall2_Nftables_Transparent_Proxy']
    if missing or any(name + '=y' in actual for name in forbidden):
        raise ValueError('Subscription profile lost settings or selected extra cores/firewall: ' + ','.join(missing))
    return {'proxy_required_settings': len(required), 'one_core': True, 'firewall': 'fw3'}


def prepare(source, output):
    source, output = base.guarded_directory(source), base.guarded_directory(output)
    lock = load_lock()
    work = ROOT / 'tmp/qsdk-proxy-inputs'
    upstream = checkout(lock['passwall2'], work / 'passwall2')
    for name, digest in lock['passwall2']['reviewed_files'].items():
        if base.sha256(upstream / name) != digest:
            raise ValueError('Reviewed PassWall2 file mismatch: ' + name)
    packages = source / 'package/cr8808-proxy'
    if packages.exists():
        raise ValueError('Refusing to overwrite staged proxy packages')
    package = packages / 'luci-app-passwall2'
    shutil.copytree(upstream / 'luci-app-passwall2', package)
    normalise_translations(package)
    recipe = (package / 'Makefile').read_text(encoding='utf-8')
    recipe = replace_exact(recipe, '\t+geoview +v2ray-geoip +v2ray-geosite \\\n', '')
    recipe = replace_exact(recipe, '\tselect PACKAGE_chinadns-ng\n', '', 2)
    recipe = replace_exact(recipe, '\tselect PACKAGE_iptables-nft\n', '')
    recipe = replace_exact(recipe, '\tselect PACKAGE_iptables-zz-legacy\n', '')
    # OpenWrt21.02 bundles the socket extension in iptables-mod-tproxy.
    recipe = replace_exact(recipe, '\tselect PACKAGE_iptables-mod-socket\n', '')
    base.write(package / 'Makefile', recipe)
    init = package / 'root/etc/init.d/passwall2'
    text = init.read_text(encoding='utf-8')
    text = replace_exact(text, 'STOP=15\n', 'STOP=15\n\nexport GOGC=50 GOMEMLIMIT=32MiB GOMAXPROCS=2\n')
    base.write(init, text, True)
    base.write(package / 'root/usr/share/passwall2/0_default_config',
               (POLICY / 'passwall2-default.config').read_bytes())
    base.write(packages / 'tcping/Makefile', (POLICY / 'tcping.Makefile').read_bytes())
    core_recipe = '''# SPDX-License-Identifier: MPL-2.0
include $(TOPDIR)/rules.mk
PKG_NAME:=xray-core
PKG_VERSION:=@VERSION@
PKG_RELEASE:=1
PKG_LICENSE:=MPL-2.0
include $(INCLUDE_DIR)/package.mk
define Package/xray-core
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Pinned static ARM32 Xray with VLESS, Hysteria2 and certificate pins
endef
define Build/Prepare
endef
define Build/Configure
endef
define Build/Compile
endef
define Package/xray-core/install
\t$(INSTALL_DIR) $(1)/usr/bin $(1)/usr/share/licenses/xray-core
\t$(INSTALL_BIN) ./files/xray $(1)/usr/bin/xray
\t$(INSTALL_DATA) ./files/LICENSE $(1)/usr/share/licenses/xray-core/LICENSE
endef
$(eval $(call BuildPackage,xray-core))
'''.replace('@VERSION@', lock['core']['version'])
    base.write(packages / 'xray-core/Makefile', core_recipe)
    policy = packages / 'cr8808-qsdk-proxy-policy'
    base.write(policy / 'files/etc/uci-defaults/zzz-cr8808-qsdk-proxy',
               (POLICY / 'proxy-policy').read_bytes(), True)
    base.write_json(policy / 'files/etc/cr8808-qsdk/proxy-sources.json', lock)
    policy_recipe = '''# SPDX-License-Identifier: GPL-2.0-or-later
include $(TOPDIR)/rules.mk
PKG_NAME:=cr8808-qsdk-proxy-policy
PKG_VERSION:=2026.11.01
PKG_RELEASE:=1
include $(INCLUDE_DIR)/package.mk
define Package/cr8808-qsdk-proxy-policy
  SECTION:=base
  CATEGORY:=Base system
  TITLE:=CR8808 fw3 subscription policy
  DEPENDS:=+xray-core +luci-app-passwall2 +flock +zram-swap
endef
define Build/Compile
endef
define Package/cr8808-qsdk-proxy-policy/install
\t$(CP) ./files/. $(1)/
endef
$(eval $(call BuildPackage,cr8808-qsdk-proxy-policy))
'''
    base.write(policy / 'Makefile', policy_recipe)
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'staged-not-built', 'source_lock': lock,
              'changes': ['single static ARM32 core', 'fw3 legacy iptables',
                          'no geodata or geoview', 'dnsmasq ipset fallback',
                          'bounded Go heap target and32MiB zram', 'disabled until privately configured'],
              'private_configuration_included': False}
    base.write_json(output / 'proxy-preparation-report.json', report)
    return report


def configure(source):
    source = base.guarded_directory(source)
    seed = (base.POLICY / 'cr8808.config').read_text(encoding='utf-8')
    seed += '\n' + (POLICY / 'proxy.config').read_text(encoding='utf-8')
    base.write(source / '.config', seed)


def build_core(source, output):
    source, output = base.guarded_directory(source), base.guarded_directory(output)
    lock = load_lock()
    work = ROOT / 'tmp/qsdk-proxy-inputs'
    core = checkout(lock['core'], work / 'xray')
    for name in ('go.mod', 'go.sum'):
        if base.sha256(core / name) != lock['core'][name.replace('.', '_') + '_sha256']:
            raise ValueError('Go module graph mismatch')
    for name, digest in lock['core']['reviewed_files'].items():
        if base.sha256(core / name) != digest:
            raise ValueError('Reviewed certificate verifier source mismatch')
    archive = work / ('go' + lock['go']['version'] + '.tar.gz')
    if not archive.exists():
        part = archive.with_suffix('.part')
        with urllib.request.urlopen(lock['go']['url'], timeout=90) as stream, part.open('wb') as out:
            shutil.copyfileobj(stream, out)
        part.replace(archive)
    if archive.stat().st_size != lock['go']['bytes'] or base.sha256(archive) != lock['go']['sha256']:
        raise ValueError('Go toolchain download mismatch')
    toolchain = work / ('toolchain-' + lock['go']['version'])
    if not (toolchain / 'go/bin/go').exists():
        toolchain.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, 'r:gz') as tar:
            tar.extractall(toolchain, filter='data')
    go = (toolchain / 'go/bin/go').resolve()
    destination = source / 'package/cr8808-proxy/xray-core/files'
    destination.mkdir(parents=True, exist_ok=True)
    binary = (destination / 'xray').resolve()
    env = dict(os.environ, GOOS='linux', GOARCH='arm', GOARM='7', CGO_ENABLED='0',
               GOTOOLCHAIN='local', GOWORK='off', GOSUMDB='sum.golang.org', GOPROXY='https://proxy.golang.org,direct')
    ldflags = '-s -w -buildid= -X github.com/xtls/xray-core/core.build=' + lock['core']['commit'][:7]
    subprocess.run([str(go), 'build', '-mod=readonly', '-trimpath',
                    '-ldflags', ldflags, '-o', str(binary), lock['core']['main']], cwd=core, env=env, check=True)
    shutil.copyfile(core / 'LICENSE', destination / 'LICENSE')
    version = subprocess.check_output(['qemu-arm', str(binary), 'version'], text=True, timeout=30)
    if lock['core']['version'] not in version or 'go' + lock['go']['version'] not in version:
        raise ValueError('Built core version/toolchain mismatch')
    output.mkdir(parents=True, exist_ok=True)
    overlay = output / 'proxy-pin-test-overlay.json'
    base.write_json(overlay, {'Replace': {
        str((core / 'transport/internet/tls/cr8808_profile_test.go').resolve()):
        str((POLICY / 'tests/pinning_profile_test.go').resolve())}})
    subprocess.run([str(go), 'test', '-mod=readonly', '-overlay', str(overlay.resolve()),
                    '-exec', 'qemu-arm', '-run', '^TestCR8808CertificatePinning$',
                    './transport/internet/tls'], cwd=core, env=env, check=True, timeout=240)
    overlay.unlink()
    report = {'status': 'core-built-qemu-version-verified', 'source_lock': lock,
              'bytes': binary.stat().st_size, 'sha256': base.sha256(binary),
              'qemu_version': version, 'certificate_pin_positive_negative_test_passed': True,
              'private_configuration_included': False}
    output.mkdir(parents=True, exist_ok=True)
    base.write_json(output / 'proxy-core-build.json', report)
    return report


def verify_image(source, output):
    import qsdk_candidate_image as image
    source, output = base.guarded_directory(source), base.guarded_directory(output)
    verify_config(source / '.config')
    target = source / 'bin/targets/ipq50xx/arm'
    factory = next(target.glob('*-squashfs-nand-factory.ubi'))
    volumes, ubi = image.read_ubi(factory.read_bytes())
    if struct.unpack_from('<I', volumes['rootfs'], 12)[0] != 65536:
        raise ValueError('Compiled proxy filesystem must use64KiB blocks')
    rootfs = output / 'proxy-rootfs-check.squashfs'
    rootfs.write_bytes(volumes['rootfs'])
    reader = source / 'staging_dir/host/bin/unsquashfs4'
    def data(path):
        return subprocess.check_output([str(reader), '-cat', str(rootfs), path])
    manifest = (target / 'openwrt-ipq50xx-arm-redmi_ax3000.manifest').read_text()
    for name in ['xray-core', 'luci-app-passwall2', 'luci-i18n-passwall2-zh-cn',
                 'iptables-mod-tproxy', 'kmod-ipt-tproxy', 'zram-swap']:
        if not re.search(r'^' + re.escape(name) + r' - ', manifest, re.M):
            raise ValueError('Compiled proxy package missing: ' + name)
    blob = data('usr/bin/xray')
    if not image.arm32_elf(blob):
        raise ValueError('Wrong proxy core architecture')
    built = json.loads((output / 'proxy-core-build.json').read_text())
    if hashlib.sha256(blob).hexdigest() != built['sha256']:
        raise ValueError('Image core differs from tested core')
    init = data('etc/init.d/passwall2').decode()
    if 'GOMEMLIMIT=32MiB' not in init:
        raise ValueError('Runtime heap target missing')
    defaults = data('usr/share/passwall2/0_default_config').decode()
    if "option enabled '0'" not in defaults:
        raise ValueError('Public proxy must start unconfigured and disabled')
    kernel = image.find_built_kernel_config(source).read_text()
    for symbol in ['CONFIG_NETFILTER_XT_TARGET_TPROXY', 'CONFIG_NETFILTER_XT_MATCH_SOCKET', 'CONFIG_ZRAM']:
        if not re.search(r'^' + symbol + r'=[ym]$', kernel, re.M):
            raise ValueError('Required proxy kernel feature absent: ' + symbol)
    for path in ['usr/share/passwall2/subscribe.lua', 'usr/lib/lua/luci/passwall2/util_xray.lua']:
        fixture = output / (Path(path).name + '.check.lua')
        fixture.write_bytes(data(path))
        subprocess.run(['luac5.1', '-p', str(fixture)], check=True)
        fixture.unlink()
    rootfs.unlink()
    readonly_lebs = sum(len(volumes[name]) // 126976 for name in ('kernel', 'rootfs'))
    estimated_data_lebs = 288 - 2 - 20 - 2 - readonly_lebs
    if estimated_data_lebs < 48:
        raise ValueError('Proxy image leaves insufficient UBI data volume headroom')
    report = {'status': 'proxy-image-checks-passed-device-validation-pending',
              'factory_bytes': factory.stat().st_size, 'estimated_rootfs_data_lebs': estimated_data_lebs,
              'core_sha256': built['sha256'], 'single_core': True, 'firewall': 'fw3',
              'private_configuration_included': False, 'automatic_flash': False}
    base.write_json(output / 'proxy-image-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'configure', 'verify-config', 'build-core', 'verify-image'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.command == 'verify-config':
        result = verify_config(args.config)
    elif args.command == 'configure':
        result = configure(args.source)
    else:
        function = {'prepare': prepare, 'build-core': build_core, 'verify-image': verify_image}[args.command]
        result = function(args.source, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
