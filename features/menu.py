"""Overlay config menu (raygui) drawn inside the pyMeow overlay.

Toggled with Insert. When open the overlay becomes interactive (mouse not
passed through); when closed it goes back to click-through so gameplay is
unaffected. The Skins tab is a three-pane browser: category -> weapon -> skin.
Selecting a skin saves it into ``Options["SkinChanger"]`` and the skin changer
applies it to the held weapon on the next frame.
"""
import math
import os

import pyMeow as pme

from ext import items
from ext import paths
from features import preview
from features import skinchanger


def _read_version():
    try:
        p = paths.resolve_data("version.txt")
        if p:
            with open(p, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return "?"


_VERSION = _read_version()
_ACCENT = "#2D6BFF"

VK_INSERT = 0x2D

_open = False
_prev_insert = False
_interactive = False

# Skins tab state
_tab = 0
_sel_category = 0
_sel_weapon = 0
_sel_skin = 0
_scroll_weapons = 0
_scroll_skins = 0
_seed_text = "0"
_wear = 0.01

_TABS = ["Skins", "Aimbot", "ESP & Visuals", "Triggerbot", "Reactions", "Recoil", "Colors", "Misc"]

WIN_X, WIN_Y = 24.0, 24.0
WIN_W, WIN_H = 940.0, 620.0
TAB_H = 28.0
TAB_TOP = 64.0

LIST_ITEM_H = 26.0
LIST_ITEM_W = 220.0
COLS_X = [WIN_X + 20.0, WIN_X + 250.0, WIN_X + 480.0]
COLS_Y = WIN_Y + TAB_TOP + 20.0
PREVIEW_X = WIN_X + 720.0
PREVIEW_Y = COLS_Y
PREVIEW_W = 220.0
PREVIEW_H = 230.0


def is_open():
    return _open


def update():
    global _open, _prev_insert, _interactive
    insert = bool(pme.key_pressed(VK_INSERT))
    if insert and not _prev_insert:
        _open = not _open
    _prev_insert = insert

    if _open and not _interactive:
        pme.toggle_mouse()
        _interactive = True
    elif not _open and _interactive:
        pme.toggle_mouse()
        _interactive = False


def _weapons_in_category(db, cat_key):
    return [w for w in db["weapons"].values() if w["category"] == cat_key]


def _skins_for_weapon(db, weapon):
    skins = [db["paint_kits"][pid] for pid in weapon["skins"] if pid in db["paint_kits"]]
    # Knife/glove skins are not in the collections; pull them from the preview map.
    if not skins and weapon["category"] in ("gloves", "knives"):
        m = preview.get_mapping()
        pids = [pid for (wn, pid) in m if wn == weapon["name"] and pid in db["paint_kits"]]
        skins = [db["paint_kits"][pid] for pid in pids]
    return skins


def _scroll_list(x, y, w, items_count, visible, scroll, item_h, draw_row):
    """Draw a scrollable list of buttons; returns (new_scroll, new_selection)."""
    selection = -1
    max_scroll = max(0, items_count - visible)
    if scroll > max_scroll:
        scroll = max_scroll
    for i in range(visible):
        idx = scroll + i
        if idx >= items_count:
            break
        clicked = draw_row(idx, x, y + i * item_h, w, item_h)
        if clicked:
            selection = idx
    if items_count > visible:
        scroll = pme.gui_scroll_bar(x + w + 4.0, y, 14.0, visible * item_h, scroll, 0, max_scroll)
    return scroll, selection


def _draw_skins_tab(proc, clientBase, Options, Offsets):
    global _sel_category, _sel_weapon, _sel_skin, _scroll_weapons, _scroll_skins, _seed_text, _wear
    db = items.get_database()
    if not db:
        pme.gui_label(COLS_X[0], COLS_Y, 300, 20, "Item database unavailable")
        return

    categories = db["categories"]
    weapons = _weapons_in_category(db, categories[_sel_category]["key"])
    skins = _skins_for_weapon(db, weapons[_sel_weapon]) if weapons else []

    # --- enable toggle ---
    cfg = Options.get("SkinChanger", {}) or {}
    enabled = bool(cfg.get("enabled", False))
    new_enabled = pme.gui_check_box(WIN_X + 20.0, WIN_Y + 66.0, 22.0, 22.0, "Enable Skin Changer", enabled)
    if new_enabled != enabled:
        c2 = dict(cfg)
        c2["enabled"] = new_enabled
        Options.update({"SkinChanger": c2})

    # --- category column ---
    for i, cat in enumerate(categories):
        label = cat["label"]
        if i == _sel_category:
            label = "> " + label
        if pme.gui_button(COLS_X[0], COLS_Y + i * LIST_ITEM_H, LIST_ITEM_W, LIST_ITEM_H, label):
            _sel_category = i
            _sel_weapon = 0
            _sel_skin = 0
            _scroll_weapons = 0
            _scroll_skins = 0

    # --- weapon column ---
    def weapon_row(idx, x, y, w, h):
        wname = weapons[idx]
        label = ("> " if idx == _sel_weapon else "") + wname["label"]
        return pme.gui_button(x, y, w, h, label)

    _scroll_weapons, sel_w = _scroll_list(
        COLS_X[1], COLS_Y, LIST_ITEM_W, len(weapons), 16, _scroll_weapons, LIST_ITEM_H, weapon_row
    )
    if sel_w >= 0:
        _sel_weapon = sel_w
        _sel_skin = 0
        _scroll_skins = 0

    # --- skin column ---
    def skin_row(idx, x, y, w, h):
        sname = ("> " if idx == _sel_skin else "") + skins[idx]["label"]
        return pme.gui_button(x, y, w, h, sname)

    _scroll_skins, sel_s = _scroll_list(
        COLS_X[2], COLS_Y, LIST_ITEM_W, len(skins), 16, _scroll_skins, LIST_ITEM_H, skin_row
    )
    if sel_s >= 0:
        _sel_skin = sel_s
        if weapons and skins:
            try:
                seed = int(_seed_text.strip())
            except (ValueError, TypeError):
                seed = 0
            _apply_selection(Options, weapons[_sel_weapon], skins[_sel_skin], seed=seed, wear=_wear)

    # --- preview / info panel ---
    pme.gui_panel(PREVIEW_X, PREVIEW_Y, PREVIEW_W, PREVIEW_H)
    if weapons and skins:
        w = weapons[_sel_weapon]
        s = skins[_sel_skin]
        preview.request_preview(w["name"], s["id"])
        tex = preview.get_texture(w["name"], s["id"])
        if tex is not None:
            pme.draw_texture(tex, PREVIEW_X + 8.0, PREVIEW_Y + 8.0, pme.get_color("#ffffff"), 0.0, 1.0)
        else:
            pme.gui_label(PREVIEW_X + 8.0, PREVIEW_Y + 8.0, PREVIEW_W - 16.0, 20.0, "Loading preview...")
        pme.gui_label(PREVIEW_X + 8.0, PREVIEW_Y + 170.0, PREVIEW_W - 16.0, 20.0, w["label"])
        pme.gui_label(PREVIEW_X + 8.0, PREVIEW_Y + 192.0, PREVIEW_W - 16.0, 20.0, s["label"])
        # seed + wear inputs (applied on the next skin click)
        pme.gui_label(PREVIEW_X + 8.0, PREVIEW_Y + PREVIEW_H + 10.0, 40.0, 22.0, "Seed")
        _seed_text = pme.gui_text_box(PREVIEW_X + 52.0, PREVIEW_Y + PREVIEW_H + 8.0, 100.0, 22.0, _seed_text, 100)
        _wear = pme.gui_slider(PREVIEW_X + 8.0, PREVIEW_Y + PREVIEW_H + 36.0, PREVIEW_W - 16.0, 22.0, "Wear", f"{_wear:.2f}", _wear, 0.0, 1.0)
        if pme.gui_button(PREVIEW_X + 8.0, PREVIEW_Y + PREVIEW_H + 64.0, PREVIEW_W - 16.0, 24.0, "Clear This Skin"):
            c2 = dict(Options.get("SkinChanger", {}) or {})
            w2 = dict(c2.get("weapons", {}) or {})
            w2.pop(w["name"], None)
            c2["weapons"] = w2
            Options.update({"SkinChanger": c2})
    else:
        pme.gui_label(PREVIEW_X + 8.0, PREVIEW_Y + 8.0, PREVIEW_W - 16.0, 20.0, "No skins")


def _apply_selection(Options, weapon, skin, seed=0, wear=0.0):
    """Persist the chosen paint kit for this weapon into the config."""
    quality = 3 if weapon["category"] == "knives" else 0
    cfg = dict(Options.get("SkinChanger", {}) or {})
    weapons = dict(cfg.get("weapons", {}) or {})
    if weapon["category"] == "knives":
        # Only one knife is active at a time (it's a model swap, not per-knife
        # paint). Picking a new knife replaces any previously picked knife.
        db = items.get_database()
        if db:
            for name in list(weapons.keys()):
                w = db["weapons"].get(name)
                if w and w["category"] == "knives":
                    weapons.pop(name, None)
    # Move to the end so "last weapon/knife in config" = "most recently picked".
    weapons.pop(weapon["name"], None)
    weapons[weapon["name"]] = {
        "paint_kit": skin["id"],
        "seed": int(seed),
        "wear": float(wear),
        "stat_trak": -1,
        "quality": quality,
    }
    cfg["weapons"] = weapons
    cfg["enabled"] = True
    Options.update({"SkinChanger": cfg})
    print(f"[skin-changer] Saved {weapon['label']} -> {skin['label']} (pk {skin['id']}, seed {seed})")


def _apply_now(proc, clientBase, Offsets, weapon, skin):
    """Immediately apply the skin to the currently held weapon if it matches."""
    try:
        cur = skinchanger.get_active_weapon(proc, clientBase, Offsets)
        if not cur:
            return
        cur_def = skinchanger.get_active_weapon_def(proc, clientBase, Offsets, cur)
        if cur_def != weapon["def_index"]:
            return
        quality = 3 if weapon["category"] == "knives" else 0
        skinchanger.apply_skin(
            proc, cur, Offsets,
            paint_kit=skin["id"], seed=0, wear=0.0, stat_trak=-1,
            def_index=cur_def, quality=quality,
        )
        print(f"[skin-changer] Applied {weapon['label']} -> {skin['label']} (pk {skin['id']})")
    except Exception as e:
        print(f"[skin-changer] apply error: {e}")


# --- generic setting widgets -------------------------------------------------
_listening = None          # config key currently being rebound
_PALETTE = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#00FFFF", "#FF00FF", "#FF8000", "#FFFFFF"]


def _vk_name(vk):
    vk = int(vk)
    if vk == 0x01:
        return "LMB"
    if vk == 0x02:
        return "RMB"
    if vk == 0x04:
        return "MMB"
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if vk == 0x20:
        return "Space"
    if vk == 0x10:
        return "Shift"
    if vk == 0x11:
        return "Ctrl"
    if vk == 0x12:
        return "Alt"
    if vk == 0x2D:
        return "Insert"
    if vk == 0x23:
        return "End"
    if vk == 0x24:
        return "Home"
    return f"VK_{vk:02X}"


def _check(Options, key, x, y, label):
    val = bool(Options.get(key, False))
    new = pme.gui_check_box(x, y, 22.0, 22.0, label, val)
    if new != val:
        Options.update({key: new})


def _slider(Options, key, x, y, w, label, vmin, vmax, is_int=True):
    val = float(Options.get(key, 0))
    new = pme.gui_slider(x, y, w, 22.0, label, f"{int(val)}" if is_int else f"{val:.2f}", val, vmin, vmax)
    if is_int:
        new = round(new)
    if new != (int(val) if is_int else round(val, 2)):
        Options.update({key: new if is_int else round(new, 2)})


def _color_button(Options, key, x, y, label):
    cur = str(Options.get(key, "#FFFFFF")).upper()
    idx = _PALETTE.index(cur) if cur in _PALETTE else 0
    pme.draw_rectangle(x + 4.0, y + 4.0, 14.0, 14.0, pme.get_color(cur))
    if pme.gui_button(x + 24.0, y, 220.0, 22.0, f"{label}: {cur}"):
        idx = (idx + 1) % len(_PALETTE)
        Options.update({key: _PALETTE[idx]})


def _keybind(Options, key, x, y, label):
    global _listening
    if _listening == key:
        if pme.gui_button(x, y, 260.0, 22.0, f"{label}: press a key..."):
            _listening = None
        for vk in range(1, 0x100):
            if pme.key_pressed(vk):
                Options.update({key: vk})
                _listening = None
                break
    else:
        cur = int(Options.get(key, 0))
        if pme.gui_button(x, y, 260.0, 22.0, f"{label}: {_vk_name(cur)}"):
            _listening = key


def _draw_aimbot_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    _check(Options, "EnableAimbot", x, y, "Enable Aimbot"); y += 28
    _check(Options, "EnableAimbotTeamCheck", x, y, "Team Check"); y += 28
    _check(Options, "EnableAimbotVisibilityCheck", x, y, "Visibility Check"); y += 28
    _check(Options, "EnableAimbotPrediction", x, y, "Prediction (Velocity)"); y += 28
    _slider(Options, "AimbotFOV", x, y, 280, "FOV", 1, 200); y += 28
    _slider(Options, "AimbotSmoothing", x, y, 280, "Smoothing", 1, 10); y += 28
    positions = ["Head", "Neck", "Torso", "Leg"]
    cur = Options.get("AimPosition", "Head")
    idx = positions.index(cur) if cur in positions else 0
    if pme.gui_button(x, y, 220.0, 22.0, f"Aim Position: {positions[idx]}"):
        Options.update({"AimPosition": positions[(idx + 1) % len(positions)]})
    y += 28
    _keybind(Options, "AimbotKey", x, y, "Aimbot Key")


def _draw_esp_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    for k, lbl in [
        ("EnableESPTeamCheck", "Team Check"),
        ("EnableESPSkeletonRendering", "Skeleton"),
        ("EnableESPBoxRendering", "Box"),
        ("EnableESPTracerRendering", "Tracers"),
        ("EnableESPNameText", "Names"),
        ("EnableESPHealthBarRendering", "Health Bar"),
        ("EnableESPHealthText", "Health Text"),
        ("EnableESPDistanceText", "Distance"),
        ("EnableFOVCircle", "FOV Circle"),
        ("EnableESPBombTimer", "Bomb Timer"),
    ]:
        _check(Options, k, x, y, lbl); y += 26
    y += 6
    _check(Options, "EnableGrenadeTrajectory", x, y, "Grenade Trajectory"); y += 26
    _slider(Options, "GrenadeTrajectoryThrowStrength", x, y, 280, "Throw Strength", 0.0, 1.0, is_int=False); y += 28
    _slider(Options, "GrenadeTrajectoryRestitution", x, y, 280, "Elasticity", 0.0, 1.0, is_int=False); y += 28
    _slider(Options, "GrenadeTrajectoryGhostFade", x, y, 280, "Ghost Fade", 0.0, 4.0, is_int=False)


def _draw_trigger_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    _check(Options, "EnableTriggerbot", x, y, "Enable Triggerbot"); y += 28
    _check(Options, "EnableTriggerbotTeamCheck", x, y, "Team Check"); y += 28
    _check(Options, "EnableTriggerbotKeyCheck", x, y, "Key Check"); y += 28
    _check(Options, "EnablePerWeaponTapTimes", x, y, "Per-Weapon Tap Times"); y += 28
    _slider(Options, "TriggerbotTapInterval", x, y, 280, "Tap Interval", 0.0, 2.0, is_int=False); y += 28
    _keybind(Options, "TriggerbotKey", x, y, "Triggerbot Key")


def _draw_reactions_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    _check(Options, "EnableSimulatedReactionTime", x, y, "Simulated Reaction"); y += 28
    _check(Options, "AffectTriggerbotReaction", x, y, "Affect Triggerbot"); y += 28
    _slider(Options, "ReactionTime", x, y, 280, "Reaction (ms)", 0, 1000)


def _draw_recoil_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    _check(Options, "EnableRecoilControl", x, y, "Enable Recoil Control"); y += 28
    _slider(Options, "RecoilControlSmoothing", x, y, 280, "Smoothing", 1.0, 3.0, is_int=False)


def _draw_colors_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    _color_button(Options, "CT_color", x, y, "Counter-Terrorist"); y += 30
    _color_button(Options, "T_color", x, y, "Terrorist"); y += 30
    _color_button(Options, "FOV_color", x, y, "FOV Circle"); y += 30
    _color_button(Options, "GrenadeTrajectoryColor", x, y, "Grenade")


def _draw_misc_tab(Options):
    x = WIN_X + 40.0
    y = COLS_Y
    for k, lbl in [
        ("EnableAntiFlashbang", "Anti Flashbang"),
        ("EnableBhop", "Bhop"),
        ("EnableRadarHack", "Radar Hack"),
        ("EnableDiscordRPC", "Discord RPC"),
        ("EnableFovChanger", "FOV Changer"),
    ]:
        _check(Options, k, x, y, lbl); y += 26
    _slider(Options, "FovChangeSize", x, y, 280, "Set FOV", 50, 170)


def draw(proc, clientBase, Options, Offsets):
    global _tab
    if not _open:
        return
    pme.gui_window_box(WIN_X, WIN_Y, WIN_W, WIN_H, f"cs2py v{_VERSION}")

    # tab bar
    for i, name in enumerate(_TABS):
        bx = WIN_X + 12.0 + i * 114.0
        if i == _tab:
            pme.draw_rectangle(bx, WIN_Y + 34.0 + TAB_H - 2.0, 108.0, 2.0, pme.get_color(_ACCENT))
        if pme.gui_button(bx, WIN_Y + 34.0, 108.0, TAB_H, name):
            _tab = i

    if _tab == 0:
        _draw_skins_tab(proc, clientBase, Options, Offsets)
    elif _tab == 1:
        _draw_aimbot_tab(Options)
    elif _tab == 2:
        _draw_esp_tab(Options)
    elif _tab == 3:
        _draw_trigger_tab(Options)
    elif _tab == 4:
        _draw_reactions_tab(Options)
    elif _tab == 5:
        _draw_recoil_tab(Options)
    elif _tab == 6:
        _draw_colors_tab(Options)
    elif _tab == 7:
        _draw_misc_tab(Options)
