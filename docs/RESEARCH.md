# Research notes: Falcon Design Space internals

Version examined: **Falcon Design Space 1.10.7** (Windows, Qt Installer Framework package
`org.chuangxiang.falcondesignspace`).

## Architecture
- `FalconDesignSpace.exe`: Qt 6 / C++. Bundles OpenCV 4.5.3 DLLs, statically links Clipper2.
  Single instance ("The program is already running!").
- UI = QML in external Qt resource bundles `mui/qml.rcc` (669 files), `mui/qml_new.rcc` (410),
  `mui/translations.rcc`. The exe registers every `*.rcc` in `mui/` (string "No .rcc files found in:").
- rcc format v3: header `qres`, version, tree/data/names offsets, overall flags; 22-byte tree
  nodes; children sorted by `qt_hash`; zlib payloads with 4-byte BE length prefix.
  **File nodes must have language = QLocale::C (1)**, otherwise QResource can't find them. Timestamps of 0
  make the QML disk cache fall back to the exe mtime (stale cache risk), so the packer writes real ones.
- C++ objects exposed to QML include `clCamera` (ClCamera), `cameraPosition` (ClCameraPosition),
  `cameraManager`, `deviceCtl`, `clApplication`, `CameraPatternCalibrationController`.
  Method names come from the moc string table in the exe.

## Camera calibration
- File: `%LOCALAPPDATA%\Falcon Design Space\conf\camera\cameraConfig.txt` (JSON).
  `Calibration Data[] -> {Device, ID, camera[] -> {CameraName, configs[]}}`; config keys:
  `IntrinsicMat, DistCoeffs, NewCameraMatrix, WorldMatrix` (`{data,rowMajor,shape}`), `OffsetX/Y`,
  `Thickness`, `LaserModule`, `Selected`, `SaveTime`, `dataVersion`, ...
- Entries keyed by the machine ID reported by GRBL `$I` (`ID:XXXXXXXXXXXX`, 12 hex digits).
- Bed view (`image/cam.jpg`) = `flipV(warpPerspective(undistort(raw,K,D,NewK), W, (W_mm*6, H_mm*6)))`.
  Verified: mean abs difference 4/255 against the app's own output.
- Stock NewK = OpenCV 4.5 `getOptimalNewCameraMatrix(K, D, size, alpha=0)`. At runtime the app uses
  the **stored** NewK.
- Material/processing height t: effective focal = NewK_f * (180 - t)/(180 - Thickness), about
  NewK's principal point (heights 0 and 20 mm differ by exactly 8/9).
- `Thickness == 0` is treated as missing → 7 mm is used (the result fits t_cal = 7.0 exactly).
- The app keeps the calibration in memory and rewrites the whole file on exit. No QML-callable
  reload: `readCameraConfigList(path)` returns an opaque object; `initConfigs`, `reSetCrrConfig`,
  `changeConfigs`, `cameraConfigModel.reSetConfigs` don't re-read; `saveDefaultConfig()` dumps memory to the file.
- Camera: 2592x1944 NV12 UVC device "Creality Falcon Camera", mounted in the **lid**. A
  half-open lid gives a different perspective.
- Canvas photo: `patternCalibController.startCapture(10)` → raw `image/10.jpg`, bed view `image/cam.jpg`,
  signal `cameraPosition.signal_ImageCaptured` with `ImageCaptured === 10`.

## Lens model
- 5-term OpenCV model leaves a systematic, image-independent residual up to ~1 mm at the front-right
  corner. Rational (k4-k6) alone: no gain and unstable (k1/k4 near-singular pairs). Thin prism
  (s1-s4) with k4-k6 = 0: fit 0.66 -> 0.42 px, consistent between photos.
- The app honours 12 DistCoeffs: bed view matches cv::undistort with all 12 to 0.57/255 mean abs
  (using only the first 5 would differ by 31.7/255).
- Remaining ~±0.3 mm bow of the left frame line appears with every model, consistent with
  bed-plate flatness (parallax: shift ≈ r·Δz/H) and ~1 px resolution at the edge. Lateral
  chromatic aberration: per-channel calibrations differ by up to 1.8 mm (R vs G) at the corners.
  Detection uses luminance.

## A1 bed grid (laser coordinates, canvas mm, y down from the back)
Measured against an engraving-based calibration: inner vertical lines x = 145.45, 271.48;
inner horizontal lines y = 98.8, 199.2. The outer frame is fitted per image (≈ 17.7 / 397.0 and
−2.0 / 300.3). Work area (GRBL `$130/$131`) 381 x 305 mm.

Coordinate frames: the canvas and G-code use **Y up from the front-left** (rulers: 0 at the
bottom). The calibration "world" frame (X = canvas x, Y = 305 − y_down) is the same as G-code
X/Y, so laser coordinates can be compared directly.

## Stock "Camera Alignment" (A1)
- Pattern: `gcode.genCalibationPathGcodes(381, 305, 1, power, noComment, materialParams)` (callable
  from QML without a device) → crosshair circles Ø20 mm with a cross at (100.5, 242.5),
  (280.5, 242.5), (280.5, 62.5), (100.5, 62.5) mm, numbered 1-4 (1 back-left … 4 front-left),
  plus a double ring Ø10/Ø20 at (190.5, 152.5) and the digits. `genCalibationPathBorderGcodes`
  gives its frame. `clApplication.startEngraveCalibationPath(materialParams)` engraves it.
- Align view (`CameraAlignView.qml`): `patternCalibController.startCapture(9)` →
  `onPreviewImageReady(image)`. The image is the **undistorted** photo (straight lines), 2592×2138.
  `ClImageShow` has `setPoints(QVariantList)`, `pointsCount`, `pointsClear()`,
  `saveAlignImageToJpeg(path)` (plain path).
- `clCamera.setPielPos(i, QPointF)` ×4 → `clCamera.checkPoints()` (0 = ok, 1 = wrong order) →
  `clCamera.genWorldMatirx(w, h, thickness)`: a WorldMatrix that maps exactly those 4 points
  (in align-image pixels) to the marker coordinates (verified: 0.000 mm). It keeps K and all 12
  DistCoeffs and stores `Thickness = thickness` (0 → treated as 7 mm, see above).
  The change is live in memory; saved on exit or by `saveDefaultConfig()`.
- `cameraConfigModel` (ClCameraConfigModel) is empty without a connected device. It has `setData`,
  `saveItem`, `changeCrrConfig`, `setConfigs`, but no QML way to inject arbitrary K/D was found, so
  bed-grid results still need the restart path.

## Fill patterns
`ClLayer.FillPattern {OneWay, Bidirectional, Cross, Offset, ZigZag}` plus `FillAngle`,
`TransformFillAngle`. `qml_new/qml/Popup/LayerEditorPopup.qml` hides index > 1 and the angle unless
`deviceCtl.currDevice.isGalvo`. The gantry G-code generator honours all of them (exported and
rendered G-code: concentric rings, continuous zigzag, 45° cross hatch with overscan).

## Spiral fill: QML-side building blocks
- There is no spiral pattern in the engine; the toolpath is generated in JS (`patches/spiral_fill.py`).
- Reading geometry: `ClShape.path` is an opaque `QPainterPath` in QML. `clApplication.saveSvg(url)`
  writes **every** shape on the canvas (QSvgGenerator, mm, one `<g transform="matrix(...)">` per
  shape, `fill-rule` on the path). `ClShape.getBoundingRect()` is the tight canvas-mm box and is
  used to pick the selected shapes out of that file.
- QML can't read the file: XHR file reads are disabled (`QML_XHR_ALLOW_FILE_READ` not set) and
  the shipped `qml/qml/QtQml/XmlListModel` folder is empty. A hidden `WebEngineView` with
  `loadHtml(html, "file:///<appDir>/tmp/")` can read it with XHR. It can't fetch `qrc:` and V4
  doesn't expose function source, so the page code is embedded as a string at patch time.
- Speed: QML's V4 ran the generator ~25–130× slower than V8 (80 mm heart at 0.1 mm: 109 s vs
  0.8 s), so the page also does the computation.
- Writing: `webCommon.saveSvg(svgText)` imports an SVG string at true mm size, centred on the
  canvas, and selects it (`clApplication.importUrl(url)` places files elsewhere).
- Moving: `clCanvas.select.updateSelected()`, then set `clCanvas.select.selectBoundingRect =
  clCanvas.getTransformRect(r)` with `r` from `getOriginRect(...)` (the X/Y field path). Origin
  rects are in job-origin coordinates (bottom-left on the A1: `y = 305 − y_canvas − h`).
  `ClShape.setRect` doesn't move anything.
- `clApplication.setSelectShapesLayerMode(ClLayer.Line)` puts the selection on a Line layer
  (`ClLayer::Mode {Line, Fill, Image, Relief, ImageColor, FillColor, LineDeep}`).
- G-code without the dialog: `clApplication.saveGcodeFile(url, callback, false)`.
- Dev hook: `Loader` from a folder Qt already listed fails with "File name case mismatch" (Qt
  caches directory listings) and `FolderListModel` reports `c:/`, so each run gets its own folder.
- On exit the app rewrites `conf/camera/cameraConfig.txt` and may re-order the "Calibration Data"
  entries (e.g. the 5-coefficient "Creality Falcon A1" default entry before the machine-ID entry).
  Matched by ID nothing changes; the user's 12-term entry stays intact. A plain file hash or a
  short diff therefore looks like a change; compare entries by ID.

## Single-view focal length
For a single (nearly fronto-parallel) planar view, f, camera height and radial distortion
trade off perfectly: fits with f = 600…1117 px all give the same 0.89 px RMS. The image→bed
mapping is identical, so only the app's thickness compensation could care, and it uses a
fixed 180 mm height. The tool therefore keeps the prior focal length.
