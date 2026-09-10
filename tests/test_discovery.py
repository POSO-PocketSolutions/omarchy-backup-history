import importlib.util
import json
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


LSBLK = json.dumps({
    "blockdevices": [
        {
            "name": "sda", "type": "disk", "uuid": None, "label": None,
            "size": "1.8T", "fstype": None, "mountpoint": None, "rm": True,
            "children": [
                {
                    "name": "sda1", "type": "part",
                    "uuid": "1f0e5a3c-1111-2222-3333-444455556666",
                    "label": "backup", "size": "1.8T", "fstype": "ext4",
                    "mountpoint": "/run/media/user/backup", "rm": True,
                }
            ],
        },
        {
            "name": "nvme0n1p2", "type": "part",
            "uuid": "aaaa-bbbb", "label": "root", "size": "930G",
            "fstype": "ext4", "mountpoint": "/", "rm": False,
        },
        {
            "name": "sdb1", "type": "part", "uuid": None, "label": "unformatted",
            "size": "16G", "fstype": None, "mountpoint": None, "rm": True,
        },
    ]
})


class ParseDisksTest(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend()

    def test_flattens_children_and_keeps_filesystems_with_uuids(self):
        disks = self.backend.parse_disks(LSBLK)
        uuids = [disk["uuid"] for disk in disks]
        self.assertIn("1f0e5a3c-1111-2222-3333-444455556666", uuids)
        self.assertNotIn(None, uuids)
        # The root filesystem (mountpoint "/") is excluded unconditionally as
        # defense-in-depth, even without root_source.
        self.assertEqual(len(disks), 1)

    def test_reports_expected_fields(self):
        disks = self.backend.parse_disks(LSBLK)
        disk = next(d for d in disks if d["label"] == "backup")
        self.assertEqual(disk["size"], "1.8T")
        self.assertEqual(disk["fstype"], "ext4")
        self.assertEqual(disk["mountpoint"], "/run/media/user/backup")
        self.assertTrue(disk["removable"])

    def test_excludes_the_root_filesystem(self):
        disks = self.backend.parse_disks(LSBLK, root_source="/dev/nvme0n1p2")
        self.assertEqual([disk["label"] for disk in disks], ["backup"])

    def test_caps_the_disk_count(self):
        many = json.dumps({"blockdevices": [
            {"name": f"sd{index}", "type": "part", "uuid": f"uuid-{index}",
             "label": None, "size": "1G", "fstype": "ext4",
             "mountpoint": None, "rm": False}
            for index in range(100)
        ]})
        self.assertEqual(len(self.backend.parse_disks(many)), self.backend.MAX_DISKS)

    def test_offers_a_disk_with_a_non_ascii_label_and_mountpoint(self):
        accented = json.dumps({"blockdevices": [
            {
                "name": "sdc1", "type": "part", "uuid": "cccc-dddd",
                "label": "Sauvegarde-été", "size": "2T", "fstype": "ext4",
                "mountpoint": "/run/media/user/Sauvegarde-été", "rm": True,
            },
        ]})
        disks = self.backend.parse_disks(accented)
        self.assertEqual([disk["label"] for disk in disks], ["Sauvegarde-été"])
        self.assertEqual(disks[0]["mountpoint"], "/run/media/user/Sauvegarde-été")

    def test_never_offers_a_disk_the_writer_would_refuse(self):
        dangerous = json.dumps({"blockdevices": [
            {
                "name": "sdc1", "type": "part", "uuid": "cccc-1111",
                "label": "label=value", "size": "2T", "fstype": "ext4",
                "mountpoint": "/mnt/a", "rm": True,
            },
            {
                "name": "sdc2", "type": "part", "uuid": "cccc-2222",
                "label": "line\nBACKUP_TARGET_PATH=/etc", "size": "2T",
                "fstype": "ext4", "mountpoint": "/mnt/b", "rm": True,
            },
            {
                "name": "sdc3", "type": "part", "uuid": "cccc-3333",
                "label": "escape", "size": "2T", "fstype": "ext4",
                "mountpoint": "/mnt/../etc", "rm": True,
            },
            {
                "name": "sdc4", "type": "part", "uuid": "cccc-4444",
                "label": "fine", "size": "2T", "fstype": "ext4",
                "mountpoint": "/mnt/fine", "rm": True,
            },
        ]})
        disks = self.backend.parse_disks(dangerous)
        self.assertEqual([disk["uuid"] for disk in disks], ["cccc-4444"])

    def test_malformed_json_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.backend.parse_disks("{not json")

    def test_excludes_root_mountpoint_even_without_root_source(self):
        rooted = json.dumps({"blockdevices": [
            {
                "name": "nvme0n1p2", "type": "part", "uuid": "aaaa-bbbb",
                "label": "root", "size": "930G", "fstype": "ext4",
                "mountpoint": "/", "rm": False,
            },
            {
                "name": "sda1", "type": "part",
                "uuid": "1f0e5a3c-1111-2222-3333-444455556666",
                "label": "backup", "size": "1.8T", "fstype": "ext4",
                "mountpoint": "/run/media/user/backup", "rm": True,
            },
        ]})
        disks = self.backend.parse_disks(rooted)
        self.assertEqual([disk["label"] for disk in disks], ["backup"])


SYSTEMCTL = json.dumps([
    {"unit": "accounts-daemon.service", "active": "active", "sub": "running"},
    {"unit": "restic-backup.service", "active": "inactive", "sub": "dead"},
    {"unit": "borg-backup.service", "active": "active", "sub": "running"},
    {"unit": "not-a-unit", "active": "active", "sub": "running"},
    {"unit": "user@1000.service", "active": "active", "sub": "running"},
])


class ParseServicesTest(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend()

    def test_keeps_only_valid_service_names(self):
        units = [service["unit"] for service in self.backend.parse_services(SYSTEMCTL)]
        self.assertIn("restic-backup.service", units)
        self.assertNotIn("not-a-unit", units)

    def test_excludes_units_that_do_not_look_like_backup_jobs(self):
        units = [service["unit"] for service in self.backend.parse_services(SYSTEMCTL)]
        self.assertNotIn("accounts-daemon.service", units)
        self.assertNotIn("user@1000.service", units)
        self.assertEqual(units, ["restic-backup.service", "borg-backup.service"])

    def test_keeps_units_whose_type_is_oneshot_when_the_listing_reports_it(self):
        listing = json.dumps([
            {"unit": "vault-sync.service", "type": "oneshot", "active": "inactive"},
            {"unit": "vault-daemon.service", "type": "simple", "active": "active"},
            # A name that matches the heuristic but is not oneshot: the listing's
            # own Type wins where it is knowable.
            {"unit": "backup-monitor.service", "type": "simple", "active": "active"},
        ])
        units = [service["unit"] for service in self.backend.parse_services(listing)]
        self.assertEqual(units, ["vault-sync.service"])

    def test_keeps_units_matching_the_configured_units_stem(self):
        listing = json.dumps([
            {"unit": "vault-sync.service", "active": "inactive"},
            {"unit": "vault-sync-prune.service", "active": "inactive"},
            {"unit": "accounts-daemon.service", "active": "active"},
        ])
        units = [
            service["unit"]
            for service in self.backend.parse_services(listing, configured="vault-sync.service")
        ]
        self.assertEqual(units, ["vault-sync.service", "vault-sync-prune.service"])

    def test_configured_unit_is_kept_even_when_it_does_not_match_the_heuristic(self):
        listing = json.dumps([
            {"unit": "accounts-daemon.service", "active": "active", "sub": "running"},
            {"unit": "zzz.service", "active": "active", "sub": "running"},
        ])
        services = self.backend.parse_services(listing, configured="zzz.service")
        self.assertEqual([service["unit"] for service in services], ["zzz.service"])
        self.assertEqual(services[0]["state"], "active")
        self.assertTrue(services[0]["exists"])

    def test_reports_active_state(self):
        services = self.backend.parse_services(SYSTEMCTL)
        borg = next(service for service in services if service["unit"] == "borg-backup.service")
        self.assertEqual(borg["state"], "active")
        self.assertTrue(borg["exists"])

    def test_configured_unit_is_listed_first_even_when_absent(self):
        services = self.backend.parse_services(SYSTEMCTL, configured="missing-backup.service")
        self.assertEqual(services[0]["unit"], "missing-backup.service")
        self.assertFalse(services[0]["exists"])

    def test_configured_unit_is_not_duplicated(self):
        services = self.backend.parse_services(SYSTEMCTL, configured="restic-backup.service")
        units = [service["unit"] for service in services]
        self.assertEqual(units.count("restic-backup.service"), 1)
        self.assertEqual(units[0], "restic-backup.service")

    def test_caps_the_service_count(self):
        many = json.dumps([
            {"unit": f"backup-{index}.service", "active": "inactive", "sub": "dead"}
            for index in range(200)
        ])
        self.assertEqual(len(self.backend.parse_services(many)), self.backend.MAX_SERVICES)


if __name__ == "__main__":
    unittest.main()
