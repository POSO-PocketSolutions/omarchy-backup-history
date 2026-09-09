import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "backup-history"


def load_backend(name):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(SCRIPT)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_until_gone(pid, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(0.02)
    return not Path(f"/proc/{pid}").exists()


class BoundedProcessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = load_backend("backup_history_bounded")

    def test_normal_command_returns_bounded_stdout(self):
        output = self.backend.bounded_run(
            sys.executable,
            "-c",
            "print('ok')",
            timeout_seconds=1.0,
            max_stdout_bytes=128,
        )
        self.assertEqual(output, "ok\n")

    def test_stdout_overflow_terminates_quickly(self):
        started = time.monotonic()
        with self.assertRaises(self.backend.ProcessOutputLimitExceeded):
            self.backend.bounded_run(
                sys.executable,
                "-c",
                "import os; os.write(1, b'x' * 8192)",
                timeout_seconds=2.0,
                max_stdout_bytes=1024,
            )
        self.assertLess(time.monotonic() - started, 1.5)

    def test_wait_status_keeps_group_leader_unreaped_until_cleanup(self):
        process = self.backend.subprocess.Popen(
            [sys.executable, "-c", "pass"],
            process_group=0,
        )
        return_code = self.backend._wait_without_reaping(process, 1.0)
        self.assertEqual(return_code, 0)
        self.assertIsNone(process.returncode)
        state = Path(f"/proc/{process.pid}/stat").read_text().rpartition(")")[2].split()[0]
        self.assertEqual(state, "Z")
        self.assertTrue(self.backend.terminate_process_group(process))
        self.assertFalse(Path(f"/proc/{process.pid}").exists())

    def test_multibyte_stdout_limit_is_measured_in_bytes(self):
        text = "é🙂"
        encoded = text.encode("utf-8")
        self.assertEqual(len(encoded), 6)

        output = self.backend.bounded_run(
            sys.executable,
            "-c",
            f"import os; os.write(1, {encoded!r})",
            timeout_seconds=1.0,
            max_stdout_bytes=6,
        )
        self.assertEqual(output, text)

        with self.assertRaises(self.backend.ProcessOutputLimitExceeded):
            self.backend.bounded_run(
                sys.executable,
                "-c",
                f"import os; os.write(1, {encoded!r})",
                timeout_seconds=1.0,
                max_stdout_bytes=5,
            )

    def test_record_overflow_is_rejected(self):
        with self.assertRaises(self.backend.ProcessRecordLimitExceeded):
            self.backend.bounded_run(
                sys.executable,
                "-c",
                "import os; os.write(1, b'{}\\n' * 4)",
                timeout_seconds=1.0,
                max_stdout_bytes=1024,
                max_records=3,
            )

    def test_timeout_kills_and_reaps_term_resistant_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_file = Path(directory) / "parent.pid"
            child_file = Path(directory) / "child.pid"
            child_code = (
                "import os,signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(child_file)!r},'w').write(str(os.getpid()));"
                "time.sleep(60)"
            )
            parent_code = (
                "import os,signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(parent_file)!r},'w').write(str(os.getpid()));"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
                "time.sleep(60)"
            )

            started = time.monotonic()
            with self.assertRaises(self.backend.ProcessDeadlineExceeded):
                self.backend.bounded_run(
                    sys.executable,
                    "-c",
                    parent_code,
                    timeout_seconds=0.4,
                    max_stdout_bytes=1024,
                )
            self.assertLess(time.monotonic() - started, 1.5)

            parent_pid = int(parent_file.read_text())
            child_pid = int(child_file.read_text())
            self.assertTrue(wait_until_gone(parent_pid), f"parent {parent_pid} survived")
            self.assertTrue(wait_until_gone(child_pid), f"child {child_pid} survived")

    def test_successful_parent_cannot_leave_descendant_running(self):
        with tempfile.TemporaryDirectory() as directory:
            child_file = Path(directory) / "successful-child.pid"
            child_code = (
                "import os,signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(child_file)!r},'w').write(str(os.getpid()));"
                "time.sleep(60)"
            )
            parent_code = (
                "import os,subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                f"p={str(child_file)!r};"
                "deadline=time.monotonic()+1;"
                "\nwhile not os.path.exists(p) and time.monotonic()<deadline: time.sleep(0.01)\n"
                "print('done')"
            )

            output = self.backend.bounded_run(
                sys.executable,
                "-c",
                parent_code,
                timeout_seconds=2.0,
                max_stdout_bytes=1024,
            )
            self.assertEqual(output, "done\n")
            child_pid = int(child_file.read_text())
            self.assertTrue(wait_until_gone(child_pid), f"descendant {child_pid} survived")

    def test_payload_and_error_are_bounded(self):
        encoded = self.backend.encode_payload({
            "service": "example.service",
            "state": "unknown",
            "days": [],
            "error": "line\n" + "x" * 1000,
        })
        payload = json.loads(encoded)
        self.assertLessEqual(len(encoded.encode("ascii")), self.backend.JSON_MAX_BYTES)
        self.assertLessEqual(len(payload["error"]), self.backend.ERROR_MAX_CHARS)
        self.assertNotIn("\n", payload["error"])

        oversized = self.backend.encode_payload({
            "service": "example.service",
            "state": "idle",
            "days": ["x" * (self.backend.JSON_MAX_BYTES + 1)],
        })
        fallback = json.loads(oversized)
        self.assertEqual(fallback["state"], "unknown")
        self.assertEqual(fallback["days"], [])

    def test_session_token_is_restricted(self):
        token = "0123456789abcdef-0123456789abcdef"
        self.assertEqual(self.backend.validate_session_token(token), token)
        self.assertEqual(self.backend.validate_session_token(""), "")
        for invalid in ("short", "contains spaces 012345", "x" * 129):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.backend.validate_session_token(invalid)

    def test_service_name_is_restricted(self):
        self.assertEqual(
            self.backend.validate_service("backup@home.service"),
            "backup@home.service",
        )
        for invalid in ("backup", "../backup.service", "backup service.service", "x" * 256):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.backend.validate_service(invalid)

    def test_collect_applies_producer_and_systemctl_bounds(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == "journalctl":
                return ""
            return "ActiveState=inactive\nSubState=dead\nResult=success\n"

        original = self.backend.bounded_run
        self.backend.bounded_run = fake_run
        try:
            payload = self.backend.collect("backup.service", 4)
        finally:
            self.backend.bounded_run = original

        journal_args, journal_bounds = calls[0]
        systemctl_args, systemctl_bounds = calls[1]
        self.assertEqual(journal_args[0], "journalctl")
        self.assertIn("--output-fields=MESSAGE_ID,__REALTIME_TIMESTAMP", journal_args)
        self.assertIn(str(self.backend.JOURNAL_MAX_RECORDS + 1), journal_args)
        self.assertEqual(journal_bounds["max_records"], self.backend.JOURNAL_MAX_RECORDS)
        self.assertEqual(journal_bounds["max_stdout_bytes"], self.backend.JOURNAL_MAX_BYTES)
        self.assertEqual(journal_bounds["timeout_seconds"], self.backend.JOURNAL_TIMEOUT_SECONDS)
        self.assertEqual(systemctl_args[:2], ("systemctl", "show"))
        self.assertEqual(systemctl_bounds["max_stdout_bytes"], self.backend.SYSTEMCTL_MAX_BYTES)
        self.assertEqual(systemctl_bounds["timeout_seconds"], self.backend.SYSTEMCTL_TIMEOUT_SECONDS)
        self.assertEqual(payload["state"], "idle")


if __name__ == "__main__":
    unittest.main()
