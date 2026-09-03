![CS2PY](https://raw.githubusercontent.com/sukkaphat1/CS2pySukk/main/img/cs2py_banner.png)

> Forked from [GsDeluxe/cs2py](https://github.com/GsDeluxe/cs2py)

## v1.0.9 — Release Notes

- **Overlay GUI redesign** — the old DearPyGui menu is replaced with a sleek in-game overlay menu. Press **Insert** to toggle it; it's interactive while open and click-through when closed.
- **Local skin changer** — pick skins for weapons, knives, and gloves from a full item database parsed out of `items_game.txt`, with live Steam CDN preview images. Skins are visual-only (only you see them) and per-weapon configs are saved.
- **Grenade trajectory preview** — aim a grenade and see its predicted flight path before you throw it.

> Found a bug? Please report it in the Discord.

## About

**cs2py** is an external Counter-Strike 2 cheat written in Python. It reads game memory to draw a raylib overlay (ESP) and automates an aimbot, triggerbot, recoil control, anti-flash, bunnyhop, FOV changer, bomb timer, grenade trajectory, a skin changer, and Discord Rich Presence. On launch it pulls the latest game offsets from this repo, so it keeps working after CS2 updates without a rebuild.

> Offsets are dumped with [a2x/cs2-dumper](https://github.com/a2x/cs2-dumper).

## Installation

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