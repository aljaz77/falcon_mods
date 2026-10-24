#!/usr/bin/env python3
"""Build FalconBedGridCalib (PyInstaller, one-folder, windowed) into build/dist/bedgrid."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_patcher():
    """One-file console exe of tools/patcher.py with the (non-dev) patch definitions."""
    stage = os.path.join(ROOT, "build", "patches_stage")
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "patches"), stage,
                    ignore=shutil.ignore_patterns("dev_*", "FalconModsDevHook.qml", "__pycache__"))
    dist = os.path.join(ROOT, "build", "dist")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--console", "--onefile",
        "--name", "FalconModsPatcher", "--icon", os.path.join(ROOT, "installer", "falconmods.ico"),
        "--paths", os.path.join(ROOT, "tools"),
        "--add-data", stage + os.pathsep + "patches",
        "--exclude-module", "numpy", "--exclude-module", "cv2", "--exclude-module", "scipy",
        "--exclude-module", "tkinter",
        "--distpath", dist, "--workpath", os.path.join(ROOT, "build", "work_patcher"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "tools", "patcher.py"),
    ])
    print("built", os.path.join(dist, "FalconModsPatcher.exe"))


def main():
    dist = os.path.join(ROOT, "build", "dist")
    shutil.rmtree(os.path.join(dist, "bedgrid"), ignore_errors=True)
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", "FalconBedGridCalib",
        "--paths", os.path.join(ROOT, "calib"),
        "--add-data", os.path.join(ROOT, "calib", "falcon_bedgrid", "templates") + os.pathsep + "falcon_bedgrid/templates",
        "--exclude-module", "scipy", "--exclude-module", "matplotlib", "--exclude-module", "pandas",
        "--exclude-module", "PIL", "--exclude-module", "IPython",
        "--distpath", dist, "--workpath", os.path.join(ROOT, "build", "work"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "calib", "FalconBedGridCalib.py"),
    ]
    icon = os.path.join(ROOT, "installer", "falconmods.ico")
    if os.path.isfile(icon):
        args[3:3] = ["--icon", icon]
    subprocess.check_call(args)
    os.replace(os.path.join(dist, "FalconBedGridCalib"), os.path.join(dist, "bedgrid"))
    # video I/O is not used; drop the 30 MB FFmpeg plugin
    cv2dir = os.path.join(dist, "bedgrid", "_internal", "cv2")
    for name in os.listdir(cv2dir):
        if name.startswith("opencv_videoio_ffmpeg"):
            os.remove(os.path.join(cv2dir, name))
    print("built", os.path.join(dist, "bedgrid"))


if __name__ == "__main__":
    if "--patcher-only" not in sys.argv:
        main()
    if "--tool-only" not in sys.argv:
        build_patcher()
