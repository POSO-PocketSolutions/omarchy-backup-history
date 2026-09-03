import QtQuick
import QtQuick.Effects
import Quickshell.Io
import qs.Commons
import qs.Ui

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
  property string state: "loading"
  property string error: ""

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
  readonly property string runPath: pathFor("scripts/run-backup")
  readonly property string logsPath: pathFor("scripts/open-logs")
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

  function refresh() {
    if (!historyProc.running) historyProc.running = true
  }

  function update(raw) {
    try {
      var payload = JSON.parse(raw)
      days = payload.days || []
      summary = payload.summary || ({ "success": 0, "failed": 0, "missing": 0 })
      latest = payload.latest || null
      latestSuccess = payload.latestSuccess || null
      state = payload.state || "unknown"
      error = payload.error || ""
    } catch (exception) {
      days = []
      state = "unknown"
      error = String(exception)
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

  Process {
    id: historyProc
    command: [root.backendPath, "--service", root.service, "--weeks", String(root.weeks)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.update(text)
    }
  }

  Process {
    id: runProc
    command: [root.runPath, root.service]
    onExited: root.refresh()
  }

  Timer {
    interval: root.refreshInterval
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
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
          visible: root.error !== ""
          width: parent.width
          text: root.error
          color: root.failureColor
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }

        Row {
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
      }
    }
  }
}
