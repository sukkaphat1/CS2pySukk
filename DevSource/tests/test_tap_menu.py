import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

from features import menu, combined


class Options(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_now = Mock()


class TapMenuTests(unittest.TestCase):
    def setUp(self):
        self.options = Options(CurrentWeapon="Glock-18", TriggerbotTapInterval=0.35,
            WeaponTapTimes={"Glock-18": 0.12}, EnablePerWeaponTapTimes=True)
        self.offsets = SimpleNamespace(offset=SimpleNamespace(dwLocalPlayerPawn=10))
        self.pointer = patch.object(menu.memfuncs.ProcMemHandler, "ReadPointer", return_value=1234)
        self.pointer.start()
        self.addCleanup(self.pointer.stop)

    def test_click_detects_held_weapon_not_stale_label_and_saves(self):
        with patch.object(combined, "get_current_weapon_name", return_value="AWP") as detect:
            self.assertTrue(menu._save_current_weapon_tap_time(None, 100, self.offsets, self.options))
        detect.assert_called_once_with(None, 100, 1234, self.offsets)
        self.assertEqual(self.options["WeaponTapTimes"], {"Glock-18": 0.12, "AWP": 0.35})
        self.assertEqual(self.options["CurrentWeapon"], "AWP")
        self.options.save_now.assert_called_once()

    def test_unknown_or_non_gun_does_not_overwrite(self):
        for weapon in (None, "Unknown(999)", "Knife", "HE Grenade"):
            with self.subTest(weapon=weapon), patch.object(combined, "get_current_weapon_name", return_value=weapon):
                self.assertFalse(menu._save_current_weapon_tap_time(None, 100, self.offsets, self.options))
        self.assertEqual(self.options["WeaponTapTimes"], {"Glock-18": 0.12})
        self.options.save_now.assert_not_called()

    def test_invalid_interval_is_rejected(self):
        for tap in (float("nan"), float("inf"), -1, 3):
            with self.subTest(tap=tap), patch.object(combined, "get_current_weapon_name", return_value="AWP"):
                self.options["TriggerbotTapInterval"] = tap
                self.assertFalse(menu._save_current_weapon_tap_time(None, 100, self.offsets, self.options))
        self.options.save_now.assert_not_called()

    def test_button_is_connected_to_save_handler(self):
        with patch.object(menu, "_check"), patch.object(menu, "_slider"), patch.object(menu, "_keybind"), \
             patch.object(menu.pme, "gui_label"), patch.object(menu.pme, "gui_button", return_value=True), \
             patch.object(menu, "_save_current_weapon_tap_time") as save:
            menu._draw_trigger_tab(None, 100, self.options, self.offsets)
        save.assert_called_once_with(None, 100, self.offsets, self.options)

    def test_m4_names_match_local_database_definitions(self):
        self.assertEqual(combined.WEAPON_NAMES[16], "M4A4")
        self.assertEqual(combined.WEAPON_NAMES[60], "M4A1-S")

    def test_explicit_save_bypasses_slider_throttle(self):
        # Load only the config definitions: importing main would register
        # hotkeys/start application setup, which a unit test must not do.
        path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
                 and node.name in {"ManagedConfig", "SaveConfig"}]
        env = {"time": SimpleNamespace(monotonic=lambda: 100.1), "_save_ts": 100.0,
               "globals": SimpleNamespace(SAVE_FILE="unused-test-settings.json"), "json": json}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), env)
        config = env["ManagedConfig"]({"WeaponTapTimes": {"AWP": 0.35}}, env["SaveConfig"])
        with patch("builtins.open", mock_open()) as output:
            env["SaveConfig"](config._dict)
            output.assert_not_called()
            config.save_now()
            output.assert_called_once_with("unused-test-settings.json", "w")


if __name__ == "__main__":
    unittest.main()
