from ext.datatypes import *

from functions import memfuncs
from functions import calculations
from functions import gameinput

import globals
import win32api, win32gui
import time

WEAPON_NAMES = {
	1: "Desert Eagle", 2: "Dual Berettas", 3: "Five-SeveN", 4: "Glock-18",
	7: "AK-47", 8: "AUG", 9: "AWP", 10: "FAMAS", 11: "G3SG1",
	13: "M249", 16: "M4A4", 17: "MAC-10", 19: "P90",
	23: "MP5-SD", 24: "UMP-45", 25: "XM1014", 26: "PP-Bizon", 27: "MAG-7",
	28: "Negev", 29: "Sawed-Off", 30: "Tec-9", 32: "P2000", 33: "MP7",
	34: "MP9", 35: "Nova", 36: "P250", 38: "SCAR-20", 39: "SG 553",
	40: "SSG 08", 42: "Knife", 59: "Knife", 60: "M4A1-S", 61: "USP-S", 63: "CZ75-Auto",
	64: "R8 Revolver",
	43: "Flashbang", 44: "HE Grenade", 45: "Smoke Grenade",
	46: "Molotov", 47: "Decoy Grenade", 48: "Incendiary Grenade",
}

def get_current_weapon_name(processHandle, clientBaseAddress, localPlayer, Offsets):
	"""Read the local player's active weapon name. Returns None on failure."""
	try:
		weapon_services = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPlayer + Offsets.offset.m_pWeaponServices)
		if not weapon_services:
			return None
		weapon_handle = memfuncs.ProcMemHandler.ReadInt(processHandle, weapon_services + Offsets.offset.m_hActiveWeapon)
		if not weapon_handle:
			return None
		entityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
		list_entry = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityList + 0x8 * ((weapon_handle & 0x7FFF) >> 9) + 0x10)
		weapon_entity = memfuncs.ProcMemHandler.ReadPointer(processHandle, list_entry + 0x70 * (weapon_handle & 0x1FF))
		if not weapon_entity:
			return None
		# m_AttributeManager (C_EconEntity) and m_Item (C_AttributeContainer) are INLINE
		# objects, not pointers, so add their offsets directly to reach m_iItemDefinitionIndex.
		item_def_index = memfuncs.ProcMemHandler.ReadUShort(processHandle, weapon_entity + Offsets.offset.m_AttributeManager + Offsets.offset.m_Item + Offsets.offset.m_iItemDefinitionIndex)
		return WEAPON_NAMES.get(item_def_index, f"Unknown({item_def_index})")
	except Exception:
		return None

_last_tap_time = 0.0
_reaction_done = False
_reaction_deadline = 0.0
_last_known_weapon = None

def Triggerbot_AntiFlash_Update(processHandle, clientBaseAddress, Offsets, Options):
	global _last_tap_time, _reaction_done, _reaction_deadline, _last_known_weapon
	localPlayer = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
	if (not localPlayer): return

	try:
		if Options["EnableAntiFlashbang"]:
			memfuncs.ProcMemHandler.WriteFloat(processHandle, localPlayer + Offsets.offset.m_flFlashMaxAlpha, 0.0)
		else:
			memfuncs.ProcMemHandler.WriteFloat(processHandle, localPlayer + Offsets.offset.m_flFlashMaxAlpha, 255.0)

		weapon_name = get_current_weapon_name(processHandle, clientBaseAddress, localPlayer, Offsets)
		if weapon_name and weapon_name != _last_known_weapon:
			_last_known_weapon = weapon_name
			if Options.get("CurrentWeapon", "") != weapon_name:
				Options["CurrentWeapon"] = weapon_name

		key_held = (win32api.GetAsyncKeyState(Options["TriggerbotKey"]) or not Options["EnableTriggerbotKeyCheck"])

		if not key_held:
			_reaction_done = False
		elif (win32gui.GetWindowText(win32gui.GetForegroundWindow()) == "Counter-Strike 2" and Options["EnableTriggerbot"]):
			localPlayerID = memfuncs.ProcMemHandler.ReadInt(processHandle, localPlayer + Offsets.offset.m_iIDEntIndex)
			if (localPlayerID > 0):
				entityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
				entityListEntry = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityList + 0x8 * (localPlayerID >> 9) + 0x10)
				TargetEntity = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityListEntry + 112 * (localPlayerID & 0x1FF))

				TargetEntityTeam = memfuncs.ProcMemHandler.ReadInt(processHandle, TargetEntity + Offsets.offset.m_iTeamNum)
				localPlayerTeam = memfuncs.ProcMemHandler.ReadInt(processHandle, localPlayer + Offsets.offset.m_iTeamNum)

				if not Options["EnableTriggerbotTeamCheck"] or TargetEntityTeam != localPlayerTeam:
					TargetEntityHP = memfuncs.ProcMemHandler.ReadInt(processHandle, TargetEntity + Offsets.offset.m_iHealth)
					if (TargetEntityHP > 0):
						if Options.get("EnableSimulatedReactionTime", False) and Options.get("AffectTriggerbotReaction", True):
							now = time.monotonic()
							if not _reaction_done:
								_reaction_done = True
								_reaction_deadline = now + float(Options.get("ReactionTime", 250)) / 1000.0
							if now < _reaction_deadline:
								return
						interval = float(Options.get("TriggerbotTapInterval", 0.0))
						if Options.get("EnablePerWeaponTapTimes", False) and weapon_name:
							saved = dict(Options.get("WeaponTapTimes", {})).get(weapon_name)
							if saved is not None:
								interval = float(saved)
						if interval <= 0.0:
							if not win32api.GetAsyncKeyState(0x01):
								gameinput.LeftClick()
						else:
							now = time.monotonic()
							if (now - _last_tap_time) >= interval and not win32api.GetAsyncKeyState(0x01):
								gameinput.LeftClick()
								_last_tap_time = now
	except:
		pass
