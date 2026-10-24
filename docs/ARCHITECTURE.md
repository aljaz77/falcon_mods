# Architecture

```
 Falcon Design Space (Qt 6, closed source)                         FalconMods
 ─────────────────────────────────────────                         ──────────
 FalconDesignSpace.exe ── loads every mui/*.rcc ◄──────────────── patcher.py: extract → anchored
   │                       (QML UI as plain text)                  edits + new files → repack
   │                                                               (originals kept in <app>/falconmods/backup)
   │  QML pages patched by FalconMods
   │   ├─ PrepareCalibration: + "Quick Calibration" card
   │   ├─ FalconModsQuickCalibPage ──┐
   │   ├─ CameraAlignView: + "Detect markers"
   │   │                             │ Qt.openUrlExternally("falconbedgrid://<action>?token=T...")
   │   │                             ▼
   │   │                    FalconBedGridCalib.exe (helper, Python frozen)
   │   │                             │ writes %LOCALAPPDATA%/…/falconmods/jobs/T/{result.qml,*.jpg}
   │   └─ FalconModsJob (FolderListModel + Loader) ◄──┘
   ├─ LayerEditorPopup: all fill patterns for gantry lasers
   └─ ClTopToolBar: + "Spiral" (hidden WebEngineView runs FalconModsSpiral.js)
```

## Patches (`patches/*.py`)

Each module defines `ID`, `DESCRIPTION`, `PATCHES` and optionally `DEV = True` (dev-only).
A patch entry is either

```python
{"rcc": "qml.rcc", "file": "Some/File.qml", "find": "<exact text>", "replace": "<text>", "count": 1}
{"rcc": "qml.rcc", "file": "Some/New.qml", "new_file": True, "source": "qml/New.qml"}   # or "content": "..."
```

`@FALCONMODS_TOOL_EXE@` in new files is replaced with the helper's install path. The patcher
always starts from the pristine backup, so re-running it is safe; it refuses to run while the app
is open (the app memory-maps the `.rcc` files). `tools/rcc.py` writes Qt resource format v3:
children sorted by `qt_hash`, file nodes with language `QLocale::C` (1), non-zero timestamps
(otherwise the QML disk cache can serve stale code).

## Helper ↔ UI job protocol (`calib/falcon_bedgrid/jobs.py`, `patches/qml/FalconModsJob.qml`)

QML can launch URLs and load QML/images, but cannot read or write arbitrary files. So:

1. QML makes a token (`FalconModsJob.prepare()`), optionally saves an input image named after it
   (`image/falconmods_align_<token>.jpg`), and launches `falconbedgrid://<action>?token=<token>&…`.
2. The helper does the work and publishes `jobs/<token>.tmp/` → renames to `jobs/<token>/`
   (atomic, and a brand-new folder, which avoids Qt's directory-listing cache: files that
   appear later in a folder Qt has already listed fail with "File name case mismatch").
3. `FalconModsJob` watches `jobs/` with a `FolderListModel`, loads `jobs/<token>/result.qml`
   (`QtObject { property var result: {...} }`) and emits `finished(result)`; images are loaded
   from the same folder.

Actions: `calibrate` (bed-grid calibration → result + `pending.json`), `apply` (close the app,
write `pending.json` of that job into `cameraConfig.txt`, relaunch, no answer),
`markers` (find the 4 stock alignment markers).

**Security.** Any program or web page can open a `falconbedgrid://` link (browsers ask first), so
the helper trusts nothing in it:
- URL parameters are validated (token `[A-Za-z0-9]{6,40}`, image number `\d{1,3}`, device id);
  anything else is dropped, so a token can never become a path.
- `apply` only works for a job the helper created less than 2 h ago. Its matrices are checked
  (`__main__._valid_pending`), and it writes only `config_io.default_config_path()`, never a path
  from the job folder. Worst case for a forged link: the app restarts.
- Old job folders and `image/falconmods_align_*.jpg` are deleted after a day. Calibration backups
  are capped at 30.
- The page's `applyWatch` timer unlocks the page if the app wasn't closed within 45 s.
- `tests/test_helper_security.py` covers all of this.

## Camera calibration data flow

- **Quick Calibration**: photo `image/10.jpg` (via `patternCalibController.startCapture(10)`)
  → `pipeline.run`: prior = app-effective model of the current config (`registration.app_model`,
  includes the processing-height formula) → registration (learned grid positions if the current
  config wasn't written by us) → `core.calibrate` (thin-prism lens model) → quality gate →
  `export_matrices` (K, D[12], NewK, WorldMatrix; Thickness 0.001) → on Apply the app is closed,
  the file written, `registration.record_applied`, app relaunched.
- **Camera Alignment** (stock flow): engrave the stock pattern → capture (the align image is the
  *undistorted* photo, 2592×2138) → *Detect markers* → `clCamera.setPielPos(i, pt)` +
  `ClImageShow.setPoints` → stock *Finish* → `clCamera.genWorldMatirx(w, h, thickness)` computes a
  WorldMatrix from exactly these 4 points (verified) and keeps our K/D. Live, no restart.
- Afterwards the stored WorldMatrix differs from what we wrote → the next Quick Calibration
  learns the inner grid-line positions through it (`registration.learn_positions`) and saves
  them as `falconmods/template_<device>.json`.

## Finding things in the running app (dev hook)

```js
function walk(it, f, d) { if (!it || d > 60) return null; if (f(it)) return it
  var ch = it.children || []; for (var i = 0; i < ch.length; i++) { var r = walk(ch[i], f, d + 1); if (r) return r } return null }
var cam  = walk(appWindow.contentItem, function (o) { return o.patternCalibController !== undefined && o.calibStepIndex !== undefined }, 0)   // CameraCalibrationV1
var page = walk(appWindow.contentItem, function (o) { return typeof o.startCalibration === "function" }, 0)                                 // Quick Calibration page
// main workbench stack: workbenchViewIndex 2 = camera calibration; cam.workbenchViewIndex: 0 prepare, 1 stock steps, 2 Quick Calibration
```
