#!/usr/bin/env python3
"""Render laser G-code (GRBL style, G0/G1 with S power) to a PNG for quick inspection.

    python gcode_preview.py file.gcode [out.png] [--px-per-mm 20]

Burn moves (G1 with S>0 under M3/M4) are black, travel moves are light red.
Also prints a summary: burn length, travel length, number of burn segments.
"""
import math
import re
import sys

import cv2
import numpy as np

WORD = re.compile(r"([A-Z])\s*(-?\d*\.?\d+)")


def parse(path):
    x = y = 0.0
    s = 0.0
    laser_on = False
    mode = 0
    absolute = True
    segs = []  # (x0, y0, x1, y1, burn)
    for raw in open(path, errors="ignore"):
        line = raw.split(";")[0].strip().upper()
        if not line:
            continue
        words = WORD.findall(line)
        nx, ny = x, y
        for k, v in words:
            v = float(v)
            if k == "G":
                g = int(v)
                if g in (0, 1, 2, 3):
                    mode = g
                elif g == 90:
                    absolute = True
                elif g == 91:
                    absolute = False
            elif k == "M":
                m = int(v)
                if m in (3, 4):
                    laser_on = True
                elif m == 5:
                    laser_on = False
            elif k == "S":
                s = v
            elif k == "X":
                nx = v if absolute else x + v
            elif k == "Y":
                ny = v if absolute else y + v
        if (nx, ny) != (x, y):
            burn = mode != 0 and laser_on and s > 0
            segs.append((x, y, nx, ny, burn))
            x, y = nx, ny
    return segs


def render(segs, out, ppm=20.0):
    burn = [s for s in segs if s[4]]
    pts = [(s[0], s[1]) for s in burn] + [(s[2], s[3]) for s in burn]
    if not pts:
        print("no burn moves")
        return
    xs, ys = zip(*pts)
    x0, x1, y0, y1 = min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2
    w, h = int((x1 - x0) * ppm), int((y1 - y0) * ppm)
    scale = min(1.0, 3000 / max(w, h))
    ppm *= scale
    w, h = int((x1 - x0) * ppm) + 1, int((y1 - y0) * ppm) + 1
    img = np.full((h, w, 3), 255, np.uint8)

    def P(px, py):  # G-code Y up -> image Y down
        return int((px - x0) * ppm), int((y1 - py) * ppm)

    blen = tlen = 0.0
    for a, b, c, d, on in segs:
        L = math.hypot(c - a, d - b)
        if on:
            blen += L
            cv2.line(img, P(a, b), P(c, d), (0, 0, 0), 1, cv2.LINE_AA)
        else:
            tlen += L
            if x0 <= a <= x1 and y0 <= b <= y1:
                cv2.line(img, P(a, b), P(c, d), (180, 180, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out, img)
    print(f"burn segments {len(burn)}, burn {blen:.1f} mm, travel {tlen:.1f} mm, bbox "
          f"{x0+2:.2f},{y0+2:.2f} .. {x1-2:.2f},{y1-2:.2f} -> {out}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ppm = 20.0
    if "--px-per-mm" in sys.argv:
        ppm = float(sys.argv[sys.argv.index("--px-per-mm") + 1])
    src = args[0]
    out = args[1] if len(args) > 1 else src.rsplit(".", 1)[0] + ".png"
    render(parse(src), out, ppm)
