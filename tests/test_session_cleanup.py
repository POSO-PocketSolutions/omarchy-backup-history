import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TERMINATOR = ROOT / "scripts" / "terminate-history-session"
SESSION_TOKEN_ENV = "BACKUP_HISTORY_SESSION_TOKEN"
SESSION_TOKEN = "0123456789abcdef-0123456789abcdef"


def wait_for_file(path, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def process_is_alive(pid):
    stat = Path(f"/proc/{pid}/stat")
    try:
        fields = stat.read_text().rpartition(")")[2].split()
    except OSError:
        return False
    return bool(fields) and fields[0] != "Z"


def wait_until_stopped(pid, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_alive(pid):
            return True
        time.sleep(0.02)
    return not process_is_alive(pid)


class SessionCleanupTest(unittest.TestCase):
    def test_terminator_kills_leader_command_and_grandchild_only_in_target_session(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            leader_file = directory / "leader.json"
            command_file = directory / "command.json"
            grandchild_file = directory / "grandchild.json"
            ready_file = directory / "ready"

            grandchild_code = (
                "import json,os,signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(grandchild_file)!r},'w').write(json.dumps([os.getpid(),os.getpgid(0),os.getsid(0)]));"
                "time.sleep(60)"
            )
            command_code = (
                "import json,os,signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(command_file)!r},'w').write(json.dumps([os.getpid(),os.getpgid(0),os.getsid(0)]));"
                f"subprocess.Popen([sys.executable,'-c',{grandchild_code!r}]);"
                f"p={str(grandchild_file)!r};deadline=time.monotonic()+2;"
                "\nwhile not os.path.exists(p) and time.monotonic()<deadline: time.sleep(0.01)\n"
                "time.sleep(60)"
            )
            leader_code = (
                "import json,os,signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(leader_file)!r},'w').write(json.dumps([os.getpid(),os.getpgid(0),os.getsid(0)]));"
                f"subprocess.Popen([sys.executable,'-c',{command_code!r}],process_group=0);"
                f"p={str(grandchild_file)!r};deadline=time.monotonic()+2;"
                "\nwhile not os.path.exists(p) and time.monotonic()<deadline: time.sleep(0.01)\n"
                f"open({str(ready_file)!r},'w').write('ready');"
                "time.sleep(60)"
            )

            environment = os.environ.copy()
            environment[SESSION_TOKEN_ENV] = SESSION_TOKEN
            leader = subprocess.Popen(
                [sys.executable, "-c", leader_code],
                start_new_session=True,
                env=environment,
            )
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
            try:
                self.assertTrue(wait_for_file(ready_file), "session tree did not start")
                leader_info = json.loads(leader_file.read_text())
                command_info = json.loads(command_file.read_text())
                grandchild_info = json.loads(grandchild_file.read_text())

                self.assertEqual(leader_info, [leader.pid, leader.pid, leader.pid])
                self.assertEqual(command_info[0], command_info[1])
                self.assertEqual(command_info[2], leader.pid)
                self.assertEqual(grandchild_info[1], command_info[1])
                self.assertEqual(grandchild_info[2], leader.pid)

                result = subprocess.run(
                    [str(TERMINATOR), "--sid", str(leader.pid), "--token", SESSION_TOKEN],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                leader.wait(timeout=2)

                for pid in (leader_info[0], command_info[0], grandchild_info[0]):
                    self.assertTrue(wait_until_stopped(pid), f"process {pid} survived")
                self.assertIsNone(unrelated.poll(), "neighbor session was terminated")
            finally:
                if leader.poll() is None:
                    os.killpg(leader.pid, signal.SIGKILL)
                    leader.wait(timeout=2)
                if unrelated.poll() is None:
                    os.killpg(unrelated.pid, signal.SIGKILL)
                    unrelated.wait(timeout=2)

    def test_terminator_cleans_session_after_leader_has_exited(self):
        with tempfile.TemporaryDirectory() as directory:
            child_file = Path(directory) / "orphan.json"
            child_code = (
                "import json,os,signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                f"open({str(child_file)!r},'w').write(json.dumps([os.getpid(),os.getsid(0)]));"
                "time.sleep(60)"
            )
            leader_code = (
                "import os,subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}],process_group=0);"
                f"p={str(child_file)!r};deadline=time.monotonic()+2;"
                "\nwhile not os.path.exists(p) and time.monotonic()<deadline: time.sleep(0.01)\n"
            )
            environment = os.environ.copy()
            environment[SESSION_TOKEN_ENV] = SESSION_TOKEN
            leader = subprocess.Popen(
                [sys.executable, "-c", leader_code],
                start_new_session=True,
                env=environment,
            )
            leader.wait(timeout=3)
            self.assertTrue(wait_for_file(child_file))
            child_pid, session_id = json.loads(child_file.read_text())
            self.assertEqual(session_id, leader.pid)

            result = subprocess.run(
                [str(TERMINATOR), "--sid", str(session_id), "--token", SESSION_TOKEN],
                capture_output=True,
                text=True,
                timeout=4,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(wait_until_stopped(child_pid), f"orphan {child_pid} survived")

    def test_wrong_token_cannot_signal_reused_or_unrelated_session(self):
        environment = os.environ.copy()
        environment[SESSION_TOKEN_ENV] = SESSION_TOKEN
        leader = subprocess.Popen(
            [sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
            start_new_session=True,
            env=environment,
        )
        try:
            result = subprocess.run(
                [
                    str(TERMINATOR),
                    "--sid", str(leader.pid),
                    "--token", "fedcba9876543210-fedcba9876543210",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIsNone(leader.poll(), "wrong token signaled target session")
        finally:
            if leader.poll() is None:
                os.killpg(leader.pid, signal.SIGKILL)
            leader.wait(timeout=2)

    def test_terminator_rejects_unsafe_or_own_session(self):
        for session_id in ("0", "1", str(os.getsid(0))):
            with self.subTest(session_id=session_id):
                result = subprocess.run(
                    [str(TERMINATOR), "--sid", session_id, "--token", SESSION_TOKEN],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
