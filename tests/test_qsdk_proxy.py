import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import qsdk_candidate as base
import qsdk_proxy as proxy


class SubscriptionProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / '.config'
        self.base = (base.POLICY / 'cr8808.config').read_text(encoding='utf-8')
        self.seed = self.base + '\n' + (proxy.POLICY / 'proxy.config').read_text(encoding='utf-8')

    def test_single_fw3_core_profile_is_accepted(self):
        self.path.write_text(self.seed, encoding='utf-8')
        self.assertTrue(proxy.verify_config(self.path)['one_core'])

    def test_unreviewed_core_install_is_rejected(self):
        self.path.write_text(self.base + '\nCONFIG_PACKAGE_sing-box=y\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reviewed subscription policy'):
            base.verify_config(self.path)

    def test_fw4_and_secondary_cores_are_rejected(self):
        for setting in ['CONFIG_PACKAGE_firewall4=y', 'CONFIG_PACKAGE_iptables-nft=y',
                        'CONFIG_PACKAGE_sing-box=y', 'CONFIG_PACKAGE_geoview=y',
                        'CONFIG_PACKAGE_luci-app-passwall2_Basic_Core_All=y']:
            with self.subTest(setting=setting):
                self.path.write_text(self.seed + '\n' + setting + '\n', encoding='utf-8')
                with self.assertRaises(ValueError):
                    proxy.verify_config(self.path)

    def test_missing_udp_or_socket_support_is_rejected(self):
        for setting in ['CONFIG_PACKAGE_iptables-mod-tproxy=y', 'CONFIG_PACKAGE_kmod-ipt-tproxy=y']:
            with self.subTest(setting=setting):
                self.path.write_text(self.seed.replace(setting, ''), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'lost settings'):
                    proxy.verify_config(self.path)

    def test_locked_build_retains_required_subscription_protocol_features(self):
        lock = proxy.load_lock()
        self.assertEqual(lock['core']['name'], 'xray')
        self.assertTrue(lock['core']['supports_hysteria2_certificate_pins'])
        self.assertFalse(lock['runtime']['private_configuration_included'])
        self.assertFalse(lock['runtime']['geo_datasets_included'])

    def test_download_flags_keep_ca_checks_and_node_pins_unchanged(self):
        source = 'args = {"-fskL", "-skfL"}; pinSHA256 = "fixture"'
        patched = proxy.verified_https(source)
        self.assertEqual(patched, 'args = {"-fsL", "-sfL"}; pinSHA256 = "fixture"')

    def test_translation_aliases_keep_only_one_canonical_package_input(self):
        package = Path(self.directory.name) / 'package'
        for old, new in [('zh-cn', 'zh_Hans'), ('zh-tw', 'zh_Hant')]:
            source = package / 'po' / old
            source.mkdir(parents=True)
            (source / 'passwall2.po').write_text('translation fixture', encoding='utf-8')
            (package / 'po' / new).write_text(old, encoding='utf-8')
        proxy.normalise_translations(package)
        self.assertEqual(sorted(p.name for p in (package / 'po').iterdir()), ['zh_Hans', 'zh_Hant'])
        self.assertEqual((package / 'po/zh_Hans/passwall2.po').read_text(), 'translation fixture')


if __name__ == '__main__':
    unittest.main()
