import importlib.util
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "set-target"


def load_writer():
    spec = importlib.util.spec_from_loader(
        "set_target", SourceFileLoader("set_target", str(SCRIPT))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.writer = load_writer()

    def test_accepts_well_formed_arguments(self):
        values = self.writer.validate_values(
            "restic-backup.service",
            "1f0e5a3c-1111-2222-3333-444455556666",
            "/run/media/user/backup",
            "backup",
        )
        self.assertEqual(values["unit"], "restic-backup.service")

    def test_accepts_an_empty_path_for_an_unmounted_disk(self):
        values = self.writer.validate_values(
            "restic-backup.service", "1f0e5a3c", "", "backup"
        )
        self.assertEqual(values["path"], "")

    def test_accepts_a_non_ascii_label_and_mountpoint(self):
        values = self.writer.validate_values(
            "restic-backup.service",
            "1f0e5a3c",
            "/run/media/user/Sauvegarde-été",
            "Sauvegarde-été",
        )
        self.assertEqual(values["label"], "Sauvegarde-été")
        self.assertEqual(values["path"], "/run/media/user/Sauvegarde-été")

    def test_accepts_ordinary_punctuation_in_a_label(self):
        values = self.writer.validate_values(
            "restic-backup.service", "1f0e5a3c", "/mnt/My Disk (2)", "My Disk (2)"
        )
        self.assertEqual(values["label"], "My Disk (2)")

    def test_rejects_bad_inputs(self):
        cases = [
            ("restic-backup", "1f0e", "/mnt/b", "b"),
            ("restic-backup.service", "1f 0e", "/mnt/b", "b"),
            ("restic-backup.service", "1f0e", "relative", "b"),
            ("restic-backup.service", "1f0e", "/mnt/../etc", "b"),
            ("restic-backup.service", "1f0e", "/mnt/b\nBACKUP_TARGET_PATH=/etc", "b"),
            ("restic-backup.service", "1f0e", "/mnt/b", "bad;label$(id)"),
            ("restic-backup.service", "1f0e", "/mnt/b", "label=value"),
            ("restic-backup.service", "1f0e", "/mnt/b", "label\nBACKUP_TARGET_PATH=/etc"),
            ("restic-backup.service", "1f0e", "/mnt/b", "back`id`tick"),
            ("restic-backup.service", "1f0e", "/mnt/b", 'quo"te'),
            ("restic-backup.service", "1f0e", "/mnt/b=x", "b"),
            ("restic-backup.service", "1f0e", "/mnt/b", "x" * 65),
            ("../../etc/passwd.service", "1f0e", "/mnt/b", "b"),
        ]
        for unit, uuid, path, label in cases:
            with self.subTest(unit=unit, uuid=uuid, path=path, label=label):
                with self.assertRaises(ValueError):
                    self.writer.validate_values(unit, uuid, path, label)


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.writer = load_writer()
        self.root = tempfile.mkdtemp()

    def paths(self, unit="restic-backup.service"):
        env = Path(self.root + self.writer.TARGET_ENV_PATH)
        drop_in = Path(self.root + self.writer.TARGET_DROP_IN_TEMPLATE.format(unit=unit))
        return env, drop_in

    def test_writes_env_file_and_drop_in(self):
        self.writer.write_target(
            self.root,
            "restic-backup.service",
            "1f0e5a3c",
            "/run/media/user/backup",
            "backup",
        )
        env, drop_in = self.paths()
        self.assertIn("BACKUP_TARGET_UUID=1f0e5a3c", env.read_text())
        self.assertIn("BACKUP_TARGET_PATH=/run/media/user/backup", env.read_text())
        self.assertIn("EnvironmentFile=-/etc/backup-history/target.env", drop_in.read_text())
        self.assertIn("[Service]", drop_in.read_text())
        self.assertEqual(env.stat().st_mode & 0o777, 0o644)

    def test_rewrite_replaces_rather_than_appends(self):
        for label in ("first", "second"):
            self.writer.write_target(
                self.root, "restic-backup.service", "1f0e5a3c", "/mnt/b", label
            )
        env, _ = self.paths()
        self.assertEqual(env.read_text().count("BACKUP_TARGET_LABEL="), 1)
        self.assertIn("BACKUP_TARGET_LABEL=second", env.read_text())

    def test_clear_removes_both_files(self):
        self.writer.write_target(
            self.root, "restic-backup.service", "1f0e5a3c", "/mnt/b", "backup"
        )
        self.writer.clear_target(self.root, "restic-backup.service")
        env, drop_in = self.paths()
        self.assertFalse(env.exists())
        self.assertFalse(drop_in.exists())

    def test_clear_is_idempotent(self):
        self.writer.clear_target(self.root, "restic-backup.service")
        self.writer.clear_target(self.root, "restic-backup.service")

    def test_clear_leaves_a_foreign_drop_in_in_place(self):
        _, drop_in = self.paths()
        drop_in.parent.mkdir(parents=True, exist_ok=True)
        drop_in.write_text("[Service]\nExecStart=/bin/false\n")

        self.writer.clear_target(self.root, "restic-backup.service")

        self.assertTrue(drop_in.exists())
        self.assertEqual(drop_in.read_text(), "[Service]\nExecStart=/bin/false\n")

    def test_clear_removes_a_drop_in_matching_our_content(self):
        _, drop_in = self.paths()
        drop_in.parent.mkdir(parents=True, exist_ok=True)
        drop_in.write_text(self.writer.DROP_IN_BODY)

        self.writer.clear_target(self.root, "restic-backup.service")

        self.assertFalse(drop_in.exists())

    def test_clear_removes_env_file_unconditionally(self):
        env, _ = self.paths()
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text("anything")

        self.writer.clear_target(self.root, "restic-backup.service")

        self.assertFalse(env.exists())


class RecordingResult:
    def __init__(self, returncode=0):
        self.returncode = returncode


class SystemctlInvocationTest(unittest.TestCase):
    def setUp(self):
        self.writer = load_writer()
        self.calls = []
        self.addCleanup(setattr, self.writer.subprocess, "run", subprocess.run)

    def fake_run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return RecordingResult(returncode=0)

    def test_unit_exists_invokes_systemctl_with_list_argv_and_timeout(self):
        self.writer.subprocess.run = self.fake_run

        result = self.writer.unit_exists("restic-backup.service")

        self.assertTrue(result)
        self.assertEqual(len(self.calls), 1)
        argv, kwargs = self.calls[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv, [self.writer.SYSTEMCTL, "cat", "--", "restic-backup.service"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], self.writer.SYSTEMCTL_TIMEOUT_SECONDS)

    def test_daemon_reload_invokes_systemctl_with_list_argv_and_timeout(self):
        self.writer.subprocess.run = self.fake_run

        self.writer.daemon_reload()

        self.assertEqual(len(self.calls), 1)
        argv, kwargs = self.calls[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv, [self.writer.SYSTEMCTL, "daemon-reload"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], self.writer.SYSTEMCTL_TIMEOUT_SECONDS)


class MainSubprocessTest(unittest.TestCase):
    ETC_ENV_PATH = Path("/etc/backup-history/target.env")

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            text=True,
        )

    def test_rejects_invalid_unit_without_touching_etc(self):
        existed_before = self.ETC_ENV_PATH.exists()

        result = self.run_script(
            "--unit", "not-a-service", "--uuid", "1f0e", "--path", "/mnt/b", "--label", "b"
        )

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        self.assertEqual(self.ETC_ENV_PATH.exists(), existed_before)

    def test_rejects_invalid_uuid_without_touching_etc(self):
        existed_before = self.ETC_ENV_PATH.exists()

        result = self.run_script(
            "--unit",
            "restic-backup.service",
            "--uuid",
            "not a uuid",
            "--path",
            "/mnt/b",
            "--label",
            "b",
        )

        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())
        self.assertEqual(self.ETC_ENV_PATH.exists(), existed_before)


if __name__ == "__main__":
    unittest.main()
