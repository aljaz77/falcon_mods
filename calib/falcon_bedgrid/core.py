"""Camera calibration from the printed bed grid of a laser engraver.

Model
-----
Pinhole camera with OpenCV's 5-term distortion (k1, k2, p1, p2, k3) looking at the bed plane Z=0.
World coordinates are millimetres in the app's "world space":  X = canvas x,  Y = H - canvas y
(canvas y grows towards the front of the machine; world Y grows towards the back).

Pipeline
--------
1. Start from a prior model (the existing calibration or a built-in default).
2. Coarse alignment: brute-force image shift that best overlays the predicted grid on the ridges.
3. Model-guided ridge search: sample points along every template line, search along the image
   normal for the thin bright line (top-hat filtered), sub-pixel peak.
4. Robust non-linear least squares of all camera parameters (+ free border-line positions):
   residual = perpendicular image distance of each detection to its projected line.
5. Repeat 3-4 with a shrinking search radius, rejecting outliers.
6. Export K, D, NewK, WorldMatrix in Falcon Design Space's convention.
"""

import cv2
import numpy as np
from . import lm

NP = 14  # f, cx, cy, k1, k2, p1, p2, k3, rx, ry, rz, tx, ty, tz  (+ optional extra distortion terms)
# Extra OpenCV distortion terms appended after the 14 base parameters, per lens model:
#   5  -> k1 k2 p1 p2 k3                    (classic)
#   8  -> + k4 k5 k6                         (rational)
#   12 -> + k4 k5 k6 s1 s2 s3 s4             (rational + thin prism)
#   "prism" -> stored as 12 terms with k4..k6 held at 0 (default: the rational terms are
#              numerically unstable on this lens, thin prism captures the decentring/tilt)
LENS_MODELS = {5: 0, 8: 3, 12: 7, "prism": 7}
DEFAULT_LENS_MODEL = "prism"
FREE_RANGE_MM = 12.0  # how far a "free" template line may move from its nominal position


class CalibrationError(Exception):
    pass


# --------------------------------------------------------------------------- template

class Template:
    def __init__(self, d):
        self.raw = d
        self.W, self.H = d["work_area_mm"]
        self.ppm = d.get("px_per_mm", 6)
        self.clear = d.get("crossing_clearance_mm", 8.0)
        self.step = d.get("sample_step_mm", 2.5)
        # line: [kind, canvas position, free]
        self.lines = [["v", l["x"], bool(l.get("free"))] for l in d["vertical"]] + \
                     [["h", l["y"], bool(l.get("free"))] for l in d["horizontal"]]
        self.free_idx = [i for i, l in enumerate(self.lines) if l[2]]

    def positions(self, free_vals=None):
        pos = np.array([l[1] for l in self.lines], float)
        if free_vals is not None:
            pos[self.free_idx] = free_vals
        return pos

    def kinds(self):
        return np.array([l[0] == "v" for l in self.lines])

    def sample_params(self, pos=None):
        """Along-line sample positions (canvas mm), skipping crossings. Returns (line_id, s).
        Uses the template's nominal positions so the sample set never depends on the fit."""
        pos = self.positions()
        is_v = self.kinds()
        vpos, hpos = pos[is_v], pos[~is_v]
        ids, ss = [], []
        for i, (kind, _, _) in enumerate(self.lines):
            cross = hpos if kind == "v" else vpos
            lo, hi = cross.min(), cross.max()
            s = np.arange(lo, hi + 1e-9, self.step)
            keep = np.min(np.abs(s[:, None] - cross[None, :]), axis=1) > self.clear
            ids.append(np.full(keep.sum(), i))
            ss.append(s[keep])
        return np.concatenate(ids), np.concatenate(ss)

    def world(self, line_ids, s, pos):
        """Canvas line samples -> world XY (mm)."""
        is_v = self.kinds()[line_ids]
        p = pos[line_ids]
        x = np.where(is_v, p, s)
        y = np.where(is_v, s, p)
        return np.stack([x, self.H - y], axis=1)

    def along(self, line_ids, world_xy):
        """World XY -> along-line canvas coordinate for each sample's line."""
        is_v = self.kinds()[line_ids]
        return np.where(is_v, self.H - world_xy[:, 1], world_xy[:, 0])


