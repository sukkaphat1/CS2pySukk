"""CS2py launcher.

A tiny bootstrapper that keeps the actual cheat source in a stable folder
(``Documents\\CS2pySukk``) and runs it from there. This is the reliable way to
launch cs2py: the internal skin changer DLL must be injected from a real folder
(not a PyInstaller temp dir), and the source-run layout is exactly what already
works.

Each launch the launcher:
  1. pulls the latest source from GitHub (git clone on first run, else git pull),
  2. verifies the local files match the remote version,
  3. installs/refreshes Python dependencies if needed,
  4. runs ``main.py`` from the Documents folder.

It is intentionally packaged as a tiny onefile exe with NO bundled data — the
source and DLL always come from Documents via git, so a new release never needs
a rebuilt launcher.
"""
import os
import subprocess
import sys

REPO_URL = "https://github.com/sukkaphat1/CS2pySukk.git"
BRANCH = "main"
INSTALL_DIR = os.path.join(os.path.expanduser("~"), "Documents", "CS2pySukk")
MAIN_SCRIPT = "main.py"
REQUIREMENTS = "requirements.txt"
VERSION_FILE = "version.txt"


def log(msg=""):
    print(msg, flush=True)


def run(cmd, cwd=None, check=False):
    """Run a command, returning CompletedProcess. Never raises on nonzero."""
    return subprocess.run(cmd, cwd=cwd, shell=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def git_available():
    r = run("git --version")
    return r.returncode == 0


def python_launcher():
    """Return a command prefix that runs the system Python with the deps."""
    # Prefer the Windows py launcher; fall back to plain python.
    r = run("py -3 --version")
    if r.returncode == 0:
        return ["py", "-3"]
    r = run("python --version")
    if r.returncode == 0:
        return ["python"]
    return None


def ensure_cloned():
    """Clone the repo if the install dir is missing/empty, else return True."""
    if not os.path.isdir(INSTALL_DIR):
        log(f"First run: cloning {REPO_URL} ...")
        r = run(f'git clone --depth 1 --branch {BRANCH} "{REPO_URL}" "{INSTALL_DIR}"')
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

    # Fetch + fast-forward; a hard reset keeps local edits (settings.json etc.
    # are gitignored anyway) from blocking the update.
    r = run(f"git fetch origin {BRANCH}", cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] git fetch failed (offline?):\n{r.stdout}")
    r = run(f"git reset --hard origin/{BRANCH}", cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] git reset failed:\n{r.stdout}")

    # Verify: local version.txt must match the remote tip's version.txt.
    local_v = _read_version()
    r = run(f"git show origin/{BRANCH}:{VERSION_FILE}", cwd=INSTALL_DIR)
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


def ensure_dependencies(py):
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
    r = run(" ".join(py + ["-m", "pip", "install", "-r", REQUIREMENTS]), cwd=INSTALL_DIR)
    if r.returncode != 0:
        log(f"[WARN] pip install had errors (continuing anyway):\n{r.stdout[-800:]}")
    else:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(sha)
        except OSError:
            pass


def check_pymew(py):
    """pyMeow isn't in requirements.txt (installed from a wheel); warn if absent."""
    r = run(" ".join(py + ["-c", "import pyMeow"]))
    if r.returncode != 0:
        log("[WARN] pyMeow is not installed. Install it from https://github.com/qb-0/pyMeow")


def main():
    log("=" * 60)
    log("  CS2py Launcher")
    log("=" * 60)
    log(f"Install dir: {INSTALL_DIR}")

    if not git_available():
        log("[ERROR] git was not found on PATH. Install Git for Windows and re-run.")
        input("\nPress Enter to exit ...")
        return 1

    py = python_launcher()
    if py is None:
        log("[ERROR] No Python interpreter found (tried 'py' and 'python').")
        input("\nPress Enter to exit ...")
        return 1

    if not ensure_cloned():
        input("\nPress Enter to exit ...")
        return 1

    version = sync_and_verify()
    log(f"Version: v{version}")
    ensure_dependencies(py)
    check_pymew(py)

    log(f"\nLaunching {MAIN_SCRIPT} from {INSTALL_DIR} ...")
    log("(Keep this window open; it is the cheat's console.)\n")
    # Run main.py in the foreground so its console stays attached and the
    # Arduino/input prompts work normally.
    r = run(" ".join(py + [MAIN_SCRIPT]), cwd=INSTALL_DIR)
    log(f"\n[cs2py exited with code {r.returncode}]")
    if r.returncode != 0:
        log(r.stdout[-2000:] if r.stdout else "(no output)")
    input("\nPress Enter to exit ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
