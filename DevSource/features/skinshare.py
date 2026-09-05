"""Client-only state sharing for the future remote skin applier.

Number 2 deliberately stops at the transport/state layer. It observes the
read-only match snapshot, packages the local player's currently equipped skin,
and optionally exchanges snapshots with a relay. It does not write to cs2.exe
and it does not apply received data to any game entity.

The transport accepts newline-delimited JSON over TCP/TLS for local tools and
text JSON WebSockets for the Cloudflare relay. An empty relay setting keeps
the feature completely offline. All network work runs on a daemon thread so
a slow or unavailable relay cannot stall the overlay loop.
"""

import hashlib
import json
import math
import os
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from ext import items
from features._relay_transport import RelayConnection


PROTOCOL_VERSION = 1
DEFAULT_RELAY_PORT = 37175
HEARTBEAT_SECONDS = 2.0
SNAPSHOT_TTL_MS = 5000
MAIN_UPDATE_TIMEOUT_SECONDS = 3.0
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0

_LOG_PATH = os.path.join(os.path.expanduser("~"), "cs2py_skinshare_debug.log")


def _log(message):
    line = f"[skin-share] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
    except Exception:
        pass


def _stable_signature(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        raw = repr(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _valid_item_key(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        return False
    return all(char.isalnum() or char in "_-" for char in value)


def _weapon_index(database):
    result = {}
    for name, weapon in (database or {}).get("weapons", {}).items():
        try:
            result[int(weapon["def_index"])] = (name, weapon)
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _skin_record(database, item_name, skin):
    if not isinstance(skin, dict):
        return None
    weapon = (database or {}).get("weapons", {}).get(item_name)
    if not weapon:
        return None
    try:
        target_def = int(weapon["def_index"])
        paint_kit = int(skin.get("paint_kit", 0))
        seed = int(skin.get("seed", 0))
        wear = float(skin.get("wear", 0.0))
        stat_trak = int(skin.get("stat_trak", -1))
        quality = int(skin.get("quality", 0))
    except (TypeError, ValueError, KeyError):
        return None
    if not 0 <= target_def <= 65535:
        return None
    if not 0 <= paint_kit <= 1_000_000:
        return None
    if not 0 <= seed <= 1_000_000:
        return None
    if not math.isfinite(wear) or not 0.0 <= wear <= 1.0:
        return None
    paint = (database or {}).get("paint_kits", {}).get(paint_kit, {})
    mesh_mask = 2 if paint.get("legacy") else 1
    return {
        "item_key": item_name,
        "category": weapon.get("category", ""),
        "target_def": target_def,
        "paint_kit": paint_kit,
        "seed": seed,
        "wear": wear,
        "stat_trak": stat_trak,
        "quality": quality,
        "mesh_mask": mesh_mask,
    }


def build_local_payload(snapshot, options):
    """Build a validated outgoing state payload, or return None.

    Only a settled live match is eligible. The payload contains the current
    roster so the relay can later support migration when a player joins or
    leaves. The active weapon is the only skin configuration sent.
    """
    if not snapshot or snapshot.get("phase") != "LIVE":
        return None
    match_id = snapshot.get("settled_fingerprint")
    local_steam_id = snapshot.get("local_steam_id")
    map_name = snapshot.get("map")
    if not match_id or not local_steam_id or not map_name:
        return None

    roster = sorted({
        str(player["steam_id"])
        for player in snapshot.get("players", [])
        if player.get("steam_id")
    })
    local_player = next(
        (
            player
            for player in snapshot.get("players", [])
            if player.get("steam_id") == local_steam_id
        ),
        None,
    )
    if not local_player:
        return None

    database = items.get_database()
    if not database:
        return None
    by_def = _weapon_index(database)
    active_def = local_player.get("active_def")
    active_weapon = None
    if active_def is not None and active_def in by_def:
        active_name, active_item = by_def[active_def]
        skin_config = (options.get("SkinChanger", {}) or {}).get("weapons", {}) or {}
        selected_name = active_name

        # Knife selection follows the existing local skin changer: the last
        # configured knife is the active replacement knife.
        if active_item.get("category") == "knives":
            for configured_name in skin_config:
                configured_item = database["weapons"].get(configured_name)
                if configured_item and configured_item.get("category") == "knives":
                    selected_name = configured_name

        active_weapon = _skin_record(
            database,
            selected_name,
            skin_config.get(selected_name),
        )
        if active_weapon:
            active_weapon["source_def"] = int(active_def)

    return {
        "protocol": PROTOCOL_VERSION,
        "match_id": str(match_id),
        "map": str(map_name),
        "player_id": str(int(local_steam_id)),
        "roster": roster,
        "session_number": int(snapshot.get("session_number", 0)),
        "active_weapon": active_weapon,
        "ttl_ms": SNAPSHOT_TTL_MS,
    }


def _parse_relay(value, tls_default):
    value = str(value or "").strip()
    if not value:
        return None
    if "://" not in value:
        scheme = "wss" if tls_default else "ws"
        value = f"{scheme}://{value}"
    parsed = urlsplit(value)
    if parsed.scheme not in ("tcp", "tls", "ssl", "ws", "wss") or not parsed.hostname:
        return None
    try:
        default_port = 443 if parsed.scheme in ("ws", "wss") else DEFAULT_RELAY_PORT
        port = parsed.port or default_port
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return parsed.scheme, parsed.hostname, port, parsed.path or "/"


def _validate_remote_state(message, current_payload):
    if not isinstance(message, dict) or not isinstance(current_payload, dict):
        return None
    state = message.get("state") if isinstance(message.get("state"), dict) else message
    if state.get("protocol") != PROTOCOL_VERSION:
        return None
    if state.get("match_id") != current_payload.get("match_id"):
        return None
    player_id = state.get("player_id")
    if not isinstance(player_id, str) or not player_id.isdigit():
        return None
    if player_id == current_payload.get("player_id"):
        return None
    active = state.get("active_weapon")
    if active is not None:
        if not isinstance(active, dict) or not _valid_item_key(active.get("item_key")):
            return None
        try:
            source_def = int(active["source_def"])
            target_def = int(active["target_def"])
            paint_kit = int(active["paint_kit"])
            seed = int(active["seed"])
            wear = float(active["wear"])
            mesh_mask = int(active["mesh_mask"])
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 <= source_def <= 65535 or not 0 <= target_def <= 65535:
            return None
        if not 0 <= paint_kit <= 1_000_000 or not 0 <= seed <= 1_000_000:
            return None
        if not math.isfinite(wear) or not 0.0 <= wear <= 1.0:
            return None
        if mesh_mask not in (1, 2):
            return None
    return state


class SkinShareClient:
    """Background transport client; no CS2 memory writes are performed."""

    def __init__(self):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._enabled = False
        self._relay = ""
        self._tls = True
        self._auth_token = ""
        self._latest_payload = None
        self._latest_signature = None
        self._latest_revision = 0
        self._last_snapshot = None
        self._last_main_update = 0.0
        self._skin_config_signature = None
        self._settings_signature = None
        self._remote_states = {}
        self._thread = threading.Thread(
            target=self._worker,
            name="cs2py-skin-share",
            daemon=True,
        )
        self._thread.start()

    def update(self, snapshot, options):
        """Accept fresh local state from the main loop without blocking."""
        now = time.monotonic()
        share_config = dict(options.get("SkinShare", {}) or {})
        enabled = bool(share_config.get("enabled", False))
        relay = str(share_config.get("relay", "") or "").strip()
        tls = bool(share_config.get("tls", True))
        auth_token = str(share_config.get("auth_token", "") or "")
        skin_config = options.get("SkinChanger", {}) or {}
        skin_signature = _stable_signature(skin_config)
        settings_signature = _stable_signature({
            "enabled": enabled,
            "relay": relay,
            "tls": tls,
            # Do not log or expose the token, but include it in the internal
            # signature so changing credentials forces a reconnect.
            "auth_token": auth_token,
        })

        with self._lock:
            self._last_main_update = now
            if snapshot is not None:
                self._last_snapshot = snapshot
            settings_changed = settings_signature != self._settings_signature
            snapshot_changed = snapshot is not None
            config_changed = skin_signature != self._skin_config_signature
            match_before = (self._latest_payload or {}).get("match_id")
            self._enabled = enabled
            self._relay = relay
            self._tls = tls
            self._auth_token = auth_token
            self._settings_signature = settings_signature
            self._skin_config_signature = skin_signature

            if settings_changed:
                _log(
                    f"config enabled={enabled} relay={'set' if relay else 'empty'} "
                    f"tls={tls}"
                )

            if not enabled:
                self._latest_payload = None
                self._latest_signature = None
                self._remote_states.clear()
            elif snapshot_changed or config_changed:
                payload = build_local_payload(self._last_snapshot, options)
                payload_signature = _stable_signature(payload) if payload else None
                if payload_signature != self._latest_signature:
                    self._latest_payload = payload
                    self._latest_signature = payload_signature
                    self._latest_revision += 1
                    active = payload.get("active_weapon") if payload else None
                    if active:
                        _log(
                            f"local snapshot sequence={self._latest_revision} "
                            f"item={active.get('item_key')} "
                            f"paint_kit={active.get('paint_kit')}"
                        )
                    else:
                        _log(
                            f"local snapshot sequence={self._latest_revision} "
                            "active_weapon=none"
                        )
                    if match_before != (payload or {}).get("match_id"):
                        self._remote_states.clear()
            self._wake.set()

    def get_remote_states(self):
        """Return a copy for the later DLL/state-file integration."""
        with self._lock:
            return {
                player_id: dict(state)
                for player_id, state in self._remote_states.items()
            }

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=1.0)

    def _settings(self):
        with self._lock:
            return {
                "enabled": self._enabled,
                "relay": self._relay,
                "tls": self._tls,
                "auth_token": self._auth_token,
                "payload": dict(self._latest_payload) if self._latest_payload else None,
                "revision": self._latest_revision,
                "last_main_update": self._last_main_update,
            }

    @staticmethod
    def _connect(relay, tls_default, match_id=None):
        parsed = _parse_relay(relay, tls_default)
        if not parsed:
            raise ValueError(
                "invalid relay; use wss://host/path or tcp://host:port"
            )
        scheme, host, port, path = parsed

        if scheme in ("ws", "wss"):
            from features._relay_transport import _websocket

            if _websocket is None:
                raise RuntimeError(
                    "WebSocket relay support needs the websocket-client package"
                )
            room_path = path.rstrip("/") or "/ws"
            if match_id:
                room_path = f"{room_path}/{match_id}"
            default_port = (
                (scheme == "wss" and port == 443)
                or (scheme == "ws" and port == 80)
            )
            port_suffix = "" if default_port else f":{port}"
            url = f"{scheme}://{host}{port_suffix}{room_path}"
            websocket = _websocket.create_connection(url, timeout=3.0)
            websocket.settimeout(0.1)
            return RelayConnection(websocket, is_websocket=True), (
                scheme,
                host,
                port,
                path,
                match_id,
            )

        raw_socket = socket.create_connection((host, port), timeout=3.0)
        if scheme in ("tls", "ssl"):
            context = ssl.create_default_context()
            raw_socket = context.wrap_socket(raw_socket, server_hostname=host)
        raw_socket.settimeout(0.1)
        return RelayConnection(raw_socket, is_websocket=False), (
            scheme,
            host,
            port,
            path,
        )

    def _handle_message(self, message, current_payload):
        if not isinstance(message, dict):
            return
        message_type = message.get("type")
        if message_type == "welcome":
            # A client process can restart its local sequence counter. The
            # relay resets that player's room state on hello, so discard the
            # cached remote sequences before replayed snapshots arrive.
            with self._lock:
                self._remote_states.clear()
            _log("relay welcome received")
            return
        if message_type == "error":
            _log(f"relay error={message.get('code', 'unknown')}")
            return
        if message_type != "snapshot":
            return
        state = _validate_remote_state(message, current_payload)
        if not state:
            return
        player_id = state["player_id"]
        try:
            sequence = int(message.get("sequence", state.get("sequence", 0)))
        except (TypeError, ValueError):
            return
        with self._lock:
            previous = self._remote_states.get(player_id)
            previous_sequence = int(previous.get("sequence", -1)) if previous else -1
            if sequence <= previous_sequence:
                return
            stored = dict(state)
            stored["sequence"] = sequence
            stored["received_at"] = time.time()
            self._remote_states[player_id] = stored
        if not previous or sequence != previous_sequence:
            _log(f"received player={player_id} sequence={sequence}")

    def _worker(self):
        sock = None
        endpoint_key = None
        connected_match = None
        connected_player = None
        sent_revision = -1
        last_heartbeat = 0.0
        reconnect_at = 0.0
        backoff = RECONNECT_MIN_SECONDS
        receive_buffer = b""

        while not self._stop.is_set():
            settings = self._settings()
            now = time.monotonic()
            stale_main = now - settings["last_main_update"] > MAIN_UPDATE_TIMEOUT_SECONDS
            payload = settings["payload"]
            ready = (
                settings["enabled"]
                and bool(settings["relay"])
                and payload is not None
                and not stale_main
            )
            desired_endpoint = (
                settings["relay"],
                settings["tls"],
                settings["auth_token"],
                payload.get("match_id") if payload else None,
            )

            if not ready:
                if sock is not None:
                    sock.close()
                sock = None
                endpoint_key = None
                connected_match = None
                connected_player = None
                sent_revision = -1
                receive_buffer = b""
                self._wake.wait(0.5)
                self._wake.clear()
                continue

            if sock is not None and endpoint_key != desired_endpoint:
                sock.close()
                sock = None
                endpoint_key = None
                connected_match = None
                connected_player = None
                sent_revision = -1
                receive_buffer = b""

            if sock is None:
                if now < reconnect_at:
                    self._wake.wait(min(0.25, reconnect_at - now))
                    self._wake.clear()
                    continue
                try:
                    sock, _ = self._connect(
                        settings["relay"],
                        settings["tls"],
                        payload["match_id"],
                    )
                    endpoint_key = desired_endpoint
                    connected_match = None
                    connected_player = None
                    sent_revision = -1
                    last_heartbeat = 0.0
                    receive_buffer = b""
                    backoff = RECONNECT_MIN_SECONDS
                    _log("relay connected")
                except Exception as exc:
                    if sock is not None:
                        sock.close()
                    sock = None
                    _log(f"relay connect failed={type(exc).__name__}; retrying")
                    reconnect_at = now + backoff
                    backoff = min(RECONNECT_MAX_SECONDS, backoff * 2.0)
                    self._wake.wait(min(0.5, backoff))
                    self._wake.clear()
                    continue

            try:
                if connected_match != payload["match_id"] or connected_player != payload["player_id"]:
                    hello = {
                        "type": "hello",
                        "protocol": PROTOCOL_VERSION,
                        "client": "cs2py",
                        "match_id": payload["match_id"],
                        "map": payload["map"],
                        "player_id": payload["player_id"],
                        "roster": payload["roster"],
                    }
                    if settings["auth_token"]:
                        hello["auth_token"] = settings["auth_token"]
                    sock.send(hello)
                    connected_match = payload["match_id"]
                    connected_player = payload["player_id"]
                    sent_revision = -1
                    _log(f"room candidate={connected_match}")

                if sent_revision != settings["revision"]:
                    sock.send({
                        "type": "snapshot",
                        "protocol": PROTOCOL_VERSION,
                        "match_id": payload["match_id"],
                        "player_id": payload["player_id"],
                        "sequence": settings["revision"],
                        "state": payload,
                    })
                    sent_revision = settings["revision"]

                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    sock.send({
                        "type": "heartbeat",
                        "protocol": PROTOCOL_VERSION,
                        "match_id": payload["match_id"],
                        "player_id": payload["player_id"],
                        "sequence": settings["revision"],
                    })
                    last_heartbeat = now

                try:
                    chunk = sock.recv()
                    if chunk is None:
                        pass
                    elif not chunk:
                        raise ConnectionError("relay closed connection")
                    elif sock.is_websocket:
                        message = json.loads(
                            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                        )
                        self._handle_message(message, payload)
                    else:
                        if isinstance(chunk, str):
                            chunk = chunk.encode("utf-8")
                        receive_buffer += chunk
                        while b"\n" in receive_buffer:
                            line, receive_buffer = receive_buffer.split(b"\n", 1)
                            if not line:
                                continue
                            message = json.loads(line.decode("utf-8"))
                            self._handle_message(message, payload)
                except socket.timeout:
                    pass
            except Exception as exc:
                _log(f"relay disconnected={type(exc).__name__}")
                if sock is not None:
                    sock.close()
                sock = None
                endpoint_key = None
                connected_match = None
                connected_player = None
                sent_revision = -1
                receive_buffer = b""
                reconnect_at = time.monotonic() + backoff
                backoff = min(RECONNECT_MAX_SECONDS, backoff * 2.0)

            self._wake.wait(0.1)
            self._wake.clear()

        if sock is not None:
            sock.close()
