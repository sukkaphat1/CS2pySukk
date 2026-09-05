
from ext.datatypes import *
from functions import memfuncs
from features.live_context import read_context
import globals
import win32api
import time


def Bhop_Update(processHandle, clientBaseAddress, Offsets, Options):
    if not Options.get("EnableBhop", False):
        return
    try:
        context = read_context(processHandle, clientBaseAddress, Offsets.offset)
        if context is None:
            return
        localPlayer = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerController)
        if not localPlayer:
            return

        localPawn = memfuncs.ProcMemHandler.ReadInt(processHandle, localPlayer + Offsets.offset.m_hPlayerPawn)
        if not localPawn:
            return

        entityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
        listEntry = memfuncs.ProcMemHandler.ReadPointer(processHandle, entityList + (0x8 * ((localPawn & 0x7FFF) >> 9) + 0x10))
        localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, listEntry + (112 * (localPawn & 0x1FF)))
        
        if localPawn:
            flags = memfuncs.ProcMemHandler.ReadInt(processHandle, localPawn + Offsets.offset.m_fFlags)
            if win32api.GetAsyncKeyState(0x20) and flags & (1 << 0) and context.current(processHandle, clientBaseAddress, Offsets.offset):
                memfuncs.ProcMemHandler.WriteInt(processHandle, clientBaseAddress + Offsets.offset.ButtonJump, 65537)
                time.sleep(0.01)
                if context.current(processHandle, clientBaseAddress, Offsets.offset):
                    memfuncs.ProcMemHandler.WriteInt(processHandle, clientBaseAddress + Offsets.offset.ButtonJump, 256)
    except Exception:
        return
