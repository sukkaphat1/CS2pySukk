"""CS2 radar / minimap projection for the grenade landing dot.

Projects a world-space landing point onto the in-game top-left radar so the dot
tracks the player's actual radar. The transform is reconstructed from:

  * the radar HUD geometry shipped in ``panorama/styles/hud/hudradar.vcss_c``
    (``#Radar { x:0; y:40; width:300px; height:300px }``, round radar 250px),
  * the live radar ConVars (``cl_radar_scale``, ``cl_hud_radar_scale``,
    ``hud_scaling``, ...) read once from the game process,
  * the map's minimap world bounds (``C_CSGameRules::m_vMinimapMins/Maxs``),
  * the local player origin + view yaw.

The ConVar values live in heap-allocated ConVar objects; their addresses are
found with a one-time background scan (cached for the session) and then read as
plain floats each frame. Until the scan finishes (or if it fails) the defaults
are used, which match the common default radar.
"""
import ctypes
import struct
import threading
import math

from ctypes import wintypes

from functions import memfuncs
from ext.datatypes import Vector3


# --------------------------------------------------------------------------
# Radar HUD geometry (from the shipped radar CSS)
# --------------------------------------------------------------------------
RADAR_PANEL = 300.0     # #Radar panel width/height (px)
RADAR_X = 0.0           # #Radar x
RADAR_Y = 40.0          # #Radar y
RADAR_ROUND = 250.0     # round radar visible diameter (default)
RADAR_SQUARE = 290.0    # square radar (scoreboard open)


# --------------------------------------------------------------------------
# ConVar reading
# --------------------------------------------------------------------------
# Source 2 ConVar object layout (observed empirically in cs2.exe):
#   +0x30 -> m_pszName (char*), +0x90 min, +0x98 max, +0xA0 float value.
CONVAR_NAME_OFF = 0x30
CONVAR_FLOAT_VAL_OFF = 0xA0

_FLOAT_CONVARS = ("cl_radar_scale", "cl_hud_radar_scale", "hud_scaling", "cl_radar_scale_alternate")
_BOOL_CONVARS = ("cl_radar_rotate", "cl_radar_always_centered", "cl_radar_square_with_scoreboard")

_DEFAULTS = {
    "cl_radar_scale": 0.7,
    "cl_hud_radar_scale": 1.0,
    "hud_scaling": 1.0,
    "cl_radar_scale_alternate": 1.0,
    "cl_radar_rotate": 1.0,
    "cl_radar_always_centered": 1.0,
    "cl_radar_square_with_scoreboard": 1.0,
}

_convar_objs = {}          # name -> heap ConVar object address
_scan_started = False
_scan_done = False
_scan_lock = threading.Lock()


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_size_t),
        ("AllocationBase", ctypes.c_size_t),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_VirtualQueryEx = _kernel32.VirtualQueryEx
_VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
_VirtualQueryEx.restype = ctypes.c_size_t

_MEM_COMMIT = 0x1000
_PAGE_NOACCESS = 0x01
_PAGE_GUARD = 0x100
_MEM_PRIVATE = 0x20000


def _read(proc, addr, size):
    try:
        return proc.read_bytes(addr, size)
    except Exception:
        return None


