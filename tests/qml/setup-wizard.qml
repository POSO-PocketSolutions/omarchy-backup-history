import QtQuick
import Quickshell
import Quickshell.Io
import "SetupWizard.js" as SetupWizard

// Drives the setup wizard's state machine with real Process objects standing in
// for the privileged writer, so writer invocations can be counted. It mirrors
// Panel.qml's setup properties and handlers and reuses the same SetupWizard.js
// decisions; it deliberately pulls in no bar module, so no Style or Button.
ShellRoot {
  id: root

  property int setupStep: SetupWizard.STEP_SERVICE
  property string setupService: ""
  property var setupDisk: null
  property bool setupBusy: false
  property bool setupApplyPending: false
  property string setupError: ""
  property int setupGeneration: 0
  property int setupWriteGeneration: -1

  property int writerStarts: 0
  property int phase: 0
  property bool failed: false

  readonly property var pickedDisk: ({
    "uuid": "1f0e5a3c-1111-2222-3333-444455556666",
    "label": "backup",
    "mountpoint": "/run/media/user/backup"
  })
  readonly property bool setupWriteRunning: setTargetProc.running || setServiceProc.running

  function fail(message) {
    failed = true
    console.error("QML_WIZARD_FAIL " + message)
    Qt.quit()
  }

  function check(condition, message) {
    if (!condition) fail(message)
    return condition
  }

  function openSetup() {
    setupGeneration += 1
    setupStep = SetupWizard.STEP_SERVICE
    setupError = ""
    setupDisk = null
    setupApplyPending = false
    setupBusy = false
    setupService = "restic-backup.service"
  }

  function closeSetup() {
    setupGeneration += 1
    setupApplyPending = false
    setupBusy = false
  }

  function applyTarget() {
    if (!SetupWizard.serviceNameLooksValid(setupService) || !setupDisk || setupBusy) return
    if (setupWriteRunning) {
      setupError = "A previous change is still being applied"
      return
    }
    setupBusy = true
    setupError = ""
    setupApplyPending = true
    setupWriteGeneration = setupGeneration
    setServiceProc.running = true
  }

  // Phase 1: stepping through the wizard escalates nothing, and one Apply
  // produces exactly one writer invocation.
  function runSteppingPhase() {
    openSetup()
    if (!check(setupStep === SetupWizard.STEP_SERVICE, "initial step=" + setupStep)) return

    setupStep = SetupWizard.stepAfterService("restic-backup.service")
    if (!check(setupStep === SetupWizard.STEP_DISK, "after service step=" + setupStep)) return

    setupDisk = pickedDisk
    setupStep = SetupWizard.stepAfterDisk(setupDisk)
    if (!check(setupStep === SetupWizard.STEP_REVIEW, "after disk step=" + setupStep)) return

    if (!check(SetupWizard.stepAfterService("not-a-unit") === SetupWizard.STEP_SERVICE,
               "a malformed typed unit advanced the wizard")) return
    if (!check(!SetupWizard.canApply("not-a-unit", setupDisk, false, false),
               "a malformed typed unit could be applied")) return

    if (!check(writerStarts === 0, "writer started while stepping: " + writerStarts)) return

    phase = 1
    applyTarget()
  }

  // Phase 2: a write whose generation was retired by cancel-then-reopen must
  // not touch the new session's step or busy state.
  function runRetirementPhase() {
    openSetup()
    setupStep = SetupWizard.stepAfterService(setupService)
    setupDisk = pickedDisk
    setupStep = SetupWizard.stepAfterDisk(setupDisk)
    phase = 2
    applyTarget()
  }

  function handleServiceExited(exitCode) {
    if (!setupApplyPending) return
    if (!SetupWizard.writeBelongsToCurrentAttempt(setupWriteGeneration, setupGeneration)) {
      setupApplyPending = false
      return
    }
    setupApplyPending = false
    if (exitCode !== 0) {
      setupBusy = false
      setupError = "Could not save the service selection"
      return
    }
    setTargetProc.running = true
  }

  function handleWriteExited(exitCode) {
    if (!SetupWizard.writeBelongsToCurrentAttempt(setupWriteGeneration, setupGeneration)) {
      // Retired: the panel refreshes, but leaves step, busy state and error be.
      if (phase === 2) verifyRetirement()
      return
    }
    if (phase === 2) {
      fail("a retired write was treated as the current attempt")
      return
    }
    setupBusy = false
    if (exitCode === 0) setupStep = SetupWizard.STEP_DONE
    else setupError = "write failed"
    if (phase === 1) verifySingleWrite()
  }

  function verifySingleWrite() {
    if (!check(writerStarts === 1, "writer invocations for one Apply: " + writerStarts)) return
    if (!check(setupStep === SetupWizard.STEP_DONE, "step after apply=" + setupStep)) return
    if (!check(!setupBusy, "still busy after apply")) return
    // Let the writer fully settle before the next attempt starts.
    Qt.callLater(runRetirementPhase)
  }

  function verifyRetirement() {
    if (!check(setupStep === SetupWizard.STEP_SERVICE,
               "a retired write moved the new session to step " + setupStep)) return
    if (!check(!setupBusy, "a retired write left the new session busy")) return
    if (!check(writerStarts === 2, "writer invocations overall: " + writerStarts)) return
    console.log("QML_WIZARD_OK writes=" + writerStarts)
    Qt.quit()
  }

  Component.onCompleted: runSteppingPhase()

  Process {
    id: setServiceProc
    command: ["/usr/bin/python", "-c", "pass"]
    onExited: function(exitCode, exitStatus) { root.handleServiceExited(exitCode) }
  }

  Process {
    id: setTargetProc
    command: ["/usr/bin/python", "-c", "import time;time.sleep(0.1)"]
    onStarted: {
      root.writerStarts += 1
      if (root.phase !== 2) return
      // Cancel this attempt and open a fresh one while the writer is still in
      // flight, exactly as Cancel followed by reopening the wizard does.
      root.closeSetup()
      root.openSetup()
    }
    onExited: function(exitCode, exitStatus) { root.handleWriteExited(exitCode) }
  }

  Timer {
    interval: 5000
    running: true
    repeat: false
    onTriggered: root.fail("timeout phase=" + root.phase)
  }
}
