from ext.datatypes import *
from functions import memfuncs


def is_valid_address(address):
	return address is not None and 0x10000 < address < 0x7FFFFFFFFFFF


def RadarHack_Update(processHandle, clientBaseAddress, Offsets):
	"""Force every enemy player to show as spotted on the radar."""
	try:
		localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
		if not localPawn:
			return
		localTeam = memfuncs.ProcMemHandler.ReadInt(processHandle, localPawn + Offsets.offset.m_iTeamNum)
		EntityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
		if not EntityList:
			return

		for i in range(64):
			try:
				ListEntry = memfuncs.ProcMemHandler.ReadPointer(processHandle, EntityList + (8 * (i & 0x7FFF) >> 9) + 16)
				if not ListEntry:
					continue

				controller = memfuncs.ProcMemHandler.ReadPointer(processHandle, ListEntry + 112 * (i & 0x1FF))
				if not controller:
					continue

				pawnHandle = memfuncs.ProcMemHandler.ReadInt(processHandle, controller + Offsets.offset.m_hPlayerPawn)
				if pawnHandle == 0:
					continue

				ListEntry2 = memfuncs.ProcMemHandler.ReadPointer(processHandle, EntityList + 0x8 * ((pawnHandle & 0x7FFF) >> 9) + 0x10)
				if not ListEntry2:
					continue

				pawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, ListEntry2 + 0x70 * (pawnHandle & 0x1FF))
				if not pawn or pawn == localPawn:
					continue

				team = memfuncs.ProcMemHandler.ReadInt(processHandle, pawn + Offsets.offset.m_iTeamNum)
				if team == localTeam or team < 2:
					continue

				spottedState = pawn + Offsets.offset.m_entitySpottedState
				memfuncs.ProcMemHandler.WriteBool(processHandle, spottedState + Offsets.offset.m_bSpotted, True)
				memfuncs.ProcMemHandler.WriteUInt(processHandle, spottedState + Offsets.offset.m_bSpottedByMask, 0xFFFFFFFF)
			except Exception:
				continue
	except Exception:
		pass
