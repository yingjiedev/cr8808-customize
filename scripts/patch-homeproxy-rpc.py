"""Avoid starting a second sing-box process for the pinned compressed core's UI.

The cached feature list comes from the verified sing-box-tiny 1.12.25 ELF's
version output. It is used only when the installed executable is the mounted
package core and its manifest identifies that exact binary. Other installations
keep HomeProxy's normal feature probe.
"""
import argparse
from pathlib import Path


BINARY_SHA256 = 'c3faeded3104bf8c581d2050b5786425b8a7862cea42c1ae19f0e2b98d582af5'
MARKER = '// CR8808: avoid a second Go process for the verified compressed core.'
ANCHOR = "\t\t\tconst fd = popen('/usr/bin/sing-box version');"
END = "\n\t\t\tfeatures.hp_has_ip_full = access('/usr/libexec/ip-full');"


def patch(source):
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count(BINARY_SHA256) != 1:
            raise ValueError('Unexpected partial RPC patch')
        return source
    if source.count(ANCHOR) != 1 or source.count(END) != 1:
        raise ValueError('Unexpected HomeProxy version: feature probe does not match')
    start = source.index(ANCHOR)
    end = source.index(END, start)
    probe = source[start:end].rstrip('\n')
    if not probe.endswith('\t\t\t}'):
        raise ValueError('Unexpected HomeProxy feature probe ending')
    fallback = '\n'.join('\t' + line if line else line for line in probe.splitlines())
    cached = f'''\t\t\t{MARKER}
\t\t\tconst packaged = lstat('/tmp/sing-box-squashfs/sing-box');
\t\t\tconst installed = lstat('/usr/bin/sing-box');
\t\t\tlet manifest = {{}};
\t\t\ttry {{
\t\t\t\tmanifest = json(readfile('/usr/share/sing-box-squashfs/manifest.json') || '{{}}');
\t\t\t}} catch (e) {{}}
\t\t\tif (packaged?.type === 'file' && installed?.type === 'file' &&
\t\t\t    packaged.inode === installed.inode &&
\t\t\t    packaged.dev.major === installed.dev.major &&
\t\t\t    packaged.dev.minor === installed.dev.minor &&
\t\t\t    packaged.size === 29688696 && installed.size === packaged.size &&
\t\t\t    manifest?.binary_sha256 === '{BINARY_SHA256}' &&
\t\t\t    manifest?.binary_bytes === packaged.size) {{
\t\t\t\tfeatures = {{
\t\t\t\t\tversion: '1.12.25',
\t\t\t\t\twith_clash_api: true,
\t\t\t\t\twith_gvisor: true,
\t\t\t\t\twith_quic: true,
\t\t\t\t\twith_utls: true,
\t\t\t\t\twith_wireguard: true
\t\t\t\t}};
\t\t\t}} else {{
{fallback}
\t\t\t}}
'''
    return source[:start] + cached + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = patch(args.input.read_text(encoding='utf-8'))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_bytes(result.encode('utf-8'))
    print('Applied verified compressed-core feature metadata to HomeProxy RPC')


if __name__ == '__main__':
    main()
