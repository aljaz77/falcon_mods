# Progress log

## 2026-10-23

### Research
- Falcon Design Space 1.10.7 is in `C:\Program Files\Falcon Design Space`. Qt 6 + QML, closed source.
- QML UI comes from `mui/*.rcc`. Wrote `tools/rcc.py` (list/extract/pack). Round trip is byte-identical.
  The packer writes non-zero timestamps so Qt's QML disk cache can't serve stale code.
- The app enforces a single running instance ("The program is already running!"), so testing needs the installed app closed.
- Camera calibration format reverse-engineered and verified against the app output (see PLAN.md §1).
- The camera is on the lid. `QR_code.jpg` was taken with the lid not fully closed and shows a different perspective.
- Found `FillPatternOffset` (concentric) etc. already in the engine, hidden for non-galvo devices.
- First estimate of the A1 bed grid from the existing calibration: verticals at x ≈ 19.5 / 145 / 271 / 392 mm,
  horizontals at y ≈ 0 / 100 / 200 / 300 mm (canvas coords, y down from the back). Cells ≈ 125 x 100 mm.
- EULA forbids modification and redistribution, so the repo only ships original code plus a patcher.

### Fill patterns: done
- Patch `patches/fill_patterns.py` (one QML line). Tested on the portable patched copy with the A1 connected:
  exported G-code for a heart shape with each mode and rendered it with `tools/gcode_preview.py`.
  - Offset Fill: concentric contour-parallel rings at the set interval, inside-out. ✔
  - Zigzag Fill: one continuous boustrophedon path. ✔
  - Cross Fill + fill angle 45°: crossed hatch at 45°, with overscan. ✔
- Result image: `work/gcode/fill_compare.png`.
- Bug found and fixed in `rcc.py`: file entries need language = QLocale::C (1), otherwise QResource can't
  find any file and the app shows a misleading "restart with administrator privileges" error.
- The device reports a work area of `$130=381 $131=305` and the machine ID (GRBL `$I`) matches the calibration entry key.

### Bed-grid calibration: engine + in-app integration done
- Engine `calib/falcon_bedgrid`: model-guided ridge detection, staged robust LM fit (own NumPy LM solver,
  no SciPy), quality gate, preview image, config writer with backups.
  - Recorded frames: 0.65–0.78 px RMS, 96–97 % of the grid found; fitted border positions agree
    between frames within ±0.25 mm. Lid-open frame correctly rejected.
- Findings from experiments in the real app:
  - The app keeps calibration in memory and writes it back to cameraConfig.txt on exit; no QML-callable
    reload exists (tested readCameraConfigList/initConfigs/reSetCrrConfig/changeConfigs/reSetConfigs;
    `saveDefaultConfig()` used as probe). → Apply = close app politely, write, relaunch.
  - Material-height compensation: f_eff = NewK_f · (180 − t)/(180 − Thickness) (fixed 180 mm camera height;
    20 mm vs 0 mm gives exactly 8/9). So the unobservable focal length doesn't matter.
  - `Thickness: 0` is treated as unset and replaced by 7 mm → we store 0.001.
  - The stored NewCameraMatrix is used as-is (verified: f 1096.500 vs stored 1096.494).
  - The stock NewCameraMatrix = OpenCV 4.5 getOptimalNewCameraMatrix(alpha=0).
- In-app: "Quick Calibration" card on Camera Calibration page → captures image 10 → opens the tool via
  `falconbedgrid://` URL (fallback: exe path baked in by patcher) → Apply restarts the app.
- E2E verified on the machine: after apply, grid lines in the app's own camera view are within ~0.3 mm of
  their laser positions, straight edge to edge; user's OffsetY (−0.4) preserved; backup written.

### Installer and repo: done
- `tools/build_release.py`: pytest → PyInstaller (tool: one-folder windowed, 111 MB; patcher: one-file
  console, 8 MB) → Inno Setup → `dist/FalconMods-Setup-1.0.0.exe` (46 MB).
- Installer: finds the Falcon Design Space folder (uninstall registry keys, then the default path), refuses to run
  while the app is open, installs to `<app>\falconmods`, registers `falconbedgrid://`, runs the patcher
  (shows its log on failure, so an incompatible app version is left untouched), Start-menu entries.
  The uninstaller restores the original `.rcc` files.
- Tested silently against a pristine copy: install OK, app loads and the card shows; uninstall restores
  both `.rcc` files byte-for-byte and removes files and registry keys.
- Tests: 8 pytest tests (rcc format, LM solver, synthetic calibration recovery < 0.5 mm, rejection).
- GitHub Actions: tests on push/PR; tagged `v*` builds the installer and attaches it to a release.

### Open / possible follow-ups
- True *spiral* (one continuous path) fill isn't in the engine → done on 2026-10-24 as our own
  toolpath generation (Spiral tool, see below).
- Bed-grid template is measured on one A1. Other units should be within ~1 mm and can trim with
  Camera Offset X/Y. Reports from more machines would let the defaults be refined.

### 1.0.1: corner accuracy ("lines look bent near the corners")
- Residuals of the 5-term fit were systematic (same in all photos): up to ~1 mm toward the front-right corner.
- Tested 8 (rational), 12 (rational + thin prism) and thin prism only. The app accepts 12 DistCoeffs
  (verified in the real app). Chose thin prism only: stable and best on the latest photo
  (0.42 px, 98% < 0.37 mm). Rational solutions jumped between photos (k1 −2.0 vs −0.38).
- Applied on the machine. Measured in the app's view (new `tools/straightness.py`, band-centroid gauge):
  inner lines max bend 0.35 → 0.21 mm, front border sag reduced, left border ±0.3 mm bow remains with
  every model (likely bed flatness, ~1 px at the edge). Colour channels disagree by up to 1.8 mm at
  the corners (lateral chromatic aberration), so ±0.5 mm is the practical floor.

## 2026-10-24

### Spiral fill: done
- Generator `patches/qml/FalconModsSpiral.js` (distance field → marching-squares rings → ring tree →
  one turn per ring). Node tests on 7 shapes: coverage gap ≤ 1.1 × interval (p99 ≤ 0.6), nothing
  outside the shape or across holes; 1 path for simple shapes, 1 per hole / lobe.
- In-app tool (test copy with the dev hook): heart → 1 spiral path at the original position
  (+ interval/2), Line layer; 80 mm heart at 0.1 mm: 2.7 s click-to-result; square with hole:
  outer + hole + 4 corner lobes.
- G-code (`saveGcodeFile`) of the heart: one `G0` into the job, then 2183 `G1` moves of one
  unbroken burn path. Render: `docs/img/spiral-fill.png`.
- Not checked in the app: undo of the steps, text objects, a real engraving on the machine.


### 1.2.0: in-app UI, automatic laser alignment, remembered registration
- Probed live updates: `ClCameraConfigModel` is empty without a device and offers no way to inject
  K/D; earlier tests showed no file reload. So Quick Calibration keeps the automatic restart.
  The stock alignment's `genWorldMatirx` is live, so laser alignment needs no restart.
- Stock pattern coordinates read from `gcode.genCalibationPathGcodes` via the dev hook.
- `markers.py`: ring + cross matched filter, square/scale check, cross-arm line fit. Synthetic tests:
  max error 0.07-0.13 mm, including blur and low contrast. Regression: the bed grid's printed "+" marks
  were first mistaken for markers on the real bed photo; now rejected (ring required, 180 mm square).
- In the test copy with the laser connected: Quick Calibration page → helper → result in ~6 s
  (0.38 px, 96 % of the grid); Apply closed the app, wrote the 12-term calibration and relaunched it.
  Align view: the saved image is the undistorted photo (2592x2138); `genWorldMatirx` maps exactly
  the given points to the marker positions (0.000 mm). Calibration file snapshotted and restored.
- Not tested: a real engraving of the alignment pattern with *Detect markers* (needs material on the
  bed and someone present), and a visual check of the new page (the PC was locked, and Qt doesn't
  render while locked).

### 1.2.1: real-world test of Detect markers
- With the user at the machine: the new page looked right (the illustration's "+" marks were off-centre,
  and the check grid was dark blue because of a BGR mix-up; both fixed).
  Quick Calibration ran again (0.41 px, 95 %).
- Stock alignment pattern engraved on 4 mm basswood (two boards side by side). The first Detect markers
  attempt found 0 of 4. Causes: normalised correlation = 1.0 on the black bed (junk candidates), marker 3
  half off the board edge, the centre ring + board seam passing as a marker. All fixed; the real photo is
  now `tests/data/real_align_basswood.jpg`.
- After *Finish* (live, no restart): camera photo at height 4 mm, cross centres measured in the app's
  bed view vs. the burned laser coordinates: X within ±0.08 mm; Y +0.23..+0.35 mm by my first sum,
  but 0.17 mm of that was my own pixel-convention error (the bed view is drawn flipped, which shifts
  the row maths by one pixel) → about 0.1–0.2 mm true error, around one camera pixel. Camera
  Fine-Tuning was already 0/0 after the alignment.
