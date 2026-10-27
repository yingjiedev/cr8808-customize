"""Verify the frozen baseline, explicitly fetch a locked SDK/tool, or build offline."""
import argparse
import json
from pathlib import Path
from dependency_lib import by_id, build, fetch, load_lock, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    verification = commands.add_parser('verify', help='Offline SHA256, source-tree, IPK metadata and dependency checks')
    verification.add_argument('--downloads', action='store_true', help='Also verify all cached Release downloads')
    commands.add_parser('list', help='List archived artifacts and optional locked downloads')
    download = commands.add_parser('fetch', help='Explicit HTTPS download with pinned size and SHA256')
    download.add_argument('id')
    download.add_argument('--upstream', action='store_true', help='Bootstrap a Release from original upstream URLs')
    package = commands.add_parser('build', help='Offline public packages/overlay ZIP; does not contact router')
    package.add_argument('--output', required=True, type=Path)
    package.add_argument('--candidate', action='store_true',
                         help='Allow changed custom patch outputs; never changes the approved lock')
    args = parser.parse_args()
    try:
        lock = load_lock()
        if args.command == 'verify':
            result = verify(lock, downloads=args.downloads)
        elif args.command == 'list':
            result = [{'id': a['id'], 'storage': a['storage'], 'bytes': a['bytes'],
                       'path': a['path']} for a in lock['artifacts']]
        elif args.command == 'fetch':
            result = {'verified_download': str(fetch(by_id(lock, args.id), upstream_only=args.upstream))}
        else:
            result = build(lock, args.output, candidate=args.candidate)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, KeyError, StopIteration) as error:
        raise SystemExit(f'Dependency operation failed: {error}') from error


if __name__ == '__main__':
    main()
