"""Read a compiled FIT device tree and reject incompatible NAND policy."""
import gzip
import hashlib
import struct
import zlib


def read_fdt(blob):
    if len(blob) < 40:
        raise ValueError('Truncated FDT header')
    magic, size, start, strings, _, _, _, _, string_size, tree_size = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or not 40 <= size <= len(blob):
        raise ValueError('Invalid FDT size or magic')
    end = start + tree_size
    if start < 40 or end > size or strings + string_size > size:
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
    config_path = '/configurations/config@mp02.1'
    if config_path not in nodes or 'fdt' not in nodes[config_path]:
        raise ValueError('Expected mp02.1 FIT configuration')
    name = nodes[config_path]['fdt'].rstrip(b'\0').decode()
    path = '/images/' + name
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
    hashes = [p for n,p in nodes.items() if n.startswith(path+'/') and 'algo' in p]
    if not hashes:
        raise ValueError('FIT device tree hash missing')
    for entry in hashes:
        algo = entry['algo'].rstrip(b'\0').decode()
        if algo == 'crc32':
            digest = struct.pack('>I', zlib.crc32(data))
        elif algo in ('sha1', 'sha256'):
            digest = hashlib.new(algo, data).digest()
        else:
            raise ValueError('Unsupported FIT hash algorithm')
        if digest != entry.get('value'):
            raise ValueError('FIT device tree hash mismatched')
    compression = props.get('compression', b'none\0')
    if compression == b'gzip\0':
        data = gzip.decompress(data)
    elif compression != b'none\0':
        raise ValueError('Unsupported FIT device tree compression')
    return read_fdt(data)[0]


def verify_nand_tree(tree):
    if b'xiaomi,cr8806' not in tree['/'].get('compatible', b'').split(b'\0'):
        raise ValueError('Unexpected compiled board identity')
    chips = [(n,p) for n,p in tree.items()
             if b'spi-nand' in p.get('compatible', b'').split(b'\0')]
    if len(chips) != 1 or 'nand-ecc-engine' not in chips[0][1]:
        raise ValueError('Expected one QPIC SPI-NAND chip')
    path, props = chips[0]
    if 'nand-ecc-strength' in props or 'nand-ecc-step-size' in props:
        raise ValueError('Compiled NAND ECC must use QPIC OOB selection; forced ECC8 rejects 64-byte OOB')
    return {'selection': 'qpic-auto-oob', 'compiled_nand_path': path,
            'observed_oob_bytes': 64, 'expected_strength': 4, 'step_bytes': 512,
            'compiled_override_absent': True}


def verify_nand_fit(blob):
    return verify_nand_tree(fit_device_tree(blob))
