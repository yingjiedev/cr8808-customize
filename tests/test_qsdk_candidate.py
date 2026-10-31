import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import qsdk_candidate as qsdk
from qsdk_candidate_image import fit_device_tree, read_ubi, verify_tree, ubi_crc


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


def reviewed_tree():
    return {'/': {'compatible': b'redmi,ax3000\0qcom,ipq5018\0'},
            '/nand': {'compatible': b'qcom,ebi2-nandc-bam-v2.1.1\0'},
            '/nand/nandcs@0': {'compatible': b'qcom,nandcs\0',
                               'nand-ecc-strength': struct.pack('>I', 4),
                               'nand-ecc-step-size': struct.pack('>I', 512)},
            '/cpus/cpu@0': {'device_type': b'cpu\0', 'operating-points': struct.pack('>4I', 800000, 1100000, 1008000, 1100000)},
            '/cpus/cpu@1': {'device_type': b'cpu\0', 'operating-points': struct.pack('>4I', 800000, 1100000, 1008000, 1100000)},
            '/reserved-memory/nss@40000000': {'reg': struct.pack('>4I', 0, 0x40000000, 0, 8388608)},
            '/reserved-memory/q6_mem_regions@4b000000': {'reg': struct.pack('>4I', 0, 0x4b000000, 0, 50331648)},
            '/dp1': {'compatible': b'qcom,nss-dp\0', 'qcom,id': struct.pack('>I', 1)},
            '/dp2': {'compatible': b'qcom,nss-dp\0', 'qcom,id': struct.pack('>I', 2)}}


def encode_ubi(names=('kernel', 'rootfs', 'rootfs_data')):
    table = bytearray(172*128)
    for index, name in enumerate(names):
        record = bytearray(172)
        struct.pack_into('>III', record, 0, 1, 1, 0)
        record[12] = 1
        struct.pack_into('>H', record, 14, len(name))
        record[16:16+len(name)] = name.encode()
        struct.pack_into('>I', record, 168, ubi_crc(record[:168]))
        table[index*172:(index+1)*172] = record
    def block(volume, lnum, payload, static=False):
        data = bytearray(b'\xff' * 131072)
        ec = bytearray(64)
        ec[:5] = b'UBI#\x01'
        struct.pack_into('>III', ec, 16, 2048, 4096, 123)
        struct.pack_into('>I', ec, 60, ubi_crc(ec[:60]))
        vid = bytearray(64)
        vid[:6] = b'UBI!\x01' + bytes([2 if static else 1])
        struct.pack_into('>II', vid, 8, volume, lnum)
        if static:
            struct.pack_into('>I', vid, 20, len(payload))
            struct.pack_into('>I', vid, 24, 1)
            struct.pack_into('>I', vid, 32, ubi_crc(payload))
        struct.pack_into('>I', vid, 60, ubi_crc(vid[:60]))
        data[:64], data[2048:2112] = ec, vid
        data[4096:4096+len(payload)] = payload
        return bytes(data)
    return (block(0x7fffefff, 0, table) + block(0x7fffefff, 1, table)
            + block(0, 0, b'\xd0\x0d\xfe\xedkernel', True) + block(1, 0, b'hsqsrootfs'))


class QSDKCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_pins_match_public_original_release_inputs(self):
        lock = qsdk.load_lock()
        self.assertEqual(lock['source']['commit'], 'ab1f9ffa5b5b62f252a5e87eb23f51f4e2544511')
        self.assertEqual(lock['reference']['factory_sha256'], '8ec4fd5b5c2ad4d7f802ad57f356811216b75f032103c7662879aca985be9f3e')
        for name, digest in lock['reference']['buildinfo_sha256'].items():
            self.assertEqual(qsdk.sha256(qsdk.POLICY / 'reference' / name), digest)
        cache = lock['reference']['download_archive']
        self.assertEqual(cache['bytes'], 923668480)
        self.assertEqual(qsdk.sha256(qsdk.POLICY / 'source-cache-manifest.json'), cache['member_manifest_sha256'])

    def test_missing_ecm_or_other_board_selection_fails(self):
        config = (qsdk.POLICY / 'cr8808.config').read_text(encoding='utf-8')
        path = self.path / '.config'
        path.write_text(config, encoding='utf-8')
        qsdk.verify_config(path)
        path.write_text(config.replace('CONFIG_PACKAGE_kmod-qca-nss-ecm-standard=y', ''), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'dropped'):
            qsdk.verify_config(path)
        path.write_text(config + '\nCONFIG_TARGET_ipq50xx_arm_DEVICE_xiaomi_cr881x=y\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Only the reviewed'):
            qsdk.verify_config(path)

    def test_incompatible_application_or_large_memory_profile_is_rejected(self):
        config = (qsdk.POLICY / 'cr8808.config').read_text(encoding='utf-8')
        path = self.path / '.config'
        for name in ['CONFIG_ATH11K_MEM_PROFILE_1G', 'CONFIG_PACKAGE_firewall4',
                     'CONFIG_PACKAGE_luci-app-homeproxy', 'CONFIG_PACKAGE_dnsmasq']:
            path.write_text(config + '\n' + name + '=y\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Wrong target'):
                qsdk.verify_config(path)

    def test_ecc8_in_compiled_tree_is_rejected(self):
        tree = reviewed_tree()
        self.assertEqual(verify_tree(tree)['ecc_strength'], 4)
        tree['/nand/nandcs@0']['nand-ecc-strength'] = struct.pack('>I', 8)
        with self.assertRaisesRegex(ValueError, 'ECC4/512'):
            verify_tree(tree)

    def test_overclock_and_wrong_radio_memory_are_rejected(self):
        tree = reviewed_tree()
        tree['/cpus/cpu@0']['operating-points'] = struct.pack('>2I', 1296000, 1100000)
        with self.assertRaisesRegex(ValueError, 'CPU frequency'):
            verify_tree(tree)
        tree = reviewed_tree()
        tree['/reserved-memory/q6_mem_regions@4b000000']['reg'] = struct.pack('>4I', 0, 0x4b000000, 0, 0x3b00000)
        with self.assertRaisesRegex(ValueError, '256 MiB'):
            verify_tree(tree)

    def test_missing_independent_wan_dataplane_is_rejected(self):
        tree = reviewed_tree()
        del tree['/dp1']
        with self.assertRaisesRegex(ValueError, 'independent'):
            verify_tree(tree)

    def test_fit_checks_embedded_device_tree_digest(self):
        dtb = encode_fdt(({'compatible': b'redmi,ax3000\0'}, {}))
        fit = encode_fdt(({}, {
            'images': ({}, {'fdt@1': ({'data': dtb, 'compression': b'none\0'}, {
                'hash@1': ({'algo': b'sha256\0', 'value': hashlib.sha256(dtb).digest()}, {})})}),
            'configurations': ({}, {'config@mp02.1': ({'fdt': b'fdt@1\0'}, {})})}))
        self.assertEqual(fit_device_tree(fit)['/']['compatible'], b'redmi,ax3000\0')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            fit_device_tree(fit.replace(b'redmi,ax3000', b'redmi,ax9999', 1))

    def test_ubi_checks_crc_tables_geometry_and_volume_payloads(self):
        blob = encode_ubi()
        volumes, report = read_ubi(blob)
        self.assertTrue(volumes['kernel'].startswith(b'\xd0\x0d\xfe\xed'))
        self.assertTrue(volumes['rootfs'].startswith(b'hsqs'))
        self.assertEqual(report['min_io_bytes'], 2048)
        damaged = bytearray(blob)
        damaged[20] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
            read_ubi(damaged)
        damaged = bytearray(blob)
        damaged[2*131072+4096+4] ^= 1
        with self.assertRaisesRegex(ValueError, 'data CRC mismatch'):
            read_ubi(damaged)
        with self.assertRaisesRegex(ValueError, 'volume names'):
            read_ubi(encode_ubi(('kernel', 'rootfs', 'unexpected')))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            read_ubi(blob, slot_bytes=4*131072)

    def test_cache_members_cannot_escape_or_create_links(self):
        for name in ['../outside', '/absolute', 'sub/file', 'C:\\outside']:
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                qsdk.cache_member_name(tarfile.TarInfo(name))
        link = tarfile.TarInfo('archive.tar.xz')
        link.type = tarfile.SYMTYPE
        link.linkname = '../outside'
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            qsdk.cache_member_name(link)

    def test_restoration_verifies_archive_and_individual_members(self):
        archive, policy = self.path / 'dl.tar', self.path / 'policy'
        policy.mkdir()
        data = b'historical-source'
        with tarfile.open(archive, 'w:') as out:
            item = tarfile.TarInfo('./package.tar.xz')
            item.size = len(data)
            out.addfile(item, io.BytesIO(data))
        manifest_path = policy / 'source-cache-manifest.json'
        manifest_path.write_text(json.dumps({'package.tar.xz': {'bytes': len(data),
                                'sha256': hashlib.sha256(data).hexdigest()}}), encoding='utf-8')
        lock = {'reference': {'download_archive': {'bytes': archive.stat().st_size,
                'sha256': qsdk.sha256(archive), 'member_manifest_sha256': qsdk.sha256(manifest_path)}}}
        with mock.patch.object(qsdk, 'POLICY', policy), mock.patch.object(qsdk, 'load_lock', return_value=lock):
            result = qsdk.restore_downloads(self.path / 'source', archive)
            self.assertEqual(result['verified_members'], 1)
            self.assertEqual((self.path/'source/dl/package.tar.xz').read_bytes(), data)
            archive.write_bytes(archive.read_bytes()[:-1] + b'x')
            with self.assertRaisesRegex(ValueError, 'cache size/hash mismatch'):
                qsdk.restore_downloads(self.path / 'bad', archive)

    def test_floating_firmware_is_replaced_by_content_pinned_archive(self):
        path = self.path / 'package/firmware/test/Makefile'
        path.parent.mkdir(parents=True)
        path.write_text('PKG_SOURCE_PROTO:=git\nPKG_SOURCE_URL:=https://github.com/example/firmware\n'
                        'PKG_SOURCE_VERSION:=main\nPKG_MIRROR_HASH:=skip\n'
                        'include $(INCLUDE_DIR)/package.mk\n', encoding='utf-8')
        lock = {'cached_sources': [{'recipe': 'package/firmware/test/Makefile',
                'kind': 'firmware-archive', 'file': 'test-1.tar.xz', 'sha256': 'a'*64, 'subdir': 'test-1'}]}
        qsdk.pin_cached_sources(self.path, lock)
        text = path.read_text(encoding='utf-8')
        self.assertNotIn(':=main', text)
        self.assertNotIn(':=skip', text)
        self.assertIn('PKG_HASH:=' + 'a'*64, text)
        self.assertIn('PKG_SOURCE_URL:=file://$(DL_DIR)', text)

    def test_staging_uses_only_public_policy_and_explicit_ecm_boot_link(self):
        report = qsdk.stage_policy(self.path, qsdk.load_lock(), '1'*40)
        package = self.path / 'package/cr8808/cr8808-qsdk-policy'
        text = (package / 'Makefile').read_text(encoding='utf-8')
        self.assertIn('$(LN) ../init.d/qca-nss-ecm $(1)/etc/rc.d/S19qca-nss-ecm', text)
        self.assertFalse(report['private_configuration_included'])
        self.assertTrue((self.path / 'files/etc/opkg/distfeeds.conf').is_file())
        self.assertFalse((package / 'files/etc/opkg/distfeeds.conf').exists())
        self.assertFalse(list(package.rglob('*.ipk')))
        self.assertFalse(list(package.rglob('*.ko')))


if __name__ == '__main__':
    unittest.main()
