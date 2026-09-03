import win32api
from ext import offsets
from ext import paths
from ext.datatypes import *
import os

SCREEN_WIDTH = win32api.GetSystemMetrics(0)
SCREEN_HEIGHT = win32api.GetSystemMetrics(1)


GAME_OFFSETS = offsets.get_offsets()

SAVE_FILE = os.path.join(paths.writable_dir(), "settings.json")

CHEAT_SETTINGS = {
    "EnableAntiFlashbang": False,
    "EnableFovChanger": False,
    "FovChangeSize": 90,
	
    "EnableAimbot": True,
	"EnableAimbotPrediction": True,
    "EnableAimbotTeamCheck": False,
    "EnableAimbotVisibilityCheck": False,
    "AimbotFOV": 75,
    "AimbotSmoothing": 1,
    "AimPosition": "Head",
    "AimbotKey": 6,
	
    "EnableRecoilControl": False,
    "RecoilControlSmoothing": 1.0,

    "EnableTriggerbot": True,
    "EnableTriggerbotKeyCheck": True,
    "TriggerbotKey": 17,
    "EnableTriggerbotTeamCheck": False,
    "TriggerbotTapInterval": 0.0,
    "EnableSimulatedReactionTime": False,
    "ReactionTime": 250,
    "AffectTriggerbotReaction": True,
    "EnablePerWeaponTapTimes": False,
    "WeaponTapTimes": {},
    "CurrentWeapon": "",

    "EnableESPDistanceRendering": True,
    "EnableESPTeamCheck": False,
    "EnableESPSkeletonRendering": True,
    "EnableESPBoxRendering": False,
    "EnableESPTracerRendering": False,
    "EnableESPNameText": False,
    "EnableESPHealthBarRendering": True,
    "EnableESPHealthText": False,
    "EnableESPDistanceText": False,
    "EnableFOVCircle": True,

    "EnableESPBombTimer": False,
    
    "CT_color": "#0000FF",
    "T_color": "#FF0000",
    "FOV_color": "#FFFFFF",

    "EnableBhop": False,

    "EnableRadarHack": False,

    "EnableGrenadeTrajectory": False,
    "GrenadeTrajectoryColor": "#00FF00",
    "GrenadeTrajectoryMap": "",
    "GrenadeTrajectoryGamePath": "",
    "GrenadeTrajectoryGravity": 320.0,
    "GrenadeTrajectoryTossSpeed": 300.0,
    "GrenadeTrajectoryThrowStrength": 1.0,
    "GrenadeTrajectoryRestitution": 0.45,
    "GrenadeTrajectorySpawnHeightOffset": 0.0,
    "GrenadeTrajectoryPitchOffset": 0.0,
    "GrenadeTrajectoryGhostFade": 1.0,

    "SkinChanger": {
        "enabled": False,
        "weapons": {},
    },

    "EnableDiscordRPC": True,
}


RCS_CTRL_BY_AIMBOT = False