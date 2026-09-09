import QtQuick
import Quickshell
import Quickshell.Io
import "HistoryLifecycle.js" as HistoryLifecycle

ShellRoot {
  id: root

  property bool streamFinished: false
  property bool processExited: false
  property int completedUpdates: 0
  property int collectedBytes: -1
  property string collectedText: ""
  property bool failed: false

  function fail(message) {
    failed = true
    console.error("QML_LIFECYCLE_FAIL " + message)
    Qt.quit()
  }

  function verifyCallbackOrders() {
    var streamFirstUpdates = 0
    var streamDone = true
    var processDone = false
    if (HistoryLifecycle.shouldFinish(streamDone, processDone, false, false)) streamFirstUpdates += 1
    processDone = true
    if (HistoryLifecycle.shouldFinish(streamDone, processDone, false, false)) streamFirstUpdates += 1

    var exitFirstUpdates = 0
    streamDone = false
    processDone = true
    if (HistoryLifecycle.shouldFinish(streamDone, processDone, false, false)) exitFirstUpdates += 1
    streamDone = true
    if (HistoryLifecycle.shouldFinish(streamDone, processDone, false, false)) exitFirstUpdates += 1

    if (streamFirstUpdates !== 1 || exitFirstUpdates !== 1) {
      fail("callback order coordination")
      return false
    }
    if (HistoryLifecycle.shouldFinish(true, true, true, false)
        || HistoryLifecycle.shouldFinish(true, true, false, true)) {
      fail("aborted lifecycle coordination")
      return false
    }
    return true
  }

  function finishIfReady() {
    if (!streamFinished || !processExited || failed) return
    completedUpdates += 1
    if (completedUpdates !== 1) {
      fail("completion count=" + completedUpdates)
      return
    }
    if (collectedBytes !== 6) {
      fail("collector byte count=" + collectedBytes)
      return
    }
    if (collectedText !== "é🙂") {
      fail("collector text mismatch")
      return
    }
    console.log("QML_LIFECYCLE_OK bytes=" + collectedBytes + " updates=" + completedUpdates)
    Qt.quit()
  }

  Component.onCompleted: {
    if (!verifyCallbackOrders()) return
    detachedWriter.startDetached()
    producer.running = true
  }

  Process {
    id: detachedWriter
    command: [
      "/usr/bin/python",
      "-c",
      "import pathlib,time;time.sleep(0.3);pathlib.Path('/tmp/backup-history-qml-detached-marker').write_text('survived')"
    ]
  }

  Process {
    id: producer
    command: [
      "/usr/bin/python",
      "-c",
      "import os;os.write(1,'é🙂'.encode('utf-8'))"
    ]
    stdout: StdioCollector {
      id: collector
      waitForEnd: false
      onDataChanged: root.collectedBytes = collector.data.byteLength
      onStreamFinished: {
        root.collectedBytes = collector.data.byteLength
        root.collectedText = collector.text
        root.streamFinished = true
        root.finishIfReady()
      }
    }
    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0) {
        root.fail("producer exit=" + exitCode)
        return
      }
      root.processExited = true
      root.finishIfReady()
    }
  }

  Timer {
    interval: 3000
    running: true
    repeat: false
    onTriggered: root.fail("timeout")
  }
}
