"""Offline dependency verification and public baseline builds (standard library only)."""
import hashlib
from http.client import HTTPException
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import struct
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'dependencies/lock.json'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if not value or '\\' in value or ':' in value or path.is_absolute() or '..' in path.parts:
        raise ValueError(f'Unsafe relative path: {value}')
    return path


def inside(root, value):
    path = (root / str(relative_path(value))).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes root: {value}')
    return path


def load_lock(path=LOCK):
    lock = json.loads(path.read_text(encoding='utf-8'))
    if lock.get('schema_version') != 1:
        raise ValueError('Unsupported dependency lock schema')
    ids, paths = set(), set()
    for entry in lock['artifacts']:
        if entry['id'] in ids or entry['path'] in paths:
            raise ValueError('Duplicate artifact ID or path')
        ids.add(entry['id'])
        paths.add(entry['path'])
        relative_path(entry['path'])
        if entry['storage'] not in ('vendored', 'download'):
            raise ValueError('Unknown artifact storage')
        if not re.fullmatch('[0-9a-f]{64}', entry['sha256']) or entry['bytes'] <= 0:
            raise ValueError('Invalid artifact digest or size')
        if any(not url.startswith('https://') for url in entry.get('urls', [])):
            raise ValueError('Downloads require HTTPS')
    for tree in lock['trees']:
        relative_path(tree['path'])
        for name in tree['files']:
            relative_path(name)
    return lock


def by_id(lock, artifact_id):
    return next(entry for entry in lock['artifacts'] if entry['id'] == artifact_id)


def check_bytes(data, entry):
    if len(data) != entry['bytes'] or sha256(data) != entry['sha256']:
        raise ValueError(f"Size or SHA256 mismatch: {entry['id']}")


def tree_hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink in source tree: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return result


