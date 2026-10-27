"""Allow the pinned HomeProxy status page to fetch its already allowed log files."""
import argparse
import hashlib
from pathlib import Path


SOURCE_SHA256 = '4d275bb87e71c2755b7c8eef785bc27e6f8e6907ab8b0293f7174d0ca4466d2d'
ANCHOR = b'\t\t"read": {\n'
PERMISSION = b'\t\t\t"cgi-io": [ "download" ],\n'


def patch(source):
    original = source.replace(PERMISSION, b'', 1)
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unexpected HomeProxy ACL: expected the pinned original or this patch')
    if PERMISSION in source:
        return source
    return source.replace(ANCHOR, ANCHOR + PERMISSION, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = patch(args.input.read_bytes())
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_bytes(result)
    print('Enabled CGI log downloads with the existing HomeProxy file allowlist')


if __name__ == '__main__':
    main()
