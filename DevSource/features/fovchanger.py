import time
from types import SimpleNamespace
from functions import memfuncs
from features.live_context import read_context, valid_pointer


def FovChanger_Update(process, client, Offsets, Options):
    """One guarded pass; disabled never writes a default FOV."""
    if not Options.get("EnableFovChanger", False):
        return
    try:
        o = Offsets.offset
        context = read_context(process, client, o)
        if context is None:
            return
        camera = memfuncs.ProcMemHandler.ReadPointer(process, context.pawn + o.m_pCameraServices)
        if not valid_pointer(camera) or memfuncs.ProcMemHandler.ReadBool(process, context.pawn + o.m_bIsScoped):
            return
        desired = int(Options["FovChangeSize"])
        if not 1 <= desired <= 179:
            return
        if memfuncs.ProcMemHandler.ReadInt(process, camera + o.m_iFOV) != desired:
            if (context.current(process, client, o) and
                memfuncs.ProcMemHandler.ReadPointer(process, context.pawn + o.m_pCameraServices) == camera and
                not memfuncs.ProcMemHandler.ReadBool(process, context.pawn + o.m_bIsScoped)):
                memfuncs.ProcMemHandler.WriteInt(process, camera + o.m_iFOV, desired)
    except Exception:
        # A process/map can disappear between any two memory operations.
        return


def FovChangerThreadFunction(Options, Offsets):
    while True:
        if not Options.get("EnableFovChanger", False):
            time.sleep(0.1)
            continue
        process = None
        try:
            process = memfuncs.GetProcess("cs2.exe")
            # Reacquire periodically, rather than caching a module indefinitely.
            client = memfuncs.GetModuleBase("client.dll", process)
            snapshot = SimpleNamespace(offset=Offsets.offset)
            snapshot.offset._engine_base = memfuncs.GetModuleBase("engine2.dll", process) or 0
            for _ in range(20):
                FovChanger_Update(process, client, snapshot, Options)
                time.sleep(0.05)
        except Exception:
            time.sleep(0.25)
        finally:
            if process is not None:
                try:
                    process.close_process()
                except Exception:
                    pass
