"""Inspect QSDK UBI/FIT and SquashFS build outputs; never execute target code."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import zlib

import qsdk_candidate as qsdk


def read_fdt(blob):
    if len(blob) < 40:
        raise ValueError('Truncated FDT header')
    magic, size, start, strings, _, _, _, _, string_size, tree_size = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or not 40 <= size <= len(blob):
        raise ValueError('Invalid FDT size or magic')
    end = start + tree_size
    if start < 40 or end > size or strings < end or strings + string_size > size:
        raise ValueError('FDT block exceeds its header size')
    nodes, stack, pos = {}, [], start
    while pos + 4 <= end:
        token = struct.unpack_from('>I', blob, pos)[0]
        pos += 4
        if token == 1:
            zero = blob.index(0, pos, end)
            stack.append(blob[pos:zero].decode())
            pos = (zero + 4) & ~3
            path = '/' + '/'.join(stack[1:])
            if path in nodes:
                raise ValueError('Duplicate FDT node')
            nodes[path] = {}
        elif token == 2:
            if not stack:
                raise ValueError('Unbalanced FDT node')
            stack.pop()
        elif token == 3:
            if not stack or pos + 8 > end:
                raise ValueError('Invalid FDT property')
            length, name_offset = struct.unpack_from('>II', blob, pos)
            pos += 8
            if name_offset >= string_size or pos + length > end:
                raise ValueError('FDT property exceeds block')
            at = strings + name_offset
            zero = blob.index(0, at, strings + string_size)
            name = blob[at:zero].decode()
            props = nodes['/' + '/'.join(stack[1:])]
            if name in props:
                raise ValueError('Duplicate FDT property')
            props[name] = blob[pos:pos+length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError('Unclosed FDT node')
            return nodes, size
        else:
            raise ValueError('Unknown FDT token')
    raise ValueError('FDT has no END token')


def fit_device_tree(blob):
    nodes, size = read_fdt(blob)
    config = nodes.get('/configurations/config@mp02.1', {})
    if 'fdt' not in config:
        raise ValueError('Expected mp02.1 FIT configuration')
    path = '/images/' + config['fdt'].rstrip(b'\0').decode()
    props = nodes[path]
    if 'data' in props:
        data = props['data']
    else:
        offset = (int.from_bytes(props['data-position'], 'big') if 'data-position' in props
                  else ((size+3) & ~3) + int.from_bytes(props['data-offset'], 'big'))
        length = int.from_bytes(props['data-size'], 'big')
        if offset < size or offset + length > len(blob):
            raise ValueError('External FIT data exceeds image')
        data = blob[offset:offset+length]
    hashes = [p for name, p in nodes.items() if name.startswith(path+'/') and 'algo' in p]
    if not hashes:
        raise ValueError('FIT device tree hash missing')
    for item in hashes:
        algo = item['algo'].rstrip(b'\0').decode()
        if algo == 'crc32':
            digest = struct.pack('>I', zlib.crc32(data))
        elif algo in ('sha1', 'sha256'):
            digest = hashlib.new(algo, data).digest()
        else:
            raise ValueError('Unsupported FIT hash algorithm')
        if digest != item.get('value'):
            raise ValueError('FIT device tree hash mismatch')
    compression = props.get('compression', b'none\0')
    if compression == b'gzip\0':
        data = gzip.decompress(data)
    elif compression != b'none\0':
        raise ValueError('Unsupported FIT device tree compression')
    return read_fdt(data)[0]


def cells(value):
    if len(value) % 4:
        raise ValueError('Invalid FDT cells')
    return struct.unpack('>{}I'.format(len(value)//4), value)


def compatible(props, name):
    return name.encode() in props.get('compatible', b'').split(b'\0')


def verify_tree(tree):
    if not compatible(tree.get('/', {}), 'redmi,ax3000'):
        raise ValueError('Unexpected compiled board identity')
    chips = [(name, props) for name, props in tree.items() if compatible(props, 'qcom,nandcs')]
    controllers = [props for props in tree.values() if compatible(props, 'qcom,ebi2-nandc-bam-v2.1.1')]
    if len(chips) != 1 or len(controllers) != 1:
        raise ValueError('Expected the reviewed QSDK NAND controller/chip')
    name, chip = chips[0]
    if (cells(chip.get('nand-ecc-strength', b'')) != (4,)
            or cells(chip.get('nand-ecc-step-size', b'')) != (512,)):
        raise ValueError('Compiled NAND must use ECC4/512 for the observed 64-byte OOB')
    cpus = [p for n, p in tree.items() if n.startswith('/cpus/') and p.get('device_type') == b'cpu\0']
    if len(cpus) != 2:
        raise ValueError('Expected two CPU nodes')
    frequencies = []
    for cpu in cpus:
        points = cells(cpu.get('operating-points', b''))
        if not points or len(points) % 2:
            raise ValueError('Expected reviewed CPU operating points')
        frequencies.extend(hz * 1000 for hz in points[::2])
    if max(frequencies) != 1008000000:
        raise ValueError('CPU frequency policy changed')
    for path, size in [('/reserved-memory/nss@40000000', 8388608),
                       ('/reserved-memory/q6_mem_regions@4b000000', 50331648)]:
        reg = cells(tree.get(path, {}).get('reg', b''))
        if len(reg) != 4 or reg[2:] != (0, size):
            raise ValueError('Wrong 256 MiB reserved-memory layout')
    dataplanes = [p for p in tree.values() if compatible(p, 'qcom,nss-dp')]
    if sorted(cells(p.get('qcom,id', b'')) for p in dataplanes) != [(1,), (2,)]:
        raise ValueError('Expected independent QSDK WAN/LAN dataplanes')
    return {'nand_path': name, 'ecc_strength': 4, 'ecc_step_bytes': 512,
            'cpu_max_hz': max(frequencies), 'q6_reserved_bytes': 50331648,
            'nss_reserved_bytes': 8388608, 'dataplanes': 2}


def ubi_crc(data):
    return zlib.crc32(data) ^ 0xffffffff


def verify_crc(data, label):
    if struct.unpack_from('>I', data, len(data)-4)[0] != ubi_crc(data[:-4]):
        raise ValueError(label + ' CRC mismatch')


def read_ubi(blob, slot_bytes=37748736):
    peb, layout_id = 131072, 0x7fffefff
    if not blob or len(blob) % peb:
        raise ValueError('UBI image is not aligned to 128 KiB')
    tables, blocks, sequences = [], {}, set()
    for offset in range(0, len(blob), peb):
        block = blob[offset:offset+peb]
        ec = block[:64]
        if ec[:4] != b'UBI#' or ec[4] != 1:
            raise ValueError('Unexpected UBI EC header')
        verify_crc(ec, 'UBI EC header')
        vid_at, data_at, sequence = struct.unpack_from('>III', ec, 16)
        if (vid_at, data_at) != (2048, 4096):
            raise ValueError('UBI minimum I/O/layout changed')
        sequences.add(sequence)
        vid = block[vid_at:vid_at+64]
        if vid[:4] != b'UBI!' or vid[4] != 1:
            raise ValueError('Unexpected UBI VID header')
        verify_crc(vid, 'UBI VID header')
        volume, lnum = struct.unpack_from('>II', vid, 8)
        payload = block[data_at:]
        if volume == layout_id:
            tables.append(payload[:172*128])
            continue
        if vid[5] not in (1, 2):
            raise ValueError('Unknown UBI volume type')
        if vid[5] == 2:
            size = struct.unpack_from('>I', vid, 20)[0]
            if size > len(payload):
                raise ValueError('UBI static payload exceeds block')
            payload = payload[:size]
            if ubi_crc(payload) != struct.unpack_from('>I', vid, 32)[0]:
                raise ValueError('UBI static volume data CRC mismatch')
        key = (volume, lnum)
        if key in blocks:
            raise ValueError('Duplicate UBI logical block')
        blocks[key] = payload
    if len(sequences) != 1 or len(tables) != 2 or tables[0] != tables[1]:
        raise ValueError('UBI image sequence or redundant volume tables differ')
    table, names, reserved = tables[0], {}, 0
    for index in range(128):
        record = table[index*172:(index+1)*172]
        count = struct.unpack_from('>I', record)[0]
        if count == 0:
            continue
        verify_crc(record, 'UBI volume table record')
        name_size = struct.unpack_from('>H', record, 14)[0]
        if not 1 <= name_size <= 127:
            raise ValueError('Invalid UBI volume name')
        name = record[16:16+name_size].decode()
        if name in names.values():
            raise ValueError('Duplicate UBI volume name')
        names[index] = name
        reserved += count
    if names != {0: 'kernel', 1: 'rootfs', 2: 'rootfs_data'} or reserved + 2 > slot_bytes // peb:
        raise ValueError('Unexpected UBI volume names or capacity')
    result = {}
    for volume, name in names.items():
        indices = sorted(lnum for key, lnum in blocks if key == volume)
        if indices != list(range(len(indices))):
            raise ValueError('Missing UBI logical block')
        result[name] = b''.join(blocks[(volume, lnum)] for lnum in indices)
    if any(volume not in names for volume, _ in blocks):
        raise ValueError('UBI contains an undeclared volume')
    if not result['kernel'].startswith(b'\xd0\x0d\xfe\xed') or not result['rootfs'].startswith(b'hsqs'):
        raise ValueError('Expected FIT kernel and SquashFS rootfs')
    return result, {'peb_bytes': peb, 'min_io_bytes': 2048,
                    'declared_reserved_pebs': reserved, 'volume_names': list(names.values())}


def arm32_elf(data):
    return len(data) >= 20 and data[:6] == b'\x7fELF\x01\x01' and struct.unpack_from('<H', data, 18)[0] == 40


def verify_rootfs(root, lock):
    root = Path(root)
    if not arm32_elf((root / 'bin/busybox').read_bytes()):
        raise ValueError('Rootfs must contain ARM32 userspace')
    for name in ['ecm', 'qca-nss-drv']:
        link = root / ('etc/rc.d/S19qca-nss-ecm' if name == 'ecm' else 'etc/rc.d/S70qca-nss-drv')
        expected = '../init.d/' + ('qca-nss-ecm' if name == 'ecm' else name)
        if not link.is_symlink() or os.readlink(link) != expected:
            raise ValueError('Missing or changed NSS/ECM boot link')
    module_dir = root / 'lib/modules/5.4.164'
    for name in ['qca-nss-dp.ko', 'qca-nss-drv.ko', 'ecm.ko', 'ath11k.ko', 'ath11k_ahb.ko', 'ath11k_pci.ko']:
        data = (module_dir / name).read_bytes()
        if not arm32_elf(data) or b'vermagic=5.4.164 ' not in data:
            raise ValueError('Kernel module ELF/vermagic mismatch: ' + name)
    if qsdk.sha256(root / 'lib/firmware/qca-nss0-retail.bin') != lock['reference']['nss_firmware_sha256']:
        raise ValueError('NSS firmware differs from the verified reference image')
    for directory in ['IPQ5018', 'qcn6122']:
        if not list((root / 'lib/firmware' / directory).glob('*.mdt')):
            raise ValueError('Missing radio firmware: ' + directory)
    feeds = (root / 'etc/opkg/distfeeds.conf').read_text(encoding='utf-8')
    if any(line.strip() and not line.lstrip().startswith('#') for line in feeds.splitlines()):
        raise ValueError('Candidate must not use an incompatible online feed')
    policy = json.loads((root / 'etc/cr8808-qsdk/candidate.json').read_text(encoding='utf-8'))
    if policy['source_lock'] != lock or policy['private_configuration_included'] is not False:
        raise ValueError('Embedded candidate provenance differs')
    return {'userspace': 'ARM32', 'kernel_module_vermagic': '5.4.164',
            'nss_ecm_boot_links_verified': True, 'matching_radio_firmware_present': True,
            'nss_firmware_sha256': lock['reference']['nss_firmware_sha256']}


def finish(source, output):
    source, output = qsdk.guarded_directory(source), qsdk.guarded_directory(output)
    lock = qsdk.load_lock()
    config = qsdk.verify_config(source / '.config')
    downloads = qsdk.verify_downloads(source)
    target = source / 'bin/targets/ipq50xx/arm'
    prefix = 'openwrt-ipq50xx-arm-redmi_ax3000'
    factory = target / (prefix + '-squashfs-nand-factory.ubi')
    initramfs = target / (prefix + '-initramfs-fit-uImage.itb')
    if not 0 < factory.stat().st_size <= lock['maximum_factory_bytes']:
        raise ValueError('Factory image exceeds candidate slot limit')
    for pattern in ['openwrt-sdk-*.tar.xz', 'openwrt-imagebuilder-*.tar.xz']:
        if len(list(target.glob(pattern))) != 1:
            raise ValueError('Missing or ambiguous matching SDK/ImageBuilder')
    volumes, ubi = read_ubi(factory.read_bytes(), lock['slot_bytes'])
    tree = verify_tree(fit_device_tree(volumes['kernel']))
    if verify_tree(fit_device_tree(initramfs.read_bytes())) != tree:
        raise ValueError('Factory/initramfs compiled device trees differ in policy')
    candidates = [target / (prefix + '.manifest'), target / 'openwrt-ipq50xx-arm.manifest']
    manifests = [path for path in candidates if path.exists()]
    if len(manifests) != 1:
        raise ValueError('Missing or ambiguous target package manifest')
    manifest = manifests[0]
    installed = {line.split(' - ', 1)[0] for line in manifest.read_text(encoding='utf-8').splitlines()}
    required = {'cr8808-qsdk-policy', 'kmod-qca-nss-dp', 'kmod-qca-nss-drv',
                'kmod-qca-nss-ecm-standard', 'kmod-ath11k', 'qca-nss-fw-ipq50xx-retail',
                'ath11k-firmware-ipq5018', 'ath11k-firmware-qcn6122', 'dnsmasq-full',
                'luci-base', 'firewall', 'swconfig', 'iperf3'}
    if not required <= installed or installed & {'dnsmasq', 'firewall4', 'luci-app-homeproxy', 'sing-box'}:
        raise ValueError('Unexpected QSDK driver/application package manifest')
    # Inspect the built filesystem rather than assuming config selections were
    # installed. Only trusted native host tools are run, never ARM binaries.
    inspection = output.parent / 'qsdk-inspection'
    inspection.mkdir(parents=True, exist_ok=False)
    squashfs = inspection / 'rootfs.squashfs'
    squashfs.write_bytes(volumes['rootfs'])
    root = inspection / 'root'
    subprocess.run([str(source / 'staging_dir/host/bin/unsquashfs'), '-no-progress',
                    '-d', str(root), str(squashfs), 'etc', 'lib/modules', 'lib/firmware', 'bin/busybox'], check=True)
    filesystem = verify_rootfs(root, lock)
    output.mkdir(parents=True, exist_ok=True)
    for path in [factory, initramfs, manifest]:
        shutil.copy2(path, output / path.name)
    for name in ['config.buildinfo', 'feeds.buildinfo', 'version.buildinfo']:
        shutil.copy2(target / name, output / name)
    if (source / 'key-build.pub').exists():
        shutil.copy2(source / 'key-build.pub', output / 'package-signing-key.pub')
    patch = subprocess.check_output(['git', '-C', str(source), 'diff', '--binary', 'HEAD', '--'])
    qsdk.write(output / 'upstream-build.patch', patch)
    # bin/ and these explicit overlays contain public build outputs. Never
    # archive key-build, device backups, or arbitrary workspace directories.
    with tarfile.open(output / 'public-build-overlay.tar.gz', 'w:gz') as archive:
        for name in ['feeds.conf', '.config', 'version', 'files', 'package/cr8808']:
            archive.add(source / name, arcname=name)
    checksums = {}
    for parent in [target, source / 'bin/packages']:
        for path in sorted(parent.rglob('*')):
            if path.is_file():
                if not path.resolve().is_relative_to(source):
                    raise ValueError('Build output symlink escapes the source tree')
                checksums[path.relative_to(source).as_posix()] = qsdk.sha256(path)
    downloaded = {path.name: qsdk.sha256(path) for path in sorted((source / 'dl').iterdir())
                  if path.is_file() and not path.name.startswith('.')}
    qsdk.write_json(output / 'downloads-used.json', downloaded)
    qsdk.write(output / 'SHA256SUMS-bin', ''.join('{}  {}\n'.format(value, key) for key, value in checksums.items()))
    report = {'status': 'build-complete-device-validation-pending', 'source_lock': lock,
              'config': config, 'downloads': downloads, 'ubi': ubi, 'device_tree': tree,
              'filesystem': filesystem, 'factory_bytes': factory.stat().st_size,
              'physical_slot_headroom_bytes': lock['slot_bytes'] - factory.stat().st_size,
              'file_checksums': checksums, 'private_configuration_included': False,
              'automatic_flash': False, 'wifi_stability_validated': False,
              'stable_500_mbps_validated': False, 'homeproxy_migration_complete': False}
    qsdk.write_json(output / 'build-report.json', report)
    return report
