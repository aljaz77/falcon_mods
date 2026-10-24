// FalconMods: Quick Calibration page (camera calibration from the printed bed grid).
// Lives in CameraCalibrationV1's StackLayout next to the stock pages and uses the same building
// blocks (CButton, CLabel, MessageBoxDialog, step tabs) so it looks like part of the app.
// The heavy lifting is done by the FalconBedGridCalib helper (see FalconModsJob.qml).
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import org.Cl.qml 1.0
import "qrc:/"
import "qrc:/qml/Common"
import "qrc:/qml/Popup"
import "../../"

Rectangle {
    id: page
    color: "#FFFFFF"

    property int step: 0                 // 0 prepare, 1 calibrating, 2 result
    property string phase: ""            // text under the spinner
    property var result: null
    property bool applying: false
    property bool capturing: false
    readonly property bool resultOk: result !== null && result.status === "ok"

    function reset() {
        step = 0
        result = null
        applying = false
        capturing = false
        job.cancel()
    }

    onVisibleChanged: if (visible) reset()

    function startCalibration() {
        if (!camearaCalibreation || !camearaCalibreation.patternCalibController) {
            clToast.show(qsTr("Camera is not ready"), 5000)
            return
        }
        result = null
        step = 1
        phase = qsTr("Taking a photo of the bed...")
        capturing = true
        captureTimeout.restart()
        camearaCalibreation.patternCalibController.startCapture(10)
    }

    function captureDone(ok, message) {
        if (!capturing)
            return
        capturing = false
        captureTimeout.stop()
        if (!ok) {
            result = { status: "error", message: message && message.length ? message : qsTr("The camera photo failed.") }
            step = 2
            return
        }
        phase = qsTr("Finding the bed grid and fitting the lens model...")
        var dev = ""
        try { dev = clCamera.getCrrMachineId() } catch (e) { dev = "" }
        job.start("calibrate", "image=10&device=" + encodeURIComponent(dev))
    }

    function apply() {
        // The helper closes the app (it may ask to save the project), writes the calibration of
        // this job and starts the app again - so there is no answer to wait for.
        if (!Qt.openUrlExternally("falconbedgrid://apply?token=" + job.token)) {
            clToast.show(qsTr("The FalconMods helper could not be started. Please run the FalconMods installer again."), 8000)
            return
        }
        applying = true
        clToast.show(qsTr("Falcon Design Space restarts to load the new calibration..."), 8000)
    }

    Timer {
        id: captureTimeout
        interval: 30000
        onTriggered: page.captureDone(false, qsTr("The camera photo timed out."))
    }

    Connections {
        target: cameraPosition
        function onSignal_ImageCaptured() {
            if (cameraPosition.ImageCaptured === 10)
                page.captureDone(true)
        }
        function onCameraCaptureError(errorCode, errorDesc, fromUserCapture) {
            page.captureDone(false, errorDesc)
        }
    }

    FalconModsJob {
        id: job
        timeoutMs: 120000
        onFinished: function (r) {
            page.result = r
            page.step = 2
        }
    }

    MessageBoxDialog {
        id: applyDlg
        title: qsTr("Apply calibration")
        iconType: MessageBoxDialog.Warning
        standardButtons: CDialog.Ok | CDialog.Cancel
        positiveButton.text: qsTr("Apply and restart")
        text: qsTr("Falcon Design Space restarts to load the new camera calibration. If your project has unsaved changes you will be asked to save them first.")
        onAccepted: page.apply()
    }

    CButton {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 16
        state: "icon"
        iconSource: "qrc:/qml/res/control/close.svg"
        enabled: !page.applying
        onClicked: {
            page.reset()
            workbenchStack.workbenchViewIndex = 0
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 70
        spacing: 0

        // ---- step tabs (same look as the stock calibration pages)
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            Row {
                anchors.centerIn: parent
                Repeater {
                    model: [qsTr("Prepare"), qsTr("Calibrate"), qsTr("Result")]
                    delegate: Item {
                        implicitWidth: tabRow.implicitWidth + 72
                        implicitHeight: 48
                        Row {
                            id: tabRow
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 16
                            rightPadding: 40
                            Rectangle {
                                width: 24; height: 24; radius: 12
                                color: page.step === index ? "#12D1EB" : "#F2F3F5"
                                Text {
                                    anchors.centerIn: parent
                                    text: (index + 1).toString()
                                    color: page.step === index ? "#FFFFFF" : "#4e5969"
                                    font.pixelSize: Constants.fontSize.Px12
                                    visible: page.step <= index
                                }
                                Image { anchors.centerIn: parent; source: "qrc:image/autofocus/ok.svg"; visible: page.step > index }
                            }
                            Text {
                                text: modelData
                                height: 24
                                verticalAlignment: Text.AlignVCenter
                                color: page.step === index ? "#1d2129" : "#4e5969"
                                font.pixelSize: Constants.fontSize.Px14
                                font.bold: page.step === index
                            }
                        }
                        Rectangle {
                            width: parent.width - 24; height: 2
                            anchors.left: parent.left; anchors.bottom: parent.bottom
                            color: page.step === index ? "#12D1EB" : "#ffffff"
                        }
                        Icon {
                            anchors.right: parent.right
                            size: 24
                            source: "qrc:image/autofocus/rightArrow.svg"
                            visible: index < 2
                            colorize: false
                        }
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 24
            currentIndex: page.step

            // ---- 1. prepare
            Item {
                RowLayout {
                    anchors.centerIn: parent
                    spacing: 60

                    Rectangle {
                        Layout.preferredWidth: 360
                        Layout.preferredHeight: 290
                        radius: 8
                        color: "#1d2129"
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 28
                            color: "transparent"
                            border.color: "#9ED8F0"
                            border.width: 3
                            Repeater {
                                model: 2
                                Rectangle { x: (index + 1) * parent.width / 3 - 1; width: 2; height: parent.height; color: "#E5E6EB" }
                            }
                            Repeater {
                                model: 2
                                Rectangle { y: (index + 1) * parent.height / 3 - 1; height: 2; width: parent.width; color: "#E5E6EB" }
                            }
                            Repeater {
                                model: 4
                                Text {
                                    x: ((index % 2) + 1) * parent.width / 3 - width / 2
                                    y: (Math.floor(index / 2) + 1) * parent.height / 3 - height / 2
                                    text: "+"; color: "#FFFFFF"; font.pixelSize: 22; font.bold: true
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 420
                        spacing: 18
                        CLabel {
                            text: qsTr("Quick Calibration")
                            font.pixelSize: Constants.fontSize.Px14 + 4
                            font.weight: Font.Bold
                        }
                        CLabel {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            lineHeight: 1.3
                            color: "#4e5969"
                            text: qsTr("Calibrates lens distortion and camera alignment in one step from the grid printed on the bed plate. One photo, no calibration card and no engraving.")
                        }
                        Repeater {
                            model: [
                                qsTr("Take out the honeycomb panel and clear the bed. Small marks and stains are fine."),
                                qsTr("Close the lid completely. The camera sits in the lid."),
                                qsTr("Make sure the laser is connected so the camera can take a photo.")
                            ]
                            delegate: RowLayout {
                                Layout.fillWidth: true
                                spacing: 12
                                Rectangle {
                                    Layout.alignment: Qt.AlignTop
                                    width: 22; height: 22; radius: 11; color: "#E8FAFD"
                                    Text { anchors.centerIn: parent; text: index + 1; color: "#12A9C0"; font.bold: true; font.pixelSize: Constants.fontSize.Px12 }
                                }
                                CLabel {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: modelData
                                    color: "#1d2129"
                                }
                            }
                        }
                        CLabel {
                            visible: deviceCtl.displayName !== "Creality Falcon A1"
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: "#db0d27"
                            text: qsTr("Quick Calibration is made for the Creality Falcon A1 bed plate.")
                        }
                    }
                }
            }

            // ---- 2. calibrating
            Item {
                Column {
                    anchors.centerIn: parent
                    spacing: 20
                    Spinner {
                        anchors.horizontalCenter: parent.horizontalCenter
                        running: page.step === 1
                        width: 48; height: 48
                    }
                    CLabel {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: page.phase
                        color: "#4e5969"
                    }
                }
            }

            // ---- 3. result
            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 16

                    // status banner
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: bannerText.implicitHeight + 24
                        radius: 6
                        color: page.resultOk ? "#E8FFEA" : "#FFECE8"
                        CLabel {
                            id: bannerText
                            anchors.fill: parent
                            anchors.margins: 12
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignVCenter
                            color: page.resultOk ? "#00A146" : "#CB2634"
                            text: !page.result ? ""
                                  : page.result.status === "ok"
                                    ? qsTr("Calibration looks good. Check that the bed view on the right is straight, then click Apply.")
                                    : page.result.status === "rejected"
                                      ? qsTr("Calibration rejected: %1. Close the lid, remove the honeycomb panel and loose items, then try again.").arg(page.result.message)
                                      : qsTr("Calibration failed: %1").arg(page.result.message)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 16
                        visible: page.result !== null && page.result.status !== "error"
                        Repeater {
                            model: [
                                { file: "detect.jpg", caption: qsTr("Camera photo with the detected grid") },
                                { file: "bed.jpg", caption: qsTr("Bed view after calibration (50 mm check grid)") }
                            ]
                            delegate: ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                spacing: 6
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    color: "#F2F3F5"
                                    radius: 6
                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        cache: false
                                        source: page.step === 2 && job.folderUrl ? job.folderUrl + "/" + modelData.file : ""
                                    }
                                }
                                CLabel {
                                    text: modelData.caption
                                    color: "#86909c"
                                    font.pixelSize: Constants.fontSize.Px12
                                }
                            }
                        }
                    }

                    GridLayout {
                        visible: page.result !== null && page.result.status !== "error"
                        columns: 4
                        columnSpacing: 24
                        rowSpacing: 6
                        CLabel { text: qsTr("Fit error"); color: "#86909c" }
                        CLabel { text: page.result ? page.result.rmsPx + " px" : "" }
                        CLabel { text: qsTr("Grid found"); color: "#86909c" }
                        CLabel { text: page.result ? page.result.coverage + " %  (" + page.result.points + " " + qsTr("points") + ")" : "" }
                        CLabel { text: qsTr("Change vs. current"); color: "#86909c" }
                        CLabel {
                            text: page.result && page.result.changeMedianMm !== null && page.result.changeMedianMm !== undefined
                                  ? qsTr("median %1 mm, max %2 mm").arg(page.result.changeMedianMm).arg(page.result.changeMaxMm) : "-"
                        }
                        CLabel { text: qsTr("Laser reference"); color: "#86909c" }
                        CLabel {
                            Layout.maximumWidth: 420
                            elide: Text.ElideRight
                            text: page.result && page.result.registration ? page.result.registration : "-"
                        }
                    }
                }
            }
        }

        // ---- bottom buttons
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            Layout.topMargin: 16
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 30
                CButton {
                    width: 145
                    state: "line"
                    visible: page.step === 2
                    enabled: !page.applying
                    text: qsTr("Retake")
                    onClicked: page.startCalibration()
                }
                CButton {
                    width: 145
                    state: "primary"
                    visible: page.step !== 1
                    isBusy: page.applying
                    enabled: page.step === 0 ? deviceCtl.displayName === "Creality Falcon A1" : page.resultOk && !page.applying
                    text: page.step === 0 ? qsTr("Calibrate") : qsTr("Apply")
                    onClicked: page.step === 0 ? page.startCalibration() : applyDlg.open()
                }
            }
        }
    }

    // same rotating circle as the stock alignment page (that one is file-local there)
    component Spinner: Image {
        id: spinner
        property bool running: false
        source: "qrc:/image/circle.svg"
        sourceSize: Qt.size(64, 64)
        visible: running
        RotationAnimator {
            target: spinner
            from: 0
            to: 360
            duration: 700
            easing.type: Easing.OutInQuad
            loops: Animation.Infinite
            running: spinner.running
        }
    }
}
