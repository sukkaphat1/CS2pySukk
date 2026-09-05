"""Development-channel launcher.

The shared launcher implementation is configured before import so this build
uses a separate Documents\\CS2pyDev checkout and only the DevSource subtree.
"""

import os
import sys


os.environ.setdefault(
    "CS2PY_INSTALL_DIR",
    os.path.join(os.path.expanduser("~"), "Documents", "CS2pyDev"),
)
os.environ.setdefault("CS2PY_SOURCE_SUBDIR", "DevSource")
os.environ.setdefault("CS2PY_LAUNCHER_NAME", "CS2py Dev Launcher")

from launcher import main


if __name__ == "__main__":
    sys.exit(main())
