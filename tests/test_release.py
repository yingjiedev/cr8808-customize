# SPDX-License-Identifier: GPL-2.0-or-later
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dependency_lib as deps
import release_lib as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.settings = {'schema_version': 1, 'repository': 'owner/repo', 'tag': 'v0.1.0',
                         'title': 'Test', 'notes': 'notes.md', 'license': 'GPL-2.0-or-later',
                         'large_artifact_ids': ['sdk']}
        (self.root / 'dependencies').mkdir()
        release.write_json(self.root / 'dependencies/release.json', self.settings)
        for name, data in [('sdk.tar.zst', b'public sdk'), ('RELEASE-NOTES.md', b'Notes')]:
            (self.assets / name).write_bytes(data)
        self.records = [release.metadata(path, 'test') for path in sorted(self.assets.iterdir())]
        self.commit = 'a' * 40

    def finalize(self):
        release.stage_manifest(self.assets, self.settings, self.commit, {}, self.records)
        return release.staged_assets(self.assets)[1]

    @staticmethod
    def remote(records):
        return [{'name': name, 'state': 'uploaded', 'size': record['bytes'],
                 'digest': 'sha256:' + record['sha256']} for name, record in records.items()]

    def api_response(self, args, remote):
        if '/commits/' in args[1]:
            return json.dumps({'sha': self.commit})
        if '/releases?' in args[1]:
            return json.dumps([[{'id': 123, 'tag_name': 'v0.1.0', **remote}]])
        return json.dumps(remote)

    def test_staging_refuses_unlisted_private_file(self):
        (self.assets / 'private-backup.zip').write_bytes(b'not authorized')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            release.stage_manifest(self.assets, self.settings, self.commit, {}, self.records)

    def test_checksum_and_exact_asset_inventory_are_required(self):
        self.finalize()
        (self.assets / 'sdk.tar.zst').write_bytes(b'tampered sdk')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            release.staged_assets(self.assets)

    def test_duplicate_checksum_entry_is_rejected(self):
        self.finalize()
        path = self.assets / 'SHA256SUMS'
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + '\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            release.staged_assets(self.assets)

    def test_remote_requires_full_size_digest_and_upload_state(self):
        records = self.finalize()
        original = self.remote(records)
        for key, wrong in [('size', 0), ('digest', None), ('state', 'starter')]:
            remote = copy.deepcopy(original)
            remote[0][key] = wrong
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'differs'):
                release.check_remote_assets(remote, records, complete=True)
        self.assertEqual(release.check_remote_assets(original, records, complete=True), set())

    def test_incomplete_or_extra_remote_assets_are_rejected(self):
        records = self.finalize()
        remote = self.remote(records)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            release.check_remote_assets(remote[:-1], records, complete=True)
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            release.check_remote_assets(remote + [{'name': 'unknown'}], records)

    def test_published_release_is_never_modified(self):
        records = self.finalize()
        remote = {'draft': False, 'html_url': 'https://example.invalid/release', 'assets': self.remote(records)}
        mutations = []
        def gh(*args, **kwargs):
            if args[0] != 'api':
                mutations.append(args)
            return self.api_response(args, remote)
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh', side_effect=gh):
            result = release.publish('v0.1.0', self.assets, self.root)
        self.assertTrue(result['already_published'])
        self.assertEqual(mutations, [])

    def test_incomplete_published_release_cannot_be_overwritten(self):
        self.finalize()
        remote = {'draft': False, 'assets': []}
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh') as gh:
            gh.side_effect = lambda *_args, **_kwargs: self.api_response(_args, remote)
            with self.assertRaisesRegex(ValueError, 'refusing to modify'):
                release.publish('v0.1.0', self.assets, self.root)
            self.assertTrue(all(call.args[0] == 'api' for call in gh.call_args_list))

    def test_fully_uploaded_draft_is_checked_then_published(self):
        records = self.finalize()
        remote = {'draft': True, 'html_url': 'https://example.invalid/release', 'assets': self.remote(records)}
        mutations = []
        def gh(*args, **kwargs):
            if args[0] == 'release':
                mutations.append(args)
                self.assertEqual(args[1], 'edit')
                remote['draft'] = False
                return ''
            return self.api_response(args, remote)
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh', side_effect=gh):
            result = release.publish('v0.1.0', self.assets, self.root)
        self.assertFalse(result['already_published'])
        self.assertEqual(len(mutations), 1)

    def test_changed_remote_digest_blocks_draft_publication(self):
        records = self.finalize()
        remote = {'draft': True, 'assets': self.remote(records)}
        remote['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh') as gh:
            gh.side_effect = lambda *_args, **_kwargs: self.api_response(_args, remote)
            with self.assertRaisesRegex(ValueError, 'differs'):
                release.publish('v0.1.0', self.assets, self.root)
            self.assertTrue(all(call.args[0] == 'api' for call in gh.call_args_list))

    def test_new_release_uploads_explicit_assets_before_publication(self):
        records = self.finalize()
        remote = {'draft': True, 'html_url': 'https://example.invalid/release', 'assets': []}
        exists = False
        mutations = []
        def gh(*args, **kwargs):
            nonlocal exists
            if args[0] == 'api':
                if '/commits/' in args[1]:
                    return json.dumps({'sha': self.commit})
                return self.api_response(args, remote) if exists else json.dumps([])
            mutations.append(args)
            if args[1] == 'create':
                exists = True
                self.assertIn('--draft', args)
            elif args[1] == 'upload':
                name = Path(args[3]).name
                self.assertNotIn('--clobber', args)
                remote['assets'].append(self.remote({name: records[name]})[0])
            else:
                release.check_remote_assets(remote['assets'], records, complete=True)
                remote['draft'] = False
            return ''
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh', side_effect=gh):
            result = release.publish('v0.1.0', self.assets, self.root)
        self.assertEqual(result['verified_assets'], len(records))
        self.assertEqual([call[1] for call in mutations], ['create'] + ['upload'] * len(records) + ['edit'])

    def test_existing_draft_resumes_only_missing_uploads(self):
        records = self.finalize()
        uploaded = self.remote(records)
        remote = {'draft': True, 'html_url': 'https://example.invalid/release', 'assets': uploaded[:-1]}
        uploads = []
        def gh(*args, **kwargs):
            if args[0] == 'api':
                return self.api_response(args, remote)
            if args[1] == 'upload':
                uploads.append(Path(args[3]).name)
                remote['assets'].append(uploaded[-1])
            elif args[1] == 'edit':
                remote['draft'] = False
            else:
                self.fail('Existing draft must not be recreated')
            return ''
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh', side_effect=gh):
            release.publish('v0.1.0', self.assets, self.root)
        self.assertEqual(uploads, [uploaded[-1]['name']])

    def test_wrong_remote_tag_blocks_mutation(self):
        self.finalize()
        with patch.object(release, 'git', return_value=self.commit), patch.object(release, 'gh', return_value=json.dumps({'sha': 'b' * 40})) as gh:
            with self.assertRaisesRegex(ValueError, 'Remote tag'):
                release.publish('v0.1.0', self.assets, self.root)
            self.assertEqual(gh.call_count, 1)

    def test_invalid_release_tag_is_rejected(self):
        self.settings['tag'] = 'main; upload-private-files'
        release.write_json(self.root / 'dependencies/release.json', self.settings)
        with self.assertRaisesRegex(ValueError, 'Invalid release'):
            release.config(self.root)

    def test_authenticated_collection_finds_draft_on_a_later_page(self):
        draft = {'id': 123, 'tag_name': 'v0.1.0', 'draft': True}
        with patch.object(release, 'gh', return_value=json.dumps([[], [draft]])) as gh:
            self.assertEqual(release.find_release('owner/repo', 'v0.1.0'), draft)
        self.assertIn('--paginate', gh.call_args.args)

    def test_duplicate_release_tag_is_rejected(self):
        draft = {'id': 123, 'tag_name': 'v0.1.0', 'draft': True}
        with patch.object(release, 'gh', return_value=json.dumps([[draft, draft]])):
            with self.assertRaisesRegex(ValueError, 'More than one'):
                release.find_release('owner/repo', 'v0.1.0')


