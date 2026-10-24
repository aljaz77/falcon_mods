# Falcon Design Space mods – Plan

**Status (2026-10-23): implemented and tested. See [PROGRESS.md](PROGRESS.md).**

Target: **Creality Falcon A1** with **Falcon Design Space 1.10.7** (Windows).

Goals

1. **One-shot camera calibration from the bed grid.** No dot card, no engraving, no clicking
   markers: take one photo of the empty bed and compute the full calibration from the
   printed grid that is already on the A1 bed plate.
2. **Concentric ("offset") fill** for the A1, plus the other fill patterns the engine already has.

---

## 1. What the software is (research summary)

Details in [RESEARCH.md](RESEARCH.md).

* Not open source. Native **Qt 6 / C++** app (`FalconDesignSpace.exe`, OpenCV 4.5.3 DLLs,
  Clipper2 statically linked).
* The **entire UI is QML**, shipped as plain-text source inside three external Qt resource
  bundles: `mui/qml.rcc`, `mui/qml_new.rcc`, `mui/translations.rcc`. The exe loads every
  `*.rcc` in `mui/` at start-up.
* Format is the documented Qt `rcc` binary format v3 (zlib-compressed entries). I wrote a
  reader/writer (`tools/rcc.py`) and verified a byte-identical round trip of all 410/669 files.
* So we can change UI behavior and call any C++ method that is exposed to QML,
  without touching the binary.

### Camera calibration internals

* Calibration data lives in `%LOCALAPPDATA%\Falcon Design Space\conf\camera\cameraConfig.txt`
  (JSON). Per device: `IntrinsicMat` (3x3), `DistCoeffs` (k1 k2 p1 p2 k3, OpenCV model),
  `NewCameraMatrix`, `WorldMatrix` (3x3 homography), `OffsetX/Y`, `Thickness`, etc.
* I confirmed the image pipeline numerically against the app's own output (`image/cam.jpg`):

  ```
  bed_view = flipV( warpPerspective( undistort(raw, K, D, NewK), WorldMatrix, (W*6, H*6) ) )
  ```
  W x H = work area in mm (381 x 305 for the A1), 6 px/mm. Mean pixel error between my
  reconstruction and the app's image: 4/255 (JPEG noise).
* Stock user flow (4 pages): (1) intrinsics from 9 dot-card photos or an ArUco board,
  (2) place material, (3) engrave a marker pattern, (4) capture and double-click the 4 marker
  centres. The camera sits **on the lid**, so the calibration is only valid with the lid closed.

### Bed grid

The A1 bed plate has a printed light grid: outer rectangle + 2 vertical + 2 horizontal lines
(3x3 cells, about 125 x 100 mm), with "+" marks on the 4 inner crossings. In one lid-closed photo
the whole grid is visible and the lines are strongly curved by the wide-angle lens. That
gives everything needed:

* **Lens distortion**: physically straight lines have to come out straight (plumb-line constraint).
* **Pose and scale**: 16 line crossings at known positions on the bed plane.

### Fill patterns

`ClLayer.FillPattern` already implements `OneWay, Bidirectional, Cross, Offset, ZigZag`
(Offset = concentric contour-parallel fill, made with Clipper2 offsetting) plus a fill angle.
The QML hides everything past Bidirectional unless `deviceCtl.currDevice.isGalvo` is true
(`qml_new/qml/Popup/LayerEditorPopup.qml`). The A1 is a gantry, so they're hidden.

---

## 2. Design

### 2a. Bed-grid calibration engine (`calib/`)

Python + OpenCV + NumPy/SciPy, frozen to a single windowed exe (`FalconBedGridCalib.exe`).

Input: one raw camera frame (2592x1944) of the empty bed, lid closed.
Output: an updated `cameraConfig.txt` (with a backup), a JSON report, and an overlay PNG.

Algorithm:

1. **Prior model.** Start from the camera model already in `cameraConfig.txt` (factory or
   earlier user calibration). Fall back to a built-in A1 default.
2. **Model-guided line search.** Project each template grid line into the image with the
   current model. At many points along it, search along the normal (±R px) for a thin
   bright ridge (top-hat filtered luminance, sub-pixel parabolic peak). Reject outliers
   (cards, smoke stains, glare) with MAD-based robust weighting.
