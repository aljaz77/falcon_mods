#!/usr/bin/env python3
"""FalconMods patcher for Falcon Design Space.

    python patcher.py install   [--app DIR] [--patch ID ...]
    python patcher.py uninstall [--app DIR]
    python patcher.py status    [--app DIR]
    python patcher.py build     --app DIR --out DIR      (write patched .rcc files elsewhere)

Reads the *installed* mui/*.rcc, applies the anchored text patches from ../patches,
repacks, and keeps the originals in <app>/falconmods/backup so uninstall is lossless.
Nothing from the vendor is shipped with this tool.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rcc  # noqa: E402

DEFAULT_APP = r"C:\Program Files\Falcon Design Space"
MARK = "FalconMods"


def patches_dir():
    # Frozen builds keep patches next to the executable.
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(HERE)
    return os.path.join(base, "patches")


def load_patch_sets(selected=None, dev=False):
    sets = []
    d = patches_dir()
    for name in sorted(os.listdir(d)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location("patch_" + name[:-3], os.path.join(d, name))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if selected and mod.ID not in selected:
            continue
        if getattr(mod, "DEV", False) and not dev:
            continue
        sets.append(mod)
    return sets


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_app(arg):
    candidates = [arg] if arg else []
    if not arg:
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for root in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                    try:
                        k = winreg.OpenKey(hive, root)
                    except OSError:
                        continue
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                            name = winreg.QueryValueEx(sub, "DisplayName")[0]
                            if "Falcon Design Space" in name:
                                candidates.append(winreg.QueryValueEx(sub, "InstallLocation")[0])
                        except OSError:
                            pass
        except ImportError:
            pass
        candidates.append(DEFAULT_APP)
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "FalconDesignSpace.exe")):
            return os.path.abspath(c)
    print("Falcon Design Space not found (use --app DIR)")
    sys.exit(4)


def state_path(app):
    return os.path.join(app, "falconmods", "state.json")


def read_state(app):
    try:
        with open(state_path(app)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def apply_text_patches(root, sets, log, subs=None):
    """Apply every patch under an extracted rcc tree `root` ({rcc_name: dir})."""
    touched = set()
    for mod in sets:
        for p in mod.PATCHES:
            path = os.path.join(root[p["rcc"]], *p["file"].split("/"))
            if p.get("new_file"):
                if "source" in p:
                    with open(os.path.join(patches_dir(), *p["source"].split("/")), encoding="utf-8") as f:
                        content = f.read()
                else:
                    content = p["content"]
                for k, v in (subs or {}).items():
                    content = content.replace(k, v)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                touched.add(p["rcc"])
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            n = text.count(p["find"])
            expected = p.get("count", 1)
            if n != expected:
                raise RuntimeError(
                    f"[{mod.ID}] anchor found {n}x (expected {expected}) in {p['file']} - "
                    "the app version is probably different from the one this patch was made for")
            text = text.replace(p["find"], p["replace"])
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            touched.add(p["rcc"])
        log(f"  applied {mod.ID}: {mod.DESCRIPTION}")
    return touched


def build(src_mui, out_mui, sets, log=print, subs=None):
    """Extract src rcc files, patch, write patched rcc files into out_mui. Returns names written."""
    names = sorted({p["rcc"] for m in sets for p in m.PATCHES})
    with tempfile.TemporaryDirectory(prefix="falconmods_") as tmp:
        roots = {}
        for n in names:
            roots[n] = os.path.join(tmp, n)
            rcc.cmd_extract(os.path.join(src_mui, n), roots[n])
        touched = apply_text_patches(roots, sets, log, subs)
        os.makedirs(out_mui, exist_ok=True)
        for n in sorted(touched):
            rcc.cmd_pack(roots[n], os.path.join(out_mui, n), compress=True)
    return sorted(touched)


def tool_exe(app):
    return os.path.join(app, "falconmods", "bedgrid", "FalconBedGridCalib.exe")


def substitutions(app):
    return {"@FALCONMODS_TOOL_EXE@": tool_exe(app).replace("\\", "/")}


def clear_qml_cache():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Falcon Design Space", "cache", "qmlcache")
    if os.path.isdir(base):
        shutil.rmtree(base, ignore_errors=True)


def cmd_install(app, selected, log=print, dev=False):
    mui = os.path.join(app, "mui")
    backup = os.path.join(app, "falconmods", "backup")
    state = read_state(app)
    os.makedirs(backup, exist_ok=True)
    sets = load_patch_sets(selected, dev)
    names = sorted({p["rcc"] for m in sets for p in m.PATCHES})
    # Always patch from pristine originals. A file that changed since our install means
    # the app was updated, so the new file becomes the original.
    for n in names:
        cur, bak = os.path.join(mui, n), os.path.join(backup, n)
        if not os.path.exists(bak) or sha256(cur) != state.get("patched", {}).get(n):
            shutil.copy2(cur, bak)
    log(f"Patching {app}")
    written = build(backup, mui, sets, log, substitutions(app))
    state = {
        "version": VERSION,
        "patches": [m.ID for m in sets],
        "patched": {n: sha256(os.path.join(mui, n)) for n in written},
        "original": {n: sha256(os.path.join(backup, n)) for n in written},
    }
    with open(state_path(app), "w") as f:
        json.dump(state, f, indent=2)
    clear_qml_cache()
    log("Done.")


def cmd_uninstall(app, log=print):
    backup = os.path.join(app, "falconmods", "backup")
    state = read_state(app)
    if not os.path.isdir(backup):
        log("Nothing to restore.")
        return
    for n in os.listdir(backup):
        cur = os.path.join(app, "mui", n)
        # Only put the original back if the file is still ours: if Falcon Design Space was
        # updated in the meantime, the current file is already a newer original.
        if os.path.exists(cur) and state.get("patched", {}).get(n) not in (None, sha256(cur)):
            log(f"  {n}: changed by an app update, left as is")
            continue
        shutil.copy2(os.path.join(backup, n), cur)
        log(f"  restored {n}")
    clear_qml_cache()
    try:
        os.remove(state_path(app))
    except OSError:
        pass
    log("Original files restored.")


def cmd_status(app):
    st = read_state(app)
    if not st:
        print("FalconMods not installed in", app)
        return
    print("FalconMods", st.get("version"), "patches:", ", ".join(st.get("patches", [])))
    for n, h in st.get("patched", {}).items():
        ok = sha256(os.path.join(app, "mui", n)) == h
        print(f"  {n}: {'patched' if ok else 'CHANGED (app updated? re-run install)'}")


def app_running():
    import subprocess
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq FalconDesignSpace.exe"],
                         capture_output=True, text=True, creationflags=0x08000000).stdout
    return "falcondesignspace.exe" in out.lower()


VERSION = "1.2.2"

def main(argv=None):
    ap = argparse.ArgumentParser(prog="FalconModsPatcher")
    ap.add_argument("cmd", choices=["install", "uninstall", "status", "check", "build"])
    ap.add_argument("--app", help="Falcon Design Space folder (default: auto-detect)")
    ap.add_argument("--out")
    ap.add_argument("--patch", action="append", help="only this patch id (repeatable)")
    ap.add_argument("--dev", action="store_true", help="also install development-only patches")
    a = ap.parse_args(argv)
    app = find_app(a.app)
    try:
        if a.cmd in ("install", "uninstall") and app_running():
            print("Falcon Design Space is running - close it first.")
            return 3
        if a.cmd == "install":
            cmd_install(app, a.patch, dev=a.dev)
        elif a.cmd == "uninstall":
            cmd_uninstall(app)
        elif a.cmd == "status":
            cmd_status(app)
        elif a.cmd == "check":
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(app, "falconmods", "backup")
                src = src if os.path.isdir(src) else os.path.join(app, "mui")
                build(src, tmp, load_patch_sets(a.patch, a.dev), subs=substitutions(app))
            print("All patches apply cleanly.")
        else:
            build(os.path.join(app, "mui"), a.out, load_patch_sets(a.patch, a.dev), subs=substitutions(app))
    except RuntimeError as e:
        print("ERROR:", e)
        return 2
    except PermissionError as e:
        print("ERROR: no write access (run as administrator?):", e)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