# --------------------------------------------------------------------------- camera model

def unpack(p):
    f, cx, cy, k1, k2, p1, p2, k3 = p[:8]
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
    D = np.array([k1, k2, p1, p2, k3, *p[NP:]], float)
    return K, D, np.asarray(p[8:11], float), np.asarray(p[11:14], float)


def distort_normalized(x, y, D):
    """OpenCV distortion model (5, 8 or 12 coefficients) on ideal normalized coordinates."""
    d = np.zeros(12)
    d[:min(len(D), 12)] = np.ravel(D)[:12]
    k1, k2, p1, p2, k3, k4, k5, k6, s1, s2, s3, s4 = d
    r2 = x * x + y * y
    r4 = r2 * r2
    r6 = r4 * r2
    rad = (1 + k1 * r2 + k2 * r4 + k3 * r6) / (1 + k4 * r2 + k5 * r4 + k6 * r6)
    xd = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x) + s1 * r2 + s2 * r4
    yd = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y + s3 * r2 + s4 * r4
    return xd, yd


def project(p, xy):
    K, D, rv, tv = unpack(p)
    obj = np.c_[xy, np.zeros(len(xy))].reshape(-1, 1, 3)
    uv, _ = cv2.projectPoints(obj, rv, tv, K, D)
    return uv.reshape(-1, 2)


def undistort_normalized(uv, K, D, iters=30):
    """Raw pixels -> ideal normalized coordinates (Newton solve of the distortion model)."""
    D = np.ravel(D)
    if len(D) > 5 and np.any(D[5:]):
        return _undistort_generic(uv, K, D, iters)
    k1, k2, p1, p2, k3 = D[:5]
    xd = (uv[:, 0] - K[0, 2]) / K[0, 0]
    yd = (uv[:, 1] - K[1, 2]) / K[1, 1]
    x, y = xd.copy(), yd.copy()
    for _ in range(iters):
        r2 = x * x + y * y
        rad = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 ** 3
        g = k1 + 2 * k2 * r2 + 3 * k3 * r2 * r2
        fx = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x) - xd
        fy = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y - yd
        a = rad + 2 * g * x * x + 2 * p1 * y + 6 * p2 * x
        b = 2 * g * x * y + 2 * p1 * x + 2 * p2 * y
        d = rad + 2 * g * y * y + 6 * p1 * y + 2 * p2 * x
        det = a * d - b * b
        det = np.where(np.abs(det) < 1e-12, 1e-12, det)
        dx = (d * fx - b * fy) / det
        dy = (a * fy - b * fx) / det
        x -= dx
        y -= dy
        if max(np.abs(dx).max(initial=0), np.abs(dy).max(initial=0)) < 1e-12:
            break
    return np.stack([x, y], axis=1)


def _undistort_generic(uv, K, D, iters=40):
    """Newton solve with a numeric 2x2 Jacobian (any OpenCV model up to 12 terms)."""
    xd = (uv[:, 0] - K[0, 2]) / K[0, 0]
    yd = (uv[:, 1] - K[1, 2]) / K[1, 1]
    x, y = xd.copy(), yd.copy()
    h = 1e-7
    for _ in range(iters):
        fx, fy = distort_normalized(x, y, D)
        fx -= xd
        fy -= yd
        ax, ay = distort_normalized(x + h, y, D)
        bx, by = distort_normalized(x, y + h, D)
        a = (ax - xd - fx) / h
        c = (ay - yd - fy) / h
        b = (bx - xd - fx) / h
        d = (by - yd - fy) / h
        det = a * d - b * c
        det = np.where(np.abs(det) < 1e-12, 1e-12, det)
        dx = (d * fx - b * fy) / det
        dy = (a * fy - c * fx) / det
        x -= dx
        y -= dy
        if max(np.abs(dx).max(initial=0), np.abs(dy).max(initial=0)) < 1e-12:
            break
    return np.stack([x, y], axis=1)


