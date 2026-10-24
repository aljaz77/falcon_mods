# FalconMods: user guide

FalconMods adds three features to **Falcon Design Space** (tested with 1.10.7) for the
**Creality Falcon A1**:

1. **Quick Calibration**: calibrates the camera from one photo of the grid printed on the bed
   plate. No dot card, no engraving, no clicking on markers. Plus automatic marker detection
   for the stock laser alignment.
2. **Extra fill patterns**: *Offset Fill* (concentric), *Cross Fill*, *Zigzag Fill* and a
   *Fill angle* setting. These are built into Falcon Design Space but normally only shown for
   galvo lasers.
3. **Spiral fill**: a *Spiral* tool that turns a closed shape into one continuous spiral line,
   so the laser doesn't switch off and on between the rings of a concentric fill.

> Unofficial community mod. It's not made or supported by Creality, and you use it at your own risk.

---

## Install

1. Close Falcon Design Space.
2. Run `FalconMods-Setup-x.y.z.exe`. It finds your Falcon Design Space folder automatically. If it
   doesn't, point it to the folder that contains `FalconDesignSpace.exe`.
3. Leave all options ticked and click **Install**.

After a **Falcon Design Space update**, run the installer again. Updates replace the patched
files, and the installer tells you if a new version isn't compatible yet.

## Camera calibration

There are two parts, both on **camera menu (▾ next to the camera button) → Camera Calibration →
Start Calibration**:

| | What it sets | Needs | Restart |
|---|---|---|---|
| **Quick Calibration** (new card) | lens distortion **and** camera-to-laser alignment | one photo of the empty bed | automatic |
| **Camera Alignment** → *Detect markers* | fine laser alignment, checked by real engraving | a scrap ≥ 21 × 21 cm | none |

For most people Quick Calibration alone is enough. Run the Camera Alignment once afterwards if you
want the camera locked to the laser to the last tenth of a millimetre. Quick Calibration
remembers it from then on.

### Quick Calibration

1. **Prepare the bed.** Take out the honeycomb panel and everything lying on the bed. The printed
   grid (outer frame, 2 + 2 lines and 4 "+" marks) has to be visible. Marks, stains and a small
   item or two are fine; they're ignored.
2. **Close the lid.** The camera sits in the lid, so a half-open lid gives a wrong calibration.
3. Click **Quick Calibrate** on the right-hand card, then **Calibrate**.
4. After a few seconds the **Result** page shows:
   * left: the camera photo with the detected grid (green lines, cyan dots);
   * right: the bed view you'll get, with an orange 50 mm check grid. The lines should be straight;
   * the fit error (good: under 1 px), how much of the grid was found, how much the result differs
     from your current calibration, and which laser reference was used.
5. Click **Apply**. Falcon Design Space closes (save your project if it asks), the calibration is
   written, and the app **starts again by itself** with it. If you cancel the save prompt, nothing
   is written; after about 45 s the page says so and you can click **Apply** again.

