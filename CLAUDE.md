# FalconMods: context for contributors and AI agents

Unofficial mods for **Creality Falcon Design Space** (closed-source Qt 6 / C++ laser software),
tested with 1.10.7 and a **Creality Falcon A1**. Read this first, then `docs/ARCHITECTURE.md`
(how the pieces fit) and `docs/RESEARCH.md` (reverse-engineered facts about the app).

## Ground rules

- **Never commit Creality files** (extracted QML, images, binaries, logs). The EULA forbids
  redistribution. Everything vendor-derived lives in `work/` (gitignored). Patches are *anchored
  text edits* applied on the user's machine by `tools/patcher.py`.
- **Never test against the user's real install** (`C:\Program Files\Falcon Design Space`). Copy the
  app folder (`work/app`) and use `patcher.py install --app work/app [--dev]`. The app is
  single-instance, so close the real one first.
- **Protect `%LOCALAPPDATA%\Falcon Design Space\conf\camera\cameraConfig.txt`** (the user's camera
  calibration). Any test run of the app rewrites it on exit. Snapshot it before, restore after,
  or force-stop the test copy (`taskkill /F`). The app may re-order entries on save; compare by `ID`.
- Don't write machine IDs, user names or local paths into tracked files. Grep the diff before
  pushing.
- The `falconbedgrid://` link can be opened by anything (web pages too). Validate every URL
  parameter, never take file paths from the URL or a job folder, and keep
  `tests/test_helper_security.py` passing.
- Edit docs with an editor (or the Write/Edit tools), not shell heredocs: Windows paths like
  `\falconmods` turn into `\f` escapes. Write files with `encoding="utf-8"`.
- QML/JS patches must fail loudly: every `find` anchor must match exactly `count` times
  (default 1), or the patcher aborts without touching the app.

## Layout

```
calib/falcon_bedgrid/   Python helper "FalconBedGridCalib" (OpenCV + NumPy, frozen with PyInstaller)
  core.py               camera model, grid detection, robust LM fit, export to app matrices
  lm.py                 small Levenberg-Marquardt (no SciPy in the frozen exe)
  pipeline.py           image + config -> report/preview, quality gate, config writing
  registration.py       app-effective model (processing height), learned laser registration
  markers.py            stock alignment-marker detection (matched filter + cross-line fit)
  jobs.py               file-based job protocol with the QML UI
  appctl.py             find/close/relaunch the app
  config_io.py          cameraConfig.txt read/write (+ backups)
  __main__.py           CLI, falconbedgrid:// URL handler (headless jobs), stand-alone Tk window
  templates/            bed-grid geometry per machine
patches/                one module per feature: ID, DESCRIPTION, PATCHES = [anchored edits/new files]
  qml/                  new QML/JS files added to the app's resources
tools/                  rcc.py (Qt resource pack/unpack), patcher.py, build/release scripts,
                        gcode_preview.py, straightness.py, devrun.sh (dev hook driver)
installer/              Inno Setup script (FalconMods.iss), icon, disclaimer
tests/                  pytest (synthetic data only); spiral tests also need Node.js
docs/                   ARCHITECTURE, RESEARCH, USER_GUIDE, PLAN, PROGRESS
```

## Everyday commands

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q tests                         # all tests (~20 s)
.venv/Scripts/python tools/patcher.py check --app work/app      # do all anchors still match?
.venv/Scripts/python tools/patcher.py install --app work/app --dev   # patch the test copy (+ dev hook)
bash tools/devrun.sh TAG script.js                              # run JS inside the running test app
.venv/Scripts/python tools/build_release.py                     # tests -> exes -> dist/FalconMods-Setup-x.y.z.exe
.venv/Scripts/python tools/publish_release.py                   # push + GitHub release with the installer
```

Extract the app's QML to read it: `python tools/rcc.py extract "<app>/mui/qml.rcc" work/qml`
(same for `qml_new.rcc`). Exported function names come from the moc strings in
`FalconDesignSpace.exe` (`strings -n 4 ... > work/strings/exe.txt`).

## Testing in the app

- Point the URL protocol at the source tree while developing (per-user key overrides the
  installed one; delete it when done):
  `HKCU\Software\Classes\falconbedgrid\shell\open\command` = `"<repo>\.venv\Scripts\pythonw.exe" "<repo>\calib\FalconBedGridCalib.py" "%1"`
- The dev hook (`--dev`) loads `%LOCALAPPDATA%\Falcon Design Space\falconmods\dev\<new folder>\run.qml`.
  `tools/devrun.sh` wraps your JS in an Item, waits for `FM-<TAG> end` in the app log and prints
  the `FM-<TAG>` lines. Use `console.warn` (info lines are buffered). Find objects by walking
  `appWindow.contentItem` (see `docs/ARCHITECTURE.md`).
- `grabToImage` does not complete while Windows is locked (rendering pauses). Test logic through
  the log in that case.
- Calibration flows need the laser connected (the camera is powered by it).

## Versioning / release

Bump `VERSION` in `tools/patcher.py` (used by the installer and release script), add a
`CHANGELOG.md` entry, run `tools/build_release.py`, then `tools/publish_release.py`.
