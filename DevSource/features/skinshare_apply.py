"""Validate relay selections and build receiver-local rendering instructions.

This module never trusts a peer's entity handles, model paths or category.
SteamID -> slot/pawn/weapon comes exclusively from our local match sampler.
"""
import math
import json
from functools import lru_cache
import os
import tempfile
import time
from ext import paths


@lru_cache(maxsize=1)
def cosmetic_pairs():
    # The item database only lists collection paints for guns. The skin menu
    # uses this bundled map for knife/glove compatibility, so use it here too.
    try:
        with open(os.path.join(paths.bundle_dir(), "preview_cache", "image_map.json"), encoding="utf-8") as source:
            return frozenset(json.load(source))
    except (OSError, ValueError):
        return frozenset()


def is_knife(definition):
    return definition in (42, 59) or 500 <= definition <= 526


def resolve_selection(record, database):
    if not isinstance(record, dict):
        return None
    item = database.get("weapons", {}).get(record.get("item_key"))
    if not item or item.get("category") == "gloves":
        return None
    try:
        target = int(record["target_def"])
        paint, seed = int(record["paint_kit"]), int(record["seed"])
        wear = float(record["wear"])
        if target != int(item["def_index"]) or not 0 <= seed <= 1000000:
            return None
        if not math.isfinite(wear) or not 0 <= wear <= 1:
            return None
        compatible = paint in item.get("skins", []) or (
            item.get("category") in ("knives", "gloves") and
            f"{record['item_key']}|{paint}" in cosmetic_pairs()
        )
        if paint != 0 and not compatible:
            return None
        model = item.get("model", "")
        if not model.endswith(".vmdl") or len(model) >= 320:
            return None
        if any(c.isspace() for c in model) or ".." in model or "\\" in model:
            return None
        paint_info = database.get("paint_kits", {}).get(paint) or database.get("paint_kits", {}).get(str(paint), {})
        return dict(target=target, paint=paint, seed=seed, wear=wear,
                    mesh=2 if paint_info.get("legacy") else 1,
                    model=model, category=item["category"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def build_render_records(snapshot, states, database, now=None):
    """At most one supported active weapon instruction per live player."""
    now = time.monotonic() if now is None else now
    if not snapshot or snapshot.get("phase") != "LIVE" or not snapshot.get("settled_fingerprint"):
        return []
    local_id = str(snapshot.get("local_steam_id"))
    roster = {}
    for player in snapshot.get("players", []):
        player_id = str(player.get("steam_id", 0))
        # An ambiguous SteamID mapping must never pick an arbitrary pawn.
        roster[player_id] = None if player_id in roster else player
    result = []
    for player_id, state in states.items():
        player = roster.get(player_id)
        if not player or player_id == local_id or player_id == "0":
            continue
        if state.get("match_id") != snapshot["settled_fingerprint"] or state.get("map") != snapshot.get("map"):
            continue
        if not 0 <= now - state.get("received_monotonic", -1e9) <= 5:
            continue
        pawn = int(player.get("pawn_handle", 0)) & 0xffffffff
        handle = int(player.get("active_handle", 0)) & 0xffffffff
        if pawn in (0, 0xffffffff) or not 1 <= player.get("slot", 0) <= 64:
            continue
        raw_records = state.get("loadout")
        if raw_records is None:
            raw_records = [state.get("active_weapon")]
        if not isinstance(raw_records, list) or len(raw_records) > 64:
            continue
        selections = [s for r in raw_records if (s := resolve_selection(r, database))]
        active_def = player.get("active_def")
        weapon = None
        for selection in selections:
            category = selection["category"]
            if isinstance(active_def, int):
                if (category == "knives" and is_knife(active_def)) or (
                    category != "knives" and selection["target"] == active_def
                ):
                    weapon = selection
        if weapon is None or handle in (0, 0xffffffff):
            continue
        result.append(dict(weapon, player_id=player_id, slot=player["slot"],
                           pawn=pawn, handle=handle, source=active_def, kind=0))
    return result[:128]


def render_file(snapshot, records, now_ms=None):
    deadline = int(time.time() * 1000 if now_ms is None else now_ms) + 3000
    rules = int((snapshot or {}).get("game_rules") or 0)
    local_id = int((snapshot or {}).get("local_steam_id") or 0)
    lines = [f"CS2PY_REMOTE_V1 {deadline} {rules} {local_id} {len(records)}"]
    for r in records:
        lines.append(f"{r['player_id']} {r['slot']} {r['pawn']} {r['handle']} "
                     f"{r['source']} {r['target']} {r['paint']} {r['seed']} "
                     f"{r['wear']:.8f} {r['mesh']} {r['kind']} {r['model']}")
    return "\n".join(lines) + "\n"


def write_atomic(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=os.path.dirname(path),
                                         prefix=".cs2py_remote_", delete=False) as output:
            temporary = output.name
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
