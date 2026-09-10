import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tests" / "qml" / "process-lifecycle.qml"
DESTRUCTION_HARNESS = ROOT / "tests" / "qml" / "process-destruction.qml"
WIZARD_HARNESS = ROOT / "tests" / "qml" / "setup-wizard.qml"
DESTRUCTION_DIRECTORY = Path("/tmp/backup-history-qml-destruction")
TERMINATOR = ROOT / "scripts" / "terminate-history-session"
SESSION_TREE_FIXTURE = ROOT / "tests" / "fixtures" / "session-tree"
SESSION_TOKEN = "0123456789abcdef-0123456789abcdef"
DETACHED_MARKER = Path("/tmp/backup-history-qml-detached-marker")


def process_is_alive(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
    except OSError:
        return False
    return bool(fields) and fields[0] != "Z"


def wait_until_stopped(pid, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_alive(pid):
            return True
        time.sleep(0.02)
    return not process_is_alive(pid)


@unittest.skipUnless(shutil.which("quickshell"), "quickshell is not installed")
class QmlRuntimeTest(unittest.TestCase):
    def test_multibyte_collector_callback_coordination_and_detached_lifecycle(self):
        DETACHED_MARKER.unlink(missing_ok=True)
        environment = os.environ.copy()
        environment["NO_COLOR"] = "1"

        with tempfile.TemporaryDirectory() as config_directory:
            config_directory = Path(config_directory)
            harness_copy = config_directory / HARNESS.name
            shutil.copy2(HARNESS, harness_copy)
            shutil.copy2(ROOT / "HistoryLifecycle.js", config_directory / "HistoryLifecycle.js")
            result = subprocess.run(
                ["quickshell", "--no-duplicate", "--path", str(harness_copy)],
                capture_output=True,
                text=True,
                env=environment,
                timeout=6,
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("QML_LIFECYCLE_OK bytes=6 updates=1", output)
        self.assertNotIn("QML_LIFECYCLE_FAIL", output)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not DETACHED_MARKER.exists():
            time.sleep(0.02)
        self.assertTrue(DETACHED_MARKER.exists(), "detached process died with QML root")
        self.assertEqual(DETACHED_MARKER.read_text(), "survived")
        DETACHED_MARKER.unlink(missing_ok=True)

    def test_setup_wizard_steps_escalate_once_and_retire_cancelled_writes(self):
        environment = os.environ.copy()
        environment["NO_COLOR"] = "1"

        with tempfile.TemporaryDirectory() as config_directory:
            config_directory = Path(config_directory)
            harness_copy = config_directory / WIZARD_HARNESS.name
            shutil.copy2(WIZARD_HARNESS, harness_copy)
            shutil.copy2(ROOT / "SetupWizard.js", config_directory / "SetupWizard.js")
            result = subprocess.run(
                ["quickshell", "--no-duplicate", "--path", str(harness_copy)],
                capture_output=True,
                text=True,
                env=environment,
                timeout=15,
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("QML_WIZARD_OK writes=2", output)
        self.assertNotIn("QML_WIZARD_FAIL", output)

    def test_component_destruction_dispatches_authenticated_cleanup_for_live_tree(self):
        shutil.rmtree(DESTRUCTION_DIRECTORY, ignore_errors=True)
        environment = os.environ.copy()
        environment["NO_COLOR"] = "1"
        identities = []

        try:
            with tempfile.TemporaryDirectory() as config_directory:
                harness_copy = Path(config_directory) / DESTRUCTION_HARNESS.name
                harness_source = DESTRUCTION_HARNESS.read_text()
                harness_source = harness_source.replace("__TERMINATOR__", str(TERMINATOR))
                harness_source = harness_source.replace("__FIXTURE__", str(SESSION_TREE_FIXTURE))
                harness_copy.write_text(harness_source)
                result = subprocess.run(
                    ["quickshell", "--no-duplicate", "--path", str(harness_copy)],
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=6,
                )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("QML_DESTRUCTION_DISPATCHED", output)
            self.assertNotIn("QML_DESTRUCTION_FAIL", output)

            for name in ("leader.json", "command.json", "grandchild.json"):
                path = DESTRUCTION_DIRECTORY / name
                self.assertTrue(path.exists(), f"missing {name}: {output}")
                identities.append(json.loads(path.read_text()))

            leader, command, grandchild = identities
            self.assertEqual(leader[0], leader[1])
            self.assertEqual(leader[0], leader[2])
            self.assertEqual(command[0], command[1])
            self.assertEqual(command[2], leader[2])
            self.assertEqual(grandchild[1], command[1])
            self.assertEqual(grandchild[2], leader[2])
            for pid, _group, _session in identities:
                self.assertTrue(wait_until_stopped(pid), f"process {pid} survived QML destruction")
        finally:
            if identities:
                session_id = identities[0][2]
                subprocess.run(
                    [str(TERMINATOR), "--sid", str(session_id), "--token", SESSION_TOKEN],
                    capture_output=True,
                    timeout=3,
                )
            shutil.rmtree(DESTRUCTION_DIRECTORY, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
