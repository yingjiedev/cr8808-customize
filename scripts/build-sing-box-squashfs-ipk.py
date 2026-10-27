"""Package a verified, loop-mounted sing-box core without changing its binary.

Uses only Python's standard library. Build the image separately with the upstream
gensquashfs tool; this script refuses a source binary or image hash mismatch.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tar_gz(files):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        directories = set()
        for name, _, _ in files:
            directories.update(p.as_posix() for p in Path(name).parents if p.as_posix() != ".")
        for name in sorted(directories, key=lambda value: (value.count("/"), value)):
            info = tarfile.TarInfo("./" + name + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = 0
            info.mtime = 0
            archive.addfile(info)
        for name, data, mode in files:
            info = tarfile.TarInfo("./" + name)
            info.size, info.mode = len(data), mode
            info.uid = info.gid = 0
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--source-package-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image, binary = args.image.read_bytes(), args.binary.read_bytes()
    if (digest(image) != args.image_sha256 or digest(binary) != args.binary_sha256
            or digest(args.source_package.read_bytes()) != args.source_package_sha256):
        raise SystemExit("Input hash mismatch")
    if image[:4] != b"hsqs" or binary[:5] != b"\x7fELF\x02":
        raise SystemExit("Expected a SquashFS image and a 64-bit ELF binary")
    root = Path(__file__).resolve().parent / "sing-box-squashfs"
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            content = path.read_bytes().replace(b"\r\n", b"\n")
            files.append((path.relative_to(root).as_posix(), content, 0o755))
    checksums = (f"IMAGE_SHA256='{digest(image)}'\n"
                 f"BINARY_SHA256='{digest(binary)}'\n").encode("ascii")
    manifest = {
        "version": args.version,
        "source_package": "sing-box-tiny",
        "source_package_sha256": args.source_package_sha256,
        "binary_sha256": digest(binary), "binary_bytes": len(binary),
        "image_sha256": digest(image), "image_bytes": len(image),
        "binary_modified": False,
        "source_url": "https://github.com/SagerNet/sing-box/tree/v" + args.version.split("-r")[0],
    }
    files.extend([
        ("usr/share/sing-box-squashfs/core.squashfs", image, 0o644),
        ("usr/share/sing-box-squashfs/checksums", checksums, 0o644),
        ("usr/share/sing-box-squashfs/manifest.json", json.dumps(manifest, indent=2).encode() + b"\n", 0o644),
    ])
    installed_size = sum(len(data) for _, data, _ in files)
    control = f"""Package: sing-box-squashfs
Version: {args.version}
Architecture: aarch64_cortex-a53
Depends: libc, ca-bundle, kmod-inet-diag
Provides: sing-box
Require-User: sing-box=5566:sing-box=5566
Section: net
Maintainer: cr8808-customize local build
License: GPL-3.0-or-later
Installed-Size: {installed_size}
Description: Verified sing-box core in a read-only loop-mounted SquashFS image
""".encode()
    preinst = b"""#!/bin/sh
[ -n "$IPKG_INSTROOT" ] && exit 0
[ "$(cat /tmp/sysinfo/board_name)" = 'redmi,ax3000' ] || exit 1
grep -q squashfs /proc/filesystems || exit 1
[ -c /dev/loop-control ] || exit 1
if [ -e /usr/bin/sing-box ]; then
 [ -f /usr/lib/opkg/info/sing-box-squashfs.list ] || {
  echo 'A different sing-box package is already installed.' >&2
  exit 1
 }
 [ ! -x /etc/init.d/homeproxy ] || /etc/init.d/homeproxy stop
 /etc/init.d/sing-box-squashfs stop || exit 1
fi
"""
    postinst = b"""#!/bin/sh
[ "${IPKG_NO_SCRIPT}" = '1' ] && exit 0
. ${IPKG_INSTROOT}/lib/functions.sh
default_postinst "$0" "$@" || exit $?
[ -n "$IPKG_INSTROOT" ] && exit 0
/etc/init.d/sing-box-squashfs enable
/etc/init.d/sing-box-squashfs start
"""
    prerm = b"""#!/bin/sh
if [ -z "$IPKG_INSTROOT" ]; then
 [ ! -x /etc/init.d/homeproxy ] || /etc/init.d/homeproxy stop
 /etc/init.d/sing-box-squashfs stop || exit 1
fi
. ${IPKG_INSTROOT}/lib/functions.sh
default_prerm "$0" "$@"
"""
    # This firmware's opkg uses the OpenWrt tar-wrapped IPK format.
    package = tar_gz([
        ("debian-binary", b"2.0\n", 0o644),
        ("control.tar.gz", tar_gz([("control", control, 0o644), ("preinst", preinst, 0o755),
                                    ("postinst", postinst, 0o755), ("prerm", prerm, 0o755)]), 0o644),
        ("data.tar.gz", tar_gz(files), 0o644),
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(package)
    report = {**manifest, "package_sha256": digest(package), "package_bytes": len(package),
              "installed_file_bytes": installed_size, "output": str(args.output.resolve())}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
