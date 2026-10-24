#!/usr/bin/env python3
"""Full release build: tests -> calibration tool -> patcher -> Inno Setup installer (dist/)."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISCC_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
]


def version():
    with open(os.path.join(ROOT, "tools", "patcher.py"), encoding="utf-8") as f:
        return re.search(r'VERSION = "([^"]+)"', f.read()).group(1)


def main():
    py = sys.executable
    subprocess.check_call([py, "-m", "pytest", "-q", os.path.join(ROOT, "tests")])
    subprocess.check_call([py, os.path.join(ROOT, "tools", "make_icon.py"),
                           os.path.join(ROOT, "installer", "falconmods.ico")])
    if "--skip-exe" not in sys.argv:
        subprocess.check_call([py, os.path.join(ROOT, "tools", "build_tool.py")])
    iscc = next((p for p in ISCC_CANDIDATES if os.path.isfile(p)), None)
    if not iscc:
        sys.exit("Inno Setup 6 not found (https://jrsoftware.org/isinfo.php)")
    subprocess.check_call([iscc, f"/DAppVer={version()}", os.path.join(ROOT, "installer", "FalconMods.iss")])
    print("installer:", os.path.join(ROOT, "dist", f"FalconMods-Setup-{version()}.exe"))


if __name__ == "__main__":
    main()
