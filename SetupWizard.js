.pragma library

// The setup wizard's decisions, kept free of QML types so both Panel.qml and
// tests/qml/setup-wizard.qml can drive them.

var STEP_SERVICE = 0
var STEP_DISK = 1
var STEP_REVIEW = 2
var STEP_DONE = 3

// Mirrors SERVICE_PATTERN in scripts/backup-history and scripts/set-target.
// The writer validates again under pkexec; this only keeps an obviously
// malformed name from reaching an authorization prompt.
var SERVICE_NAME_PATTERN = /^[A-Za-z0-9_.@:-]+\.service$/
var MAX_SERVICE_LENGTH = 255

function serviceNameLooksValid(name) {
  var text = String(name === undefined || name === null ? "" : name)
  if (text.length === 0 || text.length > MAX_SERVICE_LENGTH) return false
  if (text.indexOf("/") !== -1) return false
  return SERVICE_NAME_PATTERN.test(text)
}

function stepAfterService(name) {
  return serviceNameLooksValid(name) ? STEP_DISK : STEP_SERVICE
}

function stepAfterDisk(disk) {
  return disk ? STEP_REVIEW : STEP_DISK
}

function canApply(serviceName, disk, busy, writeRunning) {
  return serviceNameLooksValid(serviceName) && !!disk && !busy && !writeRunning
}

// A write started by an attempt that has since been cancelled must not touch
// the new session's step, busy state or error.
function writeBelongsToCurrentAttempt(writeGeneration, generation) {
  return writeGeneration === generation
}

function diskIsMounted(disk) {
  return !!disk && String(disk.mountpoint || "") !== ""
}

function unmountedWarning(disk) {
  if (!disk || diskIsMounted(disk)) return ""
  return "This disk is not mounted, so BACKUP_TARGET_PATH is written empty and "
    + "the backup will fail until you mount it. Mounting it later does not "
    + "update the configuration on its own — reopen this wizard and apply "
    + "again once the disk is mounted."
}

function setupIsRequired(dismissed, targetConfigured, dropInInstalled) {
  if (dismissed) return false
  return !targetConfigured || !dropInInstalled
}