def _scan_for_names(proc, names):
    """One pass over private (heap) committed memory; collect string addresses."""
    found = {n: [] for n in names}
    patterns = {n: n.encode() + b"\x00" for n in names}
    mbi = _MEMORY_BASIC_INFORMATION()
    addr = 0
    CHUNK = 0x400000
    while addr < 0x7FFFFFFFFFFF:
        ret = _VirtualQueryEx(proc.process_handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ret == 0:
            break
        base = mbi.BaseAddress
        size = mbi.RegionSize
        if (mbi.State == _MEM_COMMIT and mbi.Type == _MEM_PRIVATE
                and mbi.Protect != _PAGE_NOACCESS and (mbi.Protect & _PAGE_GUARD) == 0):
            pos = base
            while pos < base + size:
                chunk_len = min(CHUNK, base + size - pos)
                data = _read(proc, pos, chunk_len)
                if data is None:
                    break
                for name, pat in patterns.items():
                    idx = data.find(pat)
                    while idx != -1:
                        found[name].append(pos + idx)
                        idx = data.find(pat, idx + 1)
                pos += chunk_len
        addr = base + size
    return found


def _find_object(proc, saddr):
    """Find the ConVar object whose m_pszName points at ``saddr`` (search nearby)."""
    ptr_bytes = struct.pack("<Q", saddr)
    lo = saddr - 0x80000
    hi = saddr + 0x80000
    pos = lo
    while pos < hi:
        data = _read(proc, pos, min(0x400000, hi - pos))
        if data is None:
            pos += 0x1000
            continue
        idx = data.find(ptr_bytes)
        if idx != -1:
            return (pos + idx) - CONVAR_NAME_OFF
        pos += len(data)
    return None


def _do_scan(proc):
    global _convar_objs, _scan_done
    try:
        names = list(_FLOAT_CONVARS) + list(_BOOL_CONVARS)
        hits = _scan_for_names(proc, names)
        objs = {}
        for name in names:
            for s in hits.get(name, []):
                obj = _find_object(proc, s)
                if obj:
                    objs[name] = obj
                    break
        with _scan_lock:
            _convar_objs.update(objs)
            _scan_done = True
    except Exception:
        with _scan_lock:
            _scan_done = True


def start_convar_scan(proc):
    """Kick off the one-time ConVar address scan in a background thread."""
    global _scan_started
    with _scan_lock:
        if _scan_started:
            return
        _scan_started = True
    threading.Thread(target=_do_scan, args=(proc,), daemon=True).start()


def _convar_float(proc, name):
    with _scan_lock:
        obj = _convar_objs.get(name)
    if obj:
        raw = _read(proc, obj + CONVAR_FLOAT_VAL_OFF, 4)
        if raw and len(raw) == 4:
            val = struct.unpack_from("<f", raw, 0)[0]
            if -1e6 < val < 1e6:
                return val
    return _DEFAULTS.get(name, 0.0)


def _convar_bool(proc, name):
    # Bool ConVars (cl_radar_rotate / cl_radar_always_centered / ...) use a
    # different value slot than the float ConVars and default to true. We have
    # not pinned a reliable bool offset, so return the default (true) for now.
    return _DEFAULTS.get(name, 1.0) >= 0.5


def get_radar(proc, map_mins, map_maxs, player_pos, player_yaw_deg):
    """Return the radar projection parameters as a dict, or None if unavailable."""
    if map_mins is None or map_maxs is None or player_pos is None:
        return None

    start_convar_scan(proc)

    scale = _convar_float(proc, "cl_radar_scale")
    hud_radar = _convar_float(proc, "cl_hud_radar_scale")
    hud_scaling = _convar_float(proc, "hud_scaling")
    rotate = _convar_bool(proc, "cl_radar_rotate")
    centered = _convar_bool(proc, "cl_radar_always_centered")

    # Radar is round by default and only goes square while the scoreboard is up;
    # we use the round diameter, which is the normal in-game state.
    size_scale = max(0.01, hud_radar * hud_scaling)
    panel_size = RADAR_PANEL * size_scale
    cx = (RADAR_X + panel_size / 2.0)
    cy = (RADAR_Y + panel_size / 2.0)
    radius = (RADAR_ROUND / 2.0) * size_scale

    map_w = map_maxs.x - map_mins.x
    map_h = map_maxs.y - map_mins.y
    longer = max(map_w, map_h)
    if longer <= 0:
        return None

    # At cl_radar_scale == 1.0 the whole map fits the radar's visible diameter;
    # lower values zoom in (fewer world units across the same pixel span).
    units_per_px = (longer * scale) / (RADAR_ROUND * size_scale)
    px_per_world = 1.0 / units_per_px if units_per_px > 0 else 0.0

    center_world = Vector3((map_mins.x + map_maxs.x) / 2.0, (map_mins.y + map_maxs.y) / 2.0, 0.0)
    if centered:
        origin = player_pos
    else:
        origin = center_world

    yaw_rad = math.radians(player_yaw_deg) if rotate else 0.0

    return {
        "cx": cx,
        "cy": cy,
        "radius": radius,
        "px_per_world": px_per_world,
        "origin": origin,
        "rotate": rotate,
        "yaw_rad": yaw_rad,
    }


def world_to_radar(radar, point):
    """Project a world XY point into radar screen pixels (top-left origin)."""
    if not radar or point is None:
        return None
    dx = point.x - radar["origin"].x
    dy = point.y - radar["origin"].y
    if radar["rotate"]:
        dist = math.hypot(dx, dy)
        theta = math.atan2(dy, dx)
        rel = radar["yaw_rad"] - theta
        sx = dist * math.sin(rel)
        sy = -dist * math.cos(rel)
    else:
        sx = dx
        sy = -dy
    px = radar["cx"] + sx * radar["px_per_world"]
    py = radar["cy"] + sy * radar["px_per_world"]
    return px, py
