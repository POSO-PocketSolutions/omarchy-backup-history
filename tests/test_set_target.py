import importlib.util
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

    def test_rejects_bad_inputs(self):
        cases = [
            ("restic-backup", "1f0e", "/mnt/b", "b"),
            ("restic-backup.service", "1f 0e", "/mnt/b", "b"),
            ("restic-backup.service", "1f0e", "relative", "b"),
            ("restic-backup.service", "1f0e", "/mnt/../etc", "b"),
            ("restic-backup.service", "1f0e", "/mnt/b\nBACKUP_TARGET_PATH=/etc", "b"),
            ("restic-backup.service", "1f0e", "/mnt/b", "bad;label$(id)"),
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


if __name__ == "__main__":
    unittest.main()
