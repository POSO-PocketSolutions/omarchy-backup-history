import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "scripts" / "backup-history"


def process_is_alive(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
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


class SpawnSignalRaceTest(unittest.TestCase):
    def test_pending_sigterm_is_delivered_only_after_active_process_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            parent_file = directory / "parent.pid"
            child_file = directory / "child.pid"

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
            wrapper_code = f"""
import importlib.util
import os
import signal
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

spec = importlib.util.spec_from_loader('race_backend', SourceFileLoader('race_backend', {str(BACKEND)!r}))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
backend.install_signal_handlers()
real_popen = backend.subprocess.Popen
marker = Path({str(child_file)!r})

def racing_popen(*args, **kwargs):
    process = real_popen(*args, **kwargs)
    deadline = time.monotonic() + 2
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.exists():
        process.kill()
        raise RuntimeError('child marker was not created')
    os.kill(os.getpid(), signal.SIGTERM)
    return process

backend.subprocess.Popen = racing_popen
backend.bounded_run(
    sys.executable,
    '-c',
    {parent_code!r},
    timeout_seconds=10,
    max_stdout_bytes=1024,
)
"""

            started = time.monotonic()
            wrapper = subprocess.run(
                [sys.executable, "-c", wrapper_code],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(wrapper.returncode, 128 + signal.SIGTERM, wrapper.stderr)
            self.assertLess(time.monotonic() - started, 3.0)

            parent_pid = int(parent_file.read_text())
            child_pid = int(child_file.read_text())
            self.assertTrue(wait_until_stopped(parent_pid), f"parent {parent_pid} survived")
            self.assertTrue(wait_until_stopped(child_pid), f"child {child_pid} survived")


if __name__ == "__main__":
    unittest.main()
