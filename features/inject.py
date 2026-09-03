"""DLL injection for the internal skin changer.

Injects dll/skinchanger.dll into cs2.exe via LoadLibrary + CreateRemoteThread.
The DLL does the actual skin application in-process (the only way CS2 renders
client-side skins). Idempotent per process.

In a frozen (PyInstaller onefile) build the DLL lives inside the exe and is
extracted to a _MEIPASS temp folder at runtime. Injecting straight from that
temp folder is unreliable (temp folders can be cleaned up, and LoadLibraryA can
reject the path), so we mirror the DLL to a stable writable location first and
inject from there.
"""
import ctypes
import os
import shutil
import sys
from ctypes import wintypes

from ext import paths

_injected_pid = None
_DLL_NAME = "skinchanger.dll"


def _log(msg):
    # Show status in the cheat console AND record it to the debug log.
    try:
        print(f"[skin-changer] {msg}", flush=True)
    except Exception:
        pass
    try:
        with open(os.path.join(os.path.expanduser("~"), "cs2py_skin_debug.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

_MEM_COMMIT = 0x1000
_MEM_RESERVE = 0x2000
_PAGE_READWRITE = 0x04


def _dll_path():
    """Return the DLL path to inject, mirroring it out of _MEIPASS if frozen."""
    src = paths.resolve_data(os.path.join("dll", _DLL_NAME))
    if not src:
        return os.path.join(os.getcwd(), "dll", _DLL_NAME)
    if not getattr(sys, "frozen", False):
        return src
    # Frozen: copy the bundled DLL to a stable path next to the other runtime
    # files (USERPROFILE) so injection never depends on the _MEIPASS temp dir.
    dst = os.path.join(os.path.expanduser("~"), _DLL_NAME)
    try:
        need_copy = True
        if os.path.exists(dst):
            try:
                need_copy = os.path.getsize(dst) != os.path.getsize(src)
            except OSError:
                need_copy = True
        if need_copy:
            shutil.copyfile(src, dst)
            _log(f"dll: mirrored bundle to {dst} ({os.path.getsize(dst)} bytes)")
        return dst
    except Exception as e:
        _log(f"dll: mirror to {dst} failed ({e}); using bundle path {src}")
        return src


def inject_skinchanger(processHandle):
    """Inject skinchanger.dll into the given pymem process. Returns bool."""
    global _injected_pid
    try:
        pid = getattr(processHandle, "process_id", None)
        if _injected_pid == pid:
            return True

        path = _dll_path()
        if not os.path.exists(path):
            _log(f"inject: DLL not found: {path}")
            return False

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        VirtualAllocEx = kernel32.VirtualAllocEx
        VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        VirtualAllocEx.restype = ctypes.c_void_p
        WriteProcessMemory = kernel32.WriteProcessMemory
        WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        WriteProcessMemory.restype = wintypes.BOOL
        CreateRemoteThread = kernel32.CreateRemoteThread
        CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        CreateRemoteThread.restype = wintypes.HANDLE

        hproc = processHandle.process_handle

        path_bytes = path.encode("utf-8") + b"\x00"
        buf = ctypes.create_string_buffer(path_bytes)
        addr = VirtualAllocEx(hproc, None, len(path_bytes), _MEM_COMMIT | _MEM_RESERVE, _PAGE_READWRITE)
        if not addr:
            _log(f"inject: VirtualAllocEx failed, last error {ctypes.get_last_error()}")
            return False
        if not WriteProcessMemory(hproc, addr, buf, len(path_bytes), None):
            _log(f"inject: WriteProcessMemory failed, last error {ctypes.get_last_error()}")
            return False

        # Address of LoadLibraryA (kernel32 is loaded at the same base in every process).
        loadlib = ctypes.cast(kernel32.LoadLibraryA, ctypes.c_void_p).value
        thread = CreateRemoteThread(hproc, None, 0, loadlib, addr, 0, None)
        if not thread:
            _log(f"inject: CreateRemoteThread failed, last error {ctypes.get_last_error()}")
            return False
        kernel32.WaitForSingleObject(thread, 5000)

        # LoadLibraryA returns the module handle, or NULL on failure. The remote
        # thread's exit code is that return value — verify it instead of blindly
        # reporting success.
        GetExitCodeThread = kernel32.GetExitCodeThread
        GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        GetExitCodeThread.restype = wintypes.BOOL
        exit_code = wintypes.DWORD(0)
        if not GetExitCodeThread(thread, ctypes.byref(exit_code)):
            kernel32.CloseHandle(thread)
            _log(f"inject: GetExitCodeThread failed, last error {ctypes.get_last_error()}")
            return False
        kernel32.CloseHandle(thread)

        if not exit_code.value:
            _log(f"inject: LoadLibraryA returned NULL (injection failed), exit 0, path={path}")
            return False

        # LoadLibraryA's exit code is non-zero, but verify the module is actually
        # resident in the target before trusting it. A non-zero exit code can be
        # a false positive (e.g. the DLL failed DllMain and was unloaded).
        try:
            from pymem.process import module_from_name
            m = module_from_name(processHandle.process_handle, _DLL_NAME)
        except Exception:
            m = None
        if not m:
            _log(f"inject: LoadLibraryA returned {hex(exit_code.value)} but {_DLL_NAME} not resident (DllMain failed?)")
            return False

        _injected_pid = pid
        _log(f"inject: ok, module base {hex(m.lpBaseOfDll)}")
        return True
    except Exception as e:
        _log(f"inject error: {e}")
        return False
