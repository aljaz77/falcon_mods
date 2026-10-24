"""File-based job protocol between the Falcon Design Space UI (QML) and this helper.

QML can start the helper (falconbedgrid:// URL) but cannot read files, only load QML and images.
So every request carries a token and the helper publishes its answer as a folder
    %LOCALAPPDATA%/Falcon Design Space/falconmods/jobs/<token>/
        result.qml      QtObject { property var result: {...} }   <- loaded with a Loader
        *.jpg           images for the page
        pending.json    (calibrate) matrices waiting for "apply"
The folder is assembled as <token>.tmp and renamed, so it appears complete. A fresh folder per
job also avoids Qt's directory-listing cache ("File name case mismatch" for files that appear
later in a folder Qt has already listed).
"""
import json
import os
import re
import shutil
import time

from . import config_io

TOKEN_RE = re.compile(r"[A-Za-z0-9]{6,40}")
MAX_AGE_S = 2 * 3600


def jobs_dir():
    d = os.path.join(config_io.app_data_dir(), "falconmods", "jobs")
    os.makedirs(d, exist_ok=True)
    return d


def valid_token(token):
    return bool(token and TOKEN_RE.fullmatch(token))


def job_path(token):
    return os.path.join(jobs_dir(), token)


def input_image(token):
    """Image the UI saved for a job (alignment photo). The app's image folder always exists,
    so QImage::save from QML can't fail on a missing folder."""
    return os.path.join(config_io.app_data_dir(), "image", f"falconmods_align_{token}.jpg")


def cleanup():
    now = time.time()
    for name in os.listdir(jobs_dir()):
        p = os.path.join(jobs_dir(), name)
        try:
            if now - os.path.getmtime(p) > 24 * 3600:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        except OSError:
            pass


def result_qml(result):
    # json is valid JavaScript; wrap in parentheses so "{...}" is an object, not a block
    return ("import QtQuick 2.15\n"
            "QtObject {\n"
            "    property var result: (" + json.dumps(result, ensure_ascii=True) + ")\n"
            "}\n")


def publish(token, result, images=None, pending=None):
    """images: {filename: encoded bytes}."""
    final = job_path(token)
    tmp = final + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for name, data in (images or {}).items():
        with open(os.path.join(tmp, name), "wb") as f:
            f.write(data)
    if pending is not None:
        with open(os.path.join(tmp, "pending.json"), "w") as f:
            json.dump(pending, f)
    with open(os.path.join(tmp, "result.qml"), "w", encoding="utf-8") as f:
        f.write(result_qml(result))
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)


def load_pending(token):
    p = os.path.join(job_path(token), "pending.json")
    if not os.path.isfile(p) or time.time() - os.path.getmtime(p) > MAX_AGE_S:
        return None
    with open(p) as f:
        return json.load(f)
