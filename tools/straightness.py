#!/usr/bin/env python3
"""Measure how straight the bed-grid lines are in Falcon Design Space's camera view (image/cam.jpg).

    python straightness.py cam.jpg [--template falcon_a1] [--height MM]

For every grid line it tracks the line centre every 2 mm (sub-pixel), fits a straight line and
reports the deviation (how "bent" it looks) and the offset from where the line should be.
`--height` = processing height used for the capture (the app scales the view by (180-h)/180).
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calib"))
from falcon_bedgrid import pipeline  # noqa: E402


def measure(path, tmpl, height=0.0, pos=None):
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32)
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    th = cv2.GaussianBlur(th, (0, 0), 1.2)
    ppm = tmpl.ppm
    pos = tmpl.positions() if pos is None else pos
    is_v = tmpl.kinds()
    vpos, hpos = pos[is_v], pos[~is_v]
    out = []
    for i, (kind, _, _) in enumerate(tmpl.lines):
        lo, hi = (hpos.min(), hpos.max()) if kind == "v" else (vpos.min(), vpos.max())
        cross = hpos if kind == "v" else vpos
        found = []
        for s in np.arange(max(lo, 1), min(hi, (tmpl.H if kind == "v" else tmpl.W) - 1), 2.0):
            if np.min(np.abs(cross - s)) < 8:
                continue
            c = pos[i]
            offs = np.arange(-4.0, 4.0001, 1 / (2 * ppm))
            if kind == "v":
                xs, ys = (c + offs) * ppm, np.full_like(offs, s * ppm)
            else:
                xs, ys = np.full_like(offs, s * ppm), (c + offs) * ppm
            prof = cv2.remap(th, xs.astype(np.float32)[None], ys.astype(np.float32)[None], cv2.INTER_LINEAR)[0]
            k = int(np.argmax(prof))
            base = np.median(prof)
            if k in (0, len(prof) - 1) or prof[k] - base < 10:
                continue
            # intensity-weighted centre of the ridge (robust for the wide, colour-fringed frame band)
            half = prof > base + 0.5 * (prof[k] - base)
            lo_i, hi_i = k, k
            while lo_i > 0 and half[lo_i - 1]:
                lo_i -= 1
            while hi_i < len(prof) - 1 and half[hi_i + 1]:
                hi_i += 1
            w = prof[lo_i:hi_i + 1] - base
            found.append((s, c + float(np.sum(offs[lo_i:hi_i + 1] * w) / np.sum(w))))
        if len(found) < 10:
            out.append(None)
            continue
        f = np.array(found)
        A = np.c_[f[:, 0], np.ones(len(f))]
        coef, *_ = np.linalg.lstsq(A, f[:, 1], rcond=None)
        dev = f[:, 1] - A @ coef
        keep = np.abs(dev) < max(4 * 1.4826 * np.median(np.abs(dev)), 0.3)
        coef, *_ = np.linalg.lstsq(A[keep], f[keep, 1], rcond=None)
        dev = f[keep, 1] - A[keep] @ coef
        out.append({"line": f"{'V' if kind == 'v' else 'H'}{pos[i]:.0f}", "n": int(keep.sum()),
                    "bend_rms_mm": float(np.sqrt(np.mean(dev ** 2))),
                    "bend_max_mm": float(np.percentile(np.abs(dev), 97)),
                    "mean_pos_mm": float(np.mean(f[keep, 1]))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--template", default="falcon_a1")
    ap.add_argument("--positions", help="JSON list of fitted line positions (from bedgrid_report.json)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tmpl = pipeline.load_template(a.template)
    pos = np.array(json.loads(a.positions)) if a.positions else None
    res = measure(a.image, tmpl, pos=pos)
    if a.json:
        print(json.dumps(res, indent=1))
        return
    worst = 0
    for r in res:
        if r is None:
            print("  (line not found)")
            continue
        worst = max(worst, r["bend_max_mm"])
        print(f"  {r['line']:5s} bend rms {r['bend_rms_mm']:.2f} mm, max {r['bend_max_mm']:.2f} mm "
              f"(n={r['n']}), centre at {r['mean_pos_mm']:.2f}")
    print(f"  worst bend {worst:.2f} mm")


if __name__ == "__main__":
    main()
