"""Read / write Falcon Design Space's camera calibration file (cameraConfig.txt, JSON)."""
import copy
import datetime
import json
import os
import shutil

import numpy as np

CAMERA_NAME = "Creality Falcon Camera"
CALIBRATION_THICKNESS_MM = 0.001


def app_data_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Falcon Design Space")


def default_config_path():
    return os.path.join(app_data_dir(), "conf", "camera", "cameraConfig.txt")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mat(entry):
    return np.array(entry["data"], float).reshape(entry["shape"])


def _put(arr):
    arr = np.atleast_2d(np.asarray(arr, float))
    return {"data": [float(v) for v in arr.ravel()], "rowMajor": True, "shape": list(arr.shape)}


def find_device(cfg, device_id=None, device_name=None):
    """Return the 'Calibration Data' entry for a device (by machine ID, then by name)."""
    data = cfg.get("Calibration Data", [])
    if device_id:
        for d in data:
            if d.get("ID") == device_id or d.get("Device") == device_id:
                return d
    if device_name:
        for d in data:
            if d.get("Device") == device_name or d.get("ID") == device_name:
                return d
    # most recently saved entry
    best, best_t = None, ""
    for d in data:
        for cam in d.get("camera", []):
            for c in cam.get("configs", []):
                if c.get("SaveTime", "") >= best_t:
                    best, best_t = d, c.get("SaveTime", "")
    return best


def find_config(device_entry, camera_name=CAMERA_NAME):
    cams = device_entry.get("camera", [])
    cam = next((c for c in cams if c.get("CameraName") == camera_name), cams[0] if cams else None)
    if cam is None or not cam.get("configs"):
        return None
    return next((c for c in cam["configs"] if c.get("Selected")), cam["configs"][0])


def matrices(conf):
    """(K, D, NewK, WorldMatrix) of a config entry, or None if it is not calibrated."""
    try:
        K, D, NK, W = (_mat(conf[k]) for k in ("IntrinsicMat", "DistCoeffs", "NewCameraMatrix", "WorldMatrix"))
    except (KeyError, ValueError):
        return None
    if not np.any(W) or not np.any(K):
        return None
    return K, D.ravel(), NK, W


def new_device_entry(device_id, device_name, template_conf):
    conf = copy.deepcopy(template_conf) if template_conf else {
        "CalibrationPattern": "CIRCLES", "From": 0, "LaserModule": "10_", "Power": 0, "To": 10,
        "dataVersion": "1.10.0"}
    return {"Device": device_id or device_name, "ID": device_id or device_name,
            "camera": [{"CameraName": CAMERA_NAME, "configs": [conf]}]}


def apply_calibration(cfg, conf, K, D, NK, W):
    conf["IntrinsicMat"] = _put(K)
    conf["DistCoeffs"] = _put(np.ravel(D).reshape(1, -1))
    conf["NewCameraMatrix"] = _put(NK)
    conf["WorldMatrix"] = _put(W)
    # Keep the user's fine-tuning offsets (the template was measured in the same frame).
    conf.setdefault("OffsetX", 0)
    conf.setdefault("OffsetY", 0)
    # The bed plate is the calibration plane. Falcon Design Space treats Thickness == 0 as
    # "unknown" and substitutes 7 mm (verified experimentally), so store a tiny positive value.
    conf["Thickness"] = CALIBRATION_THICKNESS_MM
    conf["IsCalibration"] = True
    conf["IsConfirm"] = True
    conf["IsSave"] = True
    conf["Selected"] = True
    conf["SaveTime"] = datetime.datetime.now().strftime("%Y%m%d%H%M")
    conf.setdefault("CalibrationPattern", "CIRCLES")
    conf.setdefault("dataVersion", cfg.get("version", "1.10.0"))
    conf["FalconModsBedGrid"] = True  # marker so we can tell our calibrations apart


def save(cfg, path, backup=True):
    if backup and os.path.exists(path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bdir = os.path.join(os.path.dirname(path), "falconmods_backups")
        os.makedirs(bdir, exist_ok=True)
        shutil.copy2(path, os.path.join(bdir, f"cameraConfig-{stamp}.txt"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)
