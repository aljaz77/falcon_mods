"""Spiral fill generator (patches/qml/FalconModsSpiral.js), run under Node.

Checks topology (paths per shape), coverage (largest gap between the burn lines) and
containment (nothing outside the shape or across a hole) on synthetic shapes.
"""
import importlib.util
import json
import math
import os
import shutil
import subprocess

import cv2
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tests", "js", "spiral_cli.js")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")

HEART = "M 50,90 C 20,70 0,50 10,25 C 20,5 45,10 50,30 C 55,10 80,5 90,25 C 100,50 80,70 50,90 Z"


def circle(cx, cy, r, n=200):
    return [v for k in range(n) for v in (cx + r * math.cos(2 * math.pi * k / n),
                                          cy + r * math.sin(2 * math.pi * k / n))]


def star(n=5, r0=40, r1=16):
    return [v for k in range(2 * n) for v in (
        50 + (r0 if k % 2 == 0 else r1) * math.cos(k * math.pi / n - math.pi / 2),
        50 + (r0 if k % 2 == 0 else r1) * math.sin(k * math.pi / n - math.pi / 2))]


def run(req):
    out = subprocess.run([NODE, CLI], input=json.dumps(req), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def raster(res, interval):
    """mask (even-odd), distance to the outline and distance to the burn lines, in mm"""
    ppm = max(40, 6 / interval)
    pts = np.concatenate([np.array(p).reshape(-1, 2) for p in res["polys"]])
    x0, y0 = pts.min(0) - 1
    x1, y1 = pts.max(0) + 1
    w, h = int((x1 - x0) * ppm) + 1, int((y1 - y0) * ppm) + 1

    def px(p):
        return np.round((np.array(p).reshape(-1, 2) - [x0, y0]) * ppm).astype(np.int32)

    mask = np.zeros((h, w), np.uint8)
    for p in res["polys"]:
        one = np.zeros_like(mask)
        cv2.fillPoly(one, [px(p)], 1)
        mask ^= one
    edge = np.zeros((h, w), np.uint8)
    cv2.polylines(edge, [px(p) for p in res["polys"]], True, 1, 1)
    d_outline = cv2.distanceTransform(1 - edge, cv2.DIST_L2, 5) / ppm
    lines = np.full((h, w), 255, np.uint8)
    for p in res["paths"]:
        cv2.polylines(lines, [px(p)], False, 0, 1)
    d_lines = cv2.distanceTransform(lines, cv2.DIST_L2, 5) / ppm
    return mask > 0, d_outline, d_lines, px


CASES = {
    # name: (request, expected number of paths)
    "square": ({"polys": [[0, 0, 20, 0, 20, 20, 0, 20]], "opts": {"interval": 1}}, 1),
    "circle": ({"polys": [circle(10, 10, 10)], "opts": {"interval": 0.8}}, 1),
    "heart": ({"svg_paths": [{"d": HEART, "transform": "scale(0.3)"}], "opts": {"interval": 0.4}}, 1),
    "star": ({"polys": [star()], "opts": {"interval": 1.5}}, 1),
    "annulus": ({"polys": [circle(10, 10, 10), circle(10, 10, 4)], "opts": {"interval": 0.7}}, 2),
    "dumbbell": ({"svg_paths": [{"d": "M2,10 C2,0 14,0 14,7 L 26,8 C26,0 38,0 38,10 C38,20 26,20 26,12 "
                                      "L14,13 C14,20 2,20 2,10 Z"}], "opts": {"interval": 0.6}}, 3),
    "two_holes": ({"svg_paths": [{"d": "M0,0 H30 V40 H0 Z M6,6 V16 H24 V6 Z M6,22 V34 H24 V22 Z"}],
                   "opts": {"interval": 0.8}}, 3),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_spiral(name):
    req, n_paths = CASES[name]
    interval = req["opts"]["interval"]
    res = run(req)
    assert len(res["paths"]) == n_paths
    mask, d_outline, d_lines, px = raster(res, interval)

    # coverage: every point deeper than half an interval is close to a burn line
    deep = mask & (d_outline > interval / 2)
    assert d_lines[deep].max() < 1.1 * interval
    assert np.percentile(d_lines[deep], 99) < 0.6 * interval

    # containment: the path stays inside, about half an interval from the outline
    bad = total = 0
    h, w = mask.shape
    for p in res["paths"]:
        q = px(p)
        for a, b in zip(q[:-1], q[1:]):
            n = max(2, int(np.hypot(*(b - a))))
            s = np.clip(np.round(a + (b - a) * np.linspace(0, 1, n)[:, None]).astype(int), 0, [w - 1, h - 1])
            ok = mask[s[:, 1], s[:, 0]] & (d_outline[s[:, 1], s[:, 0]] > 0.25 * interval)
            bad += int((~ok).sum())
            total += n
    assert bad / total < 1e-3


def test_one_path_is_continuous():
    res = run(CASES["heart"][0])
    p = np.array(res["paths"][0]).reshape(-1, 2)
    steps = np.hypot(*np.diff(p, axis=0).T)
    assert steps.max() < 5          # one polyline, no jumps across the shape
    assert res["rings"] >= 15


def test_svg_output():
    req = dict(CASES["square"][0], svg=True)
    svg = run(req)["svg"]
    assert svg.count("<path") == 1
    assert 'width="19mm"' in svg and 'viewBox="0.5 0.5 19 19"' in svg


def test_patch_embeds_page_code():
    spec = importlib.util.spec_from_file_location("spiral_fill", os.path.join(ROOT, "patches", "spiral_fill.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    content = next(p["content"] for p in mod.PATCHES if p["file"] == "FalconModsSpiralSource.js")
    assert content.startswith(".pragma library\n")
    code = json.loads(content.split("var code = ", 1)[1])
    assert ".pragma" not in code
    # the page script must define the entry point and parse as plain JavaScript
    check = ("let s = require('fs').readFileSync(0, 'utf8');"
             "new Function(s + '\\nreturn typeof falconModsSpiral')() === 'function' && console.log('ok')")
    out = subprocess.run([NODE, "-e", check], input=code, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr
