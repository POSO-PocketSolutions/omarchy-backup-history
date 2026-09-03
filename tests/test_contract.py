import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PluginContractTest(unittest.TestCase):
    def test_plugin_files_exist(self):
        self.assertTrue((ROOT / "manifest.json").exists())
        self.assertTrue((ROOT / "BarWidget.qml").exists())
        self.assertTrue((ROOT / "Panel.qml").exists())
        self.assertTrue((ROOT / "assets" / "logo.png").exists())
        self.assertTrue((ROOT / "scripts" / "run-backup").exists())

    @unittest.skipUnless((ROOT / "manifest.json").exists(), "manifest not implemented")
    def test_manifest_is_publishable_bar_widget(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())

        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "io.github.mnsosa.backup-history")
        self.assertEqual(manifest["kinds"], ["bar-widget"])
        self.assertEqual(manifest["entryPoints"]["barWidget"], "BarWidget.qml")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["barWidget"]["defaults"]["weeks"], 4)


if __name__ == "__main__":
    unittest.main()