3. **Joint fit** (Levenberg–Marquardt, `scipy.optimize.least_squares`, soft-L1 loss):
   parameters are f, cx, cy, k1, k2, k3, p1, p2, rvec, tvec. Residual = image distance from
   each ridge sample to the projected template line (point-to-curve). Crossings are
   implicitly constrained because lines share parameters.
4. Iterate 2–3 with a shrinking search radius (coarse to fine).
5. **Export in the app's convention.** K, D, NewK (`getOptimalNewCameraMatrix`, alpha 0 like
   the app), and WorldMatrix = map from undistorted px to bed px at 6 px/mm, y-up
   (to match the `flipV`).
6. **Quality gate.** RMS residual and per-line coverage; refuse to write if the fit is poor.

Template (bed grid geometry in machine/canvas mm) is a JSON file
(`calib/templates/falcon_a1.json`), so other machines/plates can be added. The default A1
values were measured from this machine's existing engraving-based calibration (see
PROGRESS.md). Any small per-machine laser-to-plate offset can still be trimmed with the
app's existing *Camera Offset X/Y* setting.

### 2b. In-app integration (QML patch)

* `PrepareCalibration.qml`: add a third card, **"Quick Calibration (Bed Grid)"**.
  Flow: check lid closed and bed empty → capture a frame through the app's own camera API
  (`cameraPosition.captureImage(path)`) → launch the engine (`Qt.openUrlExternally` on the
  bundled exe, which reads that fixed path) → poll for the result overlay image → show it
  with the RMS error → **Apply** reloads the config (`clCamera.reSetCrrConfig()`,
  `cameraCtl.initConfigs()`) and refreshes the canvas background.
* The engine also runs stand-alone (CLI / double-click) on a saved photo, as a fallback.

### 2c. Concentric / offset fill

* `LayerEditorPopup.qml`: show all fill patterns (and the fill angle) for gantry devices too.
* Verify the gantry G-code generator honours `FillPattern` by exporting G-code with each
  pattern and checking the toolpaths (`tools/gcode_preview.py` renders them).
* If Offset fill works on the gantry path: done (plus a quick note on good settings).
  If not: fallback plan is a QML-side "Convert to concentric lines" action that builds offset
  contours (Clipper JS) and puts them on a Line layer.
* "Spiral": the engine's Offset fill gives concentric rings. A true continuous spiral isn't in
  the engine. It would be a follow-up via the same fallback (contour morph between rings).

### 2d. Patcher / installer

* Nothing from Creality is redistributed. The patcher reads the user's installed
  `mui/*.rcc`, applies text patches (`patches/*.py`, anchored search/replace with checks),
  repacks, backs up the originals, and installs the engine into the app folder.
* Clears the QML disk cache (`%LOCALAPPDATA%\Falcon Design Space\cache\qmlcache`).
* **Uninstall** restores the backed-up `.rcc` files.
* Packaged as a single **Inno Setup** installer (`FalconMods-Setup-x.y.z.exe`). It asks for
  admin rights (the app lives in Program Files) and detects the install path from the registry
  or the default location.

### 2e. Repository layout (for GitHub)

```
calib/            bed-grid calibration engine (+ templates, tests)
patches/          QML patch definitions
tools/            rcc.py, patcher, gcode preview, helpers
installer/        Inno Setup script, build script
docs/             PLAN, RESEARCH, PROGRESS, user guide
work/             (gitignored) extracted resources, test data, scratch
```
License: MIT for our code. README states it's unofficial, not affiliated with Creality,
and modifies a locally installed copy at the user's own risk.

---

## 3. Testing

* `rcc.py` round trip (done).
* Engine: offline tests on recorded frames from this machine (`image/0..10.jpg`).
  Check reprojection RMS, compare the bed view against the stock calibration, and check that
  grid lines come out straight in the rectified output.
* Fill: export G-code for a test shape with each pattern, render and inspect.
* App: run a portable patched copy (`work/app`) to check the QML loads with no errors (log in
  `%LOCALAPPDATA%\Falcon Design Space\Logs`) and that the new UI works end to end with the
  machine connected.

## 4. Risks

* The app may cache calibration in memory and overwrite our file. Mitigation: reload through
  the exposed API; worst case, ask for a restart.
* A1 calibration might also be stored on the device (`setFirmware*`). We only write the local
  file, which is what the app reads for the active config.
* App updates replace the `.rcc` files. Re-run the patcher (patches are anchored and fail
  loudly if the QML changed).
* EULA: Creality's terms forbid modification. Personal use is the user's call. The public repo
  contains only original code and patch instructions.
