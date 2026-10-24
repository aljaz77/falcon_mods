"""Unlock every fill pattern (incl. concentric "Offset Fill") and the fill angle on gantry lasers.

The C++ engine implements ClLayer.FillPattern {OneWay, Bidirectional, Cross, Offset, ZigZag}
for every device; the QML only hides the extra entries unless the device is a galvo.
"""

ID = "fill_patterns"
DESCRIPTION = "Show Cross / Offset (concentric) / Zigzag fill and fill angle on gantry lasers (A1)"

PATCHES = [
    {
        "rcc": "qml_new.rcc",
        "file": "qml/Popup/LayerEditorPopup.qml",
        "find": "    readonly property bool supportAllFillPatterns: deviceCtl.currDevice.isGalvo\n",
        "replace": (
            "    // FalconMods: gantry lasers support every fill pattern in the engine as well\n"
            "    readonly property bool supportAllFillPatterns: !deviceCtl.currDevice.isGalvo ||\n"
            "                                                    deviceCtl.currDevice.isGalvo\n"
        ),
    },
]
