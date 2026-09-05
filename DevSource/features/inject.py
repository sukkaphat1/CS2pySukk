"""DLL injection for the internal skin changer.

CS2's anti-tamper blocks unsigned DLL injection through the normal loader
(LoadLibraryA/LdrLoadDll report fake success but never load the module), so we
do NOT use LoadLibrary. Instead we manually map the DLL:

  1. parse the PE headers,
  2. allocate memory in cs2.exe (PAGE_READWRITE),
  3. copy headers + sections,
  4. apply base relocations,
  5. resolve the (kernel32-only) import table,
  6. mark the image executable,
  7. run a small stub that calls DllMain(base, DLL_PROCESS_ATTACH, NULL).

The DLL is built CRT-free (see dll/skinchanger.cpp), so it has no C++ runtime
that would break under manual mapping. Idempotent per process.

In a frozen (PyInstaller onefile) build the DLL lives inside the exe and is
extracted to a _MEIPASS temp folder at runtime. We mirror it to a stable
writable location first and map from there.
"""
import ctypes
import os
import shutil
import struct
import sys
import time
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
_PAGE_READONLY = 0x02
_PAGE_READWRITE = 0x04
_PAGE_WRITECOPY = 0x08
_PAGE_EXECUTE_READ = 0x20
_PAGE_EXECUTE_READWRITE = 0x40
_MEM_RELEASE = 0x8000
_IMAGE_REL_BASED_HIGHLOW = 3
_IMAGE_REL_BASED_DIR64 = 10
_ORDINAL_FLAG64 = 1 << 63
_IMAGE_SCN_MEM_EXECUTE = 0x20000000
_IMAGE_SCN_MEM_READ = 0x40000000
_IMAGE_SCN_MEM_WRITE = 0x80000000


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


# ---- PE parsing ---------------------------------------------------------

