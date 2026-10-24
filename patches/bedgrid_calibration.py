"""Camera tools: "Quick Calibration" (bed-grid camera calibration) and automatic marker detection
in the stock "Camera Alignment" step.

Both use the FalconBedGridCalib helper through the falconbedgrid:// URL protocol and the job
folders described in calib/falcon_bedgrid/jobs.py.
"""

ID = "bedgrid_calibration"
DESCRIPTION = "Quick Calibration from the bed grid + automatic alignment-marker detection (Falcon A1)"

PREPARE = "CameraModule/Qml/PrepareCalibration.qml"
STACK = "CameraModule/Qml/CameraCalibrationV1.qml"
ALIGN = "CameraModule/Qml/CameraAlignView.qml"

IS_A1 = 'deviceCtl.displayName === "Creality Falcon A1"'

ALIGN_LOGIC = '''    property int alignPointsCount: cameraAlignImage.pointsCount
    // FalconMods: automatic marker detection
    property bool hasAlignImage: false

    function detectMarkers() {
        if (markerJob.running)
            return
        var token = markerJob.prepare()
        var path = String(clApplication.appDir) + "/image/falconmods_align_" + token + ".jpg"
        if (!cameraAlignImage.saveAlignImageToJpeg(path)) {
            clToast.show(qsTr("Take a photo of the engraved markers first"), 5000)
            return
        }
        markerJob.launch("markers", "")
    }

    FalconModsJob {
        id: markerJob
        timeoutMs: 60000
        onFinished: function (r) {
            if (r.status !== "ok") {
                clToast.show(qsTr("Markers not found: %1").arg(r.message), 8000)
                return
            }
            var pts = []
            for (var i = 0; i < 4; i++) {
                var p = Qt.point(r.points[i][0], r.points[i][1])
                clCamera.setPielPos(i, p)
                pts.push(p)
            }
            cameraAlignImage.setPoints(pts)
            cameraAlignRoot.pielPosIndex = 4
            cameraAlignImage.update()
            clToast.show(qsTr("All 4 markers found. Check the marks, then click Finish."), 6000)
        }
    }
'''

DETECT_BUTTON = '''                        cameraAlignRoot.pielPosIndex = 0
                        cameraAlignImage.reset()
                    }
                }
                // FalconMods
                CButton {
                    text: qsTr("Detect markers")
                    state: "primary"
                    width: 145
                    visible: %s
                    enabled: cameraAlignRoot.hasAlignImage && !markerJob.running && !cameraAlignRoot.captureWaiting
                    onClicked: cameraAlignRoot.detectMarkers()
                    Spinner {
                        anchors.centerIn: parent
                        running: markerJob.running
                    }
                }
''' % IS_A1

STOCK_HINT = ('qsTr("2. In the captured photo, double-click the center point of each marker in the order '
              '1, 2, 3, 4 to obtain coordinates. (Refer to the right image)")')

PATCHES = [
    # --- new components
    {"rcc": "qml.rcc", "file": "CameraModule/Qml/FalconModsBedGridCard.qml", "new_file": True,
     "source": "qml/FalconModsBedGridCard.qml"},
    {"rcc": "qml.rcc", "file": "CameraModule/Qml/FalconModsQuickCalibPage.qml", "new_file": True,
     "source": "qml/FalconModsQuickCalibPage.qml"},
    {"rcc": "qml.rcc", "file": "CameraModule/Qml/FalconModsJob.qml", "new_file": True,
     "source": "qml/FalconModsJob.qml"},

    # --- Prepare Calibration page: third card
    {
        "rcc": "qml.rcc", "file": PREPARE,
        "find": "    property real cardHorizontalPadding: 28\n",
        "replace": (
            "    property real cardHorizontalPadding: 28\n"
            "    // FalconMods: make room for the Quick Calibration card\n"
            "    property real cardWidth: " + IS_A1 + "\n"
            "                             ? Math.max(300, Math.min(420, (width - 360 - 36) / 3)) : 420\n"
        ),
    },
    {"rcc": "qml.rcc", "file": PREPARE, "find": "Layout.preferredWidth: 420\n",
     "replace": "Layout.preferredWidth: cardWidth\n", "count": 2},
    {
        "rcc": "qml.rcc", "file": PREPARE,
        "find": (
            "                        color: \"transparent\"\n"
            "                    }\n"
            "                }\n"
            "            }\n"
        ),
        "replace": (
            "                        color: \"transparent\"\n"
            "                    }\n"
            "                }\n"
            "            }\n"
            "\n"
            "            // FalconMods\n"
            "            FalconModsBedGridCard {\n"
            "                Layout.preferredWidth: cardWidth\n"
            "                Layout.preferredHeight: cardHeight\n"
            "                visible: supported\n"
            "            }\n"
        ),
    },

    # --- calibration stack: Quick Calibration page = index 2
    {
        "rcc": "qml.rcc", "file": STACK,
        "find": "            // }\n        }\n    }\n",
        "replace": (
            "            // }\n        }\n"
            "        // FalconMods\n"
            "        FalconModsQuickCalibPage {\n"
            "            Layout.fillWidth: true\n"
            "            Layout.fillHeight: true\n"
            "        }\n"
            "    }\n"
        ),
    },

    # --- Camera Alignment: "Detect markers" instead of double-clicking 4 centres
    {"rcc": "qml.rcc", "file": ALIGN,
     "find": "    property int alignPointsCount: cameraAlignImage.pointsCount\n",
     "replace": ALIGN_LOGIC},
    {"rcc": "qml.rcc", "file": ALIGN,
     "find": "            cameraAlignRoot.captureWaiting = false\n            cameraAlignImage.updateImage(image, 0)\n",
     "replace": ("            cameraAlignRoot.captureWaiting = false\n"
                 "            cameraAlignRoot.hasAlignImage = true\n"
                 "            cameraAlignImage.updateImage(image, 0)\n")},
    {"rcc": "qml.rcc", "file": ALIGN,
     "find": "        captureWaiting = false\n        pielPosIndex = 0\n        cameraAlignImage.pointsClear()\n",
     "replace": ("        captureWaiting = false\n        hasAlignImage = false\n        pielPosIndex = 0\n"
                 "        cameraAlignImage.pointsClear()\n")},
    {"rcc": "qml.rcc", "file": ALIGN,
     "find": ("                        cameraAlignRoot.pielPosIndex = 0\n"
              "                        cameraAlignImage.reset()\n"
              "                    }\n"
              "                }\n"),
     "replace": DETECT_BUTTON},
    {"rcc": "qml.rcc", "file": ALIGN,
     "find": "                    text: " + STOCK_HINT + "\n",
     "replace": ("                    text: " + IS_A1 + "\n"
                 "                          ? qsTr(\"2. Click 'Detect markers' to find the 4 markers automatically, "
                 "or double-click the center of each marker in the order 1, 2, 3, 4. (Refer to the right image)\")\n"
                 "                          : " + STOCK_HINT + "\n")},
]
