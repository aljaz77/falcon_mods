"""Entry point.

    FalconBedGridCalib.exe                          GUI, uses the latest camera capture
    FalconBedGridCalib.exe --image PATH [--apply]   CLI
    FalconBedGridCalib.exe "falconbedgrid://<action>?token=T&..."
                                                    launched from Falcon Design Space (URL protocol):
        calibrate?token=T&device=ID&image=10   headless bed-grid calibration -> jobs/T/
        apply?token=T                          close the app, write job T's calibration, relaunch
        markers?token=T                        find the alignment markers in jobs/align_T.jpg
        calibrate?device=ID&image=10           (no token, FalconMods 1.0) stand-alone window
"""
import argparse
import datetime
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse

from . import appctl, config_io, core, jobs, markers, pipeline

URL_SCHEME = "falconbedgrid"


def mods_dir():
    d = os.path.join(config_io.app_data_dir(), "falconmods")
    os.makedirs(d, exist_ok=True)
    return d


class Log:
    def __init__(self):
        self.path = os.path.join(mods_dir(), "bedgrid.log")

    def __call__(self, msg):
        line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        if sys.stdout:
            try:
                print(line, flush=True)
            except Exception:  # noqa: BLE001 - windowed builds have no usable console
                pass


def parse_url(url):
    """Only accept harmless, well-formed parameters: the URL can come from anywhere."""
    u = urllib.parse.urlparse(url)
    if u.scheme.lower() != URL_SCHEME:
        raise ValueError("bad scheme")
    q = urllib.parse.parse_qs(u.query)

    def get(key, pattern, default=None):
        v = q.get(key, [None])[0]
        return v if v is not None and re.fullmatch(pattern, v) else default

    image = get("image", r"\d{1,3}", "10")
    action = (u.netloc or u.path.strip("/")).lower()
    return {
        "action": action if action in ("calibrate", "apply", "markers") else "calibrate",
        "token": get("token", jobs.TOKEN_RE.pattern),
        "device": get("device", r"[A-Za-z0-9 _.\-]{1,64}"),
        "image": os.path.join(config_io.app_data_dir(), "image", image + ".jpg"),
    }


# --------------------------------------------------------------------------- headless (in-app UI)

def _jpg(img, quality=88):
    import cv2
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


def headless_calibrate(token, image, device, log):
    try:
        rep = pipeline.run(image, device_id=device, log=log, out_dir=mods_dir())
    except core.CalibrationError as e:
        log(f"job {token}: {e}")
        jobs.publish(token, {"status": "error", "message": str(e)})
        return
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        jobs.publish(token, {"status": "error", "message": f"{type(e).__name__}: {e}"})
        return
    K, D, NK, W = rep["_matrices"]
    det, bed = rep["_job_images"]
    result = {
        "status": "ok" if rep["ok"] else "rejected",
        "message": "; ".join(rep["problems"]),
        "rmsPx": round(rep["rms_px"], 2),
        "points": rep["points"],
        "coverage": round(rep["coverage_mean"] * 100),
        "registration": rep.get("registration", ""),
        "changeMedianMm": round(rep["change_vs_old_mm"]["median"], 2) if "change_vs_old_mm" in rep else None,
        "changeMaxMm": round(rep["change_vs_old_mm"]["max"], 2) if "change_vs_old_mm" in rep else None,
        "detectImage": "detect.jpg",
        "bedImage": "bed.jpg",
    }
    pending = None
    if rep["ok"]:
        pending = {"K": K.tolist(), "D": [float(v) for v in D], "NK": NK.tolist(), "W": W.tolist(),
                   "device": rep.get("device") or device, "config_path": rep["config_path"]}
    jobs.publish(token, result, {"detect.jpg": _jpg(det), "bed.jpg": _jpg(bed)}, pending)
    log(f"job {token}: calibration {result['status']}")


def headless_apply(token, log):
    import numpy as np
    pend = jobs.load_pending(token)
    if not pend:
        log(f"job {token}: nothing to apply (unknown or expired job)")
        return
    rep = {"_matrices": tuple(np.array(pend[k], float) for k in ("K", "D", "NK", "W")),
           "config_path": pend["config_path"], "device": pend["device"]}
    try:
        apply_report(rep, pend["device"], log)
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())


def headless_markers(token, log):
    import cv2
    path = jobs.input_image(token)
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        jobs.publish(token, {"status": "error", "message": "the alignment photo could not be read"})
        return
    try:
        res = markers.detect(img)
    except markers.MarkerError as e:
        log(f"job {token}: {e}")
        jobs.publish(token, {"status": "error", "message": str(e)})
        return
    vis = img.copy()
    for i, (x, y) in enumerate(res["points"]):
        r = int(res["radius_px"])
        cv2.circle(vis, (int(round(x)), int(round(y))), r, (18, 209, 235), 3, cv2.LINE_AA)
        cv2.putText(vis, str(i + 1), (int(x + r * 0.8), int(y - r * 0.8)), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                    (18, 209, 235), 4, cv2.LINE_AA)
    log(f"job {token}: markers {[[round(v, 1) for v in pt] for pt in res['points']]}")
    jobs.publish(token, {"status": "ok", "points": res["points"], "imageWidth": img.shape[1],
                         "imageHeight": img.shape[0], "lineRmsPx": round(res["line_rms_px"], 2)},
                 {"markers.jpg": _jpg(vis)})


