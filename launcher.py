"""CS2py launcher.

A tiny bootstrapper that keeps the actual cheat source in a stable folder
(``Documents\\CS2pySukk``) and runs it from there. This is the reliable way to
launch cs2py: the internal skin changer DLL must be injected from a real folder
(not a PyInstaller temp dir), and the source-run layout is exactly what already
works.

Each launch the launcher:
  1. makes sure Python and Git are installed (downloads + silently installs the
     official installers next to this exe when they are missing),
  2. pulls the latest source from GitHub (git clone on first run, else git pull),
  3. verifies the local files match the remote version,
  4. installs/refreshes Python dependencies if needed,
  5. runs ``main.py`` from the Documents folder.

It is intentionally packaged as a tiny onefile exe with NO bundled data — the
source and DLL always come from Documents via git, so a new release never needs
a rebuilt launcher.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

REPO_URL = "https://github.com/sukkaphat1/CS2pySukk.git"
BRANCH = "main"
INSTALL_DIR = os.path.join(os.path.expanduser("~"), "Documents", "CS2pySukk")
MAIN_SCRIPT = "main.py"
REQUIREMENTS = "requirements.txt"
VERSION_FILE = "version.txt"

# Official installers, fetched on demand when a prerequisite is missing.
PYTHON_VERSION = "3.13.9"
PYTHON_INSTALLER = f"python-{PYTHON_VERSION}-amd64.exe"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_INSTALLER}"
PYTHON_LOCAL = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe")

GIT_INSTALLER = "Git-2.55.0.3-64-bit.exe"
GIT_URL = f"https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/{GIT_INSTALLER}"

# Resolved once at startup: command prefix for Python, path for git.exe.
_PY = None
_GIT = None


def log(msg=""):
    print(msg, flush=True)


def run(cmd, cwd=None):
    """Run a command, returning CompletedProcess. Never raises on nonzero."""
    return subprocess.run(cmd, cwd=cwd, shell=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _download(url, dest):
    """Download a file with a simple progress line. Returns True on success."""
    log(f"Downloading {os.path.basename(dest)} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cs2py-launcher/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    sys.stdout.write(f"\r  {pct}% ({done // 1048576} MB)   ")
                    sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True
    except Exception as e:
        log(f"[ERROR] download failed: {e}")
        return False


def _installer_path(name):
    """Place installers next to the exe (fall back to %TEMP% if not writable)."""
    d = _exe_dir()
    p = os.path.join(d, name)
    if not os.path.isdir(d):
        d = os.environ.get("TEMP", os.path.expanduser("~"))
        p = os.path.join(d, name)
    return p


def _find_python():
    """Return a command prefix for a working Python, or None."""
    for prefix in (["py", "-3"], ["python"], ["python3"]):
        if run(" ".join(prefix + ["--version"])).returncode == 0:
            return prefix
    for cand in (PYTHON_LOCAL,
                 os.path.expandvars(r"%ProgramFiles%\Python313\python.exe"),
                 r"C:\Python313\python.exe"):
        if os.path.isfile(cand):
            return [cand]
    return None


def _find_git():
    """Return a git.exe path (string) or None."""
    if run("git --version").returncode == 0:
        return "git"
    for cand in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
                 os.path.expandvars(r"%ProgramFiles%\Git\cmd\git.exe"),
                 os.path.expandvars(r"%ProgramFiles(x86)%\Git\cmd\git.exe")):
        if os.path.isfile(cand):
            return cand
    return None


def ensure_python():
    """Ensure a Python interpreter exists, installing one if necessary."""
    global _PY
    _PY = _find_python()
    if _PY:
        return True

    log("Python was not found.")
    p = _installer_path(PYTHON_INSTALLER)
    if not (os.path.isfile(p) and os.path.getsize(p) > 10 * 1024 * 1024) and not _download(PYTHON_URL, p):
        log("[ERROR] Could not download the Python installer.")
        log(f"Install Python manually from https://www.python.org/downloads/ (>= 3.10), then re-run.")
        return False

    log("Installing Python silently (per-user, with pip) ...")
    # /quiet + InstallAllUsers=0 = no admin, per-user install; Include_pip=1.
    r = run(f'"{p}" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=0 SimpleInstall=1')
    if r.returncode != 0:
        log(f"[WARN] Python installer returned {r.returncode}; checking result ...")

    _PY = _find_python()
    if _PY:
        log("Python installed successfully.")
        return True
    log("[ERROR] Python install did not produce a usable interpreter.")
    log(f"Run \"{p}\" manually, then re-launch.")
    return False


def ensure_git():
    """Ensure git.exe exists, installing Git for Windows if necessary."""
    global _GIT
    _GIT = _find_git()
    if _GIT:
        return True

    log("Git was not found.")
    p = _installer_path(GIT_INSTALLER)
    if not (os.path.isfile(p) and os.path.getsize(p) > 10 * 1024 * 1024) and not _download(GIT_URL, p):
        log("[ERROR] Could not download the Git installer.")
        log("Install Git manually from https://git-scm.com/download/win, then re-run.")
        return False

    log("Installing Git silently (per-user) ...")
    # Inno Setup: /VERYSILENT + /CURRENTUSER = no admin, no UI.
    r = run(f'"{p}" /VERYSILENT /NORESTART /NOCANCEL /SP- /CURRENTUSER /COMPONENTS="icons,assoc,assoc_sh"')
    if r.returncode != 0:
        log(f"[WARN] Git installer returned {r.returncode}; checking result ...")

    _GIT = _find_git()
    if _GIT:
        log("Git installed successfully.")
        return True
    log("[ERROR] Git install did not produce a usable git.exe.")
    log(f"Run \"{p}\" manually, then re-launch.")
    return False


def git_run(args, cwd=None):
    return run(f'"{_GIT}" {args}' if _GIT != "git" else f"{_GIT} {args}", cwd=cwd)


def ensure_cloned():
    """Clone the repo if the install dir is missing/empty, else return True."""
    if not os.path.isdir(INSTALL_DIR):
        log(f"First run: cloning {REPO_URL} ...")
        r = git_run(f"clone --depth 1 --branch {BRANCH} \"{REPO_URL}\" \"{INSTALL_DIR}\"")
        if r.returncode != 0:
            log(f"[ERROR] git clone failed:\n{r.stdout}")
            return False
        log("Clone complete.")
        return True
    if not os.path.isdir(os.path.join(INSTALL_DIR, ".git")):
        log(f"[ERROR] {INSTALL_DIR} exists but is not a git repository.")
        log("Move or delete it and re-run the launcher.")
        return False
    return True


def sync_and_verify():
    """git pull and verify version.txt matches the remote."""
    local_main = os.path.join(INSTALL_DIR, MAIN_SCRIPT)
    if not os.path.isfile(local_main):
        log(f"[ERROR] {MAIN_SCRIPT} missing after clone.")
        return None

    r = git_run(f"fetch origin {BRANCH}", cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] git fetch failed (offline?):\n{r.stdout}")
    r = git_run(f"reset --hard origin/{BRANCH}", cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] git reset failed:\n{r.stdout}")

    local_v = _read_version()
    r = git_run(f"show origin/{BRANCH}:{VERSION_FILE}", cwd=INSTALL_DIR)
    remote_v = (r.stdout or "").strip()
    if remote_v:
        if local_v and local_v != remote_v:
            log(f"[WARN] version mismatch: local {local_v}, remote {remote_v}")
        elif not local_v:
            log(f"[WARN] local {VERSION_FILE} missing; remote is {remote_v}")
        else:
            log(f"Verified: local files match remote v{local_v}.")
    else:
        log(f"[WARN] could not read remote {VERSION_FILE}.")

    return local_v or remote_v or "?"


def _read_version():
    p = os.path.join(INSTALL_DIR, VERSION_FILE)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def ensure_dependencies():
    """Install/refresh requirements if the marker doesn't match requirements.txt."""
    req = os.path.join(INSTALL_DIR, REQUIREMENTS)
    if not os.path.isfile(req):
        return
    marker = os.path.join(INSTALL_DIR, ".requirements_sha")
    try:
        with open(req, "r", encoding="utf-8") as f:
            req_text = f.read()
        import hashlib
        sha = hashlib.sha256(req_text.encode("utf-8")).hexdigest()
    except OSError:
        return

    last = None
    try:
        with open(marker, "r", encoding="utf-8") as f:
            last = f.read().strip()
    except OSError:
        pass

    if last == sha:
        return

    log("Installing/updating Python dependencies ...")
    r = run(" ".join(_PY + ["-m", "pip", "install", "-r", REQUIREMENTS]), cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] pip install had errors (continuing anyway):\n{r.stdout[-800:]}")
    else:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(sha)
        except OSError:
            pass


