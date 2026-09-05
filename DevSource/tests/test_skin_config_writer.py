"""Config handoff regression tests; use the installed application Python runtime."""
import unittest
from unittest.mock import patch

from features import skinchanger


class SkinConfigWriterTests(unittest.TestCase):
    def setUp(self):
        self.options = {"SkinChanger": {"enabled": True, "weapons": {
            "knife_test": {"paint_kit": 568, "seed": 400, "wear": 0.01}}}}
        self.database = {"weapons": {"knife_test": {"def_index": 515,
            "category": "knives", "model": "weapons/knife.vmdl"}},
            "paint_kits": {568: {"legacy": False}}}
        for context in (
            patch.object(skinchanger, "_last_cfg_write", 0),
            patch.object(skinchanger, "_last_cfg_content", "previous"),
            patch.object(skinchanger, "_log"),
            patch("builtins.print"),
        ):
            context.start()
            self.addCleanup(context.stop)

    def test_atomic_complete_selection_and_seed(self):
        with patch.object(skinchanger.items, "get_database", return_value=self.database), \
             patch.object(skinchanger.time, "monotonic", return_value=100), \
             patch.object(skinchanger, "write_atomic") as writer:
            skinchanger._write_skin_config(self.options)
            writer.assert_called_once_with(skinchanger._CONFIG_PATH,
                "515 568 400 0.01 1 weapons/knife.vmdl\n")
            self.assertEqual(skinchanger._last_cfg_content, writer.call_args.args[1])

    def test_failed_replace_does_not_commit_and_retries(self):
        with patch.object(skinchanger.items, "get_database", return_value=self.database), \
             patch.object(skinchanger.time, "monotonic", side_effect=[100, 100.2]), \
             patch.object(skinchanger, "write_atomic", side_effect=[OSError("busy"), None]) as writer:
            skinchanger._write_skin_config(self.options)
            self.assertEqual(skinchanger._last_cfg_content, "previous")
            skinchanger._write_skin_config(self.options)
            self.assertEqual(writer.call_count, 2)
            self.assertIn("568 400", skinchanger._last_cfg_content)

    def test_changed_seed_is_not_delayed_one_second(self):
        with patch.object(skinchanger.items, "get_database", return_value=self.database), \
             patch.object(skinchanger.time, "monotonic", side_effect=[100, 100.2, 100.4]), \
             patch.object(skinchanger, "write_atomic") as writer:
            skinchanger._write_skin_config(self.options)
            self.options["SkinChanger"]["weapons"]["knife_test"]["seed"] = 401
            skinchanger._write_skin_config(self.options)
            self.assertIn("568 401", writer.call_args.args[1])
            skinchanger._write_skin_config(self.options)
            self.assertEqual(writer.call_count, 2)  # unchanged state is not rewritten


if __name__ == "__main__":
    unittest.main()
