![CS2PY](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/cs2py_banner.png)

> Forked from [GsDeluxe/cs2py](https://github.com/GsDeluxe/cs2py)

## About

**cs2py** is a Counter-Strike 2 cheat written in Python. It reads game memory to draw a raylib overlay (ESP) and automates an aimbot, triggerbot, recoil control, anti-flash, bunnyhop, FOV changer, bomb timer, grenade trajectory, and Discord Rich Presence. The **skin changer is internal** (a manually-mapped DLL injected into cs2) so skins actually render on the weapon; everything else is external (read/write process memory). On launch it pulls the latest game offsets from this repo, so it keeps working after CS2 updates without a rebuild.

> Offsets are dumped with [a2x/cs2-dumper](https://github.com/a2x/cs2-dumper).

## Installation

The easiest way to run cs2py is the **launcher** (`cs2py.exe` from the latest release). It:
- downloads and silently installs **Python 3.13** and **Git for Windows** if they're missing,
- clones/updates the source to `Documents\CS2pySukk`,
- verifies the files match the latest release,
- installs Python dependencies and launches the cheat.

> Requires an internet connection on first run.

Alternatively, run from source:

```
pip install -r requirements.txt
```
> PyMeow is also a dependency, install instructions are [here](https://github.com/qb-0/pyMeow?tab=readme-ov-file#floppy_disk-installation)

## Usage

```
python main.py
```

## Features

- [x] Aimbot  
- [x] ESP
- [x] Triggerbot  
- [x] Recoil Control  
- [x] Anti Flashbang  
- [x] Auto Bhop  
- [x] FOV Changer  
- [x] Bomb Timer  
- [x] Discord RPC  
- [x] Color Customization  
- [x] Auto Save Config
- [x] Overlay GUI (Insert to toggle)
- [x] Skin Changer (weapons / knives / gloves)
- [x] Grenade Trajectory

## Credits

- Original project: [GsDeluxe/cs2py](https://github.com/GsDeluxe/cs2py)
- GUI revamp: [HWYkagiru](https://github.com/HWYkagiru) 💖

## Preview

![VISUALS_IMG](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/esp_view.png)

| Aimbot | Visuals | Triggerbot | Recoil control | Colors | Misc |
|:------:|:-------:|:-----------:|:---------------:|:------:|:----:|
| ![Aimbot](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/aimbot_tab.png) | ![Visuals](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/esp_tab.png) | ![Triggerbot](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/triggerbot_tab.png) | ![Recoil control](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/rcs_tab.png) | ![Colors](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/colors_tab.png) | ![Misc](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/misc_tab.png) |


# Use at your own risk ⚠️
I am not responsible for any misuse of this program, this is for educational and learning purposes

## 🚫 Scope & Disclaimer

- This project is not intended to be undetected by any anti cheat system.
- It does not claim to bypass or avoid detection.
