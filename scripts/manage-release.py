# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare verified public Release assets, then publish using GitHub CLI."""
import argparse
import json
from pathlib import Path
import subprocess

from release_lib import prepare, publish
from dependency_lib import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('prepare')
    package.add_argument('--tag', required=True)
    package.add_argument('--output', required=True, type=Path)
    package.add_argument('--download', action='store_true', help='Download pinned inputs from original upstream')
    upload = commands.add_parser('publish')
    upload.add_argument('--tag', required=True)
    upload.add_argument('--assets', required=True, type=Path)
    upload.add_argument('--repository-root', type=Path, default=ROOT,
                        help='Tagged source checkout; allows a corrected publisher without moving the tag')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.tag, args.output, args.download)
        else:
            result = publish(args.tag, args.assets, root=args.repository_root.resolve())
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Release operation failed: {error}') from error


if __name__ == '__main__':
    main()
