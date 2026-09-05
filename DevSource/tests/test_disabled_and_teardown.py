"""Isolated fake-process tests. Never open CS2 or write live config files."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from features import combined, fovchanger, radar, bhop, aimbot, rcs, esp, skinchanger, skinshare
from features.live_context import read_context


class FakeProcess:
    process_id = 123

    def __init__(self):
        self.data = {}
        self.reads = []
        self.writes = []

    def read(self, address):
        self.reads.append(address)
        if address not in self.data:
            raise OSError("simulated unavailable memory / error 299")
        return self.data[address]

    read_longlong = read_int = read_uint = read_float = read_bool = read

    def read_bytes(self, address, count):
        value = self.read(address)
        return value[:count] if isinstance(value, bytes) else int(value).to_bytes(count, "little")

    def write(self, address, value):
        self.writes.append((address, value))
        self.data[address] = value

    write_float = write_int = write_uint = write_bool = write


class DisabledAndTeardownTests(unittest.TestCase):
    def setUp(self):
        self.p = FakeProcess()
        self.client, self.rules, self.entities, self.chunk = 0x100000, 0x200000, 0x300000, 0x400000
        self.controller, self.pawn, self.enemy, self.enemy_controller = 0x500000, 0x600000, 0x700000, 0x800000
        self.o = SimpleNamespace(dwGameRules=8, dwEntityList=16, dwLocalPlayerController=24,
            dwLocalPlayerPawn=32, m_hPlayerPawn=16, m_iHealth=20, m_lifeState=24,
            m_iTeamNum=28, m_pCameraServices=80, m_bIsScoped=88, m_flFlashMaxAlpha=92,
            m_entitySpottedState=96, m_bSpotted=0, m_bSpottedByMask=4, m_iFOV=16)
        self.offsets = SimpleNamespace(offset=self.o)
        self.options = dict(EnableAntiFlashbang=False, EnableTriggerbot=False, EnableFovChanger=False,
            EnableRadarHack=False, EnableBhop=False, EnableAimbot=False, EnableRecoilControl=False)
        self.p.data.update({self.client+8: self.rules, self.client+16: self.entities,
            self.client+24: self.controller, self.client+32: self.pawn,
            self.entities+16: self.chunk, self.chunk+112: self.controller,
            self.chunk+112*64: self.enemy_controller,
            self.chunk+112*101: self.pawn, self.chunk+112*100: self.enemy,
            self.controller+16: 0x8065, self.enemy_controller+16: 0x8064,
            self.pawn+20: 100, self.enemy+20: 100, self.pawn+24: 0, self.enemy+24: 0,
            self.pawn+28: 2, self.enemy+28: 3, self.pawn+92: 255.0,
            self.enemy+96: False, self.enemy+100: 0,
            self.pawn+80: 0x900000, self.pawn+88: False, 0x900010: 90})
        radar._next_poll = 0
        self.weapon = patch.object(combined, "get_current_weapon_name", return_value=None)
        self.weapon.start()
        self.addCleanup(self.weapon.stop)

    def test_disabled_features_make_zero_game_writes_over_many_frames(self):
        with patch.object(combined.gameinput, "LeftClick") as click, \
             patch.object(rcs.win32gui, "GetForegroundWindow", return_value=0), \
             patch.object(rcs.win32gui, "GetWindowText", return_value="Counter-Strike 2"):
            for _ in range(165):
                combined.Triggerbot_AntiFlash_Update(self.p, self.client, self.offsets, self.options)
                fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
                radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
                bhop.Bhop_Update(self.p, self.client, self.offsets, self.options)
                aimbot.Aimbot_Update(self.p, self.client, self.offsets, self.options, None)
                rcs.RecoilControl_Update(self.p, self.client, self.offsets, self.options, None)
            click.assert_not_called()
        self.assertEqual(self.p.writes, [])

    def test_disabled_radar_and_fov_do_not_even_read_memory(self):
        radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.reads, [])

    def test_antiflash_only_writes_changed_value(self):
        self.options["EnableAntiFlashbang"] = True
        for _ in range(10):
            combined.Triggerbot_AntiFlash_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [(self.pawn+92, 0.0)])

    def test_antiflash_rejects_context_changed_before_write(self):
        self.options["EnableAntiFlashbang"] = True
        context = Mock(pawn=self.pawn)
        context.current.return_value = False
        with patch.object(combined, "read_context", return_value=context):
            combined.Triggerbot_AntiFlash_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [])

    def test_teardown_first_read_error_does_not_escape_any_writer(self):
        self.p.data.clear()
        self.options.update(EnableAntiFlashbang=True, EnableFovChanger=True, EnableRadarHack=True)
        combined.Triggerbot_AntiFlash_Update(self.p, self.client, self.offsets, self.options)
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [])

    def test_dead_or_replaced_pawn_is_not_a_live_context(self):
        self.assertIsNotNone(read_context(self.p, self.client, self.o))
        for address, bad in ((self.pawn+20, 0), (self.pawn+24, 1),
                             (self.controller+16, 0xFFFFFFFF), (self.chunk+112*101, self.enemy)):
            old = self.p.data[address]
            self.p.data[address] = bad
            self.assertIsNone(read_context(self.p, self.client, self.o))
            self.p.data[address] = old

    def test_engine_signoff_rejects_still_readable_living_pawn(self):
        self.o._engine_base = 0xA00000
        self.o.dwNetworkGameClient = 48
        self.o.dwNetworkGameClient_signOnState = 560
        self.p.data.update({0xA00030: 0xB00000, 0xB00000+560: 6})
        self.assertIsNotNone(read_context(self.p, self.client, self.o))
        self.p.data[0xB00000+560] = 0
        self.assertIsNone(read_context(self.p, self.client, self.o))
        self.options.update(EnableAntiFlashbang=True, EnableFovChanger=True, EnableRadarHack=True)
        combined.Triggerbot_AntiFlash_Update(self.p, self.client, self.offsets, self.options)
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [])

    def test_fov_changed_only_and_no_restore_when_disabled(self):
        self.options.update(EnableFovChanger=True, FovChangeSize=110)
        for _ in range(10):
            fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        self.options["EnableFovChanger"] = False
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [(0x900010, 110)])

    def test_fov_scoped_or_missing_camera_skips_write(self):
        self.options.update(EnableFovChanger=True, FovChangeSize=110)
        self.p.data[self.pawn+88] = True
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        self.p.data[self.pawn+88] = False
        self.p.data[self.pawn+80] = 0
        fovchanger.FovChanger_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [])

    def test_radar_is_throttled_and_includes_slot64_without_repeated_writes(self):
        self.options["EnableRadarHack"] = True
        with patch.object(radar.time, "monotonic") as clock, \
             patch.object(radar, "read_context", wraps=read_context) as reader:
            for frame in range(165):
                clock.return_value = frame / 165
                radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
            self.assertLessEqual(reader.call_count, 10)
            self.assertGreaterEqual(reader.call_count, 9)
        self.assertEqual(self.p.writes, [(self.enemy+96, True), (self.enemy+100, 0xFFFFFFFF)])

    def test_radar_rejects_replaced_local_context(self):
        self.options["EnableRadarHack"] = True
        context = Mock(pawn=self.pawn, controller=self.controller, entities=self.entities)
        context.current.return_value = False
        with patch.object(radar, "read_context", return_value=context):
            radar.RadarHack_Update(self.p, self.client, self.offsets, self.options)
        self.assertEqual(self.p.writes, [])

    def test_skeleton_bone_positions_use_one_contiguous_read(self):
        raw = bytearray(22*32+12)
        for index in esp.PLAYER_BONES.values():
            struct.pack_into("<fff", raw, index*32, index, index+1, index+2)
        self.p.data[0xA00000] = bytes(raw)
        bones = esp.read_bones(self.p, 0xA00000)
        self.assertEqual(self.p.reads, [0xA00000])
        self.assertEqual(bones["head"].x, 7)
        self.assertEqual(bones["ankle_R"].z, 24)

    def test_disabled_skin_config_clears_once_even_without_database(self):
        options = {"SkinChanger": {"enabled": False, "weapons": {"old": {"paint_kit": 1}}}}
        with patch.object(skinchanger, "_last_cfg_content", "old"), \
             patch.object(skinchanger, "write_atomic") as writer, \
             patch.object(skinchanger, "_log"), patch("builtins.print"), \
             patch.object(skinchanger.items, "get_database", return_value=None) as database:
            for _ in range(100):
                skinchanger._write_skin_config(options)
            writer.assert_called_once_with(skinchanger._CONFIG_PATH, "")
            database.assert_not_called()

    def test_disabled_native_control_is_written_once_without_game_reads(self):
        with patch.object(skinchanger, "_last_control_state", None), \
             patch.object(skinchanger, "_last_control_time", 0), \
             patch.object(skinchanger, "write_atomic") as writer:
            for _ in range(100):
                skinchanger._publish_control(self.p, self.client, self.offsets, {})
            writer.assert_called_once_with(skinchanger._CONTROL_PATH, "CS2PY_CONTROL_V1 123 0 0 0 0 0\n")
        self.assertEqual(self.p.reads, [])

    def test_retired_direct_skin_writer_cannot_bypass_disable(self):
        with self.assertRaises(RuntimeError):
            skinchanger.apply_skin(self.p, self.enemy, self.offsets, 1206)
        self.assertEqual(self.p.writes, [])

    def test_native_permission_heartbeat_is_bounded_but_disable_is_immediate(self):
        self.o.dwNetworkGameClient = 48
        self.o.dwNetworkGameClient_signOnState = 560
        self.p.data.update({0xA00030: 0xB00000, 0xB00000+560: 6})
        options = {"SkinChanger": {"enabled": True}}
        with patch.object(skinchanger, "_last_control_state", None), \
             patch.object(skinchanger, "_last_control_time", 0), \
             patch.object(skinchanger.memfuncs, "GetModuleBase", return_value=0xA00000), \
             patch.object(skinchanger.time, "monotonic", side_effect=[100, 100.01, 100.02]), \
             patch.object(skinchanger.time, "time", return_value=100), \
             patch.object(skinchanger, "write_atomic") as writer:
            skinchanger._publish_control(self.p, self.client, self.offsets, options)
            self.assertEqual(writer.call_args.args[1],
                f"CS2PY_CONTROL_V1 123 101500 1 0 {self.rules} {self.entities}\n")
            skinchanger._publish_control(self.p, self.client, self.offsets, options)
            self.assertEqual(writer.call_count, 1)
            skinchanger._publish_control(self.p, self.client, self.offsets, {})
            self.assertEqual(writer.call_count, 2)
            self.assertEqual(writer.call_args.args[1], "CS2PY_CONTROL_V1 123 0 0 0 0 0\n")

    def test_both_cosmetic_toggles_disabled_do_not_inject(self):
        with patch.object(skinchanger, "_write_skin_config"), \
             patch.object(skinchanger, "_publish_control"), patch.object(skinchanger, "_log"), \
             patch.object(skinchanger.inject, "inject_skinchanger") as inject:
            skinchanger.SkinChanger_Update(self.p, self.client, self.offsets, {})
            inject.assert_not_called()

    def test_disabled_share_bridge_clears_once_and_does_not_rewrite_on_timer(self):
        # Suppress thread start: this test must never connect to any relay.
        with patch.object(skinshare.threading.Thread, "start"), \
             patch.object(skinshare.items, "get_database", return_value={}), \
             patch.object(skinshare.skinshare_apply, "write_atomic") as writer, \
             patch.object(skinshare, "_log"):
            client = skinshare.SkinShareClient()
            for _ in range(10):
                client._next_render_write = 0
                client._publish_render_state(False)
            self.assertEqual(writer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
