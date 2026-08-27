from ext.datatypes import *

from functions import memfuncs
from functions import calculations
from functions import gameinput

import globals
import win32api, win32gui
import time

_last_tap_time = 0.0
_interval_logged = False

def Triggerbot_AntiFlash_Update(processHandle, clientBaseAddress, Offsets, Options):
	global _last_tap_time, _interval_logged
	localPlayer = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
	if (not localPlayer): return

	try:
		if Options["EnableAntiFlashbang"]:
			memfuncs.ProcMemHandler.WriteFloat(processHandle, localPlayer + Offsets.offset.m_flFlashMaxAlpha, 0.0)
			return
		else:
			memfuncs.ProcMemHandler.WriteFloat(processHandle, localPlayer + Offsets.offset.m_flFlashMaxAlpha, 255.0)

		if (win32gui.GetWindowText(win32gui.GetForegroundWindow()) == "Counter-Strike 2" and Options["EnableTriggerbot"] and (win32api.GetAsyncKeyState(Options["TriggerbotKey"]) or not Options["EnableTriggerbotKeyCheck"])):
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
						interval = float(Options.get("TriggerbotTapInterval", 0.0))
						if not _interval_logged:
							_interval_logged = True
							print(f"[Triggerbot] Tap Fire Interval = {interval} (0 = hold)")
						if interval <= 0.0:
							if not win32api.GetAsyncKeyState(0x01):
								gameinput.LeftClick()
						else:
							now = time.monotonic()
							if (now - _last_tap_time) >= interval and not win32api.GetAsyncKeyState(0x01):
								print(f"[Triggerbot] TAP fired, gap={now - _last_tap_time:.2f}s")
								gameinput.LeftClick()
								_last_tap_time = now
	except:
		pass