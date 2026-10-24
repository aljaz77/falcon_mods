"""Engrave the stock alignment pattern (virtually), photograph it through a distorted camera,
and check that the crosshair centres are found precisely and in the right order."""
import cv2
import numpy as np
import pytest

from falcon_bedgrid import core, markers
from test_engine_synthetic import SIZE, true_params


def strokes():
    """Stock pattern geometry in laser mm (Y up): circles with crosses, centre rings, digit clutter."""
    out = []
    a = np.linspace(0, 2 * np.pi, 120)
    for (x, y) in markers.STOCK_MARKERS_MM:
        out.append(np.c_[x + 10 * np.cos(a), y + 10 * np.sin(a)])
        out.append(np.array([[x - 10, y], [x + 10, y]]))
        out.append(np.array([[x, y - 10], [x, y + 10]]))
        # a digit-like squiggle next to it
        out.append(np.array([[x + 16, y - 6], [x + 22, y - 6], [x + 22, y + 6], [x + 16, y + 6]]))
    cx, cy = markers.STOCK_CENTRE_MM
    for r in (5, 10):
        out.append(np.c_[cx + r * np.cos(a), cy + r * np.sin(a)])
    return out


def engrave(p, dark_on_light=True, seed=0):
    rng = np.random.default_rng(seed)
    h, w = SIZE[1], SIZE[0]
    if dark_on_light:
        img = np.full((h, w), 175, np.float32)
        img += cv2.GaussianBlur(rng.normal(0, 25, (h, w)).astype(np.float32), (0, 0), sigmaX=40, sigmaY=3)  # grain
        ink = 60.0
    else:
        img = np.full((h, w), 40, np.float32)
        ink = 210.0
    for s in strokes():
        uv = core.project(p, s)
        cv2.polylines(img, [np.round(uv * 16).astype(np.int32)], False, ink, 4, cv2.LINE_AA, shift=4)
    img += rng.normal(0, 4, img.shape).astype(np.float32)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


@pytest.mark.parametrize("dark_on_light,blur,contrast", [
    (True, 0, 1.0), (False, 0, 1.0), (True, 2.0, 0.35), (False, 3.0, 0.5)])
def test_finds_markers_in_raw_image(dark_on_light, blur, contrast):
    p = true_params()
    img = engrave(p, dark_on_light).astype(np.float32)
    m = img.mean()
    img = m + (img - m) * contrast
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    res = markers.detect(np.clip(img, 0, 255).astype(np.uint8))
    truth = core.project(p, np.array(markers.STOCK_MARKERS_MM))
    err = np.linalg.norm(np.array(res["points"]) - truth, axis=1)
    assert err.max() < 1.0, err  # px (~0.2 mm)


def test_finds_markers_in_undistorted_image():
    p = true_params()
    img = engrave(p, True, seed=2)
    K, D, rv, tv = core.unpack(p)
    und = cv2.undistort(img, K, D)
    res = markers.detect(und)
    truth = core.undistort_pixels(core.project(p, np.array(markers.STOCK_MARKERS_MM)), K, D, K)
    err = np.linalg.norm(np.array(res["points"]) - truth, axis=1)
    assert err.max() < 1.0, err


def test_rejects_blank_material():
    blank = np.full((SIZE[1], SIZE[0], 3), 170, np.uint8)
    with pytest.raises(markers.MarkerError):
        markers.detect(blank)


def bed_grid_strokes():
    """The A1 bed plate's printed grid with its four '+' marks (no rings)."""
    xs, ys = [17.6, 145.45, 271.48, 397.0], [305 - y for y in (-2.0, 98.8, 199.2, 300.3)]
    out = [np.array([[x, ys[-1]], [x, ys[0]]]) for x in xs]
    out += [np.array([[xs[0], y], [xs[-1], y]]) for y in ys]
    for x in xs[1:3]:
        for y in ys[1:3]:
            out.append(np.array([[x - 4, y], [x + 4, y]]))
            out.append(np.array([[x, y - 4], [x, y + 4]]))
    return out


def test_bed_grid_crossings_are_not_markers():
    """Regression: the printed '+' crossings of the bed grid were once taken for markers."""
    p = true_params()
    img = np.full((SIZE[1], SIZE[0]), 30, np.float32)
    for s in bed_grid_strokes():
        cv2.polylines(img, [np.round(core.project(p, s) * 16).astype(np.int32)], False, 200.0, 5,
                      cv2.LINE_AA, shift=4)
    with pytest.raises(markers.MarkerError):
        markers.detect(cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_GRAY2BGR))


def test_markers_found_next_to_bed_grid():
    p = true_params()
    img = engrave(p, False, 4).astype(np.float32)
    for s in bed_grid_strokes():
        cv2.polylines(img, [np.round(core.project(p, s) * 16).astype(np.int32)], False, 200.0, 5,
                      cv2.LINE_AA, shift=4)
    res = markers.detect(img.astype(np.uint8))
    truth = core.project(p, np.array(markers.STOCK_MARKERS_MM))
    assert np.linalg.norm(np.array(res["points"]) - truth, axis=1).max() < 1.0
