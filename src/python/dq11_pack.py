#!/usr/bin/env python3
"""Extract and rebuild Dragon Quest XI (3DS) PACK/PACA archives."""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import struct
from pathlib import Path

import dq11_blz


HEADER_SIZE = 0x18
ALIGN_0X80 = {".bch", ".ptcl", ".arc"}


@dataclasses.dataclass
class Entry:
    name: str
    offset: int
    file_start: int
    unknown: int
    size: int
    table_value: int
    data: bytes


@dataclasses.dataclass
class Archive:
    magic: str
    endian: str
    declared_size: int
    original_size: int
    unknown1: int
    byte_order: int
    declared_header_size: int
    unknown2: int
    unknown3: int
    entries: list[Entry]


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def read_archive_bytes(blob: bytes, source: str = "<bytes>") -> Archive:
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"{source}: file is too small")

    magic = blob[:4].decode("ascii", errors="strict")
    if magic not in {"PACK", "PACA"}:
        raise ValueError(f"{path}: unsupported magic {magic!r}")

    bom_bytes = blob[0xA:0xC]
    if bom_bytes == b"\xff\xfe":
        endian = "<"
    elif bom_bytes == b"\xfe\xff":
        endian = ">"
    else:
        raise ValueError(f"{source}: unknown byte-order marker {bom_bytes.hex()}")

    header = struct.unpack_from(endian + "4sihHhhii", blob, 0)
    _, declared_size, unknown1, byte_order, count, declared_header_size, unknown2, unknown3 = header
    if magic == "PACK" and declared_size != len(blob):
        raise ValueError(
            f"{source}: declared size 0x{declared_size:X} does not match actual size 0x{len(blob):X}"
        )
    if count < 0:
        raise ValueError(f"{path}: negative entry count")

    offsets_pos = HEADER_SIZE
    offsets = list(struct.unpack_from(endian + f"{count}i", blob, offsets_pos))
    values_pos = offsets_pos + count * 4
    table_values = list(struct.unpack_from(endian + f"{count}q", blob, values_pos))

    entries: list[Entry] = []
    for offset, table_value in zip(offsets, table_values):
        file_start, entry_unknown, file_size = struct.unpack_from(endian + "hhI", blob, offset)
        name_start = offset + 8
        name_end = blob.index(0, name_start)
        name = blob[name_start:name_end].decode("ascii", errors="strict")
        if not name or name in {'.', '..'} or any(c in name for c in '/\\:'):
            raise ValueError('Unsafe archive entry name')
        data_start = offset + file_start
        data_end = data_start + file_size
        if data_start < name_end + 1 or data_end > len(blob):
            raise ValueError(f"{source}: invalid bounds for entry {name!r}")
        entries.append(
            Entry(
                name=name,
                offset=offset,
                file_start=file_start,
                unknown=entry_unknown,
                size=file_size,
                table_value=table_value,
                data=blob[data_start:data_end],
            )
        )

    return Archive(
        magic=magic,
        endian=endian,
        declared_size=declared_size,
        original_size=len(blob),
        unknown1=unknown1,
        byte_order=byte_order,
        declared_header_size=declared_header_size,
        unknown2=unknown2,
        unknown3=unknown3,
        entries=entries,
    )


def read_archive(path: Path) -> Archive:
    """Read PACK or PACA, expanding BLZ-compressed PACA for inspection."""
    blob = path.read_bytes()
    stored_size = len(blob)
    if blob[:4] == b"PACA":
        bom = blob[0xA:0xC]
        if bom == b"\xff\xfe":
            endian = "<"
        elif bom == b"\xfe\xff":
            endian = ">"
        else:
            endian = None
        declared_size = (struct.unpack_from(endian + "i", blob, 4)[0]
                         if endian and len(blob) >= HEADER_SIZE else None)
        if declared_size != stored_size:
            blob = dq11_blz.decompress(blob)
            archive = read_archive_bytes(blob, str(path))
            if archive.magic != "PACA":
                raise ValueError(f"{path}: decompressed archive lost PACA magic")
            # Keep the stored size so rebuild_archive() continues to reject
            # compressed PACA files until BLZ recompression is implemented.
            archive.original_size = stored_size
            return archive
    return read_archive_bytes(blob, str(path))


def build_archive(archive: Archive, replacements: Path | None = None,
                  output_magic: str | None = None) -> bytes:
    if archive.magic == "PACA" and archive.declared_size != archive.original_size:
        raise ValueError(
            "compressed/size-differing PACA rebuilding is not implemented; extraction is read-only"
        )
    endian = archive.endian
    count = len(archive.entries)
    data_offset = HEADER_SIZE + count * 4 + count * 8
    output = bytearray(data_offset)
    offsets: list[int] = []

    for entry in archive.entries:
        offsets.append(data_offset)
        replacement = replacements / entry.name if replacements else None
        data = replacement.read_bytes() if replacement and replacement.is_file() else entry.data

        name = entry.name.encode("ascii") + b"\0"
        minimum_header_end = data_offset + 0x28
        required_name_end = data_offset + 8 + len(name)
        if required_name_end > minimum_header_end:
            raise ValueError(f"entry name is too long for PACK header: {entry.name!r}")

        if len(output) < minimum_header_end:
            output.extend(b"\0" * (minimum_header_end - len(output)))
        output[data_offset + 8:required_name_end] = name

        alignment = 0x80 if Path(entry.name).suffix.lower() in ALIGN_0X80 else 1
        file_pos = _align(minimum_header_end, alignment)
        if len(output) < file_pos:
            output.extend(b"\0" * (file_pos - len(output)))
        file_start = file_pos - data_offset
        output.extend(data)
        padded_end = _align(len(output), 4)
        output.extend(b"\0" * (padded_end - len(output)))

        struct.pack_into(endian + "hhI", output, data_offset, file_start, entry.unknown, len(data))
        data_offset = len(output)

    struct.pack_into(
        endian + "4sihHhhii",
        output,
        0,
        (output_magic or archive.magic).encode("ascii"),
        len(output),
        archive.unknown1,
        archive.byte_order,
        count,
        archive.declared_header_size,
        archive.unknown2,
        archive.unknown3,
    )
    struct.pack_into(endian + f"{count}i", output, HEADER_SIZE, *offsets)
    struct.pack_into(
        endian + f"{count}q",
        output,
        HEADER_SIZE + count * 4,
        *(entry.table_value for entry in archive.entries),
    )
    return bytes(output)


