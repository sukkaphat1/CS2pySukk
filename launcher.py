"""CS2py launcher.

A tiny bootstrapper that keeps the actual cheat source in a stable folder
(``Documents\\CS2pySukk``) and runs it from there. This is the reliable way to
launch cs2py: the internal skin changer DLL must be injected from a real folder
(not a PyInstaller temp dir), and the source-run layout is exactly what already
works.

Each launch the launcher:
  1. makes sure Python and Git are installed (downloads + silently installs the
     official installers next to this exe when they are missing),
  2. makes sure pyMeow is installed (downloads + installs the wheel when missing),
  3. pulls the latest source from GitHub (git clone on first run, else git pull),
  4. verifies the local files match the remote version,
  5. installs/refreshes Python dependencies if needed,
  6. runs ``main.py`` from the Documents folder (console attached so its
     ``input()`` prompts work).

It is intentionally packaged as a tiny onefile exe with NO bundled data — the
source and DLL always come from Documents via git, so a new release never needs
a rebuilt launcher.
"""
import os
import subprocess
import sys
import urllib.request

REPO_URL = "https://github.com/sukkaphat1/CS2pySukk.git"
BRANCH = "main"
INSTALL_DIR = os.environ.get(
    "CS2PY_INSTALL_DIR",
    os.path.join(os.path.expanduser("~"), "Documents", "CS2pySukk"),
)
SOURCE_SUBDIR = os.environ.get("CS2PY_SOURCE_SUBDIR", "").strip("\\/")
RUNTIME_DIR = (
    os.path.join(INSTALL_DIR, SOURCE_SUBDIR)
    if SOURCE_SUBDIR
    else INSTALL_DIR
)
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

# pyMeow is not on PyPI; it ships as a zip from GitHub releases.
PYMEOW_VERSION = "1.73.42"
PYMEOW_ZIP = f"pyMeow-{PYMEOW_VERSION}.zip"
PYMEOW_URL = f"https://github.com/qb-0/pyMeow/releases/download/{PYMEOW_VERSION}/{PYMEOW_ZIP}"

# Resolved once at startup: command prefix for Python (list), path for git.exe.
_PY = None
_GIT = None


def log(msg=""):
    print(msg, flush=True)


