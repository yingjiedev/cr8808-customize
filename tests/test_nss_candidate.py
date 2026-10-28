import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('nss_candidate', ROOT / 'scripts/prepare-nss-candidate.py')
nss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nss)


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


if __name__ == '__main__':
    unittest.main()
