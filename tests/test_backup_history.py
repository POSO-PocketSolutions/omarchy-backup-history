import importlib.util
import json
import unittest
from datetime import date, datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "backup-history"


class BackupHistoryTest(unittest.TestCase):
    def test_backend_exists(self):
        self.assertTrue(SCRIPT.exists(), f"Missing {SCRIPT}")

    @unittest.skipUnless(SCRIPT.exists(), "backend not implemented")
    def test_latest_result_wins_for_each_day(self):
        spec = importlib.util.spec_from_loader("backup_history", SourceFileLoader("backup_history", str(SCRIPT)))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        entries = [
            json.dumps({
                "MESSAGE_ID": module.FAILURE_MESSAGE_ID,
                "__REALTIME_TIMESTAMP": "1788422400000000",
            }),
            json.dumps({
                "MESSAGE_ID": module.SUCCESS_MESSAGE_ID,
                "__REALTIME_TIMESTAMP": "1788426000000000",
            }),
            json.dumps({
                "MESSAGE_ID": module.FAILURE_MESSAGE_ID,
                "__REALTIME_TIMESTAMP": "1788508800000000",
            }),
        ]

        events = module.parse_events(entries, timezone.utc)

        self.assertEqual(events[date(2026, 9, 3)]["status"], "success")
        self.assertEqual(events[date(2026, 9, 4)]["status"], "failed")

    @unittest.skipUnless(SCRIPT.exists(), "backend not implemented")
    def test_calendar_is_sunday_aligned(self):
        spec = importlib.util.spec_from_loader("backup_history_calendar", SourceFileLoader("backup_history_calendar", str(SCRIPT)))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        days = module.build_calendar({}, weeks=2, today=date(2026, 9, 3))

        self.assertEqual(len(days), 12)
        self.assertEqual(days[0]["date"], "2026-08-23")
        self.assertEqual(days[-1]["date"], "2026-09-03")
        self.assertEqual(days[0]["weekday"], 0)
        self.assertTrue(days[-1]["today"])


if __name__ == "__main__":
    unittest.main()