def _parse_pe(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("not a PE file")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("bad NT signature")
    filehdr = e_lfanew + 4
    machine = struct.unpack_from("<H", data, filehdr)[0]
    if machine != 0x8664:
        raise ValueError("not x64 PE")
    num_sections = struct.unpack_from("<H", data, filehdr + 2)[0]
    size_opt = struct.unpack_from("<H", data, filehdr + 16)[0]
    opt = filehdr + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x20B:
        raise ValueError("not PE32+")
    entry_rva = struct.unpack_from("<I", data, opt + 16)[0]
    image_base = struct.unpack_from("<Q", data, opt + 24)[0]
    size_of_image = struct.unpack_from("<I", data, opt + 56)[0]
    size_of_headers = struct.unpack_from("<I", data, opt + 60)[0]
    num_dirs = struct.unpack_from("<I", data, opt + 108)[0]
    dirs = opt + 112
    import_rva, import_size = struct.unpack_from("<II", data, dirs + 8)
    reloc_rva, reloc_size = struct.unpack_from("<II", data, dirs + 40)

    sections = []
    sec = opt + size_opt
    for i in range(num_sections):
        s = sec + i * 40
        name = data[s:s + 8].rstrip(b"\x00").decode("latin1", "replace")
        vsize = struct.unpack_from("<I", data, s + 8)[0]
        vaddr = struct.unpack_from("<I", data, s + 12)[0]
        rawsize = struct.unpack_from("<I", data, s + 16)[0]
        rawptr = struct.unpack_from("<I", data, s + 20)[0]
        char = struct.unpack_from("<I", data, s + 36)[0]
        sections.append((name, vaddr, vsize, rawptr, rawsize, char))

    return {
        "entry_rva": entry_rva,
        "image_base": image_base,
        "size_of_image": size_of_image,
        "size_of_headers": size_of_headers,
        "import_rva": import_rva,
        "import_size": import_size,
        "reloc_rva": reloc_rva,
        "reloc_size": reloc_size,
        "sections": sections,
    }


def _read_cstr(buf, off):
    if off < 0 or off >= len(buf):
        return b""
    end = buf.find(b"\x00", off)
    if end == -1:
        end = len(buf)
    return bytes(buf[off:end])


def _build_image(pe, data):
    size = pe["size_of_image"]
    img = bytearray(size)
    sh = pe["size_of_headers"]
    img[:sh] = data[:sh]
    for _, vaddr, vsize, rawptr, rawsize, _char in pe["sections"]:
        if rawsize and rawptr + rawsize <= len(data):
            chunk = data[rawptr:rawptr + rawsize]
            end = min(vaddr + len(chunk), size)
            if vaddr < size:
                img[vaddr:end] = chunk[:end - vaddr]
    return img


def _apply_relocs(img, pe, delta):
    if not delta:
        return
    rva = pe["reloc_rva"]
    size = pe["reloc_size"]
    if not rva or not size:
        return
    off = 0
    while off + 8 <= size:
        base_rva = rva + off
        if base_rva + 8 > len(img):
            break
        page = struct.unpack_from("<I", img, base_rva)[0]
        blk = struct.unpack_from("<I", img, base_rva + 4)[0]
        if blk == 0:
            break
        if off + blk > size or blk < 8:
            break
        count = (blk - 8) // 2
        for i in range(count):
            e = struct.unpack_from("<H", img, base_rva + 8 + i * 2)[0]
            typ = e >> 12
            rel = e & 0xFFF
            addr = page + rel
            if typ == _IMAGE_REL_BASED_HIGHLOW and addr + 4 <= len(img):
                val = struct.unpack_from("<I", img, addr)[0]
                struct.pack_into("<I", img, addr, (val + delta) & 0xFFFFFFFF)
            elif typ == _IMAGE_REL_BASED_DIR64 and addr + 8 <= len(img):
                val = struct.unpack_from("<Q", img, addr)[0]
                struct.pack_into("<Q", img, addr, (val + delta) & 0xFFFFFFFFFFFFFFFF)
        off += blk


def _resolve_imports(img, pe, get_proc_addr, get_module_base):
    """Patch the import address table in-place.

    get_proc_addr(module_base, name_bytes_or_ordinal) -> int address in OUR
    process; the caller supplies a delta-adjusted resolver.
    """
    rva = pe["import_rva"]
    if not rva:
        return
    i = 0
    while True:
        desc = rva + i * 20
        if desc + 20 > len(img):
            break
        oft, ts, fc, name_rva, first_thunk = struct.unpack_from("<IIIII", img, desc)
        if oft == 0 and ts == 0 and fc == 0 and name_rva == 0 and first_thunk == 0:
            break
        dll_name = _read_cstr(img, name_rva).decode("latin1", "replace")
        mod_base = get_module_base(dll_name)
        thunk_rva = oft if oft else first_thunk
        if not thunk_rva:
            i += 1
            continue
        j = 0
        while True:
            t = thunk_rva + j * 8
            if t + 8 > len(img):
                break
            entry = struct.unpack_from("<Q", img, t)[0]
            if entry == 0:
                break
            if entry & _ORDINAL_FLAG64:
                addr = get_proc_addr(mod_base, entry & 0xFFFF)
            else:
                name_off = entry & 0x7FFFFFFF
                fname = _read_cstr(img, name_off + 2)
                addr = get_proc_addr(mod_base, fname)
            if addr:
                iat = first_thunk + j * 8
                if iat + 8 <= len(img):
                    struct.pack_into("<Q", img, iat, addr & 0xFFFFFFFFFFFFFFFF)
            j += 1
        i += 1


def _section_protection(char):
    """Translate a PE section Characteristics word to a Windows protection."""
    x = bool(char & _IMAGE_SCN_MEM_EXECUTE)
    r = bool(char & _IMAGE_SCN_MEM_READ)
    w = bool(char & _IMAGE_SCN_MEM_WRITE)
    if x and r and w:
        return _PAGE_EXECUTE_READWRITE
    if x and r:
        return _PAGE_EXECUTE_READ
    if r and w:
        return _PAGE_READWRITE
    if w:
        return _PAGE_WRITECOPY
    return _PAGE_READONLY


def _make_stub(entry, base):
    """x64 stub that calls DllMain(base, DLL_PROCESS_ATTACH=1, NULL)."""
    return (
        b"\x48\x83\xEC\x28"                                          # sub rsp, 0x28
        + b"\x48\xB9" + struct.pack("<Q", base)                      # mov rcx, base
        + b"\x48\xBA" + struct.pack("<Q", 1)                         # mov rdx, 1
        + b"\x49\xC7\xC0\x00\x00\x00\x00"                            # mov r8, 0
        + b"\x48\xB8" + struct.pack("<Q", entry)                     # mov rax, entry
        + b"\xFF\xD0"                                                # call rax
        + b"\x48\x83\xC4\x28"                                        # add rsp, 0x28
        + b"\xC3"                                                    # ret
    )


# ---- log verification ---------------------------------------------------

def _dll_log_size():
    try:
        return os.path.getsize(os.path.join(os.path.expanduser("~"), "cs2py_dll.log"))
    except OSError:
        return 0


def _read_dll_log_from(offset):
    try:
        log = os.path.join(os.path.expanduser("~"), "cs2py_dll.log")
        with open(log, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except Exception:
        return ""


# ---- injection ----------------------------------------------------------

_last_attempt = 0.0
_RETRY_INTERVAL = 3.0


def _kernel32_api(kernel32):
    VirtualAllocEx = kernel32.VirtualAllocEx
    VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    VirtualAllocEx.restype = ctypes.c_void_p
    VirtualProtectEx = kernel32.VirtualProtectEx
    VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    VirtualProtectEx.restype = wintypes.BOOL
    WriteProcessMemory = kernel32.WriteProcessMemory
    WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    WriteProcessMemory.restype = wintypes.BOOL
    CreateRemoteThread = kernel32.CreateRemoteThread
    CreateRemoteThread.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    CreateRemoteThread.restype = wintypes.HANDLE
    GetProcAddress = kernel32.GetProcAddress
    GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
    GetProcAddress.restype = ctypes.c_void_p
    return VirtualAllocEx, VirtualProtectEx, WriteProcessMemory, CreateRemoteThread, GetProcAddress


def inject_skinchanger(processHandle):
    """Manually map skinchanger.dll into the given pymem process. Returns bool."""
    global _injected_pid, _last_attempt
    try:
        pid = getattr(processHandle, "process_id", None)
        if _injected_pid == pid:
            return True

        now = time.monotonic()
        if now - _last_attempt < _RETRY_INTERVAL:
            return False
        _last_attempt = now

        path = _dll_path()
        if not os.path.exists(path):
            _log(f"inject: DLL not found: {path}")
            return False
        with open(path, "rb") as f:
            data = f.read()
        _log(f"inject: mapping {path} ({len(data)} bytes)")

        pe = _parse_pe(data)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        va, vp, wpm, crt, gpa = _kernel32_api(kernel32)
        hproc = processHandle.process_handle

        # Resolve the target's kernel32 base so we can rebase our import
        # addresses (kernel32 is ASLR'd but at the same base in every process
        # on this boot session; still, compute the delta to be exact).
        from pymem.process import module_from_name
        target_k32 = module_from_name(hproc, "kernel32.dll")
        our_k32_base = kernel32._handle
        delta = target_k32.lpBaseOfDll - our_k32_base

        def resolve_in_ours(mod_base, name_or_ord):
            if isinstance(name_or_ord, int):
                # ordinal: MAKEINTRESOURCE
                return gpa(mod_base, ctypes.cast(ctypes.c_void_p(name_or_ord), ctypes.c_char_p)) or 0
            return gpa(mod_base, ctypes.c_char_p(name_or_ord)) or 0

        def module_base_in_ours(dll_name):
            try:
                return ctypes.WinDLL(dll_name)._handle
            except Exception:
                return 0

        img = _build_image(pe, data)
        _apply_relocs(img, pe, delta)
        _resolve_imports(img, pe, resolve_in_ours, module_base_in_ours)

        size = pe["size_of_image"]
        base = va(hproc, None, size, _MEM_COMMIT | _MEM_RESERVE, _PAGE_READWRITE)
        if not base:
            _log(f"inject: VirtualAllocEx(image) failed, last error {ctypes.get_last_error()}")
            return False

        buf = (ctypes.c_char * len(img)).from_buffer_copy(bytes(img))
        if not wpm(hproc, base, buf, len(img), None):
            _log(f"inject: WriteProcessMemory(image) failed, last error {ctypes.get_last_error()}")
            return False

        old = wintypes.DWORD(0)
        # Set per-section protection: .text must be executable, .data/BSS must
        # be writable (the DLL writes its config/log paths and skin list there),
        # and the rest read-only. This avoids an RWX region, which some
        # anti-tamper code treats as suspicious.
        for _name, vaddr, vsize, _rawptr, _rawsize, char in pe["sections"]:
            prot = _section_protection(char)
            if vaddr < size:
                seg_end = min(vaddr + max(vsize, 1), size)
                if not vp(hproc, base + vaddr, seg_end - vaddr, prot, ctypes.byref(old)):
                    _log(f"inject: VirtualProtectEx({_name}) failed, last error {ctypes.get_last_error()}")

        entry = base + pe["entry_rva"]
        stub = _make_stub(entry, base)
        stub_addr = va(hproc, None, len(stub), _MEM_COMMIT | _MEM_RESERVE, _PAGE_READWRITE)
        if not stub_addr:
            _log(f"inject: VirtualAllocEx(stub) failed, last error {ctypes.get_last_error()}")
            return False
        stub_buf = (ctypes.c_char * len(stub)).from_buffer_copy(stub)
        if not wpm(hproc, stub_addr, stub_buf, len(stub), None):
            _log(f"inject: WriteProcessMemory(stub) failed, last error {ctypes.get_last_error()}")
            return False
        if not vp(hproc, stub_addr, len(stub), _PAGE_EXECUTE_READ, ctypes.byref(old)):
            _log(f"inject: VirtualProtectEx(stub) failed, last error {ctypes.get_last_error()}")

        log_offset = _dll_log_size()
        thread = crt(hproc, None, 0, stub_addr, None, 0, None)
        if not thread:
            _log(f"inject: CreateRemoteThread failed, last error {ctypes.get_last_error()}")
            return False
        kernel32.WaitForSingleObject(thread, 5000)

        GetExitCodeThread = kernel32.GetExitCodeThread
        GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        GetExitCodeThread.restype = wintypes.BOOL
        exit_code = wintypes.DWORD(0)
        GetExitCodeThread(thread, ctypes.byref(exit_code))
        kernel32.CloseHandle(thread)

        # Give the loop thread a moment to log client.dll resolution.
        time.sleep(0.4)
        new_log = _read_dll_log_from(log_offset)

        if exit_code.value != 1:
            _log(f"inject: entry point exit code {hex(exit_code.value)} (expected 1)")
            return False
        if "attach" not in new_log and "loop: client.dll" not in new_log:
            _log(f"inject: entry ran (exit 1) but DllMain did not log attach; tail={new_log[-200:]!r}")
            return False

        _injected_pid = pid
        _log(f"inject: ok, manually mapped at base {hex(base)}")
        return True
    except Exception as e:
        _log(f"inject error: {e}")
        return False
