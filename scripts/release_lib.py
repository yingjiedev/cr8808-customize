# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare explicit public assets and publish only a fully verified draft Release."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from dependency_lib import ROOT, build, by_id, check_bytes, fetch, inside, load_lock, verify


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def config(root=ROOT):
    result = json.loads((root / 'dependencies/release.json').read_text(encoding='utf-8'))
    if result.get('schema_version') != 1 or not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', result['tag']):
        raise ValueError('Invalid release configuration or tag')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', result['repository']):
        raise ValueError('Invalid repository name')
    inside(root, result['notes'])
    ids = result['large_artifact_ids']
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Invalid large artifact selection')
    return result


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def metadata(path, role, **extra):
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': file_digest(path), 'role': role, **extra}


def stage_manifest(assets, settings, commit, target, records):
    """Finalize a staging directory using its explicit file list, never a tmp glob."""
    names = [record['name'] for record in records]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate asset name')
    if set(names) != {path.name for path in assets.iterdir()}:
        raise ValueError('Unexpected or missing file in release staging directory')
    for record in records:
        path = inside(assets, record['name'])
        if path.parent != assets.resolve() or not path.is_file():
            raise ValueError('Release assets must be ordinary top-level files')
        check_bytes(path.read_bytes(), {**record, 'id': record['name']})
    manifest = {'schema_version': 1, 'repository': settings['repository'], 'tag': settings['tag'],
                'commit': commit, 'license': settings['license'], 'target': target, 'assets': records}
    write_json(assets / 'release-manifest.json', manifest)
    all_names = sorted(names + ['release-manifest.json'])
    (assets / 'SHA256SUMS').write_text(''.join(f'{file_digest(assets / name)}  {name}\n' for name in all_names),
                                        encoding='utf-8', newline='\n')
    return manifest


def staged_assets(assets):
    """Verify local checksums and exact membership before any API mutation."""
    assets = assets.resolve()
    manifest = json.loads((assets / 'release-manifest.json').read_text(encoding='utf-8'))
    expected = {}
    for line in (assets / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)', line)
        if not match or match[2] in expected:
            raise ValueError('Invalid or duplicate release checksum entry')
        expected[match[2]] = match[1]
    if set(expected) != {record['name'] for record in manifest['assets']} | {'release-manifest.json'}:
        raise ValueError('Release manifest and checksum inventory differ')
    if set(expected) | {'SHA256SUMS'} != {path.name for path in assets.iterdir()}:
        raise ValueError('Unexpected or missing staged asset')
    for name, digest in expected.items():
        path = inside(assets, name)
        if path.is_symlink() or not path.is_file() or file_digest(path) != digest:
            raise ValueError(f'Release asset checksum mismatch: {name}')
    for record in manifest['assets']:
        check_bytes(inside(assets, record['name']).read_bytes(), {**record, 'id': record['name']})
    records = {record['name']: record for record in manifest['assets']}
    for name in ('SHA256SUMS', 'release-manifest.json'):
        records[name] = metadata(assets / name, 'release-metadata')
    return manifest, records


