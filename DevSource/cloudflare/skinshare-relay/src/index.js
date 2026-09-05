const PROTOCOL_VERSION = 1;
const MAX_MESSAGE_BYTES = 64 * 1024;
const MAX_ROOM_CONNECTIONS = 64;
const STATE_TTL_SECONDS = 5;
const MAX_ROSTER_SIZE = 64;

const PLAYER_ID_PATTERN = /^\d{1,20}$/;
// The current CS2py match diagnostics intentionally publish a truncated
// 16-character SHA-256 fingerprint. Keep accepting longer fingerprints too
// so older clients can still use the same relay.
const MATCH_ID_PATTERN = /^[a-f0-9]{16,64}$/;
const ITEM_KEY_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function pathMatchId(url) {
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length !== 2 || parts[0] !== "ws") {
    return null;
  }
  return MATCH_ID_PATTERN.test(parts[1]) ? parts[1] : null;
}

function tokenMatches(provided, expected) {
  if (typeof provided !== "string" || typeof expected !== "string") {
    return false;
  }
  if (!provided || !expected || provided.length !== expected.length) {
    return false;
  }
  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) {
    difference |= provided.charCodeAt(index) ^ expected.charCodeAt(index);
  }
  return difference === 0;
}

function asInteger(value, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    return null;
  }
  return value;
}

function safePlayerId(value) {
  const playerId = typeof value === "string" ? value : String(value ?? "");
  return PLAYER_ID_PATTERN.test(playerId) ? playerId : null;
}

function safeRoster(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.map(safePlayerId).filter(Boolean))].slice(0, MAX_ROSTER_SIZE);
}

function safeActiveWeapon(value) {
  if (value === null || value === undefined) {
    return null;
  }
  if (!value || typeof value !== "object" || !ITEM_KEY_PATTERN.test(value.item_key || "")) {
    return undefined;
  }

  const targetDef = asInteger(value.target_def, 0, 65535);
  const sourceDef = asInteger(value.source_def, 0, 65535);
  const paintKit = asInteger(value.paint_kit, 0, 1000000);
  const seed = asInteger(value.seed, 0, 1000000);
  const meshMask = asInteger(value.mesh_mask, 1, 2);
  const wear = Number(value.wear);
  if (
    targetDef === null ||
    sourceDef === null ||
    paintKit === null ||
    seed === null ||
    meshMask === null ||
    !Number.isFinite(wear) ||
    wear < 0 ||
    wear > 1
  ) {
    return undefined;
  }

  return {
    item_key: value.item_key,
    category: typeof value.category === "string" ? value.category.slice(0, 32) : "",
    target_def: targetDef,
    source_def: sourceDef,
    paint_kit: paintKit,
    seed,
    wear,
    stat_trak: asInteger(value.stat_trak, -1, 1000000000) ?? -1,
    quality: asInteger(value.quality, 0, 1000000000) ?? 0,
    mesh_mask: meshMask,
  };
}

function normalizeState(message, roomId, authenticatedPlayerId) {
  const source = message && typeof message.state === "object" ? message.state : message;
  if (!source || typeof source !== "object" || source.protocol !== PROTOCOL_VERSION) {
    return null;
  }
  if (source.match_id !== roomId || source.player_id !== authenticatedPlayerId) {
    return null;
  }

  const activeWeapon = safeActiveWeapon(source.active_weapon);
  if (activeWeapon === undefined) {
    return null;
  }
  let loadout;
  if (source.loadout !== undefined) {
    if (!Array.isArray(source.loadout) || source.loadout.length > 64) return null;
    loadout = source.loadout.map(safeActiveWeapon);
    if (loadout.some((item) => !item)) return null;
  }

  const sessionNumber = asInteger(source.session_number, 0, 1000000000);
  const mapName = typeof source.map === "string" ? source.map.slice(0, 64) : "";
  if (!mapName || sessionNumber === null) {
    return null;
  }

  return {
    protocol: PROTOCOL_VERSION,
    match_id: roomId,
    map: mapName,
    player_id: authenticatedPlayerId,
    roster: safeRoster(source.roster),
    session_number: sessionNumber,
    active_weapon: activeWeapon,
    ...(loadout === undefined ? {} : { loadout }),
    ttl_ms: 5000,
  };
}

function decodeMessage(message) {
  const text = typeof message === "string" ? message : new TextDecoder().decode(message);
  if (text.length > MAX_MESSAGE_BYTES) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function sendJson(webSocket, value) {
  try {
    webSocket.send(JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return jsonResponse({ ok: true, service: "cs2py-skinshare-relay" });
    }

    const matchId = pathMatchId(url);
    if (!matchId) {
      return jsonResponse({ ok: false, error: "not_found" }, 404);
    }
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return jsonResponse({ ok: false, error: "websocket_required" }, 426);
    }

    const roomId = env.MATCH_ROOMS.idFromName(matchId);
    return env.MATCH_ROOMS.get(roomId).fetch(request);
  },
};

