"""Read-only match and player diagnostics for the future skin-sharing feature.

This module intentionally does not write to cs2.exe, open a network socket, or
apply any skin data. It samples the existing client state at a low rate and
records enough information to validate match grouping later:

* engine sign-on state and current map;
* local SteamID64;
* the connected controller roster and each controller's SteamID64;
* each player's currently active weapon definition and handle;
* a deterministic candidate match fingerprint;
* local engine connection/game-rules lifetime markers and a settled roster
  fingerprint for comparing match transitions.

The diagnostic log is written to ``%USERPROFILE%\\cs2py_match_debug.log``.
"""

import hashlib
import os
import time

from functions import memfuncs


MAP_NAME_OFFSET = 0x188
SIGNON_FULL = 6
MAX_PLAYER_SLOTS = 64
POLL_INTERVAL_SECONDS = 0.75


def _valid_pointer(address):
    return address is not None and 0x10000 < address < 0x7FFFFFFFFFFF


def _fmt_steam_id(steam_id):
    if not steam_id:
        return "0"
    return str(int(steam_id))


def _resolve_handle(process_handle, client_base_address, offsets, handle):
    """Resolve a CEntityHandle to an entity pointer without raising."""
    if not handle or handle == 0xFFFFFFFF:
        return None
    try:
        entity_list = memfuncs.ProcMemHandler.ReadPointer(
            process_handle,
            client_base_address + offsets.dwEntityList,
        )
        if not _valid_pointer(entity_list):
            return None
        list_entry = memfuncs.ProcMemHandler.ReadPointer(
            process_handle,
            entity_list + 0x8 * ((handle & 0x7FFF) >> 9) + 0x10,
        )
        if not _valid_pointer(list_entry):
            return None
        entity = memfuncs.ProcMemHandler.ReadPointer(
            process_handle,
            list_entry + 0x70 * (handle & 0x1FF),
        )
        return entity if _valid_pointer(entity) else None
    except Exception:
        return None


def _read_map_name(process_handle, client_base_address, offsets):
    try:
        global_vars = memfuncs.ProcMemHandler.ReadPointer(
            process_handle,
            client_base_address + offsets.dwGlobalVars,
        )
        if not _valid_pointer(global_vars):
            return None
        name_ptr = memfuncs.ProcMemHandler.ReadPointer(
            process_handle,
            global_vars + MAP_NAME_OFFSET,
        )
        if not _valid_pointer(name_ptr):
            return None
        name = memfuncs.ProcMemHandler.ReadString(process_handle, name_ptr, 64)
        if not name:
            return None
        name = name.strip()
        if 3 <= len(name) <= 48 and "/" not in name and "\\" not in name:
            return name
    except Exception:
        pass
    return None