The old calibration file is always backed up to
`%LOCALAPPDATA%\Falcon Design Space\conf\camera\falconmods_backups\` (the 30 newest are kept).
To go back, copy a backup over `cameraConfig.txt` while Falcon Design Space is closed.

### Laser check: Camera Alignment with automatic markers

This ties the camera to where the laser *actually* burns, using the stock alignment pattern
(four crosshair circles and a centre ring, about 20 × 20 cm), but without the clicking:

1. Click **Align** on the middle card.
2. **Place Material**: put a flat scrap (cardboard, plywood, card stock) of at least 21 × 21 cm in the
   middle of the bed and select it with its thickness.
3. **Carving Coordinates**: focus, optionally frame, then **Start**. The pattern is engraved.
4. **Camera Alignment**: click **Capture**, then **Detect markers**. The four markers are found
   automatically (shown as 1-4); check they sit on the crosses, then click **Finish**.

The alignment takes effect immediately, no restart. It keeps the Quick Calibration lens model.
The next Quick Calibration notices the new alignment and learns where this machine's bed grid sits
relative to the laser, so it keeps that accuracy ("Laser reference: learned from the app's
current calibration").

If **Detect markers** can't find them, the message says why. Check the whole pattern is visible and
the lines are burned dark (or light) enough. You can always double-click the four centres by hand as before.

### Tips

* **Processing height still matters.** The calibration is made on the bed plate (height 0).
  For material, enter its thickness as usual. With the honeycomb panel in, enter
  *honeycomb height + material thickness* as the processing height.
* **Accuracy.** After a Camera Alignment with *Detect markers*, the camera view matches the laser
  within about 0.1–0.2 mm at the markers (measured on a real A1). With Quick Calibration alone,
  expect about 0.3 mm in the middle of the bed. Toward the extreme corners expect up to about
  ±0.5 mm. That's roughly one camera pixel there, plus the lens's colour fringing.
* **Fine-tuning.** Your existing *Camera Offset X/Y* settings are kept.
* The calibration tool also runs on its own from the Start menu (*FalconMods → Falcon Bed-Grid
  Calibration*). It uses the most recent camera photo, or open any photo with **Open image…**.
* If a calibration is **rejected**, the page says why: grid not found, lid open, too much covered,
  and so on. Fix that and click **Retake**.

## Extra fill patterns

Select a layer in **Fill Engraving** mode and open its settings (the slider icon on the layer):

| Fill mode | What it does | Good for |
|---|---|---|
| Uni-directional | lines in one direction (stock) | best quality on photos |
| Bi-directional | back-and-forth lines (stock) | fast general fills |
| **Cross Fill** | two passes at 90°, a grid | smoother, more even dark fills |
| **Offset Fill** | **concentric** rings that follow the shape's outline | text, logos, outlines that should look "drawn", deep fills without line texture |
| **Zigzag Fill** | one continuous connected zig-zag path | fewer laser on/off cycles |

**Fill angle** rotates the scan direction (Uni/Bi/Cross/Zigzag). *Fixed angle* keeps the angle
on the bed; *Transform angle* rotates it with the object.

The *Interval* setting is the spacing between rings or lines, as usual.

## Spiral fill

*Offset Fill* burns separate rings: the laser stops at the end of each ring and moves to the next
one. The **Spiral** tool instead turns a shape into one continuous line that winds from the
outline to the centre, each turn one interval further in.

![Spiral fill](img/spiral-fill.png)

1. Select one or more closed vector shapes (drawn shapes or imported vector graphics).
2. Click **Spiral** in the top toolbar (next to *Offset*).
3. Set the **Line interval** (distance between the turns, e.g. 0.1–0.3 mm) and click **confirm**.

The spiral is created as a new object on a **Line Engraving** layer, exactly where the shape was.
Set that layer's speed and power like any line engraving. With *Replace the original shape* ticked
(the default) the original is removed; untick it to keep it (it is then still engraved with its
own layer's settings, so hide or delete it if you only want the spiral).

Good to know:

* The spiral starts with one full loop along the outline (a clean edge) and ends in the centre.
* Where the shape narrows and the rings would split (a dumbbell, the two bowls of an "8", the
  corners of a frame) each part gets its own spiral, so there are a few laser jumps, but far
  fewer than with separate rings. Shapes with holes get one spiral around each hole.
* To try several intervals, untick *Replace the original shape*: the original stays, and you can
  run Spiral on it again.
* Big shapes at small intervals give long toolpaths: an 80 mm heart at 0.1 mm is about 30 m of
  line. It takes a few seconds to compute.

## Uninstall

Close Falcon Design Space, then *Settings → Apps → FalconMods → Uninstall* (or Start menu →
FalconMods → Uninstall). The original Falcon Design Space files are restored. Your camera
calibration stays as it is; use a backup from `falconmods_backups` if you want an older one.

## Troubleshooting

| Problem | Fix |
|---|---|
| No "Quick Calibrate" card | The card only shows for the *Creality Falcon A1*. Re-run the installer after app updates. |
| "The FalconMods helper could not be started" | Re-run the installer (it registers the `falconbedgrid://` link). |
| "Markers not found" | The whole pattern must be in view and clearly burned. Recapture, or double-click the centres by hand. |
| *Apply* keeps spinning | The app wasn't closed (save prompt cancelled?). Wait for the message, then click Apply again. |
| A browser asks to open "FalconBedGridCalib" | Only allow it if you clicked something in Falcon Design Space. The links can only recalibrate or restart the app, never touch other files. |
| "only N grid points found" | Lid not fully closed, honeycomb still in, or the bed is covered. |
| Camera image looks shifted after calibration | Check the processing height, then adjust Camera Offset X/Y. |
| No *Spiral* button | Re-run the installer and make sure *Spiral fill tool* is ticked. |
| "No closed vector shape in the selection" | Images can't be spiralled. Select a vector shape (convert the image to a vector first). |
| "The shape is too small for this interval" | The shape is narrower than one interval. Use a smaller interval. |
| Installer says patching failed | Your Falcon Design Space version changed the patched screens. Nothing was modified. Check for a FalconMods update. |

Logs: `%LOCALAPPDATA%\Falcon Design Space\falconmods\bedgrid.log` (calibration helper) and
`<Falcon Design Space folder>\falconmods\install.log` (installer).
