import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  id: root

  property var worker: null
  property int targetSessionId: 0
  readonly property string sessionToken: "0123456789abcdef-0123456789abcdef"
  readonly property string fixtureDirectory: "/tmp/backup-history-qml-destruction"

  function destroyActiveWorker() {
    if (!worker) return
    worker.destroy()
    worker = null
    quitTimer.start()
  }

  Component.onCompleted: {
    worker = activeWorkerFactory.createObject(root)
    if (!worker) {
      console.error("QML_DESTRUCTION_FAIL worker creation")
      Qt.quit()
    }
  }

  Component {
    id: activeWorkerFactory

    Item {
      id: activeWorker
      property int backendPid: 0
      property bool readyHandled: false

      Component.onCompleted: backend.running = true
      Component.onDestruction: {
        var pid = backendPid > 1 ? backendPid : Number(backend.processId)
        if (Number.isFinite(pid) && pid > 1) {
          terminator.command = [
            "__TERMINATOR__",
            "--sid", String(Math.floor(pid)),
            "--token", root.sessionToken
          ]
          terminator.startDetached()
          if (backend.running) backend.signal(15)
        }
      }

      Process {
        id: backend
        command: [
          "__FIXTURE__",
          "--directory", root.fixtureDirectory,
          "--session-token", root.sessionToken
        ]
        stdout: StdioCollector {
          id: output
          waitForEnd: false
          onDataChanged: {
            if (!activeWorker.readyHandled && output.text.indexOf("READY") !== -1) {
              activeWorker.readyHandled = true
              root.targetSessionId = activeWorker.backendPid
              Qt.callLater(root.destroyActiveWorker)
            }
          }
        }
        onStarted: {
          activeWorker.backendPid = Math.floor(Number(backend.processId))
          root.targetSessionId = activeWorker.backendPid
        }
      }

      Process {
        id: terminator
        command: []
      }
    }
  }

  Timer {
    id: quitTimer
    interval: 50
    repeat: false
    onTriggered: {
      console.log("QML_DESTRUCTION_DISPATCHED sid=" + root.targetSessionId)
      Qt.quit()
    }
  }

  Timer {
    interval: 4000
    running: true
    repeat: false
    onTriggered: {
      console.error("QML_DESTRUCTION_FAIL timeout")
      Qt.quit()
    }
  }
}
