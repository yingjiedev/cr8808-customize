import copy
import io
from http.client import IncompleteRead
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dependency_lib as deps


def tar_bytes(files):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, depends=None, architecture='aarch64_cortex-a53'):
        abi = '6.6.137~exact-r1'
        base = self.root / 'dependencies/baseline/firmware.manifest'
        base.parent.mkdir(parents=True)
        base.write_text(f'kernel - {abi}\nlibc - 1\n', encoding='utf-8')
        control = {'Package': 'kmod-example', 'Version': '6.6.137-r1',
                   'Architecture': architecture, 'Depends': depends or f'kernel (={abi}), libc'}
        body = tar_bytes({'control': ''.join(f'{key}: {value}\n' for key, value in control.items()).encode()})
        package = tar_bytes({'debian-binary': b'2.0\n', 'control.tar.gz': body,
                             'data.tar.gz': tar_bytes({'lib/example.ko': b'example'})})
        path = self.root / 'example.ipk'
        path.write_bytes(package)
        entry = {'id': 'example', 'path': 'example.ipk', 'role': 'runtime', 'storage': 'vendored',
                 'bytes': len(package), 'sha256': deps.sha256(package), 'package': control, 'urls': []}
        return {'schema_version': 1, 'artifacts': [entry], 'trees': [],
                'target': {'architecture': 'aarch64_cortex-a53', 'kernel_abi': abi}}

    def test_frozen_repository_has_a_complete_runtime_closure(self):
        report = deps.verify(deps.load_lock())
        self.assertEqual(report['runtime_packages'], 10)
        self.assertEqual(report['base_packages'], 220)

    def test_archive_reader_does_not_extract_links_or_traversal(self):
        with self.assertRaises(ValueError):
            deps.tar_files(tar_bytes({'../escape': b'secret'}))
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            info = tarfile.TarInfo('link')
            info.type, info.linkname = tarfile.SYMTYPE, '../outside'
            archive.addfile(info)
        self.assertEqual(deps.tar_files(output.getvalue()), {})
        self.assertFalse((self.root / 'outside').exists())

    def test_relative_paths_reject_windows_and_posix_escapes(self):
        for value in ('../x', '/etc/passwd', 'C:/secret', 'a\\b', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                deps.inside(self.root, value)

    def test_wrong_bytes_rejected_before_package_parsing(self):
        lock = self.fixture()
        (self.root / 'example.ipk').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            deps.verify(lock, self.root)

    def test_kernel_version_equal_without_full_abi_is_rejected(self):
        lock = self.fixture('kernel (=6.6.137~other-r1), libc')
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            deps.dependency_closure(lock, self.root)

    def test_unpinned_kernel_dependency_is_rejected(self):
        lock = self.fixture('kernel, libc')
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            deps.dependency_closure(lock, self.root)

    def test_unresolved_dependency_is_rejected(self):
        lock = self.fixture('missing-package')
        with self.assertRaisesRegex(ValueError, 'Unresolved dependency'):
            deps.dependency_closure(lock, self.root)

    def test_ipk_metadata_and_architecture_must_match(self):
        lock = self.fixture(architecture='x86_64')
        with self.assertRaisesRegex(ValueError, 'architecture mismatch'):
            deps.dependency_closure(lock, self.root)
        lock['artifacts'][0]['package'] = copy.deepcopy(lock['artifacts'][0]['package'])
        lock['artifacts'][0]['package']['Version'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            deps.dependency_closure(lock, self.root)

    def test_upstream_tree_addition_is_detected(self):
        lock = self.fixture()
        source = self.root / 'upstream'
        source.mkdir()
        (source / 'file').write_bytes(b'original')
        lock['trees'] = [{'path': 'upstream', 'files': deps.tree_hashes(source)}]
        (source / 'unexpected').write_bytes(b'added')
        with self.assertRaisesRegex(ValueError, 'tree drift'):
            deps.verify(lock, self.root)

    def test_download_hash_failure_does_not_leave_final_or_partial_file(self):
        entry = {'id': 'tool', 'path': 'cache/tool', 'bytes': 4, 'sha256': deps.sha256(b'good'),
                 'urls': ['https://example.invalid/tool']}
        with patch.object(deps.urllib.request, 'urlopen', return_value=io.BytesIO(b'evil')):
            with self.assertRaisesRegex(ValueError, 'Download failed'):
                deps.fetch(entry, self.root)
        self.assertFalse((self.root / 'cache/tool').exists())
        self.assertFalse((self.root / 'cache/tool.part').exists())

    def test_download_size_limit_and_verified_cache(self):
        entry = {'id': 'tool', 'path': 'cache/tool', 'bytes': 4, 'sha256': deps.sha256(b'good'),
                 'urls': ['https://example.invalid/tool']}
        with patch.object(deps.urllib.request, 'urlopen', return_value=io.BytesIO(b'too much data')):
            with self.assertRaises(ValueError):
                deps.fetch(entry, self.root)
        with patch.object(deps.urllib.request, 'urlopen', return_value=io.BytesIO(b'good')):
            result = deps.fetch(entry, self.root)
        with patch.object(deps.urllib.request, 'urlopen', side_effect=AssertionError('network access')):
            self.assertEqual(deps.fetch(entry, self.root), result)

    def test_interrupted_download_is_cleaned_up(self):
        entry = {'id': 'tool', 'path': 'cache/tool', 'bytes': 4, 'sha256': deps.sha256(b'good'),
                 'urls': ['https://example.invalid/tool']}
        class Interrupted(io.BytesIO):
            def read(self, *_args):
                raise IncompleteRead(b'par', 1)
        with patch.object(deps.urllib.request, 'urlopen', return_value=Interrupted()):
            with self.assertRaisesRegex(ValueError, 'Download failed'):
                deps.fetch(entry, self.root)
        self.assertFalse((self.root / 'cache/tool.part').exists())

    def test_duplicate_or_insecure_lock_entries_rejected(self):
        lock = self.fixture()
        path = self.root / 'lock.json'
        lock['artifacts'] *= 2
        path.write_text(json.dumps(lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            deps.load_lock(path)
        lock['artifacts'] = lock['artifacts'][:1]
        lock['artifacts'][0]['urls'] = ['http://example.invalid/tool']
        path.write_text(json.dumps(lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            deps.load_lock(path)


if __name__ == '__main__':
    unittest.main()
