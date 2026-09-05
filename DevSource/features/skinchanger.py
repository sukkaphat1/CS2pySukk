"""Local skin changer.

Publishes selections and short-lived permission for the native renderer.
The skin set for each weapon is stored in ``Options["SkinChanger"]``:

    {
        "enabled": true,
        "weapons": {
            "weapon_ak47": {"paint_kit": 490, "seed": 0, "wear": 0.0, "stat_trak": -1},
            ...
        }
    }

Gloves remain disabled. This module no longer directly writes item attributes.
"""
import os
import struct
import time

from functions import memfuncs
from ext import items
from features import inject
from features.skinshare_apply import write_atomic


def get_active_weapon(processHandle, clientBaseAddress, Offsets):
    """Resolve the local player's active weapon entity. Returns None on failure."""
    try:
        localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
        if not localPawn:
            return None
        weapon_services = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPawn + Offsets.offset.m_pWeaponServices)
        if not weapon_services:
            return None
        weapon_handle = memfuncs.ProcMemHandler.ReadInt(processHandle, weapon_services + Offsets.offset.m_hActiveWeapon)
        if not weapon_handle:
            return None
        entityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
        list_entry = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityList + 0x8 * ((weapon_handle & 0x7FFF) >> 9) + 0x10)
        weapon = memfuncs.ProcMemHandler.ReadPointer(processHandle, list_entry + 0x70 * (weapon_handle & 0x1FF))
        if not weapon:
            return None
        return weapon
    except Exception:
        return None


def get_active_weapon_def(processHandle, clientBaseAddress, Offsets, weapon=None):
    weapon = weapon or get_active_weapon(processHandle, clientBaseAddress, Offsets)
    if not weapon:
        return None
    try:
        return memfuncs.ProcMemHandler.ReadUShort(
            processHandle,
            weapon + Offsets.offset.m_AttributeManager + Offsets.offset.m_Item + Offsets.offset.m_iItemDefinitionIndex,
        )
    except Exception:
        return None


def weapon_name_from_def(def_index, db=None):
    db = db or items.get_database()
    if not db:
        return None
    for name, w in db["weapons"].items():
        if w["def_index"] == def_index:
            return name
    return None


def _resolve_handle(processHandle, clientBaseAddress, Offsets, handle):
    """Resolve a CEntityHandle to its entity pointer."""
    if not handle or handle == 0xFFFFFFFF:
        return None
    try:
        entityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
        list_entry = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityList + 0x8 * ((handle & 0x7FFF) >> 9) + 0x10)
        return memfuncs.ProcMemHandler.ReadPointer(processHandle, list_entry + 0x70 * (handle & 0x1FF))
    except Exception:
        return None


def get_glove_entity(processHandle, clientBaseAddress, Offsets):
    """Find the local player's glove entity (C_EconWearable) via m_hMyWearables."""
    db = items.get_database()
    if not db:
        return None
    glove_defs = {w["def_index"] for w in db["weapons"].values() if w["category"] == "gloves"}
    try:
        localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
        if not localPawn:
            return None
        # m_hMyWearables is a CUtlVector<CEntityHandle>: data ptr at +0, size at +8.
        data_ptr = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPawn + Offsets.offset.m_hMyWearables)
        size = memfuncs.ProcMemHandler.ReadInt(processHandle, localPawn + Offsets.offset.m_hMyWearables + 8)
        if not data_ptr or not size or size > 16:
            return None
        raw = memfuncs.ProcMemHandler.ReadBytes(processHandle, data_ptr, size * 4)
        for i in range(size):
            handle = struct.unpack_from("<I", raw, i * 4)[0]
            entity = _resolve_handle(processHandle, clientBaseAddress, Offsets, handle)
            if not entity:
                continue
            def_index = get_active_weapon_def(processHandle, clientBaseAddress, Offsets, entity)
            if def_index in glove_defs:
                return entity
    except Exception:
        pass
    return None


def apply_skin(*args, **kwargs):
    """Retired external writer; all cosmetics must use the gated native path."""
    raise RuntimeError("Legacy direct skin writes are disabled; use SkinChanger_Update.")


_last_cfg_write = 0.0
_last_cfg_content = None
_last_weapons_sig = None
_last_control_time = 0.0
_last_control_state = None

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), "cs2py_skin.txt")
_CONTROL_PATH = os.path.join(os.path.expanduser("~"), "cs2py_skin_control.txt")
_DEBUG_LOG = os.path.join(os.path.expanduser("~"), "cs2py_skin_debug.log")


