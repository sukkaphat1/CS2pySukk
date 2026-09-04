"""Local skin changer.

Writes the client-side item fields on the local player's active weapon so the
game renders the chosen skin locally (only the local player sees it). The skin
set for each weapon is stored in ``Options["SkinChanger"]``:

    {
        "enabled": true,
        "weapons": {
            "weapon_ak47": {"paint_kit": 490, "seed": 0, "wear": 0.0, "stat_trak": -1},
            ...
        }
    }

Knives/gloves use the same mechanism (a different item definition index changes
the model); those are handled by the same apply path.
"""
import os
import struct
import time

from functions import memfuncs
from ext import items
from features import inject


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


def apply_skin(processHandle, weapon, Offsets, paint_kit, seed=0, wear=0.0, stat_trak=-1, def_index=None, quality=0, account_id=1):
    """Write a paint kit (+ item identity) onto a weapon entity.

    Mirrors a working CS2 skin changer: the item view must be marked initialized
    and SOC-disallowed (so the game doesn't reset it to the real inventory item),
    the account id and item id must be non-default, and the fallback paint fields
    are written on the weapon entity itself.
    """
    o = Offsets.offset

    # C_AttributeContainer (m_AttributeManager) and C_EconItemView (m_Item) are
    # inline objects, so add their offsets directly to reach the item view.
    item_view = weapon + o.m_AttributeManager + o.m_Item

    # Keep the local fake item from being replaced by the next SOC refresh.
    memfuncs.ProcMemHandler.WriteBool(processHandle, item_view + o.m_bDisallowSOC, True)
    memfuncs.ProcMemHandler.WriteBool(processHandle, item_view + o.m_bRestoreCustomMaterialAfterPrecache, True)
    memfuncs.ProcMemHandler.WriteBool(processHandle, item_view + o.m_bInitialized, True)
    memfuncs.ProcMemHandler.WriteInt(processHandle, item_view + o.m_iAccountID, int(account_id))

    if def_index is not None:
        memfuncs.ProcMemHandler.WriteUShort(processHandle, item_view + o.m_iItemDefinitionIndex, int(def_index))
    memfuncs.ProcMemHandler.WriteInt(processHandle, item_view + o.m_iEntityQuality, int(quality))
    # fake 64-bit item id: high word -1, low word 0 (matches working skinners)
    memfuncs.ProcMemHandler.WriteInt(processHandle, item_view + o.m_iItemIDHigh, -1)
    memfuncs.ProcMemHandler.WriteInt(processHandle, item_view + o.m_iItemIDLow, 0)
    memfuncs.ProcMemHandler.WriteULong(processHandle, item_view + o.m_iItemID, 0xFFFFFFFF00000000)

    # C_EconEntity fallback skin fields + owner, on the weapon entity itself.
    memfuncs.ProcMemHandler.WriteInt(processHandle, weapon + o.m_OriginalOwnerXuidLow, int(account_id))
    memfuncs.ProcMemHandler.WriteInt(processHandle, weapon + o.m_OriginalOwnerXuidHigh, 0)
    memfuncs.ProcMemHandler.WriteInt(processHandle, weapon + o.m_nFallbackPaintKit, int(paint_kit))
    memfuncs.ProcMemHandler.WriteInt(processHandle, weapon + o.m_nFallbackSeed, int(seed))
    memfuncs.ProcMemHandler.WriteFloat(processHandle, weapon + o.m_flFallbackWear, float(wear))
    memfuncs.ProcMemHandler.WriteInt(processHandle, weapon + o.m_nFallbackStatTrak, int(stat_trak))

    # Write the paint-kit attributes into the item's attribute list (the field
    # the game actually reads to render the skin).
    _set_skin_attributes(processHandle, item_view, Offsets, paint_kit, seed, wear)

    # Force the game to re-apply the skin material (UpdateSkin is the trigger).
    # NOTE: this remote-thread call crashes cs2.exe; disabled.
    # _call_update_skin(processHandle, weapon)


_ATTR_STRUCT_SIZE = 72
# CEconItemAttribute schema offsets (relative to the struct start).
_ATTR_DEF_INDEX = 48
_ATTR_VALUE = 52
_ATTR_INITIAL_VALUE = 56

_MEM_COMMIT = 0x1000
_MEM_RESERVE = 0x2000
_PAGE_READWRITE = 0x04


def _alloc(processHandle, size):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    va = k32.VirtualAllocEx
    va.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    va.restype = ctypes.c_void_p
    return va(processHandle.process_handle, None, size, _MEM_COMMIT | _MEM_RESERVE, _PAGE_READWRITE)


_attr_block = None          # cached allocated attribute block (reused each frame)
_update_skin_addr = None    # cached C_CSWeaponBase::UpdateSkin address


def _find_update_skin(processHandle):
    """Pattern-scan client.dll for C_CSWeaponBase::UpdateSkin (cached)."""
    global _update_skin_addr
    if _update_skin_addr:
        return _update_skin_addr
    try:
        from pymem.process import module_from_name
        m = module_from_name(processHandle.process_handle, "client.dll")
        data = processHandle.read_bytes(m.lpBaseOfDll, m.SizeOfImage)
        pat_str = "48 89 5C 24 08 57 48 83 EC 20 8B DA 48 8B F9 E8 ? ? ? ? F6 C3 01 74 0A"
        toks = pat_str.split()
        pat = bytearray()
        mask = bytearray()
        for t in toks:
            if t == "?":
                pat.append(0)
                mask.append(0)
            else:
                pat.append(int(t, 16))
                mask.append(0xFF)
        pat = bytes(pat)
        mask = bytes(mask)
        for i in range(0, len(data) - len(pat)):
            ok = True
            for j in range(len(pat)):
                if mask[j] and data[i + j] != pat[j]:
                    ok = False
                    break
            if ok:
                _update_skin_addr = m.lpBaseOfDll + i
                break
    except Exception:
        pass
    return _update_skin_addr


