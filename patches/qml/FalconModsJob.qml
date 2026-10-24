// FalconMods: runs one request of the FalconBedGridCalib helper and waits for its answer.
// The helper is started through the falconbedgrid:// URL protocol (registered by the installer)
// and publishes <appDir>/falconmods/jobs/<token>/result.qml (+ images) when it is done.
// See calib/falcon_bedgrid/jobs.py for the other side.
import QtQuick 2.15
import Qt.labs.folderlistmodel 2.15

Item {
    id: job
    visible: false

    property string token: ""
    property string folderUrl: ""        // file:///.../falconmods/jobs/<token>, valid after finished()
    property bool running: false
    property int timeoutMs: 120000
    signal finished(var result)

    readonly property string jobsPath: String(clApplication.appDir) + "/falconmods/jobs"
    readonly property string jobsUrl: "file:///" + jobsPath

    // FolderListModel reports "file:///c:/..."; Qt's file-name case check wants "C:".
    function fixDrive(u) {
        return String(u).replace(/^file:\/\/\/([a-z]):/, function (m, d) { return "file:///" + d.toUpperCase() + ":" })
    }

    // Step 1: reserve a token (and e.g. save an input image named after it).
    function prepare() {
        token = "fm" + Date.now().toString(36) + Math.floor(Math.random() * 1e8).toString(36)
        folderUrl = ""
        resultLoader.source = ""
        return token
    }

    // Step 2: start the helper. `query` = extra URL parameters ("device=...&image=10").
    function launch(action, query) {
        if (!token)
            prepare()
        running = true
        poll.restart()
        timeout.restart()
        var url = "falconbedgrid://" + action + "?token=" + token + (query ? "&" + query : "")
        if (!Qt.openUrlExternally(url))
            fail(qsTr("The FalconMods helper could not be started. Please run the FalconMods installer again."))
    }

    function start(action, query) {
        prepare()
        launch(action, query)
    }

    function cancel() {
        running = false
        poll.stop()
        timeout.stop()
    }

    function fail(message) {
        cancel()
        finished({ status: "error", message: message })
    }

    FolderListModel {
        id: jobsModel
        folder: job.jobsUrl
        showDirs: true
        showFiles: false
    }

    Timer {
        id: poll
        interval: 400
        repeat: true
        property int ticks: 0
        onTriggered: {
            ticks++
            for (var i = 0; i < jobsModel.count; i++) {
                if (jobsModel.get(i, "fileName") === job.token) {
                    stop()
                    job.folderUrl = job.fixDrive(jobsModel.get(i, "fileUrl"))
                    resultLoader.source = job.folderUrl + "/result.qml"
                    return
                }
            }
            // The jobs folder may not have existed when the model was created: nudge it.
            if (ticks % 10 === 0)
                jobsModel.folder = (ticks % 20 === 0) ? job.jobsUrl : job.jobsUrl + "/"
        }
    }

    Timer {
        id: timeout
        interval: job.timeoutMs
        onTriggered: job.fail(qsTr("The FalconMods helper did not answer in time."))
    }

    Loader {
        id: resultLoader
        onStatusChanged: {
            if (status === Loader.Ready) {
                var r = item.result
                job.running = false
                timeout.stop()
                job.finished(r)
            } else if (status === Loader.Error) {
                job.fail(qsTr("The helper's answer could not be read."))
            }
        }
    }
}
