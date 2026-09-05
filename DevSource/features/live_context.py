"""Read-only identity checks. These reject stale snapshots, not lock engine objects."""
from dataclasses import dataclass
from functions.memfuncs import ProcMemHandler as mem


def valid_pointer(value):
    return isinstance(value, int) and 0x10000 < value < 0x7FFFFFFFFFFF


def resolve(process, entity_list, handle):
    if not valid_pointer(entity_list) or not handle or (handle & 0xFFFFFFFF) == 0xFFFFFFFF:
        return 0
    chunk = mem.ReadPointer(process, entity_list + 8 * ((handle & 0x7FFF) >> 9) + 16)
    if not valid_pointer(chunk):
        return 0
    entity = mem.ReadPointer(process, chunk + 112 * (handle & 511))
    return entity if valid_pointer(entity) else 0


@dataclass(frozen=True)
class LiveContext:
    rules: int
    entities: int
    controller: int
    pawn: int
    handle: int

    def current(self, process, client, offsets):
        return read_context(process, client, offsets) == self


def read_context(process, client, offsets):
    """Return a living, controller-matched local pawn, or None on transition/error."""
    try:
        if not valid_pointer(client):
            return None
        # Main/FOV workers attach their current engine module to the snapshot.
        # Reject sign-off before touching otherwise still-readable pawn memory.
        engine = getattr(offsets, "_engine_base", None)
        if engine is not None:
            if not valid_pointer(engine):
                return None
            network = mem.ReadPointer(process, engine + offsets.dwNetworkGameClient)
            if not valid_pointer(network) or mem.ReadInt(process, network + offsets.dwNetworkGameClient_signOnState) != 6:
                return None
        rules = mem.ReadPointer(process, client + offsets.dwGameRules)
        entities = mem.ReadPointer(process, client + offsets.dwEntityList)
        controller = mem.ReadPointer(process, client + offsets.dwLocalPlayerController)
        pawn = mem.ReadPointer(process, client + offsets.dwLocalPlayerPawn)
        if not all(map(valid_pointer, (rules, entities, controller, pawn))):
            return None
        handle = mem.ReadUInt(process, controller + offsets.m_hPlayerPawn)
        if resolve(process, entities, handle) != pawn:
            return None
        if mem.ReadInt(process, pawn + offsets.m_iHealth) <= 0:
            return None
        if mem.ReadBytes(process, pawn + offsets.m_lifeState, 1) != b"\x00":
            return None
        return LiveContext(rules, entities, controller, pawn, handle)
    except Exception:
        return None
