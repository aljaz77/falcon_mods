"""Find the four engraved crosshair markers of Falcon Design Space's "Camera Alignment" pattern.

The stock pattern (`gcode.genCalibationPathGcodes`) engraves, in laser coordinates (mm, Y up):
  1 (100.5, 242.5)  2 (280.5, 242.5)  3 (280.5, 62.5)  4 (100.5, 62.5)
each a 20 mm circle with a cross through it, a double ring (10/20 mm) in the centre at
(190.5, 152.5), and the digits 1-4 next to the markers. In the camera image the back of the
machine is at the top, so the markers appear as 1 top-left, 2 top-right, 3 bottom-right,
4 bottom-left - the order the app expects for setPielPos(0..3).

Returns crosshair centres in the pixel coordinates of the given image (raw or undistorted),
so the result can be handed straight to clCamera.setPielPos().
"""
import itertools

import cv2
import numpy as np

STOCK_MARKERS_MM = [(100.5, 242.5), (280.5, 242.5), (280.5, 62.5), (100.5, 62.5)]
STOCK_CENTRE_MM = (190.5, 152.5)
MARKER_RADIUS_MM = 10.0


class MarkerError(Exception):
    pass


def _contrast_image(gray):
    """Engraved lines: dark on light wood or light on dark card -> use both polarities."""
    g = gray.astype(np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, k)
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k)
    return cv2.GaussianBlur(np.maximum(th, bh), (0, 0), 1.2)


def _sample(img, xs, ys):
    xs = np.asarray(xs, np.float32)
    ys = np.asarray(ys, np.float32)
    out = cv2.remap(img, xs.reshape(1, -1), ys.reshape(1, -1), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return out.reshape(xs.shape)


def _ring_score(c, x, y, r):
    """Mean contrast on the circle minus mean contrast just inside/outside it."""
    a = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    on = _sample(c, x + r * np.cos(a), y + r * np.sin(a)).mean()
    off = 0.5 * (_sample(c, x + 0.8 * r * np.cos(a), y + 0.8 * r * np.sin(a)).mean()
                 + _sample(c, x + 1.2 * r * np.cos(a), y + 1.2 * r * np.sin(a)).mean())
    return on - off


def _cross_score(c, x, y, r):
    """Contrast along the horizontal/vertical diameters vs. the diagonals (no cross on those)."""
    t = np.linspace(-0.85, 0.85, 60) * r
    t = t[np.abs(t) > 0.15 * r]
    hv = _sample(c, x + t, y + 0 * t).mean() + _sample(c, x + 0 * t, y + t).mean()
    d = t / np.sqrt(2)
    diag = _sample(c, x + d, y + d).mean() + _sample(c, x + d, y - d).mean()
    return 0.5 * (hv - diag)


def _refine_centre(c, x, y, r):
    """Sub-pixel crosshair centre: fit straight lines to the two cross arms and intersect them."""
    def arm(horizontal):
        pts = []
        for s in np.linspace(-0.85 * r, 0.85 * r, 40):
            if abs(s) < 0.18 * r:
                continue
            offs = np.linspace(-0.25 * r, 0.25 * r, 61)
            if horizontal:
                prof = _sample(c, np.full_like(offs, x + s), y + offs)
            else:
                prof = _sample(c, x + offs, np.full_like(offs, y + s))
            k = int(np.argmax(prof))
            if k in (0, len(prof) - 1) or prof[k] - np.median(prof) < 4:
                continue
            a, b, cc = prof[k - 1], prof[k], prof[k + 1]
            den = a - 2 * b + cc
            sub = 0.5 * (a - cc) / den if den != 0 else 0.0
            o = offs[k] + sub * (offs[1] - offs[0])
            pts.append((x + s, y + o) if horizontal else (x + o, y + s))
        return np.array(pts)

    h, v = arm(True), arm(False)
    if len(h) < 8 or len(v) < 8:
        return None
    # horizontal arm: y = a*x + b ; vertical arm: x = c*y + d
    a, b = np.polyfit(h[:, 0], h[:, 1], 1)
    cc, d = np.polyfit(v[:, 1], v[:, 0], 1)
    yy = (a * d + b) / (1 - a * cc)
    xx = cc * yy + d
    resid = np.r_[h[:, 1] - (a * h[:, 0] + b), v[:, 0] - (cc * v[:, 1] + d)]
    return float(xx), float(yy), float(np.sqrt(np.mean(resid ** 2)))


def _marker_template(r, width):
    size = int(2 * r * 1.25) | 1
    t = np.zeros((size, size), np.float32)
    c = size // 2
    cv2.circle(t, (c, c), int(round(r)), 1.0, width, cv2.LINE_AA)
    cv2.line(t, (c - int(r), c), (c + int(r), c), 1.0, width, cv2.LINE_AA)
    cv2.line(t, (c, c - int(r)), (c, c + int(r)), 1.0, width, cv2.LINE_AA)
    return cv2.GaussianBlur(t, (0, 0), 1.0)


def _matched_candidates(c, rmin, rmax, scale=0.5):
    """Correlate the contrast image with ring+cross templates over a range of sizes."""
    small = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    best = np.full(small.shape, -1.0, np.float32)
    best_r = np.zeros(small.shape, np.float32)
    r = rmin * scale
    while r <= rmax * scale:
        t = _marker_template(r, 2)
        if t.shape[0] >= min(small.shape):
            break
        m = cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED)
        off = t.shape[0] // 2
        resp = np.full(small.shape, -1.0, np.float32)
        resp[off:off + m.shape[0], off:off + m.shape[1]] = m
        upd = resp > best
        best[upd] = resp[upd]
        best_r[upd] = r / scale
        r *= 1.08
    # local maxima
    dil = cv2.dilate(best, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(rmin * scale) | 1,) * 2))
    ys, xs = np.where((best == dil) & (best > 0.15))
    order = np.argsort(-best[ys, xs])[:40]
    return [(xs[i] / scale, ys[i] / scale, float(best_r[ys[i], xs[i]]), float(best[ys[i], xs[i]])) for i in order]


