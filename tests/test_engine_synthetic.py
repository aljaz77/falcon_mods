"""Render a bed grid through a known (strongly distorted) camera, then recover it."""
import cv2
import numpy as np
import pytest

from falcon_bedgrid import core, pipeline

SIZE = (2592, 1944)


def true_params():
    # roughly the Falcon A1 lid camera: looking down from ~200 mm, wide-angle lens
    R = cv2.Rodrigues(np.array([np.pi, 0.0, 0.0]))[0] @ cv2.Rodrigues(np.array([0.06, -0.02, 0.01]))[0]
    rv = cv2.Rodrigues(R)[0].ravel()
    C = np.array([195.0, 140.0, 205.0])  # camera centre in world mm
    t = -R @ C
    return np.array([1110.0, 1230.0, 960.0, -0.29, 0.09, -0.004, 0.0006, -0.012, *rv, *t])


def render(p, tmpl, seed=0):
    rng = np.random.default_rng(seed)
    h, w = SIZE[1], SIZE[0]
    yy, xx = np.mgrid[0:h, 0:w]
    img = (25 + 30 * np.exp(-(((xx - 1300) / 900.0) ** 2 + ((yy - 1300) / 500.0) ** 2))).astype(np.float32)
    pos = tmpl.positions()
    is_v = tmpl.kinds()
    vpos, hpos = pos[is_v], pos[~is_v]
    for i, (kind, _, _) in enumerate(tmpl.lines):
        lo, hi = (hpos.min(), hpos.max()) if kind == "v" else (vpos.min(), vpos.max())
        s = np.arange(lo, hi, 0.25)
        uv = core.project(p, tmpl.world(np.full(len(s), i), s, pos))
        width = 10 if i in tmpl.free_idx else 6
        cv2.polylines(img, [np.round(uv * 16).astype(np.int32)], False, 200.0, width, cv2.LINE_AA, shift=4)
    img += rng.normal(0, 3, img.shape).astype(np.float32)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


@pytest.fixture(scope="module")
def setup():
    tmpl = pipeline.load_template("falcon_a1")
    p = true_params()
    return tmpl, p, render(p, tmpl)


def mapping_error_mm(p_est, p_true, tmpl):
    """Max distance between where the two models think bed points are (raw pixel -> bed)."""
    xs, ys = np.meshgrid(np.arange(10, tmpl.W, 15.0), np.arange(10, tmpl.H, 15.0))
    world = np.c_[xs.ravel(), tmpl.H - ys.ravel()]
    uv = core.project(p_true, world)
    back = core.unproject(p_est, uv)
    return float(np.linalg.norm(back - world, axis=1).max())


def test_recovers_mapping_from_perturbed_prior(setup):
    tmpl, p, img = setup
    prior = p.copy()
    prior[1] += 25
    prior[2] -= 18
    prior[3] *= 0.8
    prior[4] *= 1.3
    prior[11] += 4.0
    res = core.calibrate(img, prior, tmpl, log=lambda m: None)
    assert res["rms_px"] < 0.8
    assert min(res["coverage"]) > 0.8
    assert mapping_error_mm(res["params"], p, tmpl) < 0.5


def test_export_roundtrip_matches_model(setup):
    tmpl, p, _ = setup
    K, D, NK, W = core.export_matrices(p, tmpl, SIZE)
    assert core.straightness_check(p, tmpl, SIZE, K, D, NK, W) < 1e-6
    back = core.params_from_config(K, D, NK, W, tmpl.ppm, SIZE)
    assert mapping_error_mm(back, p, tmpl) < 1e-3


def test_rejects_image_without_grid():
    tmpl = pipeline.load_template("falcon_a1")
    blank = np.full((SIZE[1], SIZE[0], 3), 30, np.uint8)
    with pytest.raises(core.CalibrationError):
        core.calibrate(blank, true_params(), tmpl, log=lambda m: None)


def test_recovers_thin_prism_lens():
    tmpl = pipeline.load_template("falcon_a1")
    p = np.r_[true_params(), 0, 0, 0, 0.004, -0.0015, -0.003, 0.002]  # k4-k6, s1-s4
    img = render(p, tmpl, seed=3)
    prior = true_params()
    prior[1] += 15
    res5 = core.calibrate(img, prior, tmpl, log=lambda m: None, lens_model=5)
    resp = core.calibrate(img, prior, tmpl, log=lambda m: None, lens_model="prism")
    assert mapping_error_mm(resp["params"], p, tmpl) < 0.5
    assert mapping_error_mm(resp["params"], p, tmpl) < mapping_error_mm(res5["params"], p, tmpl)


def test_convert_prior_from_rational():
    tmpl = pipeline.load_template("falcon_a1")
    base = true_params()
    # a rational model equivalent-ish to the base lens
    src = np.r_[base, -0.1, 0.02, 0.0, 0, 0, 0, 0]
    conv = core.convert_prior(src, tmpl, fixed_rational=True)
    assert np.allclose(conv[core.NP:core.NP + 3], 0)
    assert mapping_error_mm(conv, src, tmpl) < 0.3
