import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from features import skinshare_apply as mapping
from features import skinshare

ROOT = Path(__file__).resolve().parents[1]
DB = json.loads((ROOT / "item_cache/items_db.json").read_text())
LOCAL, REMOTE = "76561198864001604", "76561198000000002"


def selection(name, paint=0):
    return dict(item_key=name, target_def=DB["weapons"][name]["def_index"],
                source_def=DB["weapons"][name]["def_index"], paint_kit=paint,
                seed=7, wear=.125, mesh_mask=1)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = dict(phase="LIVE", settled_fingerprint="0123456789abcdef", map="de_test",
                             local_steam_id=int(LOCAL), game_rules=123456,
                             players=[dict(steam_id=int(REMOTE), slot=64, pawn_handle=0x8064,
                                           active_handle=0x80c8, active_def=9)])
        self.state = dict(protocol=1, match_id="0123456789abcdef", map="de_test", player_id=REMOTE,
                          received_monotonic=100, loadout=[selection("weapon_awp",756)])

    def records(self):
        return mapping.build_render_records(self.snapshot, {REMOTE:self.state}, DB, 101)

    def test_all_database_models_map_to_correct_identity(self):
        for name, item in DB["weapons"].items():
            with self.subTest(name=name):
                self.state["loadout"] = [selection(name, next(iter(item["skins"]),0))]
                self.snapshot["players"][0]["active_def"] = 42 if item["category"] == "knives" else item["def_index"]
                r = self.records()
                self.assertEqual(len(r),1)
                self.assertEqual(r[0]["model"], item["model"])
                self.assertEqual(r[0]["player_id"],REMOTE)
                self.assertEqual(r[0]["slot"],64)
                self.assertEqual(r[0]["pawn"],0x8064)

    def test_invalid_identity_room_map_expiry_and_duplicate_are_skipped(self):
        cases = [("player",0), ("local",int(LOCAL)), ("duplicate",None),
                 ("match","bad"), ("map","bad"), ("time",90)]
        for case,value in cases:
            self.setUp()
            if case in ("player","local"): self.snapshot["players"][0]["steam_id"] = value
            elif case == "duplicate": self.snapshot["players"].append(dict(self.snapshot["players"][0]))
            elif case == "match": self.state["match_id"] = value
            elif case == "map": self.state["map"] = value
            else: self.state["received_monotonic"] = value
            self.assertEqual(self.records(),[],case)

    def test_wrong_weapon_and_malicious_model_do_not_override_mapping(self):
        self.state["loadout"] = [selection("weapon_glock",1120)]
        self.assertEqual(self.records(),[])
        self.state["loadout"] = [dict(selection("weapon_awp",756), model="bad", category="knives")]
        self.assertEqual(self.records()[0]["model"], DB["weapons"]["weapon_awp"]["model"])
        self.state["loadout"][0]["target_def"] = 500
        self.assertEqual(self.records(),[])

    def test_bad_paint_and_nonfinite_wear(self):
        for key,value in [("paint_kit",999999),("wear",float("nan")),("wear",float("inf"))]:
            self.setUp()
            self.state["loadout"][0][key] = value
            self.assertEqual(self.records(),[])

    def test_last_knife_and_gloves_independent_of_weapon(self):
        self.state["loadout"] = [selection("weapon_bayonet"),selection("weapon_knife_butterfly"),
                                 selection("sporty_gloves")]
        self.snapshot["players"][0]["active_def"] = 59
        r = self.records()
        self.assertEqual([v["target"] for v in r],[515,5030])
        self.assertEqual([v["handle"] for v in r],[0x80c8,0])
        self.snapshot["players"][0]["active_def"] = None
        self.assertEqual([v["target"] for v in self.records()],[5030])

    def test_respawn_uses_fresh_receiver_handles(self):
        self.state["pawn_handle"] = 12
        self.snapshot["players"][0]["pawn_handle"] = 0x10064
        self.assertEqual(self.records()[0]["pawn"],0x10064)

    def test_two_players_same_gun_keep_separate_paints(self):
        other = "76561198000000003"
        self.snapshot["players"].append(dict(steam_id=int(other),slot=2,pawn_handle=0x8065,
                                             active_handle=0x80c9,active_def=9))
        other_state = dict(self.state,player_id=other,loadout=[selection("weapon_awp",51)])
        records = mapping.build_render_records(self.snapshot,{REMOTE:self.state,other:other_state},DB,101)
        self.assertEqual({r['player_id']:(r['paint'],r['handle']) for r in records},
                         {REMOTE:(756,0x80c8),other:(51,0x80c9)})

    def test_sender_default_knives_and_disabled_loadout(self):
        self.snapshot["players"].append(dict(steam_id=int(LOCAL),active_def=42))
        options = {"SkinChanger":{"enabled":True,"weapons":{"weapon_bayonet":{"paint_kit":568}}}}
        with patch.object(skinshare.items,"get_database",return_value=DB):
            payload = skinshare.build_local_payload(self.snapshot, options)
            self.assertEqual(payload["active_weapon"]["target_def"],500)
            self.assertEqual(len(payload["loadout"]),1)
            options["SkinChanger"]["enabled"] = False
            self.assertEqual(skinshare.build_local_payload(self.snapshot, options)["loadout"],[])

    def test_session_restart_and_equal_sequence_refresh(self):
        client = skinshare.SkinShareClient.__new__(skinshare.SkinShareClient)
        client._lock = threading.RLock()
        client._remote_states = {}
        payload = dict(match_id=self.state["match_id"],map="de_test",player_id=LOCAL,roster=[REMOTE,LOCAL])
        msg = dict(type="snapshot",sequence=75,state=self.state,relay_session="old")
        with patch.object(skinshare,"_log"):
            client._handle_message(msg,payload)
            msg.update(sequence=1,relay_session="new")
            client._handle_message(msg,payload)
            self.assertEqual(client._remote_states[REMOTE]["sequence"],1)
            client._remote_states[REMOTE]["received_monotonic"] = 0
            client._handle_message(msg,payload)
            self.assertGreater(client._remote_states[REMOTE]["received_monotonic"],0)
            client._handle_message(dict(type="player_left",player_id=REMOTE,relay_session="old"),payload)
            self.assertIn(REMOTE,client._remote_states)
            client._handle_message(dict(type="player_left",player_id=REMOTE,relay_session="new"),payload)
            self.assertNotIn(REMOTE,client._remote_states)


if __name__ == "__main__":
    unittest.main()
