# Changelog

## 1.2.1 (2026-10-24)
- Detect markers works on real engravings. Tested on a Falcon A1 with 4 mm basswood: the camera
  view then matches the laser within ~0.2 mm at all four markers. Fixes:
  - featureless areas (black bed around the material) no longer flood the candidate list;
  - a marker half off the material edge is found by predicting it from the other three;
  - the centre ring (plus a seam between two boards) is no longer mistaken for a marker
    (the pattern must be an axis-aligned square);
  - faint, partial cross lines are measured with an adaptive threshold and a robust line fit.
- Quick Calibration page: orange 50 mm check grid, readable "Laser reference" text, "+" marks
  centred in the illustration.

## 1.2.0 (2026-10-24)
- Quick Calibration now runs in a page **inside Falcon Design Space** (stock look: steps, result
  images, stats). The helper works in the background, and *Apply* restarts the app automatically.
- **Detect markers** in the stock *Camera Alignment* step: finds the four engraved crosshair
  markers automatically (about 0.1 mm), so there's no double-clicking. It applies live, without a restart.
- Laser registration is remembered: after a stock alignment (or with a factory calibration), Quick
  Calibration learns where this machine's bed grid sits relative to the laser and keeps it.
- Processing-height model of the app is used for priors and comparisons.
- The stand-alone calibration window uses the app's light style.
- Docs for contributors: `CLAUDE.md`, `docs/ARCHITECTURE.md`. Release script `tools/publish_release.py`.

## 1.1.0 (2026-10-24)
- Spiral fill: new *Spiral* tool next to *Offset*. Turns the selected closed shapes into one
  continuous spiral line on a Line Engraving layer (one spiral per lobe or hole), so the laser
  doesn't stop between concentric rings. Verified by exporting G-code: one rapid move into the
  job, then one unbroken burn path.
- Dev hook (development builds only) loads each script from its own folder; works around Qt's
  cached directory listings ("File name case mismatch").

## 1.0.1 (2026-10-23)
- Calibration: new default lens model "prism" (OpenCV 5 terms + thin-prism s1..s4, stored as 12
  coefficients; Falcon Design Space applies all of them). Fixes the slight bending of the bed
  frame near the corners: inner lines max bend 0.35 -> 0.21 mm, front border sag reduced, fit
  error 0.66 -> 0.42 px on a real A1. Rational terms were tested and rejected (unstable).
- Existing calibrations with any lens model are converted automatically as the starting point.
- New `tools/straightness.py`: measures how straight the grid looks in the app's camera view.

## 1.0.0 (2026-10-23)
- Quick Calibration: one-click camera calibration from the Falcon A1 bed grid (in-app card + tool).
- Extra fill patterns for gantry lasers: Offset (concentric), Cross, Zigzag, fill angle.
- Installer with automatic Falcon Design Space detection, backup and restore of patched files.
- Tested with Falcon Design Space 1.10.7.
