// FalconMods dev hook (development builds only): loads <appDir>/falconmods/dev/<run>/run.qml.
// Every run needs a new folder: Qt caches components by URL and caches directory listings
// (a new file in a folder it already read fails with "File name case mismatch").
import QtQuick 2.15
import Qt.labs.folderlistmodel 2.15

Item {
    id: devHook

    FolderListModel {
        id: devFiles
        folder: "file:///" + String(clApplication.appDir) + "/falconmods/dev"
        showDirs: true
        showFiles: false
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: {
            if (devFiles.count > 0) {
                // FolderListModel reports "c:/"; Qt's file-name case check wants the real "C:/"
                var url = String(devFiles.get(0, "fileUrl")).replace(/^file:\/\/\/([a-z]):/, function (m, d) {
                    return "file:///" + d.toUpperCase() + ":"
                }) + "/run.qml"
                if (url !== String(devLoader.source)) {
                    console.warn("FalconMods dev hook: loading " + url)
                    devLoader.source = url
                }
            }
        }
    }

    Loader {
        id: devLoader
        onStatusChanged: if (status === Loader.Error) console.warn("FalconMods dev hook: error loading " + source)
    }

    Component.onCompleted: console.warn("FalconMods dev hook: watching " + devFiles.folder)
}