def sh_run(cmd, cwd=None):
    """Run a string command via cmd, capturing output. Never raises."""
    return subprocess.run(cmd, cwd=cwd, shell=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def py_run(args, cwd=None):
    """Run a Python command (list form — no shell quoting issues)."""
    return subprocess.run(_PY + args, cwd=cwd, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _download(url, dest):
    log(f"Downloading {os.path.basename(dest)} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cs2py-launcher/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    sys.stdout.write(f"\r  {done * 100 // total}% ({done // 1048576} MB)   ")
                    sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True
    except Exception as e:
        log(f"[ERROR] download failed: {e}")
        return False


def _installer_path(name):
    d = _exe_dir()
    p = os.path.join(d, name)
    if not os.path.isdir(d):
        d = os.environ.get("TEMP", os.path.expanduser("~"))
        p = os.path.join(d, name)
    return p


def _find_python():
    # Prefer the Windows py launcher targeting 3.13 (pyMeow's cp313 ABI), then
    # latest py, then plain python, then known install locations.
    for prefix in (["py", "-3.13"], ["py", "-3"], ["python"], ["python3"]):
        if sh_run(" ".join(prefix + ["--version"])).returncode == 0:
            return prefix
    for cand in (PYTHON_LOCAL,
                 os.path.expandvars(r"%ProgramFiles%\Python313\python.exe"),
                 r"C:\Python313\python.exe"):
        if os.path.isfile(cand):
            return [cand]
    return None


def _find_git():
    if sh_run("git --version").returncode == 0:
        return "git"
    for cand in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
                 os.path.expandvars(r"%ProgramFiles%\Git\cmd\git.exe"),
                 os.path.expandvars(r"%ProgramFiles(x86)%\Git\cmd\git.exe")):
        if os.path.isfile(cand):
            return cand
    return None


def ensure_python():
    global _PY
    _PY = _find_python()
    if _PY:
        return True

    log("Python was not found.")
    p = _installer_path(PYTHON_INSTALLER)
    if not (os.path.isfile(p) and os.path.getsize(p) > 10 * 1024 * 1024) and not _download(PYTHON_URL, p):
        log("[ERROR] Could not download the Python installer.")
        log("Install Python manually from https://www.python.org/downloads/ (>= 3.10), then re-run.")
        return False

    log("Installing Python silently (per-user, with pip) ...")
    r = sh_run(f'"{p}" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=0 SimpleInstall=1')
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
    r = sh_run(f'"{p}" /VERYSILENT /NORESTART /NOCANCEL /SP- /CURRENTUSER /COMPONENTS="icons,assoc,assoc_sh"')
    if r.returncode != 0:
        log(f"[WARN] Git installer returned {r.returncode}; checking result ...")

    _GIT = _find_git()
    if _GIT:
        log("Git installed successfully.")
        return True
    log("[ERROR] Git install did not produce a usable git.exe.")
    log(f"Run \"{p}\" manually, then re-launch.")
    return False


def _pymew_ok():
    return py_run(["-c", "import pyMeow"]).returncode == 0


def ensure_pymew():
    """Install pyMeow (wheel from GitHub) if it isn't importable."""
    if _pymew_ok():
        return True

    log("pyMeow is missing; downloading ...")
    p = _installer_path(PYMEOW_ZIP)
    if not (os.path.isfile(p) and os.path.getsize(p) > 1024 * 1024) and not _download(PYMEOW_URL, p):
        log("[ERROR] Could not download pyMeow.")
        log("Install it manually from https://github.com/qb-0/pyMeow, then re-run.")
        return False

    log("Installing pyMeow ...")
    r = py_run(["-m", "pip", "install", "--no-cache-dir", p])
    if r.returncode != 0:
        log(f"[WARN] pyMeow install returned {r.returncode}:\n{r.stdout[-800:]}")

    if _pymew_ok():
        log("pyMeow installed successfully.")
        return True
    log("[ERROR] pyMeow is still not importable after install (Python ABI mismatch?).")
    log("Make sure you are on Python 3.13; re-run after installing it.")
    return False


def git_run(args, cwd=None):
    if _GIT == "git":
        return sh_run(f"git {args}", cwd=cwd)
    return sh_run(f'"{_GIT}" {args}', cwd=cwd)


def ensure_cloned():
    if not os.path.isdir(INSTALL_DIR):
        log(f"First run: cloning {REPO_URL} ...")
        sparse = " --sparse" if SOURCE_SUBDIR else ""
        r = git_run(
            f"clone --depth 1 --branch {BRANCH}{sparse} "
            f"\"{REPO_URL}\" \"{INSTALL_DIR}\""
        )
        if r.returncode != 0:
            log(f"[ERROR] git clone failed:\n{r.stdout}")
            return False
        if SOURCE_SUBDIR:
            r = git_run(
                f"sparse-checkout set \"{SOURCE_SUBDIR}\"",
                cwd=INSTALL_DIR,
            )
            if r.returncode != 0:
                log(f"[ERROR] could not select {SOURCE_SUBDIR}:\n{r.stdout}")
                return False
        log("Clone complete.")
        return True
    if not os.path.isdir(os.path.join(INSTALL_DIR, ".git")):
        log(f"[ERROR] {INSTALL_DIR} exists but is not a git repository.")
        log("Move or delete it and re-run the launcher.")
        return False
    if SOURCE_SUBDIR:
        r = git_run(
            f"sparse-checkout set \"{SOURCE_SUBDIR}\"",
            cwd=INSTALL_DIR,
        )
        if r.returncode != 0:
            log(f"[ERROR] could not select {SOURCE_SUBDIR}:\n{r.stdout}")
            return False
    return True


def sync_and_verify():
    local_main = os.path.join(RUNTIME_DIR, MAIN_SCRIPT)
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
    remote_version_path = (
        f"{SOURCE_SUBDIR}/{VERSION_FILE}" if SOURCE_SUBDIR else VERSION_FILE
    )
    r = git_run(f"show origin/{BRANCH}:{remote_version_path}", cwd=INSTALL_DIR)
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
    p = os.path.join(RUNTIME_DIR, VERSION_FILE)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def ensure_dependencies():
    req = os.path.join(RUNTIME_DIR, REQUIREMENTS)
    if not os.path.isfile(req):
        return
    marker = os.path.join(RUNTIME_DIR, ".requirements_sha")
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
    r = py_run(["-m", "pip", "install", "-r", REQUIREMENTS], cwd=RUNTIME_DIR)
    if r.returncode != 0:
        log(f"[WARN] pip install had errors (continuing anyway):\n{r.stdout[-800:]}")
    else:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(sha)
        except OSError:
            pass


def main():
    log("=" * 60)
    log(f"  {os.environ.get('CS2PY_LAUNCHER_NAME', 'CS2py Launcher')}")
    log("=" * 60)
    log(f"Install dir: {INSTALL_DIR}")
    if SOURCE_SUBDIR:
        log(f"Source dir: {RUNTIME_DIR}")

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
    ensure_pymew()

    log(f"\nLaunching {MAIN_SCRIPT} from {RUNTIME_DIR} ...")
    log("(Keep this window open; it is the cheat's console.)\n")

    # Run main.py with the console attached (inherit stdio) so its input()
    # prompts (e.g. the Arduino question) show up and can be answered.
    r = subprocess.call(_PY + [MAIN_SCRIPT], cwd=RUNTIME_DIR)
    log(f"\n[cs2py exited with code {r}]")
    input("\nPress Enter to exit ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
