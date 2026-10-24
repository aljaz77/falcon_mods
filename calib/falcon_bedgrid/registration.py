"""Keep the laser registration of each machine across bed-grid calibrations.

The bed grid gives lens distortion and camera pose very precisely, but *where the printed grid sits
in laser coordinates* differs a little from machine to machine (and the template was measured on
one A1). Falcon Design Space's own calibrations - factory, or the "Camera Alignment" step that
engraves markers and uses them - are tied to the laser. So whenever the app's current
calibration is not the one this tool wrote last, we measure the grid lines *through that
calibration* and remember their laser positions for this machine ("learned template").
"""
import datetime
import json
import os

import numpy as np

from . import config_io, core

APP_CAMERA_HEIGHT_MM = 180.0       # Falcon Design Space's fixed value for height compensation
APP_DEFAULT_THICKNESS_MM = 7.0     # what the app uses when the stored Thickness is 0
MAX_LEARNED_SHIFT_MM = 4.0         # ignore learned positions further than this from the template


def _state_dir():
    d = os.path.join(config_io.app_data_dir(), "falconmods")
    os.makedirs(d, exist_ok=True)
    return d


def _safe(device):
    return "".join(ch for ch in str(device or "default") if ch.isalnum() or ch in "-_") or "default"


def effective_newk(NK, thickness, height=0.0):
    """NewCameraMatrix as the app applies it for a processing height (verified experimentally)."""
    t_cal = thickness if thickness and thickness > 0 else APP_DEFAULT_THICKNESS_MM
    s = (APP_CAMERA_HEIGHT_MM - height) / (APP_CAMERA_HEIGHT_MM - t_cal)
    NKe = np.array(NK, float).copy()
    NKe[0, 0] *= s
    NKe[1, 1] *= s
    return NKe


def app_model(conf, ppm, size):
    """Camera model equivalent to what the app shows at processing height 0 for a config entry."""
    m = config_io.matrices(conf)
    if m is None:
        return None
    K, D, NK, W = m
    return core.params_from_config(K, D, effective_newk(NK, conf.get("Thickness", 0)), W, ppm, size)


# ----------------------------------------------------------------------------- state files

def record_applied(device, W):
    path = os.path.join(_state_dir(), "applied.json")
    try:
        with open(path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st[_safe(device)] = {"W": [float(v) for v in np.ravel(W)],
                         "time": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(path, "w") as f:
        json.dump(st, f, indent=1)


def written_by_us(device, W):
    try:
        with open(os.path.join(_state_dir(), "applied.json")) as f:
            rec = json.load(f).get(_safe(device))
    except (OSError, ValueError):
        return False
    if not rec:
        return False
    a, b = np.array(rec["W"]), np.ravel(W)
    return a.shape == b.shape and np.allclose(a, b, rtol=1e-7, atol=1e-9)


def _template_path(device):
    return os.path.join(_state_dir(), f"template_{_safe(device)}.json")


def load_learned(device):
    try:
        with open(_template_path(device)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_learned(device, positions, source):
    with open(_template_path(device), "w") as f:
        json.dump({"positions": positions, "source": source,
                   "time": datetime.datetime.now().isoformat(timespec="seconds")}, f, indent=1)


# ----------------------------------------------------------------------------- learning

def learn_positions(image, p_app, tmpl):
    """Measure the inner grid lines through the app's current calibration -> laser positions."""
    th = core.ridge_image(image)
    noise = float(np.median(np.abs(th - np.median(th)))) * 1.4826 + 0.5
    pos = tmpl.positions()
    inner = [i for i in range(len(tmpl.lines)) if i not in tmpl.free_idx]
    ids, s, uv, _ = core.detect(th, p_app, tmpl, pos, 14, noise, inner)
    world = core.unproject(p_app, uv)
    is_v = tmpl.kinds()
    learned = {}
    expected = np.bincount(tmpl.sample_params()[0], minlength=len(tmpl.lines))
    for i in inner:
        m = ids == i
        if m.sum() < 0.4 * expected[i]:
            return None
        vals = world[m, 0] if is_v[i] else tmpl.H - world[m, 1]
        learned[i] = float(np.median(vals))
    return learned


def apply_registration(tmpl, device, image, conf, size, log=print):
    """Return (template, description). Learns from a foreign calibration, else reuses what we learned."""
    nominal = tmpl.positions()
    learned_pos, source = None, None
    m = config_io.matrices(conf) if conf else None
    if m is not None and not written_by_us(device, m[3]):
        p_app = app_model(conf, tmpl.ppm, size)
        got = learn_positions(image, p_app, tmpl)
        if got and all(abs(v - nominal[i]) <= MAX_LEARNED_SHIFT_MM for i, v in got.items()):
            learned_pos = got
            source = f"learned from the app's current calibration (saved {conf.get('SaveTime', '?')})"
            save_learned(device, {str(k): v for k, v in got.items()}, source)
            log("registration: " + source + ": " +
                ", ".join(f"{tmpl.lines[i][0]}{nominal[i]:.1f}->{v:.2f}" for i, v in got.items()))
        elif got:
            log("registration: learned positions too far from the template, ignored: " + str(got))
    if learned_pos is None:
        st = load_learned(device)
        if st:
            learned_pos = {int(k): v for k, v in st["positions"].items()}
            source = st.get("source", "learned earlier")
            log("registration: using " + source)
    if learned_pos is None:
        return tmpl, "template default"
    t = core.Template(tmpl.raw)
    for i, v in learned_pos.items():
        t.lines[i][1] = v
    return t, source
