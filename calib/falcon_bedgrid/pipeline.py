"""High level: image + existing config -> new calibration, report and preview image."""
import json
import os
import sys

import cv2
import numpy as np

from . import config_io, core, registration

# Quality gate
MAX_RMS_PX = 1.6
MIN_LINE_COVERAGE = 0.35      # every line must be found along at least this fraction
MIN_TOTAL_COVERAGE = 0.6
MAX_BORDER_SHIFT_MM = 10.0    # fitted border vs template nominal


def resource_dir():
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


def load_template(name="falcon_a1"):
    path = name if os.path.isfile(name) else os.path.join(resource_dir(), "templates", name + ".json")
    if not os.path.isfile(path):  # frozen layout
        path = os.path.join(resource_dir(), "falcon_bedgrid", "templates", name + ".json")
    with open(path, encoding="utf-8") as f:
        return core.Template(json.load(f))


def default_prior(tmpl, img_size):
    d = tmpl.raw.get("default_prior")
    if d is None:
        raise core.CalibrationError("no existing calibration found and the template has no default")
    return np.array(d, float)


def run(image_path, config_path=None, device_id=None, device_name="Creality Falcon A1",
        template="falcon_a1", fix_focal=True, apply=False, out_dir=None, log=print,
        lens_model=core.DEFAULT_LENS_MODEL):
    """Calibrate. Returns a report dict. Raises core.CalibrationError on failure."""
    tmpl = load_template(template)
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise core.CalibrationError(f"cannot read image {image_path}")
    size = (img.shape[1], img.shape[0])

    config_path = config_path or config_io.default_config_path()
    cfg = config_io.load(config_path) if os.path.isfile(config_path) else {"Calibration Data": [], "version": "1.10.0"}
    dev = config_io.find_device(cfg, device_id, device_name)
    conf = config_io.find_config(dev) if dev else None
    old = config_io.matrices(conf) if conf else None
    if old is not None:
        prior = registration.app_model(conf, tmpl.ppm, size)
        # compare against what the app actually shows at processing height 0
        old = (old[0], old[1], registration.effective_newk(old[2], conf.get("Thickness", 0)), old[3])
        log(f"prior: existing calibration of '{dev.get('ID')}' (saved {conf.get('SaveTime')})")
    else:
        prior = default_prior(tmpl, size)
        log("prior: template default")
    device_key = (dev.get("ID") if dev else None) or device_id or device_name
    tmpl, reg_info = registration.apply_registration(tmpl, device_key, img, conf, size, log=log)

    res = core.calibrate(img, prior, tmpl, log=log, fix_focal=fix_focal, lens_model=lens_model)
    p = res["params"]
    K, D, NK, W = core.export_matrices(p, tmpl, size)

    nominal = tmpl.positions()
    border_shift = float(np.abs(res["positions"] - nominal)[tmpl.free_idx].max()) if tmpl.free_idx else 0.0
    cov = np.array(res["coverage"])
    problems = []
    if res["rms_px"] > MAX_RMS_PX:
        problems.append(f"fit error {res['rms_px']:.2f}px is too high")
    if cov.min() < MIN_LINE_COVERAGE:
        problems.append(f"a grid line was barely found ({cov.min():.0%})")
    if cov.mean() < MIN_TOTAL_COVERAGE:
        problems.append(f"only {cov.mean():.0%} of the grid was found")
    if border_shift > MAX_BORDER_SHIFT_MM - 0.5:
        problems.append("border lines are far from where they should be")

    report = {
        "ok": not problems,
        "problems": problems,
        "rms_px": res["rms_px"],
        "points": res["n_inliers"],
        "coverage_min": float(cov.min()),
        "coverage_mean": float(cov.mean()),
        "line_positions_mm": [round(float(v), 2) for v in res["positions"]],
        "camera_height_mm": core.camera_height(p),
        "focal_px": float(p[0]),
        "lens_model": str(lens_model),
        "dist": [float(v) for v in D],
        "device": dev.get("ID") if dev else device_id,
        "registration": reg_info,
        "config_path": config_path,
        "image": image_path,
        "applied": False,
    }
    if old is not None:
        mx, mean, med = core.mapping_difference(p, *old, tmpl)
        report["change_vs_old_mm"] = {"max": mx, "mean": mean, "median": med}

    preview = make_preview(img, p, tmpl, res, K, D, NK, W, report)
    report["_job_images"] = job_images(img, p, tmpl, res, K, D, NK, W)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        cv2.imwrite(os.path.join(out_dir, "bedgrid_preview.png"), preview)
        with open(os.path.join(out_dir, "bedgrid_report.json"), "w") as f:
            json.dump({k: v for k, v in report.items() if not k.startswith("_")}, f, indent=2)
    report["_preview"] = preview
    report["_matrices"] = (K, D, NK, W)

    if apply:
        if not report["ok"]:
            raise core.CalibrationError("; ".join(problems))
        write_config(cfg, config_path, dev, conf, device_id, device_name, K, D, NK, W)
        report["applied"] = True
        log(f"written {config_path}")
    return report