def check_pymew():
    """pyMeow isn't in requirements.txt (installed from a wheel); warn if absent."""
    r = run(" ".join(_PY + ["-c", "import pyMeow"]))
    if r.returncode != 0:
        log("[WARN] pyMeow is not installed. Install it from https://github.com/qb-0/pyMeow")


def main():
    log("=" * 60)
    log("  CS2py Launcher")
    log("=" * 60)
    log(f"Install dir: {INSTALL_DIR}")

    if not ensure_python():
        input("\nPress Enter to exit ...")
        return 1
    if not ensure_git():
        input("\nPress Enter to exit ...")
        return 1

    if not ensure_cloned():
        input("\nPress Enter to exit ...")
        return 1

    version = sync_and_verify()
    log(f"Version: v{version}")
    ensure_dependencies()
    check_pymew()

    log(f"\nLaunching {MAIN_SCRIPT} from {INSTALL_DIR} ...")
    log("(Keep this window open; it is the cheat's console.)\n")
    r = run(" ".join(_PY + [MAIN_SCRIPT]), cwd=INSTALL_DIR)
    log(f"\n[cs2py exited with code {r.returncode}]")
    if r.returncode != 0:
        log(r.stdout[-2000:] if r.stdout else "(no output)")
    input("\nPress Enter to exit ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