def prepare(tag, output, download=False, root=ROOT):
    settings = config(root)
    if tag != settings['tag']:
        raise ValueError('Requested tag does not match dependencies/release.json')
    if git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Commit all public release files before preparing a release')
    commit = git(root, 'rev-parse', 'HEAD')
    lock = load_lock(root / 'dependencies/lock.json')
    verify(lock, root)
    selected = [by_id(lock, artifact_id) for artifact_id in settings['large_artifact_ids']]
    if any(entry['storage'] != 'download' for entry in selected):
        raise ValueError('Large assets must be explicit locked downloads')
    if download:
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Bootstrap from original sources; the new mirror is not public yet.
            futures = [executor.submit(fetch, entry, root, True) for entry in selected]
            for future in futures:
                path = future.result()
                print(f'Verified download: {path.name}', flush=True)
    verify(lock, root, downloads=True)
    output = output.resolve()
    if not output.is_relative_to((root / 'tmp').resolve()):
        raise ValueError('Release output must be under repository tmp/')
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets'
    assets.mkdir()
    report = build(lock, output / 'build', root)
    records = []

    def add(source, name, role, **extra):
        target = inside(assets, name)
        if target.parent != assets or target.exists():
            raise ValueError(f'Invalid or duplicate release asset: {name}')
        shutil.copyfile(source, target)
        records.append(metadata(target, role, **extra))

    for entry in selected:
        add(inside(root, entry['path']), Path(entry['path']).name, 'upstream-mirror', artifact_id=entry['id'],
            upstream_urls=entry['upstream_urls'], binary_modified=False)
    factory = by_id(lock, 'firmware-factory')
    add(inside(root, factory['path']), Path(factory['path']).name, 'upstream-firmware',
        artifact_id=factory['id'], upstream_urls=factory['urls'], binary_modified=False)
    for source, name, role in [
        (output / 'build' / report['bundle'], report['bundle'], 'application-bundle'),
        (output / 'build/build-report.json', 'build-report.json', 'build-report'),
        (root / 'dependencies/lock.json', 'dependencies.lock.json', 'dependency-lock'),
        (root / 'LICENSE', 'LICENSE', 'license'),
        (root / 'LICENSING.md', 'LICENSING.md', 'license-scope'),
        (inside(root, settings['notes']), 'RELEASE-NOTES.md', 'release-notes')]:
        add(source, name, role)
    archive = assets / f'cr8808-customize-{tag}.tar.gz'
    tar_path = output / 'repository.tar'
    git(root, 'archive', '--format=tar', f'--prefix=cr8808-customize-{tag}/', f'--output={tar_path}', commit)
    with tar_path.open('rb') as source, archive.open('wb') as destination:
        with gzip.GzipFile(filename='', mode='wb', fileobj=destination, mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
    tar_path.unlink()
    records.append(metadata(archive, 'public-repository-snapshot'))
    stage_manifest(assets, settings, commit, lock['target'], records)
    _, ready = staged_assets(assets)
    return {'tag': tag, 'commit': commit, 'assets': len(ready),
            'total_bytes': sum(record['bytes'] for record in ready.values()), 'directory': str(assets)}


def gh(*args, optional=False):
    process = subprocess.run(['gh', *args], capture_output=True, text=True)
    if process.returncode:
        if optional and 'HTTP 404' in process.stderr:
            return None
        raise ValueError(f'GitHub CLI {args[0]} {args[1]} failed: {process.stderr.strip()}')
    return process.stdout.strip()


def remote_matches(asset, expected):
    return (asset.get('state') == 'uploaded' and asset.get('size') == expected['bytes']
            and asset.get('digest') == 'sha256:' + expected['sha256'])


def check_remote_assets(remote, records, complete=False):
    actual = {item['name']: item for item in remote}
    if len(actual) != len(remote) or set(actual) - set(records):
        raise ValueError('Unexpected or duplicate remote release asset')
    for name, asset in actual.items():
        if not remote_matches(asset, records[name]):
            raise ValueError(f'Remote asset differs from locked staged file: {name}')
    if complete and set(actual) != set(records):
        raise ValueError('Remote release is incomplete')
    return set(records) - set(actual)


def find_release(repo, tag):
    # The /releases/tags endpoint may omit a draft. The authenticated collection
    # includes it, and subsequent reads use the stable release ID.
    pages = json.loads(gh('api', f'repos/{repo}/releases?per_page=100', '--paginate', '--slurp'))
    matches = [item for page in pages for item in page if item['tag_name'] == tag]
    if len(matches) > 1:
        raise ValueError('More than one Release has the requested tag')
    return matches[0] if matches else None


def publish(tag, assets, root=ROOT):
    settings = config(root)
    manifest, records = staged_assets(assets)
    if tag != settings['tag'] or tag != manifest['tag'] or settings['repository'] != manifest['repository']:
        raise ValueError('Release tag or repository mismatch')
    commit = git(root, 'rev-parse', f'{tag}^{{commit}}')
    if commit != manifest['commit'] or commit != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('Release tag, checkout and manifest commit must agree')
    repo = settings['repository']
    remote_commit = json.loads(gh('api', f'repos/{repo}/commits/{tag}'))['sha']
    if remote_commit != commit:
        raise ValueError('Remote tag does not match prepared commit')
    existing = find_release(repo, tag)
    if existing is None:
        gh('release', 'create', tag, '--repo', repo, '--verify-tag', '--draft', '--title', settings['title'],
           '--notes-file', str(assets / 'RELEASE-NOTES.md'))
        existing = find_release(repo, tag)
    if existing is None:
        raise ValueError('Created draft was not found in authenticated Release collection')
    endpoint = f"repos/{repo}/releases/{existing['id']}"
    release = json.loads(gh('api', endpoint))
    missing = check_remote_assets(release.get('assets', []), records)
    if not release['draft']:
        if missing:
            raise ValueError('Published Release is incomplete; refusing to modify it')
        return {'url': release['html_url'], 'verified_assets': len(records), 'already_published': True}
    for name in sorted(missing):
        gh('release', 'upload', tag, str(assets / name), '--repo', repo)
        print(f'Uploaded: {name}', flush=True)
    release = json.loads(gh('api', endpoint))
    check_remote_assets(release.get('assets', []), records, complete=True)
    gh('release', 'edit', tag, '--repo', repo, '--draft=false', '--latest')
    published = json.loads(gh('api', endpoint))
    if published['draft']:
        raise ValueError('Release did not become public')
    check_remote_assets(published.get('assets', []), records, complete=True)
    return {'url': published['html_url'], 'verified_assets': len(records), 'already_published': False}
