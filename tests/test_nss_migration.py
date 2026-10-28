import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('nss_migration',ROOT/'scripts/prepare-nss-migration.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class NSSMigrationTests(unittest.TestCase):
    def fixture(self):
        return {
            'etc/config/network': b"config interface 'loopback'\n option device 'lo'\nconfig interface 'lan'\n option device 'br-lan'\n option proto 'static'\n option ipaddr '192.168.1.1'\nconfig interface 'wan'\n option device 'wan'\n option proto 'dhcp'\nconfig interface 'wan6'\n option device 'wan'\n option proto 'dhcpv6'\n",
            'etc/config/wireless': b"config wifi-device 'radio0'\n option band '5g'\n option path 'old-device/path-5g'\nconfig wifi-iface 'default_radio0'\n option device 'radio0'\n option mode 'ap'\n option network 'lan'\n option ssid 'example #5'\n option encryption 'sae-mixed'\n option key 'dummy-example-key'\nconfig wifi-device 'radio1'\n option band '2g'\n option path 'old-device/path-2g'\nconfig wifi-iface 'default_radio1'\n option device 'radio1'\n option mode 'ap'\n option network 'lan'\n option ssid 'example #2'\n option encryption 'sae-mixed'\n option key 'dummy-example-key'\n",
            'etc/config/homeproxy':b"config homeproxy 'config'\n option main_node 'example'\n",
            'etc/config/dhcp':b"config dhcp 'lan'\n option interface 'lan'\n",
            'etc/config/firewall':b"config defaults\n option flow_offloading '0'\n",
            'etc/config/system':b"config system\n option timezone 'CST-8'\n",
            'etc/shadow':b'root:$6$dummy$hashed:1:0:99999:7:::\n',
            'etc/dropbear/dropbear_ed25519_host_key':b'dummy-key-fixture',
            'etc/fw_env.config':b'must-not-copy',
            'etc/init.d/homeproxy':b'must-not-copy',
        }

    def test_radios_follow_band_without_old_hardware_paths(self):
        data=m.settings(self.fixture())
        self.assertEqual(data['radios'][0]['band'],'5g')
        self.assertEqual(data['radios'][0]['ap_options']['ssid'],'example #5')
        self.assertNotIn('path',data['radios'][0]['device_options'])
        self.assertNotIn('device',data['network']['wan'])

    def test_public_output_directory_is_rejected_before_private_read(self):
        with self.assertRaisesRegex(ValueError,'Private migration output'):
            m.prepare(Path('does-not-exist.tar.gz'),ROOT/'firmware/private')

    def test_guest_network_is_not_silently_dropped(self):
        files=self.fixture();files['etc/config/network']+=b"config interface 'guest'\n option proto 'static'\n"
        with self.assertRaisesRegex(ValueError,'Additional network'):
            m.settings(files)

    def test_payload_does_not_restore_boot_tools_or_old_services(self):
        files,_=m.migration_files(self.fixture())
        for forbidden in ('etc/fw_env.config','etc/init.d/homeproxy','etc/config/network','etc/config/wireless','etc/shadow'):
            self.assertNotIn(forbidden,files)
        self.assertIn('etc/dropbear/dropbear_ed25519_host_key',files)
        self.assertEqual(files['etc/cr8808-nss/private-settings.json'][1],0o600)

    def test_unencrypted_ap_is_not_created(self):
        files=self.fixture();files['etc/config/wireless']=files['etc/config/wireless'].replace(b"'sae-mixed'",b"'none'")
        with self.assertRaisesRegex(ValueError,'encrypted'):
            m.settings(files)


if __name__=='__main__':unittest.main()
