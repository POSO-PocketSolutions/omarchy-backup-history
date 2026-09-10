import QtQuick
import QtQuick.Effects
import Quickshell.Io
import qs.Commons
import qs.Ui
import "HistoryLifecycle.js" as HistoryLifecycle

Panel {
  id: root
  moduleName: "io.github.mnsosa.backup-history"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var days: []
  property var summary: ({ "success": 0, "failed": 0, "missing": 0 })
  property var latest: null
  property var latestSuccess: null
  property var target: null
  property bool setupOpen: false
  property bool setupDismissed: false
  property int setupStep: 0
  property string setupService: ""
  property var setupDisk: null
  property var setupServices: []
  property var setupDisks: []
  property string setupError: ""
  property bool setupBusy: false
  property bool setupServiceFailed: false
  property bool setupApplyPending: false
  property int setupGeneration: 0
  property int setupWriteGeneration: -1
  property var discoverCollector: null
  property string discoverRaw: ""
  property bool discoverAborted: false
  property bool discoverStreamFinished: false
  property bool discoverProcessExited: false
  property string state: "loading"
  property string error: ""
  property var historyCollector: null
  property string historyRaw: ""
  property bool historyStreamFinished: false
  property bool historyProcessExited: false
  property bool historyAborted: false
  property bool historyTearingDown: false
  property int historyProcessId: 0
  property string historySessionToken: ""

  readonly property int historyJsonLimit: 64 * 1024
  readonly property int historyCollectorLimit: 96 * 1024
  readonly property int historyWatchdogMs: 10000
  readonly property int setupServiceLimit: 64
  readonly property int setupDiskLimit: 32

  readonly property var barIdentity: hostWidget || root
  readonly property string service: String(setting("service", "restic-backup.service"))
  readonly property int weeks: Math.max(2, Math.min(12, Number(setting("weeks", 4))))
  readonly property int refreshInterval: Math.max(30, Number(setting("refreshIntervalSec", 60))) * 1000
  readonly property color successColor: String(setting("successColor", "#3fb950"))
  readonly property color foregroundColor: bar ? bar.barForeground : Color.foreground
  readonly property color failureColor: bar ? bar.urgent : Color.urgent
  readonly property color mutedColor: Util.alpha(foregroundColor, 0.42)
  readonly property color missingColor: Util.alpha(foregroundColor, 0.12)
  readonly property color runningColor: Color.accent
  readonly property string backendPath: pathFor("scripts/backup-history")
  readonly property string sessionTerminatorPath: pathFor("scripts/terminate-history-session")
  readonly property string runPath: pathFor("scripts/run-backup")
  readonly property string logsPath: pathFor("scripts/open-logs")
  readonly property string setTargetPath: pathFor("scripts/set-target")
  readonly property string setServicePath: pathFor("scripts/set-service")
  readonly property string shortStatus: {
    if (state === "running") return "Backup in progress"
    if (state === "failed") return "Last backup failed"
    if (latestSuccess) return "Last backup: " + relativeTime(latestSuccess.timestamp)
    return "No successful backups"
  }
  readonly property string statusTitle: {
    if (state === "running") return "Backup in progress"
    if (state === "failed") return "Attention required"
    if (latestSuccess) return "Backups are healthy"
    return "No successful backup"
  }
  readonly property color statusColor: state === "failed"
    ? failureColor
    : state === "running" ? runningColor : latestSuccess ? successColor : mutedColor
  readonly property bool targetConfigured: !!target && target.uuid !== ""
  readonly property bool targetMounted: targetConfigured && !!target.mounted
  readonly property string targetSummary: {
    if (!targetConfigured) return "No backup disk selected"
    if (!targetMounted) return "Backup disk not connected"
    var name = target.label !== "" ? target.label : target.path
    return target.freeBytes === null ? name : name + " · " + formattedBytes(target.freeBytes) + " free"
  }
  readonly property bool setupWriteRunning: setTargetProc.running || setServiceProc.running
  readonly property bool setupRequired: !setupDismissed && !targetConfigured
  readonly property bool showSetup: setupOpen || setupRequired

  // Latch the wizard open: a periodic refresh may reconfigure `target` mid-step,
  // and the wizard must survive that until closeSetup() dismisses it.
  onShowSetupChanged: {
    if (!showSetup) return
    setupOpen = true
    if (setupServices.length === 0) loadDiscovery()
  }

  function pathFor(relativePath) {
    return decodeURIComponent(Qt.resolvedUrl(relativePath).toString().replace("file://", ""))
  }

  function relativeTime(value) {
    if (!value) return "never"
    var seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
    if (seconds < 3600) return Math.max(1, Math.floor(seconds / 60)) + "m ago"
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago"
    return Math.floor(seconds / 86400) + "d ago"
  }

  function formattedBytes(value) {
    var units = ["B", "KB", "MB", "GB", "TB"]
    var size = Number(value)
    var index = 0
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024
      index += 1
    }
    return (size < 10 ? size.toFixed(1) : Math.round(size)) + " " + units[index]
  }

  function formattedTime(value) {
    if (!value) return "Never"
    return Qt.formatDateTime(new Date(value), "ddd, d MMM · HH:mm")
  }

  function dayLabel(day) {
    var labels = { "success": "Successful", "failed": "Failed", "none": "No backup" }
    return Qt.formatDate(new Date(day.date + "T12:00:00"), "ddd, d MMM") + "\n" + labels[day.status]
  }

  function colorFor(day) {
    if (day.today && state === "running") return runningColor
    if (day.status === "success") return successColor
    if (day.status === "failed") return failureColor
    return missingColor
  }

  function setHistoryError(message) {
    days = []
    summary = ({ "success": 0, "failed": 0, "missing": 0 })
    latest = null
    latestSuccess = null
    state = "unknown"
    error = String(message).slice(0, 256)
  }

  function releaseHistoryCollector() {
    var collector = historyCollector
    historyCollector = null
    historyProc.stdout = null
    if (collector) Qt.callLater(function() { collector.destroy() })
  }

  function createHistorySessionToken() {
    var parts = [Date.now().toString(16)]
    for (var index = 0; index < 4; index++)
      parts.push(Math.floor(Math.random() * 0x100000000).toString(16).padStart(8, "0"))
    return parts.join("-")
  }

  function captureHistoryProcessId() {
    var processId = Number(historyProc.processId)
    if (Number.isFinite(processId) && processId > 1)
      historyProcessId = Math.floor(processId)
  }

  function launchHistorySessionCleanup() {
    captureHistoryProcessId()
    if (historyProcessId <= 1 || historySessionToken === "") return
    historySessionTerminator.command = [
      sessionTerminatorPath,
      "--sid", String(historyProcessId),
      "--token", historySessionToken
    ]
    historySessionTerminator.startDetached()
  }

  function startHistory() {
    if (historyProc.running || historyTearingDown) return

    releaseHistoryCollector()
    historyProcessId = 0
    historySessionToken = createHistorySessionToken()
    historyRaw = ""
    historyStreamFinished = false
    historyProcessExited = false
    historyAborted = false

    var collector = historyCollectorFactory.createObject(root)
    if (!collector) {
      setHistoryError("Unable to create bounded output collector")
      return
    }
    historyCollector = collector
    historyProc.stdout = collector
    historyWatchdog.restart()
    historyProc.running = true
  }

  function refresh() {
    startHistory()
  }

  function abortHistory(message) {
    if (historyAborted || historyTearingDown) return
    historyAborted = true
    historyWatchdog.stop()
    setHistoryError(message)
    releaseHistoryCollector()

    if (historyProc.running) {
      launchHistorySessionCleanup()
      historyProc.signal(15)
    }
  }

  function handleHistoryData(collector) {
    if (collector !== historyCollector || historyAborted || historyTearingDown) return
    if (collector.data.byteLength > historyCollectorLimit)
      abortHistory("Backend output exceeded QML collector limit")
  }

  function handleHistoryStreamFinished(collector) {
    if (collector !== historyCollector || historyAborted || historyTearingDown) return
    if (collector.data.byteLength > historyJsonLimit) {
      abortHistory("Backend JSON exceeded size limit")
      return
    }
    historyRaw = collector.text
    historyStreamFinished = true
    finishHistoryIfReady()
  }

  function handleHistoryExited(exitCode) {
    historyProcessExited = true
    if (exitCode !== 0 && !historyAborted && !historyTearingDown)
      launchHistorySessionCleanup()
    historyProcessId = 0
    if (historyAborted || historyTearingDown) {
      historyWatchdog.stop()
      releaseHistoryCollector()
      return
    }
    if (exitCode !== 0) {
      historyWatchdog.stop()
      setHistoryError("Backup history backend exited with status " + exitCode)
      releaseHistoryCollector()
      return
    }
    finishHistoryIfReady()
  }

  function finishHistoryIfReady() {
    if (!HistoryLifecycle.shouldFinish(
      historyStreamFinished,
      historyProcessExited,
      historyAborted,
      historyTearingDown
    )) return
    historyWatchdog.stop()
    update(historyRaw)
    historyRaw = ""
    releaseHistoryCollector()
  }

  function update(raw) {
    try {
      if (raw.length > historyJsonLimit) throw new Error("Backend JSON exceeded size limit")
      var payload = JSON.parse(raw)
      if (!Array.isArray(payload.days) || payload.days.length > weeks * 7)
        throw new Error("Invalid days payload")
      for (var index = 0; index < payload.days.length; index++) {
        var status = payload.days[index].status
        if (status !== "success" && status !== "failed" && status !== "none")
          throw new Error("Invalid day status")
      }
      days = payload.days
      summary = payload.summary || ({ "success": 0, "failed": 0, "missing": 0 })
      latest = payload.latest || null
      latestSuccess = payload.latestSuccess || null
      target = payload.target || null
      state = payload.state || "unknown"
      error = String(payload.error || "").slice(0, 256)
    } catch (exception) {
      setHistoryError(exception)
    }
  }

  function open() {
    refresh()
    controller.show()
  }

  function close() {
    controller.hide()
  }

  function toggle() {
    if (opened) close()
    else open()
  }

  function openLogs() {
    if (bar) bar.run(logsPath + " " + Util.shellQuote(service))
  }

  function openSetup() {
    // A new attempt. Anything still in flight from the previous one carries the
    // old generation and can no longer touch this session's state.
    setupGeneration += 1
    setupOpen = true
    setupStep = 0
    setupError = ""
    setupDisk = null
    setupDisks = []
    setupServices = []
    setupServiceFailed = false
    setupApplyPending = false
    setupService = service
    loadDiscovery()
  }

  function closeSetup() {
    // Leaving the wizard must never wait on a privileged child. Any pkexec still
    // in flight is left to finish or be refused; bumping the generation retires
    // this attempt so the child's exit can no longer drive the UI — but it is
    // still allowed to refresh, so the panel catches up with what it wrote.
    setupGeneration += 1
    setupApplyPending = false
    setupOpen = false
    setupDismissed = true
    setupBusy = false
    refresh()
  }

  function releaseDiscoverCollector() {
    var collector = discoverCollector
    discoverCollector = null
    discoverProc.stdout = null
    if (collector) Qt.callLater(function() { collector.destroy() })
  }

  function loadDiscovery() {
    if (discoverProc.running || historyTearingDown) return

    releaseDiscoverCollector()
    discoverRaw = ""
    discoverAborted = false
    discoverStreamFinished = false
    discoverProcessExited = false

    var collector = discoverCollectorFactory.createObject(root)
    if (!collector) {
      setupError = "Unable to create bounded output collector"
      return
    }
    discoverCollector = collector
    discoverProc.stdout = collector
    discoverWatchdog.restart()
    discoverProc.running = true
  }

  function abortDiscovery(message) {
    if (discoverAborted || historyTearingDown) return
    discoverAborted = true
    discoverWatchdog.stop()
    setupError = message
    releaseDiscoverCollector()

    if (discoverProc.running) discoverProc.signal(15)
  }

  function handleDiscoveryData(collector) {
    if (collector !== discoverCollector || discoverAborted || historyTearingDown) return
    if (collector.data.byteLength > historyCollectorLimit)
      abortDiscovery("Discovery output exceeded QML collector limit")
  }

  function handleDiscoveryStreamFinished(collector) {
    if (collector !== discoverCollector || discoverAborted || historyTearingDown) return
    if (collector.data.byteLength > historyJsonLimit) {
      abortDiscovery("Discovery JSON exceeded size limit")
      return
    }
    discoverRaw = collector.text
    discoverStreamFinished = true
    finishDiscoveryIfReady()
  }

  function handleDiscoveryExited(exitCode) {
    discoverProcessExited = true
    if (discoverAborted || historyTearingDown) {
      discoverWatchdog.stop()
      releaseDiscoverCollector()
      return
    }
    if (exitCode !== 0) {
      discoverWatchdog.stop()
      setupError = "Discovery failed"
      releaseDiscoverCollector()
      return
    }
    finishDiscoveryIfReady()
  }

  function finishDiscoveryIfReady() {
    if (!HistoryLifecycle.shouldFinish(
      discoverStreamFinished,
      discoverProcessExited,
      discoverAborted,
      historyTearingDown
    )) return
    discoverWatchdog.stop()
    handleDiscovery(discoverRaw)
    discoverRaw = ""
    releaseDiscoverCollector()
  }

  function handleDiscovery(text) {
    try {
      var payload = JSON.parse(text)
      var services = Array.isArray(payload.services) ? payload.services : []
      var disks = Array.isArray(payload.disks) ? payload.disks : []
      setupServices = services.slice(0, setupServiceLimit).map(function(entry) {
        return {
          "unit": String(entry.unit || ""),
          "state": String(entry.state || ""),
          "exists": !!entry.exists
        }
      })
      setupDisks = disks.slice(0, setupDiskLimit).map(function(entry) {
        return {
          "uuid": String(entry.uuid || ""),
          "label": String(entry.label || ""),
          "size": String(entry.size || ""),
          "fstype": String(entry.fstype || ""),
          "mountpoint": String(entry.mountpoint || ""),
          "removable": !!entry.removable
        }
      })
      setupError = String(payload.error || "")
    } catch (parseError) {
      setupError = "Could not read disks and services"
    }
  }

  function writerError() {
    var message = String(setTargetErrorCollector.text || "").trim()
    if (message === "") return "Could not write the backup target"
    return message.slice(0, 256)
  }

  function applyTarget() {
    if (setupService === "" || !setupDisk || setupBusy) return
    if (setupWriteRunning) {
      setupError = "A previous change is still being applied"
      return
    }
    setupBusy = true
    setupError = ""
    setupServiceFailed = false
    setupApplyPending = true
    setupWriteGeneration = setupGeneration
    // The privileged write is staged here but started only from
    // setServiceProc.onExited, so the two never race and a failed service
    // selection escalates nothing.
    setTargetProc.command = [
      "/usr/bin/pkexec",
      root.setTargetPath,
      "--unit", setupService,
      "--uuid", setupDisk.uuid,
      "--path", setupDisk.mountpoint,
      "--label", setupDisk.label
    ]
    setServiceProc.command = [root.setServicePath, setupService]
    setServiceProc.running = true
  }

  Component {
    id: historyCollectorFactory

    StdioCollector {
      id: collector
      waitForEnd: false
      onDataChanged: root.handleHistoryData(collector)
      onStreamFinished: root.handleHistoryStreamFinished(collector)
    }
  }

  Process {
    id: historyProc
    command: [
      root.backendPath,
      "--service", root.service,
      "--weeks", String(root.weeks),
      "--session-token", root.historySessionToken
    ]
    stdout: null
    onStarted: root.captureHistoryProcessId()
    onExited: function(exitCode, exitStatus) { root.handleHistoryExited(exitCode) }
  }

  Process {
    id: historySessionTerminator
    command: []
  }

  Process {
    id: runProc
    command: [root.runPath, root.service]
    onExited: root.refresh()
  }

  Component {
    id: discoverCollectorFactory

    StdioCollector {
      id: discoverStreamCollector
      waitForEnd: false
      onDataChanged: root.handleDiscoveryData(discoverStreamCollector)
      onStreamFinished: root.handleDiscoveryStreamFinished(discoverStreamCollector)
    }
  }

  Process {
    id: discoverProc
    command: [root.backendPath, "--mode", "discover", "--service", root.service]
    stdout: null
    onExited: function(exitCode, exitStatus) { root.handleDiscoveryExited(exitCode) }
  }

  Process {
    id: setServiceProc
    command: []
    onExited: function(exitCode, exitStatus) {
      if (root.historyTearingDown) return
      if (!root.setupApplyPending) return
      if (root.setupWriteGeneration !== root.setupGeneration) {
        // The attempt that started this was cancelled. Escalate nothing.
        root.setupApplyPending = false
        return
      }
      root.setupApplyPending = false
      if (exitCode !== 0) {
        root.setupServiceFailed = true
        root.setupBusy = false
        root.setupError = "Could not save the service selection"
        return
      }
      setTargetProc.running = true
    }
  }

  Process {
    id: setTargetProc
    command: []
    stderr: StdioCollector { id: setTargetErrorCollector }
    onExited: function(exitCode, exitStatus) {
      if (root.historyTearingDown) return
      if (root.setupWriteGeneration !== root.setupGeneration) {
        // A retired attempt: it may still have written to disk, so let the panel
        // catch up, but leave this session's step, busy state and error alone.
        root.refresh()
        return
      }
      root.setupBusy = false
      if (exitCode === 0) {
        root.refresh()
        if (root.setupServiceFailed) root.setupError = "Could not save the service selection"
        else root.setupStep = 3
      } else if (exitCode === 126 || exitCode === 127) {
        root.setupError = "Authorization declined"
      } else {
        root.setupError = root.writerError()
      }
    }
  }

  Timer {
    id: discoverWatchdog
    interval: root.historyWatchdogMs
    repeat: false
    onTriggered: root.abortDiscovery("Disk discovery exceeded QML watchdog")
  }

  Timer {
    id: historyWatchdog
    interval: root.historyWatchdogMs
    repeat: false
    onTriggered: root.abortHistory("Backup history backend exceeded QML watchdog")
  }

  Timer {
    interval: root.refreshInterval
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Component.onDestruction: {
    historyTearingDown = true
    historyWatchdog.stop()

    // Stop observing the wizard's processes. An in-flight pkexec is left alone:
    // it is a privileged write that must either complete or be refused by the
    // user, never be half-killed from here.
    discoverAborted = true
    discoverWatchdog.stop()
    if (discoverProc.running) discoverProc.signal(15)
    releaseDiscoverCollector()

    if (historyProc.running) {
      // The detached session terminator owns TERM-to-KILL escalation and
      // survives this component. Direct TERM only accelerates graceful exit.
      launchHistorySessionCleanup()
      historyProc.signal(15)
    }
    releaseHistoryCollector()
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) {
        if (root.bar && typeof root.bar.switchPanelFrom === "function") root.bar.switchPanelFrom(root.barIdentity, direction)
      }

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.space(18)

        Row {
          width: parent.width
          spacing: Style.space(14)

          Item {
            width: Style.space(46)
            height: width

            Image {
              id: panelLogoSource
              anchors.fill: parent
              source: Qt.resolvedUrl("assets/logo.png")
              sourceSize.width: Math.round(width * Screen.devicePixelRatio)
              sourceSize.height: Math.round(height * Screen.devicePixelRatio)
              fillMode: Image.PreserveAspectFit
              visible: false
              layer.enabled: true
            }

            MultiEffect {
              anchors.fill: panelLogoSource
              source: panelLogoSource
              colorization: 1
              colorizationColor: root.statusColor
            }
          }

          Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(3)

            Text {
              text: root.statusTitle
              color: root.foregroundColor
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              text: root.latestSuccess ? root.formattedTime(root.latestSuccess.timestamp) + " · " + root.relativeTime(root.latestSuccess.timestamp) : "No successful run recorded"
              color: root.mutedColor
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }
        }

        Rectangle {
          width: parent.width
          height: Style.spacing.hairline
          color: Util.alpha(root.foregroundColor, 0.14)
        }

        Column {
          visible: !root.showSetup
          width: parent.width
          spacing: Style.space(10)

          Text {
            text: "LAST " + root.weeks + " WEEKS"
            color: root.mutedColor
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1
          }

          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Style.space(8)

            Column {
              spacing: Style.space(5)

              Repeater {
                model: ["S", "M", "T", "W", "T", "F", "S"]

                Text {
                  required property string modelData
                  width: Style.space(14)
                  height: Style.space(14)
                  text: modelData
                  color: root.mutedColor
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.caption
                  horizontalAlignment: Text.AlignHCenter
                  verticalAlignment: Text.AlignVCenter
                }
              }
            }

            Grid {
              rows: 7
              flow: Grid.TopToBottom
              spacing: Style.space(5)

              Repeater {
                model: root.days

                Rectangle {
                  required property var modelData
                  width: Style.space(14)
                  height: width
                  radius: Style.space(3)
                  color: root.colorFor(modelData)
                  border.width: modelData.today ? Style.spacing.hairline : 0
                  border.color: root.foregroundColor

                  MouseArea {
                    id: dayMouse
                    anchors.fill: parent
                    hoverEnabled: true

                    PanelToolTip {
                      visible: dayMouse.containsMouse
                      text: root.dayLabel(parent.parent.modelData)
                      fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
                    }
                  }
                }
              }
            }
          }

          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Style.space(14)

            Repeater {
              model: [
                { "label": "Successful", "color": root.successColor },
                { "label": "Failed", "color": root.failureColor },
                { "label": "No backup", "color": root.missingColor }
              ]

              Row {
                required property var modelData
                spacing: Style.space(5)

                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(7)
                  height: width
                  radius: width / 3
                  color: parent.modelData.color
                }

                Text {
                  text: parent.modelData.label
                  color: root.mutedColor
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }
        }

        Text {
          visible: !root.showSetup && root.error !== ""
          width: parent.width
          text: root.error
          color: root.failureColor
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }

        Row {
          visible: !root.showSetup
          width: parent.width
          spacing: Style.space(8)

          Text {
            id: targetIcon
            width: Style.space(14)
            text: root.targetMounted ? "󰋊" : "󰀦"
            color: root.targetMounted ? root.foregroundColor : root.failureColor
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            width: parent.width - targetIcon.width - parent.spacing
            text: root.targetSummary
            color: root.targetMounted ? root.mutedColor : root.failureColor
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideMiddle
          }
        }

        Row {
          visible: !root.showSetup
          width: parent.width
          spacing: Style.space(10)

          Button {
            width: (parent.width - parent.spacing) / 2
            text: root.state === "running" || runProc.running ? "Backup running" : "Run backup now"
            iconText: root.state === "running" || runProc.running ? "󰑓" : "󰁯"
            iconSpinning: root.state === "running" || runProc.running
            foreground: root.foregroundColor
            accent: root.successColor
            bordered: true
            enabled: root.state !== "running" && !runProc.running
            onClicked: runProc.running = true
          }

          Button {
            width: (parent.width - parent.spacing) / 2
            text: "View logs"
            iconText: "󰆍"
            foreground: root.foregroundColor
            bordered: true
            onClicked: root.openLogs()
          }
        }

        Row {
          visible: !root.showSetup
          width: parent.width
          spacing: Style.space(10)

          Button {
            width: parent.width
            text: "Change backup disk"
            iconText: "󰋊"
            foreground: root.foregroundColor
            bordered: true
            onClicked: root.openSetup()
          }
        }

        Column {
          id: setupColumn
          visible: root.showSetup
          width: parent.width
          spacing: Style.space(12)

          Text {
            text: root.setupStep === 0 ? "Choose a backup service"
              : root.setupStep === 1 ? "Choose a backup disk"
              : root.setupStep === 2 ? "Review and apply"
              : "Setup complete"
            color: root.foregroundColor
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
          }

          Column {
            visible: root.setupStep === 0
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.setupServices

              Button {
                required property var modelData
                width: setupColumn.width
                text: modelData.unit + (modelData.exists ? "" : " (not installed)")
                foreground: root.foregroundColor
                accent: root.successColor
                bordered: root.setupService === modelData.unit
                onClicked: {
                  root.setupService = modelData.unit
                  root.setupStep = 1
                }
              }
            }
          }

          Column {
            visible: root.setupStep === 1
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.setupDisks

              Button {
                required property var modelData
                width: setupColumn.width
                text: (modelData.label !== "" ? modelData.label : modelData.uuid)
                  + " · " + modelData.size + " · " + modelData.fstype
                  + (modelData.mountpoint === "" ? " · not mounted" : "")
                foreground: root.foregroundColor
                accent: root.successColor
                bordered: !!root.setupDisk && root.setupDisk.uuid === modelData.uuid
                onClicked: {
                  root.setupDisk = modelData
                  root.setupStep = 2
                }
              }
            }
          }

          Column {
            visible: root.setupStep === 2
            width: parent.width
            spacing: Style.space(8)

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              color: root.mutedColor
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
              text: "Writes /etc/backup-history/target.env and a drop-in for "
                + root.setupService
                + " so the service reads $BACKUP_TARGET_PATH. Requires authorization."
            }

            Button {
              width: parent.width
              text: root.setupBusy || root.setupWriteRunning ? "Applying…" : "Apply"
              iconText: "󰄬"
              foreground: root.foregroundColor
              accent: root.successColor
              bordered: true
              enabled: !root.setupBusy && !root.setupWriteRunning
                && root.setupService !== "" && !!root.setupDisk
              onClicked: root.applyTarget()
            }

            Button {
              width: parent.width
              visible: root.targetConfigured
              text: root.setupBusy || root.setupWriteRunning
                ? "Working…"
                : "Forget the current disk"
              iconText: "󰆴"
              foreground: root.foregroundColor
              bordered: true
              enabled: !root.setupBusy && !root.setupWriteRunning
              onClicked: {
                if (root.setupWriteRunning) {
                  root.setupError = "A previous change is still being applied"
                  return
                }
                root.setupBusy = true
                root.setupError = ""
                root.setupServiceFailed = false
                root.setupApplyPending = false
                root.setupWriteGeneration = root.setupGeneration
                setTargetProc.command = [
                  "/usr/bin/pkexec",
                  root.setTargetPath,
                  "--unit", root.setupService,
                  "--clear"
                ]
                setTargetProc.running = true
              }
            }
          }

          Column {
            visible: root.setupStep === 3
            width: parent.width
            spacing: Style.space(8)

            Button {
              width: parent.width
              text: "Run a test backup"
              iconText: "󰁯"
              foreground: root.foregroundColor
              accent: root.successColor
              bordered: true
              enabled: !runProc.running
              onClicked: runProc.running = true
            }

            Button {
              width: parent.width
              text: "Done"
              iconText: "󰄬"
              foreground: root.foregroundColor
              bordered: true
              onClicked: root.closeSetup()
            }
          }

          Button {
            visible: root.setupStep !== 3
            width: parent.width
            text: "Cancel"
            iconText: "󰅖"
            foreground: root.foregroundColor
            bordered: true
            onClicked: root.closeSetup()
          }

          Text {
            visible: root.setupError !== ""
            width: parent.width
            text: root.setupError
            color: root.failureColor
            wrapMode: Text.Wrap
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
    }
  }
}
