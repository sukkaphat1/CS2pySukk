"""CS2 item schema database.

Parses the game's ``scripts/items/items_game.txt`` (weapons, knives, gloves,
paint kits) and ``resource/csgo_english.txt`` (localized display names) out of
``pak01_dir.vpk`` and flattens them into a small, cacheable structure for the
skin changer UI:

    categories  ->  ordered [{key, label}, ...]
    weapons     ->  {internal_name: {def_index, name, label, category, skins:[..]}}
    paint_kits  ->  {paint_kit_id: {id, name, label}}

The parsed result is cached to ``item_cache/items_db.json`` so the 8 MB VDF is
only read once.
"""
import json
import os
import struct

from ext import paths

# --------------------------------------------------------------------------
# VPK (v2, multi-chunk) reading
# --------------------------------------------------------------------------
def _parse_vpk_dir_with_archive(tree):
    """Return {filename: (archive_index, entry_offset, entry_length)}."""
    pos = 0
    files = {}

    def rs(p):
        e = tree.find(b"\x00", p)
        return tree[p:e].decode("ascii", "replace"), e + 1

    while pos < len(tree):
        ext, pos = rs(pos)
        if ext == "":
            break
        while True:
            path, pos = rs(pos)
            if path == "":
                break
            while True:
                fname, pos = rs(pos)
                if fname == "":
                    break
                crc, preload, aidx, eoff, elen, term = struct.unpack("<IHHIIH", tree[pos:pos + 18])
                pos += 18
                files[path + fname + "." + ext] = (aidx, eoff, elen)
    return files


def read_vpk_file(base, name):
    """Read a file out of pak01_dir.vpk (handles the chunk files)."""
    dirv = os.path.join(base, "csgo", "pak01_dir.vpk")
    with open(dirv, "rb") as f:
        header = f.read(28)
        dir_size = struct.unpack("<I", header[8:12])[0]
        tree = f.read(dir_size)
    files = _parse_vpk_dir_with_archive(tree)
    if name not in files:
        return None
    aidx, eoff, elen = files[name]
    if aidx == 0x7FFF:
        src = dirv
        base_off = 28 + dir_size
    else:
        src = os.path.join(base, "csgo", "pak01_%03d.vpk" % aidx)
        base_off = 0
    with open(src, "rb") as f:
        f.seek(base_off + eoff)
        return f.read(elen)


def _game_base():
    """Derive the CS2 ``game`` folder (cached)."""
    if hasattr(_game_base, "_cached"):
        return _game_base._cached
    base = None
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            try:
                if p.info.get("name") == "cs2.exe" and p.info.get("exe"):
                    base = os.path.dirname(os.path.dirname(os.path.dirname(p.info["exe"])))
                    break
            except Exception:
                continue
    except Exception:
        pass
    if not base:
        base = r"F:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game"
    _game_base._cached = base
    return base


# --------------------------------------------------------------------------
# Schema flattening
# --------------------------------------------------------------------------
_CATEGORY_ORDER = [
    ("rifles", "#CSGO_Type_Rifle"),
    ("pistols", "#CSGO_Type_Pistol"),
    ("smgs", "#CSGO_Type_SMG"),
    ("snipers", "#CSGO_Type_SniperRifle"),
    ("heavy", "#CSGO_Type_Machinegun"),
    ("shotguns", "#CSGO_Type_Shotgun"),
    ("knives", "#CSGO_Type_Knife"),
    ("gloves", "#Type_Hands"),
]

_CATEGORY_LABELS = {
    "rifles": "Rifles",
    "pistols": "Pistols",
    "smgs": "SMGs",
    "snipers": "Sniper Rifles",
    "heavy": "Heavy",
    "shotguns": "Shotguns",
    "knives": "Knives",
    "gloves": "Gloves",
}

_TYPE_TO_CATEGORY = {t: c for c, t in _CATEGORY_ORDER}

_SKIP_ITEMS = {"default", "weapon_knifegg", "weapon_knife", "weapon_knife_t"}


def _pretty_weapon(name):
    """Fallback display name for a weapon internal name."""
    s = name
    if s.startswith("weapon_"):
        s = s[len("weapon_"):]
    s = s.replace("_", " ").title()
    return s


def _build_weapon_label(name, item_name, tokens):
    """Localized display name: item_name loc key first, else #SFUI_WPNHUD_<NAME>."""
    key = item_name or ("#SFUI_WPNHUD_" + name.replace("weapon_", "").upper())
    label = tokens.get(key.lstrip("#"))
    if label:
        return label
    return _pretty_weapon(name)


def _paint_label(entry, tokens):
    """Short skin name via description_tag loc key, with fallback."""
    tag = entry.get("description_tag") or ""
    if tag:
        label = tokens.get(tag.lstrip("#"))
        if label:
            return label
    return _pretty_weapon(entry.get("name", ""))


