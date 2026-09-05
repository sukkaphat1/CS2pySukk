"""Bounded radar updates; no work while disabled, no unchanged field writes."""
import time
from functions.memfuncs import ProcMemHandler as mem
from features.live_context import read_context, resolve

_next_poll = 0.0
POLL_SECONDS = 0.1


def RadarHack_Update(process, client, Offsets, Options):
    global _next_poll
    if not Options.get("EnableRadarHack", False):
        _next_poll = 0.0
        return
    now = time.monotonic()
    if now < _next_poll:
        return
    _next_poll = now + POLL_SECONDS
    try:
        o = Offsets.offset
        context = read_context(process, client, o)
        if context is None:
            return
        local_team = mem.ReadInt(process, context.pawn + o.m_iTeamNum)
        for slot in range(1, 65):
            try:
                controller = resolve(process, context.entities, slot)
                if not controller or controller == context.controller:
                    continue
                handle = mem.ReadUInt(process, controller + o.m_hPlayerPawn)
                pawn = resolve(process, context.entities, handle)
                if not pawn or pawn == context.pawn:
                    continue
                team = mem.ReadInt(process, pawn + o.m_iTeamNum)
                if team == local_team or team not in (2, 3) or mem.ReadInt(process, pawn + o.m_iHealth) <= 0:
                    continue
                if mem.ReadBytes(process, pawn + o.m_lifeState, 1) != b"\x00":
                    continue
                spotted = pawn + o.m_entitySpottedState
                flag = mem.ReadBool(process, spotted + o.m_bSpotted)
                mask = mem.ReadUInt(process, spotted + o.m_bSpottedByMask)
                if flag and mask == 0xFFFFFFFF:
                    continue
                if not context.current(process, client, o):
                    return
                if (mem.ReadUInt(process, controller + o.m_hPlayerPawn) != handle or
                    resolve(process, context.entities, handle) != pawn):
                    continue
                if not flag:
                    mem.WriteBool(process, spotted + o.m_bSpotted, True)
                if mask != 0xFFFFFFFF:
                    mem.WriteUInt(process, spotted + o.m_bSpottedByMask, 0xFFFFFFFF)
            except Exception:
                continue
    except Exception:
        return