def tar_files(data):
    """Read regular files without extracting links, permissions or paths to disk."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive:
            name = member.name
            while name.startswith('./'):
                name = name[2:]
            if not name:
                continue
            relative_path(name)
            if member.isfile():
                if name in files:
                    raise ValueError(f'Duplicate archive file: {name}')
                files[name] = archive.extractfile(member).read()
    return files


def package_parts(path):
    outer = tar_files(path.read_bytes())
    if outer.get('debian-binary') != b'2.0\n':
        raise ValueError(f'Unexpected IPK format: {path.name}')
    control = tar_files(outer['control.tar.gz'])['control'].decode('utf-8')
    fields = {}
    for line in control.splitlines():
        if line and not line[0].isspace() and ':' in line:
            key, value = line.split(':', 1)
            fields[key] = value.strip()
    return fields, tar_files(outer['data.tar.gz'])


def base_packages(root):
    text = (root / 'dependencies/baseline/firmware.manifest').read_text(encoding='utf-8')
    return dict(line.split(' - ', 1) for line in text.splitlines() if ' - ' in line)


def dependency_closure(lock, root):
    """Check every runtime dependency against bundled IPKs or the frozen base image."""
    base = base_packages(root)
    runtime = {}
    providers = {}
    for entry in lock['artifacts']:
        if entry.get('role') == 'runtime':
            control, _ = package_parts(inside(root, entry['path']))
            for key in ('Package', 'Version', 'Architecture', 'Depends'):
                if control.get(key, '') != entry['package'].get(key, ''):
                    raise ValueError(f"IPK metadata mismatch: {entry['id']}: {key}")
            runtime[control['Package']] = control
            for provision in control.get('Provides', '').split(','):
                if provision.strip():
                    providers[provision.strip().split()[0]] = control['Package']
    available = {**base, **{name: record['Version'] for name, record in runtime.items()}}
    used_base = set()
    for name, record in runtime.items():
        for spec in record.get('Depends', '').split(','):
            spec = spec.strip()
            if not spec:
                continue
            match = re.fullmatch(r'([\w.+-]+)(?:\s*\(\s*([=<>]+)\s*([^()]+)\))?', spec)
            if not match:
                raise ValueError(f'Unsupported dependency syntax: {name}: {spec}')
            dependency, operator, version = match.groups()
            actual_name = providers.get(dependency, dependency)
            if actual_name not in available:
                raise ValueError(f'Unresolved dependency: {name} -> {spec}')
            if operator:
                if operator != '=':
                    raise ValueError(f'Version comparison needs explicit support: {spec}')
                if available[actual_name] != version.strip():
                    raise ValueError(f'Dependency version mismatch: {name} -> {spec}')
            if actual_name in base and actual_name not in runtime:
                used_base.add(actual_name)
    expected_kernel = lock['target']['kernel_abi']
    if available.get('kernel') != expected_kernel:
        raise ValueError('Base manifest kernel ABI does not match target')
    for name, record in runtime.items():
        if record.get('Architecture') not in ('all', lock['target']['architecture']):
            raise ValueError(f'Runtime package architecture mismatch: {name}')
        if name.startswith('kmod-') and not re.search(
                r'kernel\s*\(\s*=\s*' + re.escape(expected_kernel) + r'\s*\)', record.get('Depends', '')):
            raise ValueError(f'Kernel module not pinned to target ABI: {name}')
    return {'runtime_packages': len(runtime), 'base_packages': len(base),
            'direct_base_dependencies': sorted(used_base), 'kernel_abi': expected_kernel}


def verify(lock, root=ROOT):
    count, total = 0, 0
    for entry in lock['artifacts']:
        if entry['storage'] == 'vendored':
            path = inside(root, entry['path'])
            check_bytes(path.read_bytes(), entry)
            count += 1
            total += entry['bytes']
    for tree in lock['trees']:
        actual = tree_hashes(inside(root, tree['path']))
        if actual != tree['files']:
            changed = sorted(name for name in set(actual) | set(tree['files'])
                             if actual.get(name) != tree['files'].get(name))
            raise ValueError(f"Upstream tree drift: {tree['path']}: {', '.join(changed[:8])}")
    closure = dependency_closure(lock, root)
    return {'verified_artifacts': count, 'vendored_bytes': total,
            'source_trees': len(lock['trees']), **closure}


def fetch(entry, root=ROOT):
    """Only fetch an explicitly selected locked item; validate before atomic rename."""
    target = inside(root, entry['path'])
    if target.is_file():
        check_bytes(target.read_bytes(), entry)
        return target
    if not entry.get('urls'):
        raise ValueError(f"No download URL: {entry['id']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.part')
    errors = []
    for url in entry['urls']:
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'cr8808-customize/1'})
            hasher, count = hashlib.sha256(), 0
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > entry['bytes']:
                        raise ValueError('Download exceeds locked size')
                    hasher.update(chunk)
                    output.write(chunk)
            if count != entry['bytes'] or hasher.hexdigest() != entry['sha256']:
                raise ValueError('Downloaded size or SHA256 mismatch')
            temporary.replace(target)
            return target
        except (OSError, ValueError, HTTPException) as error:
            temporary.unlink(missing_ok=True)
            errors.append(str(error))
    raise ValueError(f"Download failed for {entry['id']}: {'; '.join(errors)}")


def run_script(root, name, *args):
    subprocess.run([sys.executable, str(root / 'scripts' / name), *map(str, args)], check=True)


def write_file(root, name, data):
    target = inside(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def build(lock, output, root=ROOT, candidate=False):
    """Generate a public package/overlay bundle, never reading tmp/private or /etc."""
    report = verify(lock, root)
    output = output.resolve()
    if output == root.resolve() or root.resolve().is_relative_to(output):
        raise ValueError('Output may not contain the repository')
    if output.is_relative_to(root.resolve()) and output.relative_to(root.resolve()).parts[0] != 'tmp':
        raise ValueError('Repository build output must be under tmp/')
    output.mkdir(parents=True, exist_ok=False)
    work = output / 'work'
    work.mkdir()
    # Repack the verified ELF and the exact installed image; no Go compiler or
    # SquashFS tool is needed to reproduce this package. Image regeneration is
    # a separate operation and is documented rather than claimed byte-exact.
    core_entry = by_id(lock, 'sing-box-squashfs')
    source_entry = by_id(lock, 'sing-box-tiny-input')
    _, core_files = package_parts(inside(root, core_entry['path']))
    _, source_files = package_parts(inside(root, source_entry['path']))
    image = core_files['usr/share/sing-box-squashfs/core.squashfs']
    binary = source_files['usr/bin/sing-box']
    if sha256(binary) != lock['build']['core_binary_sha256']:
        raise ValueError('Core ELF mismatch')
    if sha256(image) != lock['build']['core_image_sha256'] or struct.unpack_from('<I', image, 12)[0] != 65536:
        raise ValueError('Core SquashFS image or block size mismatch')
    write_file(work, 'core.squashfs', image)
    write_file(work, 'sing-box-tiny', binary)
    repacked = work / Path(core_entry['path']).name
    run_script(root, 'build-sing-box-squashfs-ipk.py', '--image', work / 'core.squashfs',
               '--image-sha256', sha256(image), '--binary', work / 'sing-box-tiny',
               '--binary-sha256', sha256(binary), '--source-package', inside(root, source_entry['path']),
               '--source-package-sha256', source_entry['sha256'], '--version', core_entry['package']['Version'],
               '--output', repacked)
    if not candidate:
        check_bytes(repacked.read_bytes(), core_entry)
    baseline = by_id(lock, 'homeproxy')
    _, files = package_parts(inside(root, baseline['path']))
    originals = {'homeproxy.init': 'etc/init.d/homeproxy',
                 'generate_client.uc': 'etc/homeproxy/scripts/generate_client.uc',
                 'luci.homeproxy': 'usr/share/rpcd/ucode/luci.homeproxy',
                 'node.js': 'www/luci-static/resources/view/homeproxy/node.js'}
    for name, path in originals.items():
        data = files[path]
        if sha256(data) != lock['build']['inputs'][name]:
            raise ValueError(f'Unexpected HomeProxy input: {name}')
        write_file(work, name, data)
    run_script(root, 'patch-homeproxy-rpc.py', work / 'luci.homeproxy', work / 'rpc-cached')
    run_script(root, 'patch-homeproxy-init.py', work / 'homeproxy.init', work / 'init-patched', '--gogc', '100')
    run_script(root, 'patch-homeproxy-node-ui.py', '--generator', work / 'generate_client.uc',
               '--rpc', work / 'rpc-cached', '--node-js', work / 'node.js', '--output', work / 'node-patched')
    overlay = output / 'overlay'
    outputs = {'etc/init.d/homeproxy': work / 'init-patched',
               'etc/homeproxy/scripts/generate_client.uc': work / 'node-patched/generate_client.uc',
               'usr/share/rpcd/ucode/luci.homeproxy': work / 'node-patched/luci.homeproxy',
               'etc/homeproxy/scripts/cr8808-node-test-worker.uc': work / 'node-patched/cr8808-node-test-worker.uc',
               'www/luci-static/resources/view/homeproxy/node.js': work / 'node-patched/node.js',
               'etc/init.d/cr8808-proxy-wan': root / 'scripts/cr8808-proxy-wan.init',
               'etc/hotplug.d/iface/95-cr8808-proxy-wan': root / 'scripts/cr8808-proxy-wan.hotplug'}
    for name, source in outputs.items():
        data = source.read_bytes().replace(b'\r\n', b'\n')
        if not candidate and sha256(data) != lock['build']['outputs'][name]:
            raise ValueError(f'Patch output differs from approved baseline: {name}')
        write_file(overlay, name, data)
    bundle_files = {}
    for path in overlay.rglob('*'):
        if path.is_file():
            bundle_files[path.relative_to(output).as_posix()] = path.read_bytes()
    for entry in lock['artifacts']:
        if entry.get('role') == 'runtime':
            source = repacked if entry['id'] == 'sing-box-squashfs' else inside(root, entry['path'])
            bundle_files['packages/' + Path(entry['path']).name] = source.read_bytes()
    for source, target in [
        ('dependencies/lock.json', 'dependencies.lock.json'),
        ('dependencies/baseline/firmware.manifest', 'firmware.manifest'),
        ('scripts/check-cr8808-baseline.sh', 'check-device.sh'),
        ('doc/cr8808-dependency-maintenance.md', 'MAINTENANCE.md')]:
        bundle_files[target] = (root / source).read_bytes().replace(b'\r\n', b'\n')
    for path in (root / 'dependencies/licenses').rglob('*'):
        if path.is_file():
            bundle_files['licenses/' + path.name] = path.read_bytes()
    # Ship the application sources and available source archives with the binaries.
    for tree in lock['trees']:
        for name in tree['files']:
            source = inside(root, tree['path'] + '/' + name)
            bundle_files[tree['path'] + '/' + name] = source.read_bytes()
    for entry in lock['artifacts']:
        if entry.get('role') == 'source':
            bundle_files[entry['path']] = inside(root, entry['path']).read_bytes()
    bundle_files['SHA256SUMS'] = ''.join(f'{sha256(data)}  {name}\n' for name, data in sorted(bundle_files.items())).encode()
    archive_path = output / ('cr8808-homeproxy-candidate.zip' if candidate else 'cr8808-homeproxy-baseline.zip')
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(bundle_files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = '/init.d/' in name or '/hotplug.d/' in name or name.endswith('.sh')
            info.create_system = 3
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Built archive failed CRC verification')
    result = {**report, 'candidate': candidate, 'bundle': archive_path.name, 'bundle_bytes': archive_path.stat().st_size,
              'bundle_sha256': sha256(archive_path.read_bytes()), 'overlay_files': len(outputs),
              'outputs': {name: sha256(inside(overlay, name).read_bytes()) for name in outputs},
              'core_package_sha256': sha256(repacked.read_bytes()),
              'on_device_validation': 'new build not deployed; candidate requires device validation' if candidate
                                      else 'matches previously verified file hashes; new build not deployed'}
    (output / 'build-report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