def command_list(args: argparse.Namespace) -> None:
    archive = read_archive(args.archive)
    print(f"{archive.magic}: {len(archive.entries)} entries ({'little' if archive.endian == '<' else 'big'} endian)")
    if archive.declared_size != archive.original_size:
        print(
            f"declared expanded size: {archive.declared_size} bytes; stored size: {archive.original_size} bytes"
        )
    for entry in archive.entries:
        print(f"{entry.size:10d}  {entry.name}")


def command_extract(args: argparse.Namespace) -> None:
    archive = read_archive(args.archive)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": str(args.archive.resolve()),
        "magic": archive.magic,
        "entries": [],
    }
    for entry in archive.entries:
        destination = args.output / entry.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry.data)
        manifest["entries"].append({"name": entry.name, "size": entry.size})
    (args.output / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def command_rebuild(args: argparse.Namespace) -> None:
    archive = read_archive(args.archive)
    result = build_archive(archive, args.replacements, "PACK" if args.uncompressed else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)


def command_inventory(args: argparse.Namespace) -> None:
    records = []
    extension_counts: collections.Counter[str] = collections.Counter()
    magic_counts: collections.Counter[str] = collections.Counter()
    errors = []

    for path in sorted(args.root.rglob("*.pack")):
        relative = path.relative_to(args.root).as_posix()
        magic = path.read_bytes()[:4].decode("ascii", errors="replace")
        magic_counts[magic] += 1
        try:
            archive = read_archive(path)
        except (OSError, ValueError, struct.error) as exc:
            errors.append({"archive": relative, "error": str(exc)})
            continue
        entries = []
        for entry in archive.entries:
            extension = Path(entry.name).suffix.lower() or "<none>"
            extension_counts[extension] += 1
            entries.append({"name": entry.name, "size": entry.size})
        records.append({
            "archive": relative,
            "magic": archive.magic,
            "stored_size": path.stat().st_size,
            "expanded_size": archive.declared_size,
            "entries": entries,
        })

    parsed_paca = [record for record in records if record["magic"] == "PACA"]
    result = {
        "root": str(args.root.resolve()),
        "archive_magic_counts": dict(sorted(magic_counts.items())),
        "archive_counts": {
            "files_seen": sum(magic_counts.values()),
            "parsed": len(records),
            "parse_errors": len(errors),
            "paca_parsed": len(parsed_paca),
            "compressed_paca": sum(record["stored_size"] != record["expanded_size"]
                                    for record in parsed_paca),
        },
        "entry_extension_counts": dict(extension_counts.most_common()),
        "archives": records,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("archive types:")
    for magic, count in sorted(magic_counts.items()):
        print(f"  {magic}: {count}")
    print(f"parsed archives: {len(records)} / {sum(magic_counts.values())}")
    print("top embedded file types:")
    for extension, count in extension_counts.most_common(20):
        print(f"  {extension}: {count}")
    print(f"parse errors: {len(errors)}")


def command_extract_type(args: argparse.Namespace) -> None:
    wanted = args.extension.lower()
    if not wanted.startswith("."):
        wanted = "." + wanted
    extracted = 0
    for path in sorted(args.root.rglob("*.pack")):
        archive = read_archive(path)
        archive_dir = args.output / path.relative_to(args.root).with_suffix("")
        for entry in archive.entries:
            if Path(entry.name).suffix.lower() != wanted:
                continue
            destination = archive_dir / entry.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(entry.data)
            extracted += 1
    print(f"extracted {extracted} {wanted} files to {args.output}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list archive entries")
    list_parser.add_argument("archive", type=Path)
    list_parser.set_defaults(func=command_list)

    extract_parser = subparsers.add_parser("extract", help="extract archive entries")
    extract_parser.add_argument("archive", type=Path)
    extract_parser.add_argument("output", type=Path)
    extract_parser.set_defaults(func=command_extract)

    rebuild_parser = subparsers.add_parser("rebuild", help="rebuild, optionally replacing extracted entries")
    rebuild_parser.add_argument("archive", type=Path, help="original PACK/PACA archive")
    rebuild_parser.add_argument("output", type=Path)
    rebuild_parser.add_argument("--replacements", type=Path)
    rebuild_parser.add_argument(
        "--uncompressed", action="store_true",
        help="write PACK magic so an expanded PACA can be loaded without BLZ recompression",
    )
    rebuild_parser.set_defaults(func=command_rebuild)

    inventory_parser = subparsers.add_parser("inventory", help="inventory PACK/PACA archives below a root")
    inventory_parser.add_argument("root", type=Path)
    inventory_parser.add_argument("output", type=Path)
    inventory_parser.set_defaults(func=command_inventory)

    type_parser = subparsers.add_parser("extract-type", help="bulk-extract one embedded file type")
    type_parser.add_argument("root", type=Path)
    type_parser.add_argument("output", type=Path)
    type_parser.add_argument("--extension", required=True)
    type_parser.set_defaults(func=command_extract_type)

    return parser


def main() -> None:
    args = make_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
