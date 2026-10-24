// FalconMods: "Spiral" tool in the top toolbar, next to Offset.
// Turns the selected closed shapes into one continuous spiral toolpath (Line Engraving):
//   1. clApplication.saveSvg() exports the canvas (all shapes, mm)
//   2. a hidden WebEngineView reads that file and runs FalconModsSpiral.js (see
//      FalconModsSpiralPage.js; QML's own JS engine is far too slow for this)
//   3. webCommon.saveSvg() imports the spiral, which is moved onto the original's position
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtWebEngine
import org.Cl.qml 1.0
import "FalconModsSpiralSource.js" as SpiralSource

ClToolButtonIUT {
    id: spiralTool

    // from ClTopToolBar
    property var canvas: null
    property string hoveredColor: "#EBEBEB"

    property real interval: 0.2
    property bool replaceOriginal: true
    property bool busy: false
    property var page: null
    property bool pageReady: false
    property var pending: null

    text: qsTr("Spiral")
    icon.source: "qrc:/image/falconmods/spiral.svg"
    enabled: clApplication.selectedCount > 0 && clApplication.selectedType !== "Invalid" && !busy
    background: Rectangle {
        radius: 8
        color: parent.hovered || parent.checked || parent.pressed ? spiralTool.hoveredColor : "transparent"
    }
    onClicked: {
        spiralMenu.x = x
        spiralMenu.y = y + height
        spiralMenu.open()
    }

    ClToolTip {
        text: qsTr("Spiral fill: turn the selected closed shapes into one continuous spiral line")
        visible: parent.hovered
    }

    function tmpDir() {
        return "file:///" + String(clApplication.appDir) + "/tmp/"
    }

    function start() {
        var shapes = clApplication.getCurrProject().getSelectedShapes()
        var boxes = []
        for (var i = 0; i < shapes.length; i++) {
            var r = shapes[i].getBoundingRect()
            if (r && r.width > 0 && r.height > 0)
                boxes.push({ x: r.x, y: r.y, width: r.width, height: r.height })
        }
        if (!boxes.length) {
            clToast.show(qsTr("Select a closed vector shape first"), 4000)
            return
        }
        busy = true
        var url = tmpDir() + "falconmods_spiral_" + Date.now() + ".svg"
        clApplication.saveSvg(url)
        pending = { url: url, boxes: boxes, interval: interval }
        if (!page) {
            page = pageComponent.createObject(spiralTool)
            page.loadHtml("<html><body></body></html>", tmpDir())
        } else if (pageReady) {
            runPending()
        }
    }

    function runPending() {
        var job = pending
        pending = null
        page.runJavaScript("falconModsSpiral(" + JSON.stringify(job) + ")", function (result) {
            finish(result)
        })
    }

    function finish(result) {
        busy = false
        var res
        try { res = JSON.parse(result) } catch (e) { res = { error: String(result) } }
        if (res.error) {
            console.warn("FalconMods spiral: " + res.error)
            if (res.error === "small")
                clToast.show(qsTr("The shape is too small for this interval"), 5000)
            else if (res.error === "nopath")
                clToast.show(qsTr("No closed vector shape in the selection"), 5000)
            else
                clToast.show(qsTr("Spiral fill failed"), 5000)
            return
        }
        if (replaceOriginal)
            clApplication.deleteSelectedShapes()
        if (!webCommon.saveSvg(res.svg)) {
            clToast.show(qsTr("Spiral fill failed"), 5000)
            return
        }
        moveSelectionTo(res.box[0], res.box[1])
        clApplication.setSelectShapesLayerMode(ClLayer.Line)
        clToast.show(qsTr("Spiral fill: %1 path(s), %2 m").arg(res.paths).arg((res.length / 1000).toFixed(1)), 4000)
    }

    function selectionBounds() {
        var s = clApplication.getCurrProject().getSelectedShapes()
        var x0 = Infinity, y0 = Infinity
        for (var i = 0; i < s.length; i++) {
            var r = s[i].getBoundingRect()
            x0 = Math.min(x0, r.x)
            y0 = Math.min(y0, r.y)
        }
        return { x: x0, y: y0 }
    }

    // The import lands in the canvas centre. Move it in the selection's origin coordinates
    // (the same path as the X/Y fields); their y axis can point either way, so measure and correct.
    function moveSelectionTo(x, y) {
        canvas.select.updateSelected()
        var sx = 1, sy = 1
        for (var it = 0; it < 4; it++) {
            var b = selectionBounds(), dx = x - b.x, dy = y - b.y
            if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001)
                return
            var r = canvas.getOriginRect(canvas.select.selectBoundingRect)
            r.x += sx * dx
            r.y += sy * dy
            canvas.select.selectBoundingRect = canvas.getTransformRect(r)
            var a = selectionBounds()
            if (Math.abs(dx) > 0.001 && (a.x - b.x) * dx < 0) sx = -sx
            if (Math.abs(dy) > 0.001 && (a.y - b.y) * dy < 0) sy = -sy
        }
    }

    Component {
        id: pageComponent
        WebEngineView {
            width: 8
            height: 8
            visible: false
            onLoadingChanged: function (request) {
                if (request.status === WebEngineView.LoadSucceededStatus) {
                    runJavaScript(SpiralSource.code, function () {
                        spiralTool.pageReady = true
                        if (spiralTool.pending)
                            spiralTool.runPending()
                    })
                } else if (request.status === WebEngineView.LoadFailedStatus) {
                    spiralTool.busy = false
                    spiralTool.pending = null
                    clToast.show(qsTr("Spiral fill failed"), 5000)
                }
            }
        }
    }

    Popup {
        id: spiralMenu
        leftPadding: 10
        rightPadding: 10
        topPadding: 8
        bottomPadding: 8

        ColumnLayout {
            RowLayout {
                ClText {
                    text: qsTr("Line interval(mm)")
                    color: "#d9d9d9"
                }
                Item { Layout.fillWidth: true }
                ClDoubleSpinBox {
                    id: intervalBox
                    realFrom: 0.05
                    realTo: 5
                    realStepSize: 0.05
                    decimals: 2
                    realValue: spiralTool.interval
                    onNewRealValue: spiralTool.interval = value
                    palette.text: (intervalBox.hovered || intervalBox.activeFocus) ? "#ffffff" : "#DCDCDC"
                    background: Rectangle {
                        color: "transparent"
                        border.color: (intervalBox.hovered || intervalBox.activeFocus) ? "#DCDCDC" : "#37383a"
                        border.width: intervalBox.activeFocus ? 1.5 : 1
                        radius: 8
                    }
                }
            }
            CheckBox {
                id: replaceBox
                checked: spiralTool.replaceOriginal
                onToggled: spiralTool.replaceOriginal = checked
                text: qsTr("Replace the original shape")
                contentItem: Text {
                    text: replaceBox.text
                    color: "#d9d9d9"
                    font.pixelSize: 12
                    leftPadding: replaceBox.indicator.width + replaceBox.spacing
                    verticalAlignment: Text.AlignVCenter
                }
            }
            ClText {
                Layout.maximumWidth: 260
                wrapMode: Text.WordWrap
                text: qsTr("Creates one continuous spiral line on a Line Engraving layer.")
                color: "#9a9a9a"
            }
            ClButtonPrimary {
                Layout.alignment: Qt.AlignRight
                text: spiralTool.busy ? qsTr("Working...") : qsTr("confirm")
                enabled: !spiralTool.busy
                btnRadius: parent.height / 2
                onClicked: {
                    spiralMenu.close()
                    spiralTool.start()
                }
            }
        }

        background: Rectangle {
            color: "#1E1E1E"
            radius: 8
        }
    }
}