def apply_report(rep, device, log, on_status=lambda msg: None, wait_s=600):
    """Write a calibration report into cameraConfig.txt.

    Falcon Design Space writes its in-memory calibration back to the file when it exits, so if it
    is running it is closed politely first (it may ask to save the project) and started again
    afterwards. Returns the exe that was relaunched (or None)."""
    pids = appctl.running_pids()
    exe = appctl.exe_path(pids[0]) if pids else None
    if pids:
        on_status("Waiting for Falcon Design Space to close... (answer its save prompt if it shows one)")
        log(f"closing Falcon Design Space (pids {pids})")
        for pid in pids:
            appctl.request_close(pid)
        if not appctl.wait_exit(pids, wait_s):
            raise RuntimeError("Falcon Design Space did not close")
        time.sleep(1.0)
    K, D, NK, W = rep["_matrices"]
    path = rep["config_path"]
    # Re-read: the app saved its own state on exit; merge into that.
    cfg = config_io.load(path) if os.path.isfile(path) else {"Calibration Data": [], "version": "1.10.0"}
    dev_id = device or rep.get("device")
    dev = config_io.find_device(cfg, dev_id, "Creality Falcon A1")
    conf = config_io.find_config(dev) if dev else None
    pipeline.write_config(cfg, path, dev, conf, dev_id, "Creality Falcon A1", K, D, NK, W)
    log(f"applied calibration to {path}")
    if exe:
        appctl.launch(exe)
        log(f"restarted {exe}")
    return exe


# --------------------------------------------------------------------------- GUI

