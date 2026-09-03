import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.mnsosa.backup-history"

  property var days: []
  property var summary: ({ "success": 0, "failed": 0, "missing": 0 })
  property string state: "loading"
  property string error: ""

  readonly property string service: String(setting("service", "restic-backup.service"))
  readonly property int weeks: Math.max(2, Math.min(26, Number(setting("weeks", 12))))
  readonly property int refreshInterval: Math.max(30, Number(setting("refreshIntervalSec", 60))) * 1000
  readonly property color successColor: String(setting("successColor", "#3fb950"))
  readonly property color foregroundColor: bar ? bar.barForeground : Color.foreground
  readonly property color failureColor: bar ? bar.urgent : Color.urgent
  readonly property color missingColor: Util.alpha(foregroundColor, 0.16)
  readonly property color runningColor: Color.accent
  readonly property real cellSize: Style.spaceReal(2)
  readonly property real cellGap: Style.spaceReal(1)
  readonly property string backendPath: decodeURIComponent(Qt.resolvedUrl("scripts/backup-history").toString().replace("file://", ""))
  readonly property string logsPath: decodeURIComponent(Qt.resolvedUrl("scripts/open-logs").toString().replace("file://", ""))
  readonly property string tooltip: error !== ""
    ? "Backup history\n" + error
    : service + "\n" + summary.success + " successful · " + summary.failed + " failed · " + summary.missing + " missing\nClick to follow logs"

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
      state = payload.state || "unknown"
      error = payload.error || ""
    } catch (exception) {
      days = []
      state = "unknown"
      error = String(exception)
    }
  }

  implicitWidth: vertical ? barSize : heatmap.width + Style.space(12)
  implicitHeight: vertical ? heatmap.width + Style.space(12) : barSize

  Process {
    id: historyProc
    command: [root.backendPath, "--service", root.service, "--weeks", String(root.weeks)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.update(text)
    }
  }

  Timer {
    interval: root.refreshInterval
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  WidgetButton {
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    tooltipText: root.tooltip
    horizontalMargin: 0
    verticalPadding: 0
    onPressed: if (root.bar) root.bar.run(root.logsPath + " " + Util.shellQuote(root.service))

    Grid {
      id: heatmap
      anchors.centerIn: parent
      rows: 7
      flow: Grid.TopToBottom
      spacing: root.cellGap
      rotation: root.vertical ? 90 : 0

      Repeater {
        model: root.days

        Rectangle {
          required property var modelData
          width: root.cellSize
          height: root.cellSize
          radius: root.cellSize / 3
          color: root.colorFor(modelData)
        }
      }
    }
  }
}
