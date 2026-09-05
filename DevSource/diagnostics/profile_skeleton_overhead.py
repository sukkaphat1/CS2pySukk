"""Read-only microbenchmark: IPC and bone reads, without opening CS2 or drawing.

Run with the application's Python runtime. Results are overhead measurements,
not live game FPS, GPU rendering times, or a comparison with another computer.
"""
import ctypes
from dataclasses import fields
import json
import multiprocessing
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ext.offsets import Offset
from ext.datatypes import PLAYER_BONES
from functions.memfuncs import ProcMemHandler
import pymem.memory


def elapsed_us(action, count=400):
    results = []
    for _ in range(3):
        start = time.perf_counter()
        for _ in range(count):
            action()
        results.append((time.perf_counter() - start) * 1e6 / count)
    return round(statistics.median(results), 3)


def main():
    offset = Offset(**{field.name: 0 for field in fields(Offset)})
    local = SimpleNamespace(offset=offset)
    with multiprocessing.Manager() as manager:
        shared = manager.Namespace()
        shared.offset = offset
        options = manager.dict({"EnableESPSkeletonRendering": True})
        result = {
            "offset_fields_serialized_per_lookup": len(fields(Offset)),
            "local_offset_lookup_us": elapsed_us(lambda: local.offset.m_boneArray),
            "manager_offset_lookup_us": elapsed_us(lambda: shared.offset.m_boneArray),
            "manager_option_lookup_us": elapsed_us(lambda: options["EnableESPSkeletonRendering"]),
        }
    # Match the existing 17 separate ReadVec calls, using ONLY our own memory.
    data = ctypes.create_string_buffer(23 * 32)
    address = ctypes.addressof(data)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    proc = SimpleNamespace(read_bytes=lambda address, size: pymem.memory.read_bytes(handle, address, size))

    def bones():
        for index in PLAYER_BONES.values():
            ProcMemHandler.ReadVec(proc, address + index * 32)

    result["separate_bone_reads_per_player"] = len(PLAYER_BONES)
    result["seventeen_self_process_bone_reads_us"] = elapsed_us(bones)
    result["one_self_process_bone_block_read_us"] = elapsed_us(lambda: proc.read_bytes(address, len(data)))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