def write_config_for(rep, device_id=None, device_name="Creality Falcon A1"):
    """Write a report's calibration into its config file (caller makes sure the app is closed)."""
    path = rep["config_path"]
    cfg = config_io.load(path) if os.path.isfile(path) else {"Calibration Data": [], "version": "1.10.0"}
    dev_id = device_id or rep.get("device")
    dev = config_io.find_device(cfg, dev_id, device_name)
    conf = config_io.find_config(dev) if dev else None
    write_config(cfg, path, dev, conf, dev_id, device_name, *rep["_matrices"])


def write_config(cfg, path, dev, conf, device_id, device_name, K, D, NK, W):
    if dev is None:
        dev = config_io.new_device_entry(device_id, device_name, None)
        cfg.setdefault("Calibration Data", []).append(dev)
        conf = dev["camera"][0]["configs"][0]
    elif conf is None:
        dev.setdefault("camera", []).append({"CameraName": config_io.CAMERA_NAME, "configs": [{}]})
        conf = dev["camera"][-1]["configs"][0]
    config_io.apply_calibration(cfg, conf, K, D, NK, W)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config_io.save(cfg, path)
    registration.record_applied(dev.get("ID") or device_id or device_name, W)


def job_images(img, p, tmpl, res, K, D, NK, W):
    """Two clean images for the in-app page: detected grid on the camera photo, and the bed view."""
    ov = core.draw_overlay(img, p, tmpl, res, res["positions"])
    bv = core.bed_view(img, K, D, NK, W, tmpl)
    for x in range(0, int(tmpl.W) + 1, 50):
        cv2.line(bv, (int(x * tmpl.ppm), 0), (int(x * tmpl.ppm), bv.shape[0]), (0, 140, 255), 1, cv2.LINE_AA)  # orange (BGR)
    for y in range(0, int(tmpl.H) + 1, 50):
        cv2.line(bv, (0, int(y * tmpl.ppm)), (bv.shape[1], int(y * tmpl.ppm)), (0, 140, 255), 1, cv2.LINE_AA)  # orange (BGR)
    w = 1400
    ov = cv2.resize(ov, (w, int(ov.shape[0] * w / ov.shape[1])), interpolation=cv2.INTER_AREA)
    bv = cv2.resize(bv, (w, int(bv.shape[0] * w / bv.shape[1])), interpolation=cv2.INTER_AREA)
    return ov, bv


def make_preview(img, p, tmpl, res, K, D, NK, W, report):
    """Side-by-side: detections on the raw image | resulting bed view with a 50 mm check grid."""
    ov = core.draw_overlay(img, p, tmpl, res, res["positions"])
    bv = core.bed_view(img, K, D, NK, W, tmpl)
    for x in range(0, int(tmpl.W) + 1, 50):
        cv2.line(bv, (int(x * tmpl.ppm), 0), (int(x * tmpl.ppm), bv.shape[0]), (255, 0, 255), 1)
    for y in range(0, int(tmpl.H) + 1, 50):
        cv2.line(bv, (0, int(y * tmpl.ppm)), (bv.shape[1], int(y * tmpl.ppm)), (255, 0, 255), 1)
    h = 900
    a = cv2.resize(ov, (int(ov.shape[1] * h / ov.shape[0]), h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(bv, (int(bv.shape[1] * h / bv.shape[0]), h), interpolation=cv2.INTER_AREA)
    canvas = np.full((h + 150, a.shape[1] + b.shape[1] + 10, 3), 30, np.uint8)
    canvas[:h, :a.shape[1]] = a
    canvas[:h, a.shape[1] + 10:] = b
    ok = report["ok"]
    lines = [
        ("CALIBRATION OK" if ok else "CALIBRATION REJECTED: " + "; ".join(report["problems"]),
         (80, 220, 80) if ok else (60, 60, 255)),
        (f"fit error {report['rms_px']:.2f} px   points {report['points']}   grid found "
         f"{report['coverage_mean']:.0%} (min line {report['coverage_min']:.0%})", (230, 230, 230)),
    ]
    if "change_vs_old_mm" in report:
        c = report["change_vs_old_mm"]
        lines.append((f"difference to previous calibration: median {c['median']:.2f} mm, max {c['max']:.2f} mm",
                      (230, 230, 230)))
    for i, (t, col) in enumerate(lines):
        cv2.putText(canvas, t, (20, h + 40 + 38 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2, cv2.LINE_AA)
    cv2.putText(canvas, "detected grid (raw camera)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    cv2.putText(canvas, "bed view, 50 mm grid", (a.shape[1] + 30, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 0, 255), 2)
    return canvas