export class MatchRoom {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.roomId = null;
    // Ephemeral cosmetics need no per-update database writes. Hibernation
    // clears this cache; clients republish every two seconds to repopulate it.
    this.players = new Map();
  }

  async fetch(request) {
    const roomId = pathMatchId(new URL(request.url));
    if (!roomId) {
      return jsonResponse({ ok: false, error: "not_found" }, 404);
    }
    this.roomId = roomId;

    const currentConnections = this.state.getWebSockets().length;
    if (currentConnections >= MAX_ROOM_CONNECTIONS) {
      return jsonResponse({ ok: false, error: "room_full" }, 429);
    }

    const [client, server] = Object.values(new WebSocketPair());
    this.state.acceptWebSocket(server);
    server.serializeAttachment({ authenticated: false, player_id: null, room_id: roomId });
    return new Response(null, { status: 101, webSocket: client });
  }

  _roomIdFromRequest(webSocket) {
    return this._attachment(webSocket)?.room_id || this.roomId;
  }

  _attachment(webSocket) {
    try {
      return webSocket.deserializeAttachment() || null;
    } catch {
      return null;
    }
  }

  _error(webSocket, code) {
    sendJson(webSocket, { type: "error", protocol: PROTOCOL_VERSION, code });
    try {
      webSocket.close(4003, code);
    } catch {
      // The peer may already have disconnected.
    }
  }

  async webSocketMessage(webSocket, message) {
    const parsed = decodeMessage(message);
    if (!parsed || typeof parsed !== "object") {
      this._error(webSocket, "invalid_json");
      return;
    }

    let attachment = this._attachment(webSocket);
    if (attachment?.superseded) return;
    if (!attachment?.authenticated) {
      if (parsed.type !== "hello" || parsed.protocol !== PROTOCOL_VERSION) {
        this._error(webSocket, "hello_required");
        return;
      }
      if (!tokenMatches(parsed.auth_token, this.env.ROOM_TOKEN)) {
        this._error(webSocket, "unauthorized");
        return;
      }
      const playerId = safePlayerId(parsed.player_id);
      if (!playerId || parsed.match_id !== this._roomIdFromRequest(webSocket)) {
        this._error(webSocket, "invalid_room");
        return;
      }

      for (const peer of this.state.getWebSockets()) {
        if (peer === webSocket) {
          continue;
        }
        const peerAttachment = this._attachment(peer);
        if (peerAttachment?.player_id === playerId) {
          peer.serializeAttachment({ ...peerAttachment, superseded: true });
          try {
            peer.close(4002, "replaced");
          } catch {
            // Ignore already-closed peers.
          }
        }
      }

      // A restarted client begins its local sequence counter at one. Remove
      // the previous ephemeral record so the new session is not rejected as
      // stale by the room's sequence check.
      this.players.delete(playerId);

      attachment = {
        authenticated: true,
        player_id: playerId,
        room_id: parsed.match_id,
        relay_session: crypto.randomUUID(),
        map: typeof parsed.map === "string" ? parsed.map.slice(0, 64) : "",
      };
      webSocket.serializeAttachment(attachment);
      sendJson(webSocket, { type: "welcome", protocol: PROTOCOL_VERSION });

      for (const record of this.players.values()) {
        if (!record || record.state?.player_id === playerId || Date.now() - record.updated_at > STATE_TTL_SECONDS * 1000) {
          continue;
        }
        sendJson(webSocket, {
          type: "snapshot",
          protocol: PROTOCOL_VERSION,
          sequence: record.sequence,
          relay_session: record.relay_session,
          state: record.state,
        });
      }
      return;
    }

    if (parsed.protocol !== PROTOCOL_VERSION || parsed.match_id !== this._roomIdFromRequest(webSocket)) {
      this._error(webSocket, "invalid_room");
      return;
    }

    if (parsed.type === "heartbeat") {
      sendJson(webSocket, {
        type: "heartbeat_ack",
        protocol: PROTOCOL_VERSION,
        sequence: parsed.sequence ?? 0,
      });
      return;
    }

    if (parsed.type !== "snapshot") {
      return;
    }

    const state = normalizeState(parsed, this._roomIdFromRequest(webSocket), attachment.player_id);
    const sequence = asInteger(parsed.sequence, 0, 1000000000);
    if (!state || sequence === null) {
      this._error(webSocket, "invalid_snapshot");
      return;
    }

    const previous = this.players.get(attachment.player_id);
    if (previous && previous.relay_session === attachment.relay_session && sequence < previous.sequence) {
      return;
    }
    const record = {
      sequence,
      state,
      updated_at: Date.now(),
      relay_session: attachment.relay_session,
    };
    this.players.set(attachment.player_id, record);

    const outgoing = {
      type: "snapshot",
      protocol: PROTOCOL_VERSION,
      sequence,
      relay_session: attachment.relay_session,
      state,
    };
    for (const peer of this.state.getWebSockets()) {
      if (peer === webSocket) {
        continue;
      }
      const peerAttachment = this._attachment(peer);
      if (peerAttachment?.authenticated) {
        sendJson(peer, outgoing);
      }
    }
  }

  webSocketClose(webSocket) {
    const attachment = this._attachment(webSocket);
    if (attachment?.player_id) {
      const record = this.players.get(attachment.player_id);
      if (record?.relay_session === attachment.relay_session) this.players.delete(attachment.player_id);
      for (const peer of this.state.getWebSockets()) {
        if (peer !== webSocket && this._attachment(peer)?.authenticated) {
          sendJson(peer, { type: "player_left", player_id: attachment.player_id, relay_session: attachment.relay_session });
        }
      }
    }
    try {
      webSocket.close();
    } catch {
      // Already closed.
    }
  }

  webSocketError(webSocket) {
    try {
      webSocket.close();
    } catch {
      // Nothing else is needed; stored state expires automatically.
    }
  }
}
