// FalconMods: "Quick Calibration" card on the Prepare Calibration page (next to the stock
// Camera Calibration and Camera Alignment cards). Opens FalconModsQuickCalibPage.
import QtQuick 2.15
import QtQuick.Layouts 1.15
import "qrc:/"
import "qrc:/qml/Common"
import "../../"

Rectangle {
    id: bedGridCard
    radius: 6
    color: "#EAEDF1"

    readonly property bool supported: deviceCtl.displayName === "Creality Falcon A1"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 10

        CLabel {
            Layout.alignment: Qt.AlignHCenter
            text: qsTr("Quick Calibration")
            font.pixelSize: Constants.fontSize.Px14
            font.weight: Font.Bold
        }

        CLabel {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignLeft
            wrapMode: Text.WordWrap
            lineHeight: 1.2
            text: qsTr("Lens distortion and alignment in one step, from the grid printed on the bed. No card, no engraving.")
            font.pixelSize: Constants.fontSize.Px12
            color: "#333333"
        }

        // Small drawing of the bed grid
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            Layout.preferredWidth: 140
            Layout.preferredHeight: 110
            color: "#1d2129"
            radius: 4
            Rectangle {
                anchors.fill: parent
                anchors.margins: 10
                color: "transparent"
                border.color: "#9ED8F0"
                border.width: 2
                Repeater {
                    model: 2
                    Rectangle { x: (index + 1) * parent.width / 3 - 1; width: 1.5; height: parent.height; color: "#E5E6EB" }
                }
                Repeater {
                    model: 2
                    Rectangle { y: (index + 1) * parent.height / 3 - 1; height: 1.5; width: parent.width; color: "#E5E6EB" }
                }
            }
        }

        Item { Layout.fillHeight: true }

        CButton {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: Math.max(implicitWidth + 40, 140)
            state: "primary"
            text: qsTr("Quick Calibrate")
            enabled: bedGridCard.supported
            onClicked: camearaCalibreation.workbenchViewIndex = 2
        }

        CLabel {
            Layout.alignment: Qt.AlignHCenter
            text: bedGridCard.supported ? " " : qsTr("Only for the Creality Falcon A1")
            font.pixelSize: Constants.fontSize.Px12
            color: bedGridCard.supported ? "transparent" : "#db0d27"
        }
    }
}