def gui(image=None, device=None, log=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    import cv2

    log = log or Log()
    root = tk.Tk()
    root.title("Falcon Bed-Grid Camera Calibration")
    BG, TEXT, MUTED, OK, BAD = "#FFFFFF", "#1D2129", "#4E5969", "#00A146", "#CB2634"
    root.configure(bg=BG)
    try:
        root.state("zoomed")
    except tk.TclError:
        root.geometry("1400x900")
    state = {"report": None, "photo": None, "done": False}

    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=12, pady=8)
    status = tk.Label(top, text="", fg=TEXT, bg=BG, font=("Segoe UI", 11), anchor="w", justify="left")
    status.pack(side="left", fill="x", expand=True)
    btns = tk.Frame(top, bg=BG)
    btns.pack(side="right")
    style = dict(font=("Segoe UI", 10), relief="flat", bd=0, padx=18, pady=7, cursor="hand2")
    apply_btn = tk.Button(btns, text="Apply calibration", state="disabled", bg=TEXT, fg="white",
                          activebackground="#4E5969", activeforeground="white", disabledforeground="#C9CDD4", **style)
    open_btn = tk.Button(btns, text="Open image...", bg="#F2F3F5", fg=TEXT, activebackground="#E5E6EB", **style)
    close_btn = tk.Button(btns, text="Close", bg="#F2F3F5", fg=TEXT, activebackground="#E5E6EB", **style)
    for b in (open_btn, apply_btn, close_btn):
        b.pack(side="left", padx=5)
    tk.Frame(root, bg="#12D1EB", height=2).pack(fill="x", padx=12)
    canvas = tk.Label(root, bg="#F2F3F5")
    canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def show_preview():
        rep = state["report"]
        if rep is None:
            return
        img = rep["_preview"]
        w = max(400, canvas.winfo_width() - 4)
        h = max(300, canvas.winfo_height() - 4)
        s = min(w / img.shape[1], h / img.shape[0], 1.0)
        small = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        _, png = cv2.imencode(".png", small)
        state["photo"] = tk.PhotoImage(data=png.tobytes())
        canvas.configure(image=state["photo"])

    def finished(rep, err):
        if err:
            status.configure(text="Calibration failed:\n" + err, fg=BAD)
            return
        state["report"] = rep
        txt = (f"Fit error {rep['rms_px']:.2f} px · {rep['points']} grid points · "
               f"grid found {rep['coverage_mean']:.0%}")
        if "change_vs_old_mm" in rep:
            c = rep["change_vs_old_mm"]
            txt += f"\nDifference to the previous calibration: median {c['median']:.2f} mm, max {c['max']:.2f} mm"
        if rep["ok"]:
            txt = "✔ Calibration looks good. Check that the bed view on the right is straight, then click Apply.\n" + txt
            apply_btn.configure(state="normal")
            status.configure(text=txt, fg=OK)
        else:
            status.configure(text="✖ Rejected: " + "; ".join(rep["problems"]) + "\n" + txt +
                             "\nClose the lid, remove the honeycomb panel and loose items, then capture again.",
                             fg=BAD)
        show_preview()

    def start(path):
        apply_btn.configure(state="disabled")
        state["report"] = None
        canvas.configure(image="")
        status.configure(text=f"Calibrating from {path} ...", fg=MUTED)

        def work():
            try:
                log(f"calibrate image={path} device={device}")
                age = time.time() - os.path.getmtime(path)
                if age > 600:
                    log(f"warning: image is {age / 60:.0f} minutes old")
                rep = pipeline.run(path, device_id=device, log=log, out_dir=mods_dir())
                root.after(0, finished, rep, None)
            except core.CalibrationError as e:
                log(f"error: {e}")
                root.after(0, finished, None, str(e))
            except Exception as e:  # noqa: BLE001
                log(traceback.format_exc())
                root.after(0, finished, None, f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    def finish(exe, err=None):
        if err:
            status.configure(text="Could not save the calibration: " + err, fg=BAD)
            apply_btn.configure(state="normal")
            return
        state["done"] = True
        msg = "✔ Calibration saved (the old file is backed up in conf\\camera\\falconmods_backups)."
        if exe:
            msg += "\nFalcon Design Space is starting again with the new calibration."
            root.after(4000, root.destroy)
        else:
            msg += "\nStart Falcon Design Space to use it."
        status.configure(text=msg, fg=OK)

    def do_apply():
        rep = state["report"]
        if not rep or not rep["ok"]:
            return
        pids = appctl.running_pids()
        if pids and not messagebox.askokcancel(
                "Falcon Bed-Grid Calibration",
                "Falcon Design Space has to restart to load the new calibration.\n\n"
                "It will be closed now (it may ask you to save your project), the calibration "
                "is written, and it is started again."):
            return
        apply_btn.configure(state="disabled")

        def work():
            try:
                exe = apply_report(rep, device, log,
                                   lambda m: root.after(0, lambda: status.configure(text=m, fg=MUTED)))
                root.after(0, finish, exe)
            except Exception as e:  # noqa: BLE001
                log(traceback.format_exc())
                root.after(0, finish, None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def do_open():
        p = filedialog.askopenfilename(initialdir=os.path.join(config_io.app_data_dir(), "image"),
                                       filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp")])
        if p:
            start(p)

    apply_btn.configure(command=do_apply)
    open_btn.configure(command=do_open)
    close_btn.configure(command=root.destroy)
    canvas.bind("<Configure>", lambda e: show_preview())

    if image is None:
        cand = os.path.join(config_io.app_data_dir(), "image", "10.jpg")
        image = cand if os.path.isfile(cand) else None
    if image:
        root.after(200, start, image)
    else:
        status.configure(text="Take a camera photo in Falcon Design Space (lid closed, bed empty), "
                              "then use 'Open image...'.")
    root.mainloop()


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    log = Log()
    if argv and argv[0].lower().startswith(URL_SCHEME + ":"):
        try:
            a = parse_url(argv[0])
        except ValueError:
            return 2
        jobs.cleanup()
        if a["token"] and a["action"] == "calibrate":
            headless_calibrate(a["token"], a["image"], a["device"], log)
        elif a["token"] and a["action"] == "apply":
            headless_apply(a["token"], log)
        elif a["token"] and a["action"] == "markers":
            headless_markers(a["token"], log)
        else:
            gui(a["image"], a["device"], log)
        return 0
    ap = argparse.ArgumentParser(prog="FalconBedGridCalib")
    ap.add_argument("--image")
    ap.add_argument("--config")
    ap.add_argument("--device")
    ap.add_argument("--template", default="falcon_a1")
    ap.add_argument("--apply", action="store_true", help="write the calibration if it passes the checks "
                                                         "(restarts Falcon Design Space if it is running)")
    ap.add_argument("--free-focal", action="store_true", help="also fit the focal length (ill-conditioned)")
    ap.add_argument("--lens-model", default=core.DEFAULT_LENS_MODEL, choices=["5", "8", "12", "prism"],
                    help="distortion model (default: prism = 5 terms + thin prism)")
    ap.add_argument("--out", help="directory for preview/report")
    ap.add_argument("--cli", action="store_true", help="no window")
    a = ap.parse_args(argv)
    if a.image is None and (a.cli or a.apply or a.out):
        a.image = os.path.join(config_io.app_data_dir(), "image", "10.jpg")
    if not a.cli and not a.apply and a.out is None:
        gui(a.image, a.device, log)
        return 0
    try:
        rep = pipeline.run(a.image, a.config, a.device, template=a.template, fix_focal=not a.free_focal,
                           out_dir=a.out, log=log,
                           lens_model=a.lens_model if a.lens_model == "prism" else int(a.lens_model))
    except core.CalibrationError as e:
        log(f"FAILED: {e}")
        return 1
    log(json.dumps({k: v for k, v in rep.items() if not k.startswith("_")}, indent=2))
    if not rep["ok"]:
        return 1
    if a.apply:
        if a.config:
            pipeline.write_config_for(rep, a.device)
        else:
            apply_report(rep, a.device, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