def _model_path(item, prefabs):
    """Resolve the world/viewmodel path for an item (item, then prefab chain)."""
    m = item.get("model_player") or item.get("model_world")
    if m:
        return m
    p = prefabs.get(item.get("prefab"))
    seen = 0
    while p and seen < 10:
        m = p.get("model_player") or p.get("model_world")
        if m:
            return m
        p = prefabs.get(p.get("prefab"))
        seen += 1
    return None


def _load_localization(base):
    raw = read_vpk_file(base, "resourcecsgo_english.txt")
    if not raw:
        return {}
    try:
        import vdf
        data = vdf.loads(raw.decode("utf-8", errors="replace"))
        return data.get("lang", {}).get("Tokens", {})
    except Exception:
        return {}


def _load_schema(base):
    raw = read_vpk_file(base, "scripts/itemsitems_game.txt")
    if not raw:
        return None
    try:
        import vdf
        return vdf.loads(raw.decode("utf-8", errors="replace"))["items_game"]
    except Exception:
        return None


def build_database():
    """Parse and flatten the item schema. Returns a dict, or None on failure."""
    base = _game_base()
    schema = _load_schema(base)
    if not schema:
        return None
    tokens = _load_localization(base)

    prefabs = schema.get("prefabs", {})
    items = schema.get("items", {})
    paint_kits = schema.get("paint_kits", {})
    item_sets = schema.get("item_sets", {})

    def base_type(prefab_name, depth=0):
        if depth > 10 or not prefab_name:
            return None
        p = prefabs.get(prefab_name)
        if not p:
            return None
        t = p.get("item_type_name")
        if t:
            return t
        return base_type(p.get("prefab"), depth + 1)

    # paint kit id -> {id, name, label}
    pk_by_name = {}
    pk_db = {}
    for k, pk in paint_kits.items():
        try:
            pid = int(k)
        except (ValueError, TypeError):
            continue
        if pk.get("name") in ("default", "workshop_default"):
            continue
        name = pk.get("name", "")
        entry = {
            "id": pid,
            "name": name,
            "label": _paint_label(pk, tokens),
            "legacy": pk.get("use_legacy_model") == "1",
        }
        pk_db[pid] = entry
        if name:
            pk_by_name[name] = pid

    # weapons / knives / gloves
    weapons = {}
    for k, it in items.items():
        try:
            def_index = int(k)
        except (ValueError, TypeError):
            continue
        name = it.get("name", "")
        if not name or name in _SKIP_ITEMS:
            continue
        cat = _TYPE_TO_CATEGORY.get(base_type(it.get("prefab")))
        if cat is None:
            continue
        weapons[name] = {
            "def_index": def_index,
            "name": name,
            "label": _build_weapon_label(name, it.get("item_name"), tokens),
            "category": cat,
            "model": _model_path(it, prefabs),
            "skins": [],
        }

    # weapon -> skins from collections ([paintkit]weapon entries)
    for sname, s in item_sets.items():
        if s.get("is_collection") != "1":
            continue
        for item_key in (s.get("items") or {}):
            # item_key looks like "[cu_tec9_asiimov]weapon_tec9"
            if not item_key.startswith("["):
                continue
            close = item_key.find("]")
            if close < 1:
                continue
            pk_name = item_key[1:close]
            wname = item_key[close + 1:]
            pid = pk_by_name.get(pk_name)
            w = weapons.get(wname)
            if pid is not None and w is not None:
                if pid not in w["skins"]:
                    w["skins"].append(pid)

    # categories in display order
    categories = []
    for ckey, _t in _CATEGORY_ORDER:
        categories.append({"key": ckey, "label": _CATEGORY_LABELS[ckey]})

    return {
        "categories": categories,
        "weapons": weapons,
        "paint_kits": pk_db,
    }


# --------------------------------------------------------------------------
# Cached access
# --------------------------------------------------------------------------
_CACHE_DIR = os.path.join(paths.writable_dir(), "item_cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "items_db.json")
_BUNDLED_CACHE = os.path.join(paths.bundle_dir(), "item_cache", "items_db.json")

_db = None


def get_database():
    """Return the item database, building + caching it on first use."""
    global _db
    if _db is not None:
        return _db
    # Prefer a bundled read-only copy (exe), else the writable cache.
    for candidate in (_BUNDLED_CACHE, _CACHE_FILE):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    _db = json.load(f)
                # JSON dict keys are strings; restore int paint-kit ids.
                if _db and isinstance(_db.get("paint_kits"), dict):
                    _db["paint_kits"] = {int(k): v for k, v in _db["paint_kits"].items()}
                return _db
            except Exception:
                _db = None
    print("[skin-changer] Building item database (one-time)...")
    _db = build_database()
    if _db:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_db, f)
        except Exception:
            pass
    return _db