def _log(msg):
    try:
        print(f"[skin-changer] {msg}", flush=True)
    except Exception:
        pass
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _write_skin_config(Options):
    """Write the skin config to %USERPROFILE%\\cs2py_skin.txt for the injected DLL."""
    global _last_cfg_write, _last_cfg_content
    now = time.monotonic()
    cfg = Options.get("SkinChanger", {}) or {}
    enabled = bool(cfg.get("enabled", False))
    if enabled and now - _last_cfg_write < 0.1:
        return
    _last_cfg_write = now
    try:
        weapons = (cfg.get("weapons", {}) or {}) if enabled else {}
        db = items.get_database() if weapons else {"weapons": {}, "paint_kits": {}}
        if not db:
            print("[skin-changer] write: item database unavailable")
            return
        lines = []
        for name, skin in weapons.items():
            w = db["weapons"].get(name)
            if not w:
                print(f"[skin-changer] write: unknown weapon {name}")
                continue
            if w.get("category") == "gloves":
                continue
            pk = db["paint_kits"].get(int(skin.get("paint_kit", 0))) or {}
            mesh_mask = 2 if pk.get("legacy") else 1
            model = w.get("model") or "-"
            lines.append(f"{w['def_index']} {skin.get('paint_kit', 0)} {skin.get('seed', 0)} {skin.get('wear', 0.0)} {mesh_mask} {model}")
        content = "\n".join(lines) + ("\n" if lines else "")
        if content == _last_cfg_content:
            return  # unchanged: skip the rewrite + log spam
        # The native reader must never see a truncated/intermediate loadout.
        # Only mark it committed after replacement succeeds, so failures retry.
        write_atomic(_CONFIG_PATH, content)
        _last_cfg_content = content
        print(f"[skin-changer] wrote {len(lines)} skin config line(s)")
        _log(f"write ok: {len(lines)} line(s) -> " + " | ".join(lines))
    except Exception as e:
        print(f"[skin-changer] write error: {e}")
        _log(f"write error: {e}")


_last_disabled_log = 0.0


def _publish_control(process, client, Offsets, Options):
    """Short-lived native write permission. Disabled is published once, not per frame."""
    global _last_control_time, _last_control_state
    local = bool((Options.get("SkinChanger", {}) or {}).get("enabled", False))
    shared = bool((Options.get("SkinShare", {}) or {}).get("enabled", False))
    state = (getattr(process, "process_id", 0), local, shared)
    now = time.monotonic()
    if state == _last_control_state and (not (local or shared) or now - _last_control_time < 0.25):
        return
    rules = entities = 0
    try:
        if local or shared:
            o = Offsets.offset
            engine = memfuncs.GetModuleBase("engine2.dll", process)
            network = memfuncs.ProcMemHandler.ReadPointer(process, engine + o.dwNetworkGameClient)
            signon = memfuncs.ProcMemHandler.ReadInt(process, network + o.dwNetworkGameClient_signOnState)
            if signon == 6:
                rules = memfuncs.ProcMemHandler.ReadPointer(process, client + o.dwGameRules)
                entities = memfuncs.ProcMemHandler.ReadPointer(process, client + o.dwEntityList)
    except Exception:
        rules = entities = 0
    # Never emit signed/unreadable roots as plausible permission.
    if rules <= 0x10000 or entities <= 0x10000:
        rules = entities = 0
    deadline = int(time.time() * 1000) + 1500 if (local or shared) and rules and entities else 0
    write_atomic(_CONTROL_PATH,
        f"CS2PY_CONTROL_V1 {state[0]} {deadline} {int(local)} {int(shared)} {rules} {entities}\n")
    _last_control_time, _last_control_state = now, state


def SkinChanger_Update(processHandle, clientBaseAddress, Offsets, Options):
    """Inject the internal skin changer DLL and keep its config file fresh."""
    global _last_disabled_log, _last_weapons_sig
    cfg = Options.get("SkinChanger", {}) or {}
    # Empty local configuration also clears stale files when BOTH toggles are off.
    _write_skin_config(Options)
    _publish_control(processHandle, clientBaseAddress, Offsets, Options)
    if not cfg.get("enabled", False):
        if (Options.get("SkinShare", {}) or {}).get("enabled", False):
            inject.inject_skinchanger(processHandle)
        now = time.monotonic()
        if now - _last_disabled_log > 5.0:
            _last_disabled_log = now
            _log("update: SkinChanger disabled, skipping")
        return
    # Log only when the configured weapons actually change (this was spamming
    # the console + debug log every frame).
    weapons = cfg.get("weapons", {}) or {}
    sig = repr(sorted(weapons.items()))
    if sig != _last_weapons_sig:
        _last_weapons_sig = sig
        _log(f"update: enabled, weapons={weapons}")
    inject.inject_skinchanger(processHandle)


def _apply_gloves(processHandle, clientBaseAddress, Offsets, cfg):
    """Glove replacement is disabled, including previously saved selections."""
    return