def _call_update_skin(processHandle, weapon):
    """Call C_CSWeaponBase::UpdateSkin(weapon, true) in the game process."""
    addr = _find_update_skin(processHandle)
    if not addr or not weapon:
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    va = k32.VirtualAllocEx
    va.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    va.restype = ctypes.c_void_p
    PAGE_EXECUTE_READWRITE = 0x40
    shell = (
        b"\x48\xB9" + struct.pack("<Q", weapon) +
        b"\xB2\x01" +
        b"\x48\xB8" + struct.pack("<Q", addr) +
        b"\xFF\xD0" +
        b"\xC3"
    )
    mem = va(processHandle.process_handle, None, len(shell), _MEM_COMMIT | _MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not mem:
        return
    processHandle.write_bytes(mem, shell, len(shell))
    crt = k32.CreateRemoteThread
    crt.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    crt.restype = wintypes.HANDLE
    h = crt(processHandle.process_handle, None, 0, mem, None, 0, None)
    if h:
        k32.WaitForSingleObject(h, 3000)
        k32.CloseHandle(h)


def _set_skin_attributes(processHandle, item_view, Offsets, paint_kit, seed, wear):
    """Write paint-kit attributes (prefab/seed/wear) into the item's CAttributeList."""
    global _attr_block
    o = Offsets.offset
    # CAttributeList::m_Attributes is a CUtlVector<CEconItemAttribute> at +8.
    vec = item_view + o.m_AttributeList + 8

    attrs = [(6, float(paint_kit)), (7, float(seed)), (8, float(wear))]
    n = len(attrs)
    if _attr_block is None:
        _attr_block = _alloc(processHandle, _ATTR_STRUCT_SIZE * n)
    block = _attr_block
    if not block:
        return
    buf = bytearray(_ATTR_STRUCT_SIZE * n)
    for i, (aid, val) in enumerate(attrs):
        base = i * _ATTR_STRUCT_SIZE
        struct.pack_into("<H", buf, base + _ATTR_DEF_INDEX, aid)
        struct.pack_into("<f", buf, base + _ATTR_VALUE, val)
        struct.pack_into("<f", buf, base + _ATTR_INITIAL_VALUE, val)
    processHandle.write_bytes(block, bytes(buf), len(buf))

    # CUtlVector layout: size @0 (i32), pad @4, data @8 (ptr), capacity @16 (i32)
    processHandle.write_int(vec, n)
    memfuncs.ProcMemHandler.WriteULong(processHandle, vec + 8, block)
    processHandle.write_int(vec + 16, n)


_last_cfg_write = 0.0
_last_cfg_content = None
_last_weapons_sig = None

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), "cs2py_skin.txt")
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
    if now - _last_cfg_write < 1.0:
        return
    _last_cfg_write = now
    try:
        cfg = Options.get("SkinChanger", {}) or {}
        weapons = cfg.get("weapons", {}) or {}
        db = items.get_database()
        if not db:
            print("[skin-changer] write: item database unavailable")
            return
        lines = []
        for name, skin in weapons.items():
            w = db["weapons"].get(name)
            if not w:
                print(f"[skin-changer] write: unknown weapon {name}")
                continue
            pk = db["paint_kits"].get(int(skin.get("paint_kit", 0))) or {}
            mesh_mask = 2 if pk.get("legacy") else 1
            model = w.get("model") or "-"
            lines.append(f"{w['def_index']} {skin.get('paint_kit', 0)} {skin.get('seed', 0)} {skin.get('wear', 0.0)} {mesh_mask} {model}")
        content = "\n".join(lines) + ("\n" if lines else "")
        if content == _last_cfg_content:
            return  # unchanged: skip the rewrite + log spam
        _last_cfg_content = content
        with open(_CONFIG_PATH, "w") as f:
            f.write(content)
        print(f"[skin-changer] wrote {len(lines)} skin config line(s)")
        _log(f"write ok: {len(lines)} line(s) -> " + " | ".join(lines))
    except Exception as e:
        print(f"[skin-changer] write error: {e}")
        _log(f"write error: {e}")


_last_disabled_log = 0.0


def SkinChanger_Update(processHandle, clientBaseAddress, Offsets, Options):
    """Inject the internal skin changer DLL and keep its config file fresh."""
    global _last_disabled_log, _last_weapons_sig
    cfg = Options.get("SkinChanger", {}) or {}
    if not cfg.get("enabled", False):
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
    _write_skin_config(Options)


def _apply_gloves(processHandle, clientBaseAddress, Offsets, cfg):
    glove = get_glove_entity(processHandle, clientBaseAddress, Offsets)
    if not glove:
        return
    def_index = get_active_weapon_def(processHandle, clientBaseAddress, Offsets, glove)
    name = weapon_name_from_def(def_index)
    if not name:
        return
    skin = (cfg.get("weapons", {}) or {}).get(name)
    if not skin:
        return
    apply_skin(
        processHandle,
        glove,
        Offsets,
        paint_kit=int(skin.get("paint_kit", 0)),
        seed=int(skin.get("seed", 0)),
        wear=float(skin.get("wear", 0.0)),
        stat_trak=int(skin.get("stat_trak", -1)),
        def_index=int(skin.get("def_index", def_index)),
        quality=int(skin.get("quality", 0)),
    )
