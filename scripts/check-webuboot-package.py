#!/usr/bin/env python3
"""Check candidate files and optional local backups. Never contacts a router."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


EXPECTED = {
    "MIBIB.bin": (524288, "c56efb1b07051d2c799b20cec147ac5ba672a72c5bad4529ec7de865ac54becd"),
    "APPSBL.bin": (1310720, "a92f08878499bb697e67cfb5f597bb5757e48b4846f4f250fbc612ea166ad4f3"),
    "APPSBL1.bin": (1310720, "c399dcae6af94e8067532c64f3bc7b137169fbbe80b539f952d9c468fa075cb5"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def partition_table(data, offset):
    magic1, magic2, version, count = struct.unpack_from("<4I", data, offset)
    require((magic1, magic2, version, count) ==
            (0x55EE73AA, 0xE35EBDDB, 4, 22), "Unexpected MIBIB header")
    rows = []
    for index in range(count):
        name, start, size, attributes = struct.unpack_from(
            "<16sIII", data, offset + 16 + index * 28)
        rows.append((name.split(b"\0", 1)[0].decode("ascii"), start, size, attributes))
    return rows


def check_elf(data, name):
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    require(header[0][:6] == b"\x7fELF\x01\x01" and header[2] == 40,
            name + ": expected little-endian ELF32 ARM")
    require(header[4] == 0x4A920000 and header[9] == 32 and header[10] == 4,
            name + ": unexpected entry or segment table")
    entry_covered = False
    for index in range(header[10]):
        segment = struct.unpack_from("<8I", data, header[5] + index * header[9])
        if segment[0] != 1:
            continue
        require(segment[1] + segment[4] <= len(data) and segment[4] <= segment[5],
                name + ": invalid load segment bounds")
        entry_covered |= segment[2] <= header[4] < segment[2] + segment[5]
    require(entry_covered, name + ": entry is outside load segments")


def check_backups(directory, candidate_mibib):
    manifest = json.loads((directory / "backup-manifest.json").read_text(encoding="utf-8-sig"))
    rows = manifest["partitions"]
    physical = [row for row in rows if row["type"] == "nand"]
    require(sorted(row["mtd"] for row in physical) == list(range(22)),
            "Local backup manifest must contain physical mtd0 through mtd21")
    require(sum(row["bytes"] for row in physical) == 133169152,
            "Unexpected total physical backup size")
    mibib = None
    for row in rows:
        require(Path(row["file"]).name == row["file"], "Invalid backup filename")
        data = (directory / row["file"]).read_bytes()
        require(len(data) == row["bytes"], "Wrong backup size: " + row["file"])
        require(hashlib.sha256(data).hexdigest() == row["sha256"],
                "Wrong backup checksum: " + row["file"])
        if row["mtd"] == 1 and row["type"] == "nand":
            mibib = data
    require(mibib == candidate_mibib, "Candidate MIBIB differs from local backup")
    print("LOCAL_BACKUPS_OK: {} files; 22 physical partitions, 127 MiB".format(len(rows)))
    print("CANDIDATE_MIBIB_EQUALS_LOCAL_BACKUP: yes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1] /
                        "firmware/webuboot/cr880x-20221214")
    parser.add_argument("--backups", type=Path, help="Optional original local backup directory")
    args = parser.parse_args()
    data = {}
    for name, (size, checksum) in EXPECTED.items():
        data[name] = (args.package / name).read_bytes()
        require(len(data[name]) == size, "Wrong candidate size: " + name)
        require(hashlib.sha256(data[name]).hexdigest() == checksum,
                "Wrong candidate checksum: " + name)
    mibib = data["MIBIB.bin"]
    first = partition_table(mibib, 2048)
    require(first == partition_table(mibib, 131072 + 2048), "MIBIB copies differ")
    lookup = {row[0]: row[1:3] for row in first}
    require(lookup["rootfs"] == (84, 288) and lookup["rootfs_1"] == (372, 288),
            "Unexpected original dual-slot layout")
    for name in ("APPSBL.bin", "APPSBL1.bin"):
        check_elf(data[name], name)
    print("PACKAGE_INTEGRITY_OK: 3 pinned files")
    print("MIBIB_TABLE_OK: 22 partitions; rootfs and rootfs_1 are 36 MiB each")
    print("ELF_STRUCTURE_OK: ARM32; entry 0x4a920000")
    if args.backups:
        check_backups(args.backups, mibib)
    else:
        print("LOCAL_BACKUPS: not checked")
    print("DEVICE_COMPATIBILITY: NOT_VERIFIED")
    print("FLASH_ALLOWED: NO")
    print("REBOOT_ALLOWED: NO")
    print("Only local integrity was checked. No router was contacted or changed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        print("CHECK_FAILED: " + str(error), file=sys.stderr)
        sys.exit(1)