def detect(image, expected_radius_px=None):
    """Return {'points': [[x,y] x4 in order 1..4], 'radius_px', 'quality'} or raise MarkerError."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    c = _contrast_image(gray)
    # A 20 mm marker is ~100 px across at ~0.2 mm/px; allow a wide range of image scales.
    rmin, rmax = (int(expected_radius_px * 0.6), int(expected_radius_px * 1.5)) if expected_radius_px \
        else (max(15, int(min(w, h) * 0.012)), int(min(w, h) * 0.06))
    scored = []
    for x, y, r, corr in _matched_candidates(c, rmin, rmax):
        rs, cs = _ring_score(c, x, y, r), _cross_score(c, x, y, r)
        # a stock marker is a ring AND a cross; the bed's printed "+" marks have no ring
        if cs > 2 and rs > max(2.0, 0.3 * cs):
            scored.append((corr * max(cs, 1e-3), x, y, r))
    # de-duplicate overlapping candidates, keep the best
    scored.sort(reverse=True)
    uniq = []
    for s in scored:
        if all(np.hypot(s[1] - u[1], s[2] - u[2]) > 0.8 * s[3] for u in uniq):
            uniq.append(s)
    uniq = uniq[:10]
    if len(uniq) < 4:
        raise MarkerError(f"found {len(uniq)} of 4 alignment markers - is the engraving visible and "
                          "the material inside the camera view?")

    # pick the 4 that best form a quadrilateral of similar-size markers (one per quadrant)
    best = None
    for combo in itertools.combinations(uniq, 4):
        pts = np.array([[q[1], q[2]] for q in combo])
        rad = np.array([q[3] for q in combo])
        cen = pts.mean(0)
        quad = {(int(px > cen[0]), int(py > cen[1])) for px, py in pts}
        if len(quad) != 4:
            continue
        # the markers form a 180 x 180 mm square with 20 mm circles: check shape and scale
        o = sorted(range(4), key=lambda i: (pts[i][1] > cen[1], pts[i][0] > cen[0]))
        tl, tr, bl, br = (pts[i] for i in o)
        width = 0.5 * (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl))
        height = 0.5 * (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr))
        if not 0.75 < width / height < 1.33:
            continue
        if not 0.6 < np.mean(rad) / (0.5 * (width + height) / 18.0) < 1.6:
            continue
        spread = np.std(rad) / np.mean(rad)
        score = sum(q[0] for q in combo) * (1 - min(spread, 0.9))
        if best is None or score > best[0]:
            best = (score, combo, cen)
    if best is None:
        raise MarkerError("could not find the four markers in the four corners of the pattern")
    _, combo, cen = best
    order = {(0, 0): 0, (1, 0): 1, (1, 1): 2, (0, 1): 3}  # TL, TR, BR, BL -> markers 1..4
    out = [None] * 4
    fit_rms = []
    for q in combo:
        _, x, y, r = q
        ref = _refine_centre(c, x, y, r)
        if ref is None:
            raise MarkerError("a marker's cross could not be measured precisely")
        out[order[(int(x > cen[0]), int(y > cen[1]))]] = [ref[0], ref[1]]
        fit_rms.append(ref[2])
    return {"points": out, "radius_px": float(np.mean([q[3] for q in combo])),
            "line_rms_px": float(np.mean(fit_rms))}
