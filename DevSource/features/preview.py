"""Skin preview images (Steam CDN) for the overlay skin browser.

The Steam Community Market search endpoint is heavily rate-limited, so instead we
pull the one-shot item/icon mapping from the public ByMykel CSGO-API skins.json
(weapon + paint_index -> Steam CDN image URL), cache it locally, then download
each preview straight from the Steam CDN (which is not rate-limited). Downloads
happen on a background thread; textures are created on the drawing thread.
"""
import json
import os
import threading

import requests
import pyMeow as pme

from ext import paths

_API_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"
_CACHE_DIR = os.path.join(paths.writable_dir(), "preview_cache")
_MAP_FILE = os.path.join(_CACHE_DIR, "image_map.json")
_BUNDLED_MAP = os.path.join(paths.bundle_dir(), "preview_cache", "image_map.json")

_mapping = None          # {(weapon_name, paint_index): image_url}
_textures = {}           # key -> Texture2D handle
_pending = {}            # key -> cached PNG path (ready to load on draw thread)
_loading = set()         # keys currently downloading


def _local_path(key):
    return os.path.join(_CACHE_DIR, f"{key[0]}_{key[1]}.png")


def _bundled_png(key):
    return os.path.join(paths.bundle_dir(), "preview_cache", f"{key[0]}_{key[1]}.png")


def _ensure_mapping():
    global _mapping
    if _mapping is not None:
        return _mapping
    for src in (_MAP_FILE, _BUNDLED_MAP):
        if os.path.exists(src):
            try:
                with open(src, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                m = {}
                for k, v in raw.items():
                    wn, pi = k.split("|")
                    try:
                        m[(wn, int(pi))] = v
                    except ValueError:
                        continue
                _mapping = m
                return _mapping
            except Exception:
                _mapping = None

    print("[skin-changer] Fetching skin image map (one-time)...")
    try:
        r = requests.get(_API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
    except Exception:
        _mapping = {}
        return _mapping

    m = {}
    for e in data:
        wname = (e.get("weapon") or {}).get("id")
        pi = e.get("paint_index")
        img = e.get("image")
        if wname and pi and img:
            try:
                m[(wname, int(pi))] = img
            except (ValueError, TypeError):
                continue
    _mapping = m
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump({f"{k[0]}|{k[1]}": v for k, v in m.items()}, f)
    except Exception:
        pass
    return _mapping


def _fetch(key, url):
    try:
        img = requests.get(url + "/200fx150f", timeout=15, headers={"User-Agent": "Mozilla/5.0"}).content
        if img[:8] != b"\x89PNG\r\n\x1a\n":
            return
        path = _local_path(key)
        with open(path, "wb") as f:
            f.write(img)
        _pending[key] = path
    except Exception:
        pass
    finally:
        _loading.discard(key)


def get_mapping():
    """Return the cached (weapon_name, paint_index) -> image_url map."""
    return _ensure_mapping()


def request_preview(weapon_name, paint_kit_id):
    key = (weapon_name, paint_kit_id)
    if key in _textures or key in _loading:
        return
    path = _local_path(key)
    if os.path.exists(path):
        _pending[key] = path
        return
    bundled = _bundled_png(key)
    if os.path.exists(bundled):
        _pending[key] = bundled
        return
    url = _ensure_mapping().get(key)
    if not url:
        return
    _loading.add(key)
    threading.Thread(target=_fetch, args=(key, url), daemon=True).start()


def get_texture(weapon_name, paint_kit_id):
    key = (weapon_name, paint_kit_id)
    if key in _textures:
        return _textures[key]
    if key in _pending:
        path = _pending.pop(key)
        try:
            with open(path, "rb") as f:
                tex = pme.load_texture_bytes(".png", f.read())
            _textures[key] = tex
            return tex
        except Exception:
            return None
    return None
