import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('nss_candidate', ROOT / 'scripts/prepare-nss-candidate.py')
nss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nss)
from nss_candidate_image import verify_nand_fit, verify_nand_tree


def encode_fdt(tree):
    strings, block = bytearray(), bytearray()
    def node(name, props, children):
        block.extend(struct.pack('>I', 1) + name.encode() + b'\0')
        block.extend(b'\0' * (-len(block) % 4))
        for name, value in props.items():
            offset = len(strings)
            strings.extend(name.encode() + b'\0')
            block.extend(struct.pack('>III', 3, len(value), offset) + value)
            block.extend(b'\0' * (-len(block) % 4))
        for name, (props, children) in children.items():
            node(name, props, children)
        block.extend(struct.pack('>I', 2))
    node('', *tree)
    block.extend(struct.pack('>I', 9))
    header = struct.pack('>10I', 0xd00dfeed, 56+len(block)+len(strings), 56,
                         56+len(block), 40, 17, 16, 0, len(strings), len(block))
    return header + b'\0'*16 + block + strings


class NSSCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_no_floating_feed_revisions_or_acceleration_policy_changes(self):
        lock = nss.load_lock()
        self.assertEqual(lock['profile'], 'xiaomi_cr8806')
        self.assertLess(lock['maximum_factory_bytes'], lock['slot_bytes'])

    def test_dropped_kernel_dependency_is_a_failure(self):
        config = (nss.NSS / 'cr8808.config').read_text()
        path = self.path / '.config'
        path.write_text(config)
        nss.verify_config(path)
        path.write_text(config.replace('CONFIG_PACKAGE_kmod-nft-tproxy=y', '# CONFIG_PACKAGE_kmod-nft-tproxy is not set'))
        with self.assertRaisesRegex(ValueError, 'dropped'):
            nss.verify_config(path)

    def test_accidental_second_proxy_core_is_rejected(self):
        path = self.path / '.config'
        path.write_text((nss.NSS / 'cr8808.config').read_text() + '\nCONFIG_PACKAGE_sing-box=y\n')
        with self.assertRaisesRegex(ValueError, 'Unpinned'):
            nss.verify_config(path)

    def test_wrong_memory_profile_is_rejected(self):
        path = self.path / '.config'
        path.write_text((nss.NSS / 'cr8808.config').read_text() + '\nCONFIG_NSS_MEM_PROFILE_MEDIUM=y\n')
        with self.assertRaisesRegex(ValueError, 'Wrong memory'):
            nss.verify_config(path)

    def test_minimal_dns_variant_is_rejected(self):
        path = self.path / '.config'
        path.write_text((nss.NSS / 'cr8808.config').read_text() + '\nCONFIG_PACKAGE_dnsmasq=y\n')
        with self.assertRaisesRegex(ValueError, 'dnsmasq-full'):
            nss.verify_config(path)

    def test_cpu_boost_patch_requires_expected_content(self):
        patch = self.path / nss.CPU_PATCH
        patch.parent.mkdir(parents=True)
        patch.write_text('unknown upstream content')
        with self.assertRaisesRegex(ValueError, 'inspect'):
            nss.remove_cpu_boost(self.path)
        self.assertTrue(patch.exists())
        patch.write_text('above the rated 1008 MHz\n+\t\topp-1296000000 {\n')
        self.assertEqual(len(nss.remove_cpu_boost(self.path)), 64)
        self.assertFalse(patch.exists())

    def test_nand_override_is_removed_only_from_reviewed_board_source(self):
        path = self.path / nss.BOARD_DTS
        path.parent.mkdir(parents=True)
        path.write_text(nss.ECC_OVERRIDE)
        report = nss.configure_nand_ecc(self.path)
        self.assertEqual(report['expected_strength'], 4)
        self.assertNotIn('nand-ecc-strength', path.read_text())
        path.write_text(nss.ECC_OVERRIDE.replace('<8>', '<4>'))
        with self.assertRaisesRegex(ValueError, 'inspect'):
            nss.configure_nand_ecc(self.path)

    def test_compiled_nand_rejects_original_ecc8_override(self):
        tree = {'/': {'compatible': b'xiaomi,cr8806\0qcom,ipq5018\0'},
                '/soc/nand/nand@0': {'compatible': b'spi-nand\0', 'nand-ecc-engine': b'\0\0\0\1'}}
        self.assertEqual(verify_nand_tree(tree)['expected_strength'], 4)
        tree['/soc/nand/nand@0']['nand-ecc-strength'] = (8).to_bytes(4, 'big')
        with self.assertRaisesRegex(ValueError, 'forced ECC8'):
            verify_nand_tree(tree)

    def test_fit_nand_check_reads_and_verifies_standard_hashes(self):
        chip = {'compatible': b'spi-nand\0', 'nand-ecc-engine': (1).to_bytes(4, 'big')}
        dtb = encode_fdt(({'compatible': b'xiaomi,cr8806\0'}, {'nand@0': (chip, {})}))
        hashes = {'hash-1': ({'algo': b'crc32\0', 'value': struct.pack('>I', zlib.crc32(dtb))}, {}),
                  'hash-2': ({'algo': b'sha1\0', 'value': hashlib.sha1(dtb).digest()}, {})}
        fit = encode_fdt(({}, {
            'images': ({}, {'fdt-1': ({'data': dtb, 'compression': b'none\0'}, hashes)}),
            'configurations': ({}, {'config@mp02.1': ({'fdt': b'fdt-1\0'}, {})})}))
        self.assertTrue(verify_nand_fit(fit)['compiled_override_absent'])
        with self.assertRaisesRegex(ValueError, 'hash mismatched'):
            verify_nand_fit(fit.replace(b'xiaomi,cr8806', b'xiaomi,cr8808', 1))

    def test_application_staging_preserves_verified_binary_and_acl(self):
        # Real public baseline inputs catch a mismatch between recipes, overlays,
        # core manifests and the maintenance lock. No network or device access.
        baseline = self.path / 'baseline'
        nss.deps.build(nss.deps.load_lock(), baseline)
        source = self.path / 'nss-tree'
        result = nss.stage_packages(source, baseline)
        core = source / 'package/cr8808/sing-box-squashfs/files'
        manifest = json.loads((core / 'usr/share/sing-box-squashfs/manifest.json').read_text())
        self.assertEqual(manifest['binary_sha256'], result['core_binary_sha256'])
        self.assertEqual(nss.deps.sha256((core / 'usr/share/sing-box-squashfs/core.squashfs').read_bytes()), result['core_image_sha256'])
        self.assertFalse(list(source.rglob('*.ko')))
        self.assertFalse(list(source.rglob('*.ipk')))
        app = source / 'package/cr8808/luci-app-homeproxy'
        acl = json.loads((app / 'root/usr/share/rpcd/acl.d/luci-app-homeproxy.json').read_text())
        self.assertIn('download', acl['luci-app-homeproxy']['read']['cgi-io'])
        self.assertIn('+sing-box-squashfs', (app / 'Makefile').read_text())
        self.assertIn('CR8808:', (app / 'root/usr/share/rpcd/ucode/luci.homeproxy').read_text())
        self.assertEqual(result['homeproxy_overlay_files'], 8)
        self.assertTrue((source / 'files/etc/apk/repositories.d/distfeeds.list').is_file())
        self.assertFalse((source / 'package/cr8808/cr8808-nss-policy/files/etc/apk/repositories.d/distfeeds.list').exists())


if __name__ == '__main__':
    unittest.main()
