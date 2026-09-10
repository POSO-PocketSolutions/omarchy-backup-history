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


if __name__ == "__main__":
    unittest.main()
