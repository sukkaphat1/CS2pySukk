from ext.datatypes import *

from functions import memfuncs
from functions import calculations
from functions import gameinput

import globals
import win32api, win32gui

def FovChangerThreadFunction(Options, Offsets):

	processHandle = memfuncs.GetProcess("cs2.exe")
	clientBaseAddress = memfuncs.GetModuleBase(modulename="client.dll", process_object=processHandle)

	while True:
		localPlayer = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
		if (not localPlayer): continue

		try:
			cameraServices = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPlayer + Offsets.offset.m_pCameraServices)
			currentFOV = memfuncs.ProcMemHandler.ReadInt(processHandle, cameraServices + Offsets.offset.m_iFOV)
			isScopedDown = memfuncs.ProcMemHandler.ReadBool(processHandle, localPlayer + Offsets.offset.m_bIsScoped)

			if isScopedDown:
				pass  
			else:
				if Options["EnableFovChanger"]:
					desiredFov = Options["FovChangeSize"]
				else:
					desiredFov = 90

				if currentFOV != desiredFov:
					memfuncs.ProcMemHandler.WriteInt(processHandle, cameraServices + Offsets.offset.m_iFOV, desiredFov)

		except:
			pass