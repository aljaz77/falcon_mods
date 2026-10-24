#!/usr/bin/env python3
"""Minimal reader/writer for Qt binary resource files (.rcc, format v1-v3).

    python rcc.py list    <file.rcc>
    python rcc.py extract <file.rcc> <out_dir>
    python rcc.py pack    <in_dir> <file.rcc> [--compress]

The writer emits a format-3 file that Qt 6 loads with QResource::registerResource.
"""
import os
import struct
import sys
import time
import zlib

FLAG_COMPRESSED = 0x01
FLAG_DIRECTORY = 0x02
FLAG_ZSTD = 0x04


def qt_hash(name: str) -> int:
    enc = name.encode("utf-16-be")
    h = 0
    for unit in struct.unpack(">%dH" % (len(enc) // 2), enc):
        h = ((h << 4) + unit) & 0xFFFFFFFF
        h ^= (h & 0xF0000000) >> 23
        h &= 0x0FFFFFFF
    return h


class RccReader:
    def __init__(self, data: bytes):
        self.d = data
        magic, self.version, self.tree, self.data_off, self.names = struct.unpack(">4sIIII", data[:20])
        if magic != b"qres":
            raise ValueError("not an rcc file")
        self.node_size = 14 if self.version == 1 else 22

    def name(self, off):
        n, _h = struct.unpack(">HI", self.d[self.names + off:self.names + off + 6])
        raw = self.d[self.names + off + 6:self.names + off + 6 + 2 * n]
        return raw.decode("utf-16-be")

    def node(self, idx):
        p = self.tree + idx * self.node_size
        name_off, flags = struct.unpack(">IH", self.d[p:p + 6])
        if flags & FLAG_DIRECTORY:
            count, first = struct.unpack(">II", self.d[p + 6:p + 14])
            return name_off, flags, ("dir", count, first)
        _terr, _lang, doff = struct.unpack(">HHI", self.d[p + 6:p + 14])
        return name_off, flags, ("file", doff)

    def payload(self, flags, doff):
        p = self.data_off + doff
        (size,) = struct.unpack(">I", self.d[p:p + 4])
        blob = self.d[p + 4:p + 4 + size]
        if flags & FLAG_ZSTD:
            import zstandard  # optional dependency
            return zstandard.ZstdDecompressor().decompress(blob, max_output_size=1 << 30)
        if flags & FLAG_COMPRESSED:
            return zlib.decompress(blob[4:])
        return blob

    def walk(self, idx=0, prefix=""):
        name_off, flags, info = self.node(idx)
        name = "" if idx == 0 else self.name(name_off)
        path = f"{prefix}/{name}" if idx else ""
        if info[0] == "dir":
            for c in range(info[2], info[2] + info[1]):
                yield from self.walk(c, path)
        else:
            yield path.lstrip("/"), flags, info[1]


def cmd_list(src):
    r = RccReader(open(src, "rb").read())
    for path, flags, _ in r.walk():
        print(("Z " if flags & (FLAG_COMPRESSED | FLAG_ZSTD) else "  ") + path)


def cmd_extract(src, out):
    r = RccReader(open(src, "rb").read())
    n = 0
    for path, flags, doff in r.walk():
        dst = os.path.join(out, *path.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(r.payload(flags, doff))
        n += 1
    print(f"extracted {n} files from {src}")


def cmd_pack(src_dir, dst, compress=False):
    # Build an in-memory tree of the directory.
    def scan(d):
        entries = []
        for name in os.listdir(d):
            full = os.path.join(d, name)
            entries.append((name, scan(full) if os.path.isdir(full) else full))
        return entries

    root = ("", scan(src_dir))
    names = bytearray()
    name_offsets = {}
    data = bytearray()

    def add_name(n):
        if n not in name_offsets:
            name_offsets[n] = len(names)
            enc = n.encode("utf-16-be")
            names.extend(struct.pack(">HI", len(enc) // 2, qt_hash(n)))
            names.extend(enc)
        return name_offsets[n]

    # Breadth-first numbering, children of one directory contiguous and sorted by hash
    # (QResource binary-searches children by qt_hash).
    nodes = [root]
    first_child = {}
    i = 0
    while i < len(nodes):
        name, content = nodes[i]
        if isinstance(content, list):
            content.sort(key=lambda e: qt_hash(e[0]))
            first_child[i] = len(nodes)
            nodes.extend(content)
        i += 1

    # Non-zero timestamps: Qt's QML disk cache falls back to the executable's mtime for
    # resources with timestamp 0, which would keep serving stale compiled QML.
    stamp = int(time.time() * 1000)
    tree = bytearray()
    files = 0
    for idx, (name, content) in enumerate(nodes):
        name_off = add_name(name) if idx else 0
        if isinstance(content, list):
            tree += struct.pack(">IHII", name_off, FLAG_DIRECTORY, len(content), first_child[idx])
        else:
            blob = open(content, "rb").read()
            flags = 0
            if compress and len(blob) > 64:
                z = struct.pack(">I", len(blob)) + zlib.compress(blob, 9)
                if len(z) < len(blob) * 0.95:
                    blob, flags = z, FLAG_COMPRESSED
            doff = len(data)
            data += struct.pack(">I", len(blob)) + blob
            # territory = AnyTerritory (0), language = QLocale::C (1): QResource only
            # matches entries whose locale is C or the current one.
            tree += struct.pack(">IHHHI", name_off, flags, 0, 1, doff)
            files += 1
        tree += struct.pack(">Q", 0 if isinstance(content, list) else stamp)

    header_size = 24
    data_off = header_size
    names_off = data_off + len(data)
    tree_off = names_off + len(names)
    with open(dst, "wb") as f:
        f.write(struct.pack(">4sIIIII", b"qres", 3, tree_off, data_off, names_off,
                            FLAG_COMPRESSED if compress else 0))
        f.write(data)
        f.write(names)
        f.write(tree)
    print(f"packed {files} files into {dst}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "list":
        cmd_list(a[1])
    elif a[0] == "extract":
        cmd_extract(a[1], a[2])
    elif a[0] == "pack":
        cmd_pack(a[1], a[2], "--compress" in a)
    else:
        print(__doc__)
