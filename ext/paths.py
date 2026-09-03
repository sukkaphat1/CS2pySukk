"""Runtime path resolution that works both from source and inside a PyInstaller exe.

When frozen, ``sys.executable`` is the exe path and ``sys._MEIPASS`` is the temp
folder PyInstaller extracts bundled data into. Writable runtime files (settings,
caches) live next to the exe; bundled read-only data is found in _MEIPASS, with
the exe directory and cwd as fallbacks so a source run keeps working unchanged.
"""
import os
import sys


def _frozen():
    return bool(getattr(sys, "frozen", False))


def writable_dir():
    """Directory for files the cheat writes at runtime (settings, caches)."""
    if _frozen():
        return os.path.dirname(sys.executable)
    return os.getcwd()


def bundle_dir():
    """Directory holding bundled PyInstaller data (read-only), else cwd."""
    return getattr(sys, "_MEIPASS", None) or os.getcwd()


def resolve_data(relpath):
    """Return the first existing path for a bundled data file.

    Search order: exe dir (so a user can drop an updated file next to the exe),
    _MEIPASS (bundled copy), then cwd (source run). Returns None if absent.
    """
    candidates = []
    if _frozen():
        candidates.append(os.path.join(os.path.dirname(sys.executable), relpath))
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), relpath))
    candidates.append(os.path.join(os.getcwd(), relpath))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None