def _candidate_match_fingerprint(map_name, local_steam_id, players):
    """Return a shared candidate fingerprint for the current match roster.

    The local SteamID is intentionally excluded. Including it would assign a
    different room to every player in the same match. The roster remains a
    candidate because it can change when a player joins or leaves; deaths do
    not change the controller roster.
    """
    if not map_name:
        return None
    roster_ids = sorted(
        str(player["steam_id"])
        for player in players
        if player["steam_id"]
    )
    if not roster_ids:
        return None
    material = "|".join([map_name, ",".join(roster_ids)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class MatchDiagnostics:
    """Low-rate, read-only match-state sampler."""

    def __init__(self, log_path=None):
        self.log_path = log_path or os.path.join(
            os.path.expanduser("~"),
            "cs2py_match_debug.log",
        )
        self._next_poll = 0.0
        self._last_phase = None
        self._last_fingerprint = None
        self._last_roster = None
        self._last_active = {}
        self._last_network_client = None
        self._last_game_rules = None
        self._pending_fingerprint = None
        self._pending_fingerprint_since = 0.0
        self._last_settled_fingerprint = None
        self._last_snapshot = None
        self._session_number = 0
        self._last_error = None

    def _log(self, message):
        line = f"[match-diagnostics] {message}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
        except Exception:
            pass

    def _log_error_once(self, message):
        if message == self._last_error:
            return
        self._last_error = message
        self._log(f"error={message}")

    def _read_network_state(self, process_handle, engine_base_address, offsets):
        if not engine_base_address:
            return None, None, None, None
        if not offsets.dwNetworkGameClient or not offsets.dwNetworkGameClient_signOnState:
            return None, None, None, None
        try:
            network_client = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                engine_base_address + offsets.dwNetworkGameClient,
            )
            if not _valid_pointer(network_client):
                return None, None, None, None
            sign_on_state = memfuncs.ProcMemHandler.ReadInt(
                process_handle,
                network_client + offsets.dwNetworkGameClient_signOnState,
            )
            server_tick = None
            if offsets.dwNetworkGameClient_serverTickCount:
                server_tick = memfuncs.ProcMemHandler.ReadInt(
                    process_handle,
                    network_client + offsets.dwNetworkGameClient_serverTickCount,
                )
            max_clients = None
            if offsets.dwNetworkGameClient_maxClients:
                max_clients = memfuncs.ProcMemHandler.ReadInt(
                    process_handle,
                    network_client + offsets.dwNetworkGameClient_maxClients,
                )
            return network_client, sign_on_state, server_tick, max_clients
        except Exception as exc:
            self._log_error_once(f"network_state={type(exc).__name__}")
            return None, None, None, None

    def _read_controller_steam_id(self, process_handle, controller, offsets):
        if not _valid_pointer(controller) or not offsets.m_steamID:
            return 0
        try:
            return memfuncs.ProcMemHandler.ReadULong(
                process_handle,
                controller + offsets.m_steamID,
            )
        except Exception:
            return 0

    def _read_active_weapon(self, process_handle, client_base_address, pawn, offsets):
        result = {"handle": 0, "def": None}
        if not _valid_pointer(pawn):
            return result
        try:
            weapon_services = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                pawn + offsets.m_pWeaponServices,
            )
            if not _valid_pointer(weapon_services):
                return result
            handle = memfuncs.ProcMemHandler.ReadInt(
                process_handle,
                weapon_services + offsets.m_hActiveWeapon,
            )
            result["handle"] = handle if handle else 0
            weapon = _resolve_handle(
                process_handle,
                client_base_address,
                offsets,
                handle,
            )
            if not _valid_pointer(weapon):
                return result
            result["def"] = memfuncs.ProcMemHandler.ReadUShort(
                process_handle,
                weapon + offsets.m_AttributeManager
                + offsets.m_Item
                + offsets.m_iItemDefinitionIndex,
            )
        except Exception:
            pass
        return result

    def _read_players(self, process_handle, client_base_address, offsets, max_clients):
        players = []
        if not _valid_pointer(client_base_address):
            return players
        try:
            entity_list = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                client_base_address + offsets.dwEntityList,
            )
            if not _valid_pointer(entity_list):
                return players

            slot_count = MAX_PLAYER_SLOTS
            if max_clients and 1 <= max_clients <= MAX_PLAYER_SLOTS:
                slot_count = max_clients

            # Player controller indices are 1..max_clients, inclusive.
            for slot in range(1, slot_count + 1):
                try:
                    list_entry = memfuncs.ProcMemHandler.ReadPointer(
                        process_handle,
                        entity_list + 0x8 * ((slot & 0x7FFF) >> 9) + 0x10,
                    )
                    if not _valid_pointer(list_entry):
                        continue
                    controller = memfuncs.ProcMemHandler.ReadPointer(
                        process_handle,
                        list_entry + 0x70 * (slot & 0x1FF),
                    )
                    if not _valid_pointer(controller):
                        continue

                    steam_id = self._read_controller_steam_id(
                        process_handle,
                        controller,
                        offsets,
                    )
                    pawn_handle = memfuncs.ProcMemHandler.ReadInt(
                        process_handle,
                        controller + offsets.m_hPlayerPawn,
                    )
                    pawn = _resolve_handle(
                        process_handle,
                        client_base_address,
                        offsets,
                        pawn_handle,
                    )
                    active = self._read_active_weapon(
                        process_handle,
                        client_base_address,
                        pawn,
                        offsets,
                    )
                    players.append({
                        "slot": slot,
                        "steam_id": steam_id,
                        "pawn_handle": pawn_handle or 0,
                        "active_handle": active["handle"],
                        "active_def": active["def"],
                    })
                except Exception:
                    continue
        except Exception as exc:
            self._log_error_once(f"roster={type(exc).__name__}")
        return players

    @staticmethod
    def _player_key(player):
        return player["steam_id"] or f"slot:{player['slot']}"

    def _emit_changes(self, snapshot):
        phase = snapshot["phase"]
        fingerprint = snapshot["fingerprint"]

        if phase != "LIVE":
            # A later live session must wait for a fresh settled roster even if
            # the same map and players are encountered again.
            self._pending_fingerprint = None
            self._pending_fingerprint_since = 0.0
            self._last_settled_fingerprint = None

        # These are local lifetime markers, not values that can be shared
        # between clients. They tell us whether the engine's connection object
        # and the per-map game-rules object are recreated across transitions.
        if snapshot["network_client"] != self._last_network_client:
            self._log(
                "engine_connection="
                f"0x{snapshot['network_client'] or 0:X} "
                f"server_tick={snapshot['server_tick'] if snapshot['server_tick'] is not None else '-'}"
            )
            self._last_network_client = snapshot["network_client"]
        if snapshot["game_rules"] != self._last_game_rules:
            self._log(
                f"game_rules_instance=0x{snapshot['game_rules'] or 0:X}"
            )
            self._last_game_rules = snapshot["game_rules"]

        if phase != self._last_phase or fingerprint != self._last_fingerprint:
            if phase == "LIVE" and self._last_phase != "LIVE":
                self._session_number += 1
            self._log(
                "state="
                f"{phase} session={self._session_number} "
                f"signon={snapshot['sign_on_state']} "
                f"rules={'yes' if snapshot['game_rules'] else 'no'} "
                f"map={snapshot['map'] or '-'} "
                f"local_steamid={_fmt_steam_id(snapshot['local_steam_id'])} "
                f"candidate_match={fingerprint or '-'} "
                f"server_tick={snapshot['server_tick'] if snapshot['server_tick'] is not None else '-'}"
            )
            self._last_phase = phase
            self._last_fingerprint = fingerprint

        roster_key = tuple(
            sorted(
                (
                    player["slot"],
                    player["steam_id"],
                    player["pawn_handle"],
                )
                for player in snapshot["players"]
            )
        )
        if roster_key != self._last_roster:
            self._log(
                f"roster count={len(snapshot['players'])} "
                f"max_clients={snapshot['max_clients'] or '-'}"
            )
            for player in sorted(snapshot["players"], key=lambda item: item["slot"]):
                self._log(
                    f"player slot={player['slot']} "
                    f"steamid={_fmt_steam_id(player['steam_id'])} "
                    f"pawn_handle=0x{player['pawn_handle'] & 0xFFFFFFFF:X}"
                )
            self._last_roster = roster_key

        # Wait until the candidate has remained unchanged for two seconds
        # before logging it as settled. This avoids treating every late player
        # arrival as a brand-new match identifier.
        now = time.monotonic()
        if fingerprint != self._pending_fingerprint:
            self._pending_fingerprint = fingerprint
            self._pending_fingerprint_since = now
        elif fingerprint and self._last_settled_fingerprint != fingerprint:
            if now - self._pending_fingerprint_since >= 2.0:
                self._log(
                    f"settled_candidate_match={fingerprint} "
                    f"roster_count={len(snapshot['players'])}"
                )
                self._last_settled_fingerprint = fingerprint

        current_active = {}
        for player in snapshot["players"]:
            key = self._player_key(player)
            active_key = (player["active_handle"], player["active_def"])
            current_active[key] = active_key
            if self._last_active.get(key) != active_key:
                self._log(
                    f"active slot={player['slot']} "
                    f"steamid={_fmt_steam_id(player['steam_id'])} "
                    f"handle=0x{player['active_handle'] & 0xFFFFFFFF:X} "
                    f"def={player['active_def'] if player['active_def'] is not None else '-'}"
                )
        self._last_active = current_active

    def update(self, process_handle, client_base_address, engine_base_address, offsets):
        """Sample state if the low-rate poll interval has elapsed."""
        now = time.monotonic()
        if now < self._next_poll:
            return None
        self._next_poll = now + POLL_INTERVAL_SECONDS

        try:
            network_client, sign_on_state, server_tick, max_clients = self._read_network_state(
                process_handle,
                engine_base_address,
                offsets,
            )
            game_rules = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                client_base_address + offsets.dwGameRules,
            )
            local_controller = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                client_base_address + offsets.dwLocalPlayerController,
            )
            local_pawn = memfuncs.ProcMemHandler.ReadPointer(
                process_handle,
                client_base_address + offsets.dwLocalPlayerPawn,
            )
            local_steam_id = self._read_controller_steam_id(
                process_handle,
                local_controller,
                offsets,
            )
            map_name = _read_map_name(process_handle, client_base_address, offsets)
            # Do not traverse stale player entities once engine teardown starts.
            live = sign_on_state == SIGNON_FULL and game_rules and local_controller and local_pawn
            players = self._read_players(
                process_handle,
                client_base_address,
                offsets,
                max_clients,
            ) if live else []
            fingerprint = _candidate_match_fingerprint(
                map_name,
                local_steam_id,
                players,
            )

            if sign_on_state is None:
                phase = "UNAVAILABLE"
            elif sign_on_state == SIGNON_FULL and game_rules and local_controller and local_pawn:
                phase = "LIVE"
            elif sign_on_state > 0:
                phase = "LOADING"
            else:
                phase = "MENU"

            snapshot = {
                "phase": phase,
                "sign_on_state": sign_on_state if sign_on_state is not None else -1,
                "network_client": network_client,
                "game_rules": game_rules,
                "map": map_name,
                "local_steam_id": local_steam_id,
                "players": players,
                "fingerprint": fingerprint,
                "server_tick": server_tick,
                "max_clients": max_clients,
            }
            self._emit_changes(snapshot)
            snapshot["session_number"] = self._session_number
            snapshot["settled_fingerprint"] = (
                fingerprint
                if phase == "LIVE" and self._last_settled_fingerprint == fingerprint
                else None
            )
            self._last_snapshot = snapshot
            self._last_error = None
            return snapshot
        except Exception as exc:
            self._log_error_once(f"sample={type(exc).__name__}")
            return None
