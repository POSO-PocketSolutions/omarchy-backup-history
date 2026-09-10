import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PluginContractTest(unittest.TestCase):
    def test_plugin_files_exist(self):
        self.assertTrue((ROOT / "manifest.json").exists())
        self.assertTrue((ROOT / "BarWidget.qml").exists())
        self.assertTrue((ROOT / "Panel.qml").exists())
        self.assertTrue((ROOT / "HistoryLifecycle.js").exists())
        self.assertTrue((ROOT / "assets" / "logo.png").exists())
        self.assertTrue((ROOT / "scripts" / "run-backup").exists())
        self.assertTrue((ROOT / "scripts" / "terminate-history-session").exists())

    def test_backend_supports_discover_mode(self):
        backend = (ROOT / "scripts" / "backup-history").read_text()

        self.assertIn('"--mode"', backend)
        self.assertIn('default="history"', backend)
        self.assertIn('choices=["history", "discover"]', backend)

    @unittest.skipUnless((ROOT / "manifest.json").exists(), "manifest not implemented")
    def test_manifest_is_publishable_bar_widget(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())

        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "io.github.mnsosa.backup-history")
        self.assertEqual(manifest["kinds"], ["bar-widget"])
        self.assertEqual(manifest["entryPoints"]["barWidget"], "BarWidget.qml")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["barWidget"]["defaults"]["weeks"], 4)

    def test_privileged_backup_command_uses_fixed_trusted_paths(self):
        run_backup = (ROOT / "scripts" / "run-backup").read_text()

        self.assertIn(
            'exec /usr/bin/pkexec /usr/bin/systemctl start -- "$service"',
            run_backup,
        )
        self.assertNotIn("exec pkexec", run_backup)
        self.assertIn("^[A-Za-z0-9_.@:-]+\\.service$", run_backup)

    def test_process_safety_contract(self):
        backend = (ROOT / "scripts" / "backup-history").read_text()
        terminator = (ROOT / "scripts" / "terminate-history-session").read_text()
        panel = (ROOT / "Panel.qml").read_text()

        for marker in (
            "selectors.DefaultSelector",
            "process_group=0",
            "signal.pthread_sigmask",
            "os.waitid",
            "os.WNOWAIT",
            "establish_backend_session",
            "--session-token",
            "BACKUP_HISTORY_SESSION_TOKEN",
            "os.setsid()",
            "os.killpg",
            "JOURNAL_MAX_RECORDS",
            "JOURNAL_MAX_BYTES",
            "SYSTEMCTL_TIMEOUT_SECONDS",
            "JSON_MAX_BYTES",
        ):
            self.assertIn(marker, backend)
        self.assertNotIn("start_new_session=True", backend)

        for marker in (
            "authenticated_snapshot",
            "os.pidfd_open",
            "signal.pidfd_send_signal",
            "token_matches",
            "signal.SIGTERM",
            "signal.SIGKILL",
            "refusing to terminate own session",
        ):
            self.assertIn(marker, terminator)

        for marker in (
            "waitForEnd: false",
            "collector.data.byteLength",
            "historyWatchdog",
            "historyProc.processId",
            "historySessionTerminator.startDetached()",
            "historySessionToken",
            "--token",
            "HistoryLifecycle.shouldFinish",
            "scripts/terminate-history-session",
            "historyProc.signal(15)",
            "historyProc.stdout = null",
            "Component.onDestruction",
            "historyCollectorLimit",
        ):
            self.assertIn(marker, panel)
        self.assertNotIn("historyKillTimer", panel)
        self.assertNotIn("historyProc.signal(9)", panel)
        self.assertNotIn("process.wait()", backend)

    def test_target_writer_uses_fixed_trusted_paths(self):
        writer = (ROOT / "scripts" / "set-target").read_text()

        self.assertIn('"/usr/bin/systemctl"', writer)
        self.assertNotIn('subprocess.run("systemctl', writer)
        self.assertIn("os.replace", writer)

    def test_target_writer_is_executable(self):
        self.assertTrue(os.access(ROOT / "scripts" / "set-target", os.X_OK))

    def test_service_setter_validates_and_uses_the_plugin_id(self):
        setter = (ROOT / "scripts" / "set-service").read_text()

        self.assertIn("^[A-Za-z0-9_.@:-]+\\.service$", setter)
        self.assertIn("io.github.mnsosa.backup-history", setter)
        self.assertIn('omarchy bar set io.github.mnsosa.backup-history service "$service"', setter)
        self.assertTrue(os.access(ROOT / "scripts" / "set-service", os.X_OK))

    def test_panel_renders_target_state(self):
        panel = (ROOT / "Panel.qml").read_text()

        self.assertIn("property var target: null", panel)
        self.assertIn("targetConfigured", panel)
        self.assertIn("Backup disk not connected", panel)
        self.assertIn("payload.target", panel)

    def test_panel_has_setup_wizard_wiring(self):
        panel = (ROOT / "Panel.qml").read_text()

        self.assertIn("property bool setupOpen", panel)
        self.assertIn("setupRequired", panel)
        self.assertIn('"--mode", "discover"', panel)
        self.assertIn("scripts/set-target", panel)
        self.assertIn("scripts/set-service", panel)
        self.assertIn("/usr/bin/pkexec", panel)
        self.assertIn("Change backup disk", panel)

    def test_wizard_escalates_only_on_apply(self):
        panel = (ROOT / "Panel.qml").read_text()

        # Escalation happens only on the review step: apply, and forget.
        self.assertEqual(panel.count("setTargetProc.running = true"), 2)
        self.assertIn("function applyTarget()", panel)
        self.assertIn("--clear", panel)

    def test_readme_documents_the_target_contract(self):
        readme = (ROOT / "README.md").read_text()

        self.assertIn("BACKUP_TARGET_PATH", readme)
        self.assertIn("/etc/backup-history/target.env", readme)
        self.assertIn("10-backup-history-target.conf", readme)

    def test_manifest_version_is_bumped_for_the_target_feature(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())

        self.assertEqual(manifest["version"], "0.3.0")


if __name__ == "__main__":
    unittest.main()
