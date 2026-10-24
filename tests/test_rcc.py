import os
import struct

import rcc


def test_qt_hash_known_values():
    # values produced by Qt's qt_hash() for these names (read from a Qt-generated rcc file)
    assert rcc.qt_hash("") == 0
    assert rcc.qt_hash("a") == 97
    assert rcc.qt_hash("ab") == (97 << 4) + 98


def test_pack_roundtrip(tmp_path):
    src = tmp_path / "src"
    (src / "qml" / "Popup").mkdir(parents=True)
    files = {
        "main.qml": b"import QtQuick 2.15\nItem {}\n" * 20,
        "qml/Popup/A.qml": b"Item { width: 1 }\n",
        "qml/Popup/B.svg": bytes(range(256)) * 4,
        "qml/x.txt": "ünïcödé".encode(),
    }
    for name, data in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    out = tmp_path / "t.rcc"
    rcc.cmd_pack(str(src), str(out), compress=True)
    r = rcc.RccReader(out.read_bytes())
    got = {path: r.payload(flags, doff) for path, flags, doff in r.walk()}
    assert got == files
    # Every file node must carry language QLocale::C (1) or Qt will not find it.
    for i in range(1, (len(r.d) - r.tree) // 22):
        p = r.tree + i * 22
        _, flags = struct.unpack(">IH", r.d[p:p + 6])
        if not flags & rcc.FLAG_DIRECTORY:
            terr, lang = struct.unpack(">HH", r.d[p + 6:p + 10])
            assert (terr, lang) == (0, 1)
            assert struct.unpack(">Q", r.d[p + 14:p + 22])[0] > 0  # timestamp set


def test_children_sorted_by_hash(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for n in ["zeta.qml", "alpha.qml", "Main.qml", "b.png", "C.svg"]:
        (src / n).write_text(n)
    out = tmp_path / "t.rcc"
    rcc.cmd_pack(str(src), str(out))
    r = rcc.RccReader(out.read_bytes())
    _, _, (_, count, first) = r.node(0)
    hashes = [rcc.qt_hash(r.name(r.node(i)[0])) for i in range(first, first + count)]
    assert hashes == sorted(hashes)