class MirrorTests(unittest.TestCase):
    def test_default_download_prefers_repository_mirror(self):
        import io
        with tempfile.TemporaryDirectory() as temporary:
            entry = {'id': 'sdk', 'path': 'cache/sdk', 'bytes': 4, 'sha256': deps.sha256(b'good'),
                     'urls': ['https://example.invalid/mirror', 'https://example.invalid/upstream'],
                     'upstream_urls': ['https://example.invalid/upstream']}
            with patch.object(deps.urllib.request, 'urlopen', return_value=io.BytesIO(b'good')) as open_url:
                deps.fetch(entry, Path(temporary))
            self.assertEqual(open_url.call_args.args[0].full_url, entry['urls'][0])

    def test_bootstrap_download_skips_not_yet_published_mirror(self):
        import io
        with tempfile.TemporaryDirectory() as temporary:
            entry = {'id': 'sdk', 'path': 'cache/sdk', 'bytes': 4, 'sha256': deps.sha256(b'good'),
                     'urls': ['https://example.invalid/mirror', 'https://example.invalid/upstream'],
                     'upstream_urls': ['https://example.invalid/upstream']}
            with patch.object(deps.urllib.request, 'urlopen', return_value=io.BytesIO(b'good')) as open_url:
                deps.fetch(entry, Path(temporary), upstream_only=True)
            self.assertEqual(open_url.call_args.args[0].full_url, entry['upstream_urls'][0])


if __name__ == '__main__':
    unittest.main()
