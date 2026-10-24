#!/usr/bin/env python3
"""Draw the FalconMods icon (bed grid + concentric fill) and write a multi-size .ico."""
import os
import struct
import sys

import cv2
import numpy as np


def draw(size):
    s = 1024
    img = np.zeros((s, s, 4), np.uint8)
    cv2.rectangle(img, (40, 40), (s - 40, s - 40), (41, 33, 29, 255), -1, cv2.LINE_AA)
    m = 150
    cv2.rectangle(img, (m, m), (s - m, s - m), (240, 216, 158, 255), 28, cv2.LINE_AA)
    for i in (1, 2):
        x = m + i * (s - 2 * m) // 3
        cv2.line(img, (x, m), (x, s - m), (235, 230, 229, 255), 14, cv2.LINE_AA)
        cv2.line(img, (m, x), (s - m, x), (235, 230, 229, 255), 14, cv2.LINE_AA)
    for r in range(70, 300, 55):
        cv2.circle(img, (s // 2, s // 2), r, (235, 209, 18, 255), 22, cv2.LINE_AA)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def main(out):
    sizes = [256, 64, 48, 32, 16]
    pngs = [cv2.imencode(".png", draw(n))[1].tobytes() for n in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for n, data in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(out, "wb") as f:
        f.write(header + entries + b"".join(pngs))
    cv2.imwrite(os.path.splitext(out)[0] + ".png", draw(256))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "installer/falconmods.ico")