def undistort_pixels(uv, K, D, NK):
    """Raw pixels -> pixels of the undistorted image rendered with camera matrix NK."""
    n = undistort_normalized(np.asarray(uv, float).reshape(-1, 2), K, np.ravel(D))
    return np.c_[n[:, 0] * NK[0, 0] + NK[0, 2], n[:, 1] * NK[1, 1] + NK[1, 2]]


def unproject(p, uv):
    """Raw pixels -> world XY on the bed plane."""
    K, D, rv, tv = unpack(p)
    n = undistort_normalized(uv, K, D)
    R, _ = cv2.Rodrigues(rv)
    C = -R.T @ tv
    d = (R.T @ np.c_[n, np.ones(len(n))].T).T
    s = -C[2] / d[:, 2]
    return C[:2] + s[:, None] * d[:, :2]


def params_from_config(K, D, NK, W, ppm, img_size):
    """Recover the full model (incl. pose) from an app calibration entry."""
    Hp = np.linalg.inv(W) @ np.diag([ppm, ppm, 1.0])  # world mm -> undistorted (NK) px
    M = np.linalg.inv(NK) @ Hp
    lam = 0.5 * (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
    M = M / lam
    if M[2, 2] < 0:
        M = -M
    r1, r2, t = M[:, 0], M[:, 1], M[:, 2]
    R = np.stack([r1, r2, np.cross(r1, r2)], axis=1)
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R = U @ np.diag([1, 1, -1]) @ Vt
    rv, _ = cv2.Rodrigues(R)
    f = 0.5 * (K[0, 0] + K[1, 1])
    d = list(np.ravel(D)) + [0] * 5
    extra = d[5:len(np.ravel(D))]
    return np.array([f, K[0, 2], K[1, 2], d[0], d[1], d[2], d[3], d[4], *rv.ravel(), *t, *extra])


# --------------------------------------------------------------------------- image features

def ridge_image(bgr):
    g = bgr if bgr.ndim == 2 else cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    g = g.astype(np.float32)
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    return cv2.GaussianBlur(th, (0, 0), 1.2)


def sample_image(img, x, y):
    return cv2.remap(img, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def coarse_shift(th, p, tmpl, pos, radius=120, step=4):
    """Brute-force image translation that best explains the ridges (handles a poor prior)."""
    ids, s = tmpl.sample_params(pos)
    # denser sampling for a smoother score
    uv = project(p, tmpl.world(ids, s, pos))
    h, w = th.shape
    ok = (uv[:, 0] > 0) & (uv[:, 0] < w) & (uv[:, 1] > 0) & (uv[:, 1] < h)
    uv = uv[ok]
    blur = cv2.GaussianBlur(th, (0, 0), 3)

    def score(dx, dy):
        return float(sample_image(blur, uv[:, 0] + dx, uv[:, 1] + dy).sum())

    best = (score(0, 0), 0, 0)
    for st, rad in ((step, radius), (1, step)):
        cx, cy = best[1], best[2]
        for dy in range(-rad, rad + 1, st):
            for dx in range(-rad, rad + 1, st):
                sc = score(cx + dx, cy + dy)
                if sc > best[0]:
                    best = (sc, cx + dx, cy + dy)
    return best[1], best[2]


def detect(th, p, tmpl, pos, radius, noise, lines=None):
    """Model-guided ridge search. Returns line ids, along-line s, detected uv, strength."""
    ids, s = tmpl.sample_params()
    if lines is not None:
        keep = np.isin(ids, lines)
        ids, s = ids[keep], s[keep]
    a = project(p, tmpl.world(ids, s, pos))
    b = project(p, tmpl.world(ids, s + 0.5, pos))
    t = b - a
    t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
    n = np.stack([-t[:, 1], t[:, 0]], axis=1)
    win = max(radius, 16)
    offs = np.arange(-win, win + 0.25, 0.5)
    gx = a[:, 0:1] + offs[None, :] * n[:, 0:1]
    gy = a[:, 1:2] + offs[None, :] * n[:, 1:2]
    prof = sample_image(th, gx, gy)
    prof = cv2.GaussianBlur(prof, (5, 1), 0)
    search = np.where(np.abs(offs) <= radius, prof, -np.inf)
    i = np.argmax(search, axis=1)
    rows = np.arange(len(i))
    peak = prof[rows, i]
    # background: everything further than 6 px from the peak
    far = np.abs(offs[None, :] - offs[i][:, None]) > 6
    base = np.nanmedian(np.where(far, prof, np.nan), axis=1)
    lim = np.abs(offs[i]) < radius - 0.6  # peak not clipped by the search window
    ic = np.clip(i, 1, prof.shape[1] - 2)
    y0, y1, y2 = prof[rows, ic - 1], prof[rows, ic], prof[rows, ic + 1]
    den = y0 - 2 * y1 + y2
    sub = np.where(np.abs(den) > 1e-6, 0.5 * (y0 - y2) / np.where(den == 0, 1, den), 0)
    off = offs[ic] + np.clip(sub, -1, 1) * 0.5
    uv = a + off[:, None] * n
    h, w = th.shape
    inside = (a[:, 0] > 5) & (a[:, 0] < w - 5) & (a[:, 1] > 5) & (a[:, 1] < h - 5)
    strength = peak - base
    ok = lim & inside & (strength > max(8.0, 6 * noise))
    return ids[ok], s[ok], uv[ok], strength[ok]


def scan_free_line(th, p, tmpl, pos, line, rng, noise):
    """1-D search of a free line's position: maximise how many samples sit on a ridge."""
    ids, s = tmpl.sample_params()
    s = s[ids == line]
    ids = ids[ids == line]
    blur = cv2.GaussianBlur(th, (0, 0), 1.5)
    thr = max(8.0, 6 * noise)
    best = (-1, pos[line])
    nominal = pos[line]
    for d in np.arange(-rng, rng + 1e-9, 0.2):
        q = pos.copy()
        q[line] = nominal + d
        uv = project(p, tmpl.world(ids, s, q))
        v = sample_image(blur, uv[:, 0], uv[:, 1])
        score = float(np.minimum(v / thr, 1.0).sum())
        if score > best[0]:
            best = (score, nominal + d)
    return best[1]


# --------------------------------------------------------------------------- fitting

class Fitter:
    def __init__(self, tmpl, prior, img_size, prior_weight=1.0, fix_focal=True, fixed_rational=False):
        self.t = tmpl
        self.prior = prior.copy()
        self.npm = len(prior)  # base parameters + extra distortion terms
        self.rational_sigma = 1e-6 if fixed_rational else 0.5
        self.size = img_size
        self.pw = prior_weight
        # A single view of a (nearly fronto-parallel) plane cannot separate focal length from
        # camera height; any f fits equally well.  By default keep the prior's f.
        self.f_sigma = 1e-4 if fix_focal else 0.25

    def residuals(self, x, ids, s, uv, wts):
        p, fv = x[:self.npm], x[self.npm:]
        pos = self.t.positions(fv)
        a = project(p, self.t.world(ids, s, pos))
        b = project(p, self.t.world(ids, s + 1.0, pos))
        tv = b - a
        tv /= np.linalg.norm(tv, axis=1, keepdims=True) + 1e-12
        n = np.stack([-tv[:, 1], tv[:, 0]], axis=1)
        r = np.sum((uv - a) * n, axis=1) * wts
        pr = self.prior
        priors = self.pw * np.array([
            (p[0] - pr[0]) / (self.f_sigma * pr[0]),  # focal length
            (p[1] - pr[1]) / 150.0,                # principal point: weak
            (p[2] - pr[2]) / 150.0,
            p[5] / 0.003, p[6] / 0.003,            # tangential: small
            (p[7]) / 0.05,                         # k3: small
        ])
        if self.npm > NP:
            ex = p[NP:]
            sig = np.r_[np.full(3, self.rational_sigma), np.full(4, 0.01)][:len(ex)]  # rational, thin prism
            priors = np.r_[priors, self.pw * ex / sig]
        return np.concatenate([r, priors])

    def bounds(self):
        lo = np.full(self.npm, -np.inf)
        hi = np.full(self.npm, np.inf)
        nom = self.t.positions()[self.t.free_idx]
        return (np.r_[lo, nom - FREE_RANGE_MM], np.r_[hi, nom + FREE_RANGE_MM])

    def fit(self, x0, ids, s, uv, wts, f_scale=1.0):
        lo, hi = self.bounds()
        x0 = np.clip(x0, lo + 1e-6, hi - 1e-6)
        res = lm.least_squares(self.residuals, x0, args=(ids, s, uv, wts), f_scale=f_scale,
                               bounds=(lo, hi))
        return res.x, res


def convert_prior(p_src, tmpl, n_extra=7, fixed_rational=False):
    """Re-express a camera model in another distortion model (same pose), by fitting the new
    model to points projected with the old one over the bed. Used when the prior's model has
    terms the target model doesn't (e.g. rational terms -> thin prism only)."""
    xs, ys = np.meshgrid(np.linspace(-20, tmpl.W + 20, 40), np.linspace(-20, tmpl.H + 20, 32))
    world = np.c_[xs.ravel(), ys.ravel()]
    target = project(p_src, world)
    x0 = np.zeros(NP + n_extra)
    x0[:NP] = p_src[:NP]
    if not fixed_rational:
        m = min(len(p_src) - NP, n_extra)
        x0[NP:NP + m] = p_src[NP:NP + m]
    keep = np.ones(len(x0), bool)
    keep[0] = False  # focal length stays (unobservable anyway)
    if fixed_rational:
        keep[NP:NP + 3] = False

    def res(v):
        q = x0.copy()
        q[keep] = v
        return (project(q, world) - target).ravel()

    out = lm.least_squares(res, x0[keep], f_scale=1e6, max_iter=100)
    q = x0.copy()
    q[keep] = out.x
    return q


def calibrate(image, prior_params, tmpl, log=print, fix_focal=True, lens_model=DEFAULT_LENS_MODEL):
    """Run the full pipeline. Returns dict with params, free line positions, stats, samples."""
    h, w = image.shape[:2]
    th = ridge_image(image)
    noise = float(np.median(np.abs(th - np.median(th)))) * 1.4826 + 0.5
    n_extra = LENS_MODELS[lens_model]
    p = np.zeros(NP + n_extra)
    m = min(len(prior_params), len(p))
    p[:m] = np.asarray(prior_params, float)[:m]
    npm = len(p)
    pos = tmpl.positions()
    fixed_lines = [i for i in range(len(tmpl.lines)) if i not in tmpl.free_idx]

    dx, dy = coarse_shift(th, p, tmpl, pos)
    p[1] += dx
    p[2] += dy
    log(f"coarse shift: {dx:+d}, {dy:+d} px")

    if lens_model == "prism" and np.any(p[NP:NP + 3]):
        p = convert_prior(p, tmpl, fixed_rational=True)
    elif len(prior_params) > len(p) and np.any(np.asarray(prior_params)[len(p):]):
        p = convert_prior(np.asarray(prior_params, float), tmpl, n_extra=n_extra)
    fitter = Fitter(tmpl, p, (w, h), fix_focal=fix_focal, fixed_rational=(lens_model == "prism"))
    x = np.concatenate([p, pos[tmpl.free_idx]])

    def stage(radius, lines, rounds=3):
        nonlocal x
        ids, s, uv, _ = detect(th, x[:npm], tmpl, tmpl.positions(x[npm:]), radius, noise, lines)
        if len(ids) < 60:
            raise CalibrationError(f"only {len(ids)} grid points found - is the lid closed, "
                                   "the honeycomb removed and the bed visible?")
        wts = np.ones(len(ids))
        for _ in range(rounds):
            x, res = fitter.fit(x, ids, s, uv, wts, f_scale=max(0.7, radius / 8))
            r = res.fun[:len(ids)]
            mad = 1.4826 * np.median(np.abs(r[wts > 0])) + 1e-6
            wts = (np.abs(r) < max(4 * mad, 1.0)).astype(float)
            s = tmpl.along(ids, unproject(x[:npm], uv))
        inl = wts > 0
        log(f"radius {radius:>2}px lines {'all' if lines is None else 'inner'}: "
            f"{inl.sum():4d}/{len(ids)} points, rms {np.sqrt(np.mean(r[inl] ** 2)):.3f}px")
        return ids, s, uv, inl

    # A: inner lines only (well inside the image, prior is good there)
    for radius in (40, 20, 10):
        stage(radius, fixed_lines)
    # B: place every border line by a 1-D scan along its whole length
    for li in tmpl.free_idx:
        pos = tmpl.positions(x[npm:])
        pos[li] = scan_free_line(th, x[:npm], tmpl, pos, li, FREE_RANGE_MM, noise)
        x[npm + tmpl.free_idx.index(li)] = pos[li]
    log("border lines: " + ", ".join(f"{tmpl.positions(x[npm:])[i]:.2f}" for i in tmpl.free_idx))
    # C: everything together, coarse to fine
    for radius in (16, 10, 6, 4):
        ids, s, uv, inl = stage(radius, None)

    p = x[:npm]
    pos = tmpl.positions(x[npm:])
    r = fitter.residuals(x, ids, s, uv, np.ones(len(ids)))[:len(ids)]
    per_line = np.bincount(ids[inl], minlength=len(tmpl.lines))
    expected = np.bincount(tmpl.sample_params()[0], minlength=len(tmpl.lines))
    return {
        "params": p,
        "positions": pos,
        "rms_px": float(np.sqrt(np.mean(r[inl] ** 2))),
        "n_inliers": int(inl.sum()),
        "n_samples": int(len(ids)),
        "coverage": (per_line / np.maximum(expected, 1)).tolist(),
        "samples": (ids, s, uv, inl),
    }


# --------------------------------------------------------------------------- export

def export_matrices(p, tmpl, img_size, margin_mm=5.0):
    """K, D, NewK, WorldMatrix in Falcon Design Space convention."""
    w, h = img_size
    K, D, rv, tv = unpack(p)
    R, _ = cv2.Rodrigues(rv)
    # Choose NewK (same centre, scaled focal) so the whole work area survives undistortion.
    bx = np.r_[np.linspace(-margin_mm, tmpl.W + margin_mm, 60),
               np.full(60, tmpl.W + margin_mm),
               np.linspace(tmpl.W + margin_mm, -margin_mm, 60),
               np.full(60, -margin_mm)]
    by = np.r_[np.full(60, -margin_mm),
               np.linspace(-margin_mm, tmpl.H + margin_mm, 60),
               np.full(60, tmpl.H + margin_mm),
               np.linspace(tmpl.H + margin_mm, -margin_mm, 60)]
    Xc = (R @ np.c_[bx, tmpl.H - by, np.zeros_like(bx)].T).T + tv
    xn = Xc[:, :2] / Xc[:, 2:3]
    f, cx, cy = K[0, 0], K[0, 2], K[1, 2]
    lim = []
    for v, c, size in ((xn[:, 0], cx, w), (xn[:, 1], cy, h)):
        pos_side = v > 1e-9
        neg_side = v < -1e-9
        if pos_side.any():
            lim.append(((size - 1 - c) / (f * v[pos_side])).min())
        if neg_side.any():
            lim.append((c / (-f * v[neg_side])).min())
    alpha = min(1.0, min(lim)) if lim else 1.0
    NK = np.array([[f * alpha, 0, cx], [0, f * alpha, cy], [0, 0, 1.0]])
    Hp = NK @ np.c_[R[:, 0], R[:, 1], tv]
    Wm = np.diag([tmpl.ppm, tmpl.ppm, 1.0]) @ np.linalg.inv(Hp)
    Wm /= Wm[2, 2]
    return K, D, NK, Wm


def bed_view(image, K, D, NK, Wm, tmpl):
    """What Falcon Design Space will show as canvas background (top = back of the machine)."""
    und = cv2.undistort(image, K, D, None, NK)
    out = cv2.warpPerspective(und, Wm, (int(tmpl.W * tmpl.ppm), int(tmpl.H * tmpl.ppm)))
    return cv2.flip(out, 0)


def mapping_difference(p_new, K0, D0, NK0, W0, tmpl, step=10.0):
    """Max/mean disagreement (mm) between a new model and an existing app calibration."""
    xs, ys = np.meshgrid(np.arange(step, tmpl.W, step), np.arange(step, tmpl.H, step))
    canvas = np.c_[xs.ravel(), ys.ravel()]
    uv = project(p_new, np.c_[canvas[:, 0], tmpl.H - canvas[:, 1]])
    und = undistort_pixels(uv, K0, D0, NK0)
    hw = cv2.perspectiveTransform(und.reshape(-1, 1, 2), W0).reshape(-1, 2) / tmpl.ppm
    old = np.c_[hw[:, 0], tmpl.H - hw[:, 1]]
    d = np.linalg.norm(old - canvas, axis=1)
    return float(d.max()), float(d.mean()), float(np.median(d))


def camera_height(p):
    _, _, rv, tv = unpack(p)
    R, _ = cv2.Rodrigues(rv)
    return float((-R.T @ tv)[2])


def straightness_check(p, tmpl, img_size, K, D, NK, Wm):
    """Re-detect nothing: just measure how straight template lines are in the exported bed view
    (sanity check of the export path, should be ~0)."""
    pos = tmpl.positions()
    ids, s = tmpl.sample_params(pos)
    uv = project(p, tmpl.world(ids, s, pos))
    und = undistort_pixels(uv, K, D, NK)
    hw = cv2.perspectiveTransform(und.reshape(-1, 1, 2), Wm).reshape(-1, 2) / tmpl.ppm
    world = tmpl.world(ids, s, pos)
    return float(np.abs(hw - world).max())


# --------------------------------------------------------------------------- visualisation

def draw_overlay(image, p, tmpl, result=None, pos=None):
    """Raw image with the fitted grid (green) and detections (cyan inliers, red outliers)."""
    out = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    pos = tmpl.positions() if pos is None else pos
    is_v = tmpl.kinds()
    vpos, hpos = pos[is_v], pos[~is_v]
    for i, (kind, _, _) in enumerate(tmpl.lines):
        lo, hi = (hpos.min(), hpos.max()) if kind == "v" else (vpos.min(), vpos.max())
        s = np.linspace(lo, hi, 200)
        uv = project(p, tmpl.world(np.full(len(s), i), s, pos))
        cv2.polylines(out, [np.round(uv * 4).astype(np.int32)], False, (0, 255, 0), 2, cv2.LINE_AA, shift=2)
    if result is not None:
        ids, s, uv, inl = result["samples"]
        for (u, v), ok in zip(uv, inl):
            cv2.circle(out, (int(round(u)), int(round(v))), 4, (255, 255, 0) if ok else (0, 0, 255), -1)
    return out
