import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "backup-history"


def load_backend():
    spec = importlib.util.spec_from_loader(
        "backup_history", SourceFileLoader("backup_history", str(SCRIPT))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParseTargetEnvTest(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend()

    def test_reads_known_keys(self):
        parsed = self.backend.parse_target_env(
            "BACKUP_TARGET_UUID=1f0e5a3c-1111-2222-3333-444455556666\n"
            "BACKUP_TARGET_PATH=/run/media/user/backup\n"
            "BACKUP_TARGET_LABEL=backup\n"
        )
        self.assertEqual(parsed["uuid"], "1f0e5a3c-1111-2222-3333-444455556666")
        self.assertEqual(parsed["path"], "/run/media/user/backup")
        self.assertEqual(parsed["label"], "backup")

    def test_ignores_comments_blanks_and_unknown_keys(self):
        parsed = self.backend.parse_target_env(
            "# written by backup-history\n"
            "\n"
            "SOMETHING_ELSE=ignored\n"
            "BACKUP_TARGET_PATH=/mnt/backup\n"
        )
        self.assertEqual(parsed["path"], "/mnt/backup")
        self.assertEqual(parsed["uuid"], "")
        self.assertNotIn("SOMETHING_ELSE", parsed)

    def test_rejects_values_failing_their_pattern(self):
        parsed = self.backend.parse_target_env(
            "BACKUP_TARGET_PATH=relative/path\n"
            "BACKUP_TARGET_UUID=not a uuid\n"
            "BACKUP_TARGET_LABEL=ok-label\n"
        )
        self.assertEqual(parsed["path"], "")
        self.assertEqual(parsed["uuid"], "")
        self.assertEqual(parsed["label"], "ok-label")

    def test_missing_file_yields_empty_target(self):
        parsed = self.backend.read_target_env("/nonexistent/backup-history/target.env")
        self.assertEqual(parsed, {"uuid": "", "path": "", "label": ""})


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend()

    def test_mounted_when_uuid_is_present_in_disks(self):
        disks = [{
            "uuid": "1f0e5a3c", "label": "backup", "size": "1.8T",
            "fstype": "ext4", "mountpoint": "/run/media/user/backup",
            "removable": True,
        }]
        target = self.backend.resolve_target(
            {"uuid": "1f0e5a3c", "path": "/stale/path", "label": "backup"},
            disks,
            True,
        )
        self.assertTrue(target["mounted"])
        self.assertEqual(target["path"], "/run/media/user/backup")
        self.assertTrue(target["dropInInstalled"])

    def test_unmounted_when_uuid_is_absent(self):
        target = self.backend.resolve_target(
            {"uuid": "1f0e5a3c", "path": "/run/media/user/backup", "label": "backup"},
            [],
            True,
        )
        self.assertFalse(target["mounted"])
        self.assertIsNone(target["freeBytes"])

    def test_known_uuid_without_mountpoint_is_not_mounted(self):
        disks = [{
            "uuid": "1f0e5a3c", "label": "backup", "size": "1.8T",
            "fstype": "ext4", "mountpoint": "", "removable": True,
        }]
        target = self.backend.resolve_target(
            {"uuid": "1f0e5a3c", "path": "", "label": "backup"}, disks, False
        )
        self.assertFalse(target["mounted"])
        self.assertFalse(target["dropInInstalled"])

    def test_unconfigured_target_is_reported_empty(self):
        target = self.backend.resolve_target(
            {"uuid": "", "path": "", "label": ""}, [], False
        )
        self.assertEqual(target["uuid"], "")
        self.assertFalse(target["mounted"])
        self.assertFalse(target["dropInInstalled"])


if __name__ == "__main__":
    unittest.main()
