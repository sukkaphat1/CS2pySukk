from ext.datatypes import *
from functions import memfuncs
from functions import calculations
from features.combined import get_current_weapon_name
from features import collision
from features import minimap
import globals
import win32api
import math
import os
import time
import pyMeow as pme

# Ballistic constants from the CS:GO/CS2 grenade source
# (basecsgrenade_projectile.cpp/.h + weapon_basecsgrenade.cpp, 2018+ build):
#   gravity scale 0.4 (sv_gravity 800) -> 320
#   bounce: reflect velocity, then scale by elasticity 0.45, stop if < 30 u/s
#   throw speed = GetThrowVelocity() * 0.9 (clamped 750), fixed (not pitch-dependent)
#   throw angle = view pitch + 10 deg upward boost (tapered at +/-90)
#   velocity inheritance = player velocity * 1.25
#   toss = 30% speed (GRENADE_SECONDARY_DAMPENING 0.3), spawn lowered 12 units
GRAVITY = 320.0
AIR_DRAG = 0.0         # per-second velocity attenuation (0 = pure parabola)
TIME_STEP = 0.033      # seconds per simulated step
PREDICT_STEPS = 160    # flight window

# Bounce constants (GetGrenadeElasticity = 0.45).
ELASTICITY = 0.45
MIN_SPEED = 30.0       # stop when post-bounce speed falls below this
MAX_BOUNCES = 8
HIT_EPSILON = 0.25     # nudge off the surface to avoid re-collision
SPAWN_OFFSET = 16.0    # grenade spawns forward of the eye (eye + forward*16)

# Throw constants (weapon_basecsgrenade.cpp 2018+).
THROW_BASE_VELOCITY = 750.0   # GetThrowVelocity()
VEL_INHERIT = 1.25            # grenade inherits player velocity * 1.25
TOSS_DAMPENING = 0.3          # GRENADE_SECONDARY_DAMPENING
TOSS_LOWER = 12.0             # GRENADE_SECONDARY_LOWER

GRENADE_WEAPONS = {"Flashbang", "HE Grenade", "Smoke Grenade", "Molotov", "Decoy Grenade", "Incendiary Grenade"}

_world = None
_world_key = None
_detected_game_path = None

# Ghost trajectory (frozen prediction that erases from the throw point).
_ghost_points = None
_ghost_start = 0.0
_throw_was_held = False
_last_prethrow_points = None
_landing_point = None

# (minimap landing dot projection lives in features/minimap.py)

# CGlobalVarsBase: offset of the current map name pointer (const char*). Read via
# dwGlobalVars to auto-detect the map so the trajectory works on every map.
MAP_NAME_OFFSET = 0x188


def _is_grenade_class(name):
	if not name:
		return False
	if "Base" in name or "Tracer" in name or "_API" in name:
		return False
	return ("Grenade" in name) or name.endswith("Projectile")


def _detect_game_path():
	"""Derive the CS2 ``game`` folder from the running cs2.exe path (cached)."""
	global _detected_game_path
	if _detected_game_path is not None:
		return _detected_game_path
	try:
		import psutil
		for p in psutil.process_iter(["name", "exe"]):
			try:
				if p.info.get("name") == "cs2.exe" and p.info.get("exe"):
					# .../game/bin/win64/cs2.exe  ->  .../game
					_detected_game_path = os.path.dirname(os.path.dirname(os.path.dirname(p.info["exe"])))
					return _detected_game_path
			except Exception:
				continue
	except Exception:
		pass
	_detected_game_path = r"F:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game"
	return _detected_game_path


def _find_map_vpk(map_name, Options):
	game_path = Options.get("GrenadeTrajectoryGamePath", "") or ""
	if game_path:
		base = game_path
	else:
		base = _detect_game_path()
	return os.path.join(base, "csgo", "maps", f"{map_name}.vpk")


def _detect_map_name(processHandle, clientBaseAddress, Offsets):
	"""Read the current map name from CGlobalVarsBase (dwGlobalVars)."""
	try:
		gv = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwGlobalVars)
		if not gv:
			return None
		name_ptr = memfuncs.ProcMemHandler.ReadPointer(processHandle, gv + MAP_NAME_OFFSET)
		if not name_ptr:
			return None
		name = memfuncs.ProcMemHandler.ReadString(processHandle, name_ptr, 64)
		if name and 3 <= len(name) <= 48 and "/" not in name and "\\" not in name:
			return name.strip()
	except Exception:
		pass
	return None


def _get_collision_world(processHandle, clientBaseAddress, Offsets, Options):
	global _world, _world_key
	map_name = (Options.get("GrenadeTrajectoryMap", "") or "").strip()
	if not map_name or map_name.lower() in ("auto", "automatic"):
		map_name = _detect_map_name(processHandle, clientBaseAddress, Offsets)
	if not map_name:
		_world = None
		_world_key = None
		return None
	vpk = _find_map_vpk(map_name, Options)
	key = (map_name, vpk)
	if _world is not None and _world_key == key:
		return _world
	try:
		w = collision.get_world(map_name, vpk)
	except Exception:
		w = None
	_world = w
	_world_key = key
	return w


def _read_physics(Options):
	return {
		"gravity": float(Options.get("GrenadeTrajectoryGravity", GRAVITY)),
		"elasticity": float(Options.get("GrenadeTrajectoryRestitution", ELASTICITY)),
		"throw_strength": float(Options.get("GrenadeTrajectoryThrowStrength", 1.0)),
		"spawn_height_offset": float(Options.get("GrenadeTrajectorySpawnHeightOffset", 0.0)),
		"pitch_offset": float(Options.get("GrenadeTrajectoryPitchOffset", 0.0)),
		"ghost_fade": float(Options.get("GrenadeTrajectoryGhostFade", 1.0)),
	}


def _throw_params(pitch_deg, yaw_deg, strength=1.0):
	"""CS:GO/CS2 grenade throw (weapon_basecsgrenade.cpp 2018+).

	Returns (direction, speed, lower) where lower is the spawn Z offset (toss).
	"""
	# normalize pitch to [-90, 90] (negative = up, positive = down)
	p = pitch_deg
	if p > 90.0:
		p -= 360.0
	elif p < -90.0:
		p += 360.0
	# add a 10 degree upward boost when looking horizontal, taper to 0 at extremes
	p -= 10.0 * (90.0 - abs(p)) / 90.0
	# fixed throw speed: GetThrowVelocity() * 0.9, clamped [15, 750]
	speed = max(15.0, min(750.0, THROW_BASE_VELOCITY * 0.9))
	# scale by throw strength: lerp(strength, TOSS_DAMPENING, 1.0)
	strength = max(0.0, min(1.0, strength))
	speed *= TOSS_DAMPENING + (1.0 - TOSS_DAMPENING) * strength
	# spawn lowering for underhand toss
	lower = TOSS_LOWER * (1.0 - strength)
	pr = math.radians(p)
	yr = math.radians(yaw_deg)
	direction = Vector3(math.cos(pr) * math.cos(yr), math.cos(pr) * math.sin(yr), -math.sin(pr))
	return direction, speed, lower


def _simulate(pos, vel, world=None, floor_z=None, gravity=GRAVITY, elasticity=ELASTICITY):
	"""Simulate a projectile forward.

	- ``world`` (CollisionWorld): precise wall/floor/ceiling bounces via the
	  map's real collision geometry.
	- ``floor_z``: flat-plane fallback bounce (only used when world is None).
	"""
	points = [Vector3(pos.x, pos.y, pos.z)]
	cur = Vector3(pos.x, pos.y, pos.z)
	v = Vector3(vel.x, vel.y, vel.z)
	half_g_dt2 = 0.5 * gravity * TIME_STEP * TIME_STEP
	g_dt = gravity * TIME_STEP
	drag = 1.0 - AIR_DRAG * TIME_STEP
	bounces = 0

	for _ in range(PREDICT_STEPS):
		nxt = Vector3(
			cur.x + v.x * TIME_STEP,
			cur.y + v.y * TIME_STEP,
			cur.z + v.z * TIME_STEP - half_g_dt2,
		)

		if world is not None:
			segx = nxt.x - cur.x
			segy = nxt.y - cur.y
			segz = nxt.z - cur.z
			dist = math.sqrt(segx * segx + segy * segy + segz * segz)
			if dist > 1e-9:
				hit = world.raycast(cur.x, cur.y, cur.z, segx / dist, segy / dist, segz / dist, dist)
				if hit is not None and hit[0] < dist:
					t, nx, ny, nz, mat = hit
					hx = cur.x + (segx / dist) * t
					hy = cur.y + (segy / dist) * t
					hz = cur.z + (segz / dist) * t
					if bounces >= MAX_BOUNCES:
						points.append(Vector3(hx, hy, hz))
						break
					# settle slightly off the surface along its normal
					cur = Vector3(hx + nx * HIT_EPSILON, hy + ny * HIT_EPSILON, hz + nz * HIT_EPSILON)
					points.append(cur)
					# reflect velocity, then scale the whole vector by elasticity
					# (matches ResolveFlyCollisionCustom: PhysicsClipVelocity backoff 2.0,
					#  then *= GetGrenadeElasticity()).
					vn = v.x * nx + v.y * ny + v.z * nz
					v = Vector3(
						(v.x - 2.0 * vn * nx) * elasticity,
						(v.y - 2.0 * vn * ny) * elasticity,
						(v.z - 2.0 * vn * nz) * elasticity,
					)
					bounces += 1
					if v.x * v.x + v.y * v.y + v.z * v.z < MIN_SPEED * MIN_SPEED:
						break
					continue

		cur = nxt
		v = Vector3(v.x, v.y, v.z - g_dt) * drag

		if world is None and floor_z is not None and cur.z < floor_z:
			if bounces >= MAX_BOUNCES:
				points.append(cur)
				break
			cur = Vector3(cur.x, cur.y, 2.0 * floor_z - cur.z)
			v = Vector3(v.x * elasticity, v.y * elasticity, -v.z * elasticity)
			bounces += 1

		points.append(cur)

	return points


def _draw_arc(viewMatrix, points, color):
	prev = None
	for p in points:
		s = calculations.world_to_screen(viewMatrix, p)
		if s.x <= -1 or s.y <= -1 or s.x >= globals.SCREEN_WIDTH or s.y >= globals.SCREEN_HEIGHT:
			prev = None
			continue
		if prev is not None:
			pme.draw_line(prev.x, prev.y, s.x, s.y, color=color, thick=1.5)
		prev = s
	if prev is not None:
		pme.draw_circle(int(prev.x), int(prev.y), 5, color)


def _draw_prethrow(processHandle, clientBaseAddress, Offsets, viewMatrix, color, floor_z, world, phys):
	global _ghost_points, _ghost_start, _throw_was_held, _last_prethrow_points, _landing_point
	try:
		localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
		if not localPawn:
			_throw_was_held = False
			return

		weapon = get_current_weapon_name(processHandle, clientBaseAddress, localPawn, Offsets)
		if weapon not in GRENADE_WEAPONS:
			_throw_was_held = False
			_last_prethrow_points = None
			_landing_point = None
			return

		throw = win32api.GetAsyncKeyState(0x01) & 0x8000
		toss = win32api.GetAsyncKeyState(0x02) & 0x8000
		held = throw or toss

		if not held:
			# Released -> freeze the last predicted path as a ghost that erases over time.
			if _throw_was_held and _last_prethrow_points:
				_ghost_points = _last_prethrow_points
				_ghost_start = time.time()
			_throw_was_held = False
			_landing_point = None
			return

		_throw_was_held = True

		sceneNode = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPawn + Offsets.offset.m_pGameSceneNode)
		origin = memfuncs.ProcMemHandler.ReadVec(processHandle, sceneNode + Offsets.offset.m_vecAbsOrigin)
		viewOffset = memfuncs.ProcMemHandler.ReadVec(processHandle, localPawn + Offsets.offset.m_vecViewOffset)
		eye = Vector3(origin.x + viewOffset.x, origin.y + viewOffset.y, origin.z + viewOffset.z)

		angles = memfuncs.ProcMemHandler.ReadVec(processHandle, localPawn + Offsets.offset.m_angEyeAngles)

		# throw strength: full (1.0) for left-click, toss (0.0) for right-click
		strength = 1.0 if throw else 0.0
		direction, speed, lower = _throw_params(angles.x - phys["pitch_offset"], angles.y, strength * phys["throw_strength"])

		# Grenade spawns slightly forward of the eye along the throw direction.
		spawn = Vector3(
			eye.x + direction.x * SPAWN_OFFSET,
			eye.y + direction.y * SPAWN_OFFSET,
			eye.z + direction.z * SPAWN_OFFSET + phys["spawn_height_offset"] - lower,
		)

		playerVel = memfuncs.ProcMemHandler.ReadVec(processHandle, localPawn + Offsets.offset.m_vecAbsVelocity)
		vel = Vector3(
			direction.x * speed + playerVel.x * VEL_INHERIT,
			direction.y * speed + playerVel.y * VEL_INHERIT,
			direction.z * speed + playerVel.z * VEL_INHERIT,
		)

		points = _simulate(spawn, vel, world, floor_z, phys["gravity"], phys["elasticity"])
		_last_prethrow_points = points
		_landing_point = points[-1]
		_draw_arc(viewMatrix, points, color)
	except Exception:
		pass


def _draw_ghost(viewMatrix, color, ghost_fade=1.0):
	global _ghost_points, _landing_point
	if not _ghost_points:
		return
	elapsed = time.time() - _ghost_start
	erase_idx = int(elapsed / (TIME_STEP * max(0.1, ghost_fade)))
	if erase_idx >= len(_ghost_points):
		_ghost_points = None
		_landing_point = None
		return
	_landing_point = _ghost_points[-1]
	_draw_arc(viewMatrix, _ghost_points[erase_idx:], color)


def _draw_minimap_dot(processHandle, clientBaseAddress, Offsets, color):
	"""Project the predicted landing point onto the top-left radar."""
	global _landing_point
	if _landing_point is None:
		return
	try:
		localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
		if not localPawn:
			return
		sceneNode = memfuncs.ProcMemHandler.ReadPointer(processHandle, localPawn + Offsets.offset.m_pGameSceneNode)
		if not sceneNode:
			return
		playerPos = memfuncs.ProcMemHandler.ReadVec(processHandle, sceneNode + Offsets.offset.m_vecAbsOrigin)
		angles = memfuncs.ProcMemHandler.ReadVec(processHandle, localPawn + Offsets.offset.m_angEyeAngles)

		gameRules = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwGameRules)
		if not gameRules:
			return
		mins = memfuncs.ProcMemHandler.ReadVec(processHandle, gameRules + Offsets.offset.m_vMinimapMins)
		maxs = memfuncs.ProcMemHandler.ReadVec(processHandle, gameRules + Offsets.offset.m_vMinimapMaxs)

		radar = minimap.get_radar(processHandle, mins, maxs, playerPos, angles.y)
		pt = minimap.world_to_radar(radar, _landing_point)
		if pt is None:
			return
		px, py = pt

		# only draw when the landing dot falls inside the round radar
		dx = px - radar["cx"]
		dy = py - radar["cy"]
		if dx * dx + dy * dy > radar["radius"] * radar["radius"]:
			return

		pme.draw_circle(int(px), int(py), 4, color)
		pme.draw_circle(int(px), int(py), 3, color)
	except Exception:
		pass


def GrenadeTrajectory_Update(processHandle, clientBaseAddress, Offsets, Options):
	try:
		viewMatrix = memfuncs.ProcMemHandler.ReadMatrix(processHandle, clientBaseAddress + Offsets.offset.dwViewMatrix)
		EntityList = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
		if not EntityList:
			return

		color = pme.get_color(Options.get("GrenadeTrajectoryColor", "#00FF00"))

		floor_z = None
		try:
			localPawn = memfuncs.ProcMemHandler.ReadPointer(processHandle, clientBaseAddress + Offsets.offset.dwLocalPlayerPawn)
			if localPawn:
				floor_z = memfuncs.ProcMemHandler.ReadVec(processHandle, localPawn + Offsets.offset.m_vOldOrigin).z
		except Exception:
			pass

		world = _get_collision_world(processHandle, clientBaseAddress, Offsets, Options)
		phys = _read_physics(Options)

		_draw_prethrow(processHandle, clientBaseAddress, Offsets, viewMatrix, color, floor_z, world, phys)
		_draw_ghost(viewMatrix, color, phys["ghost_fade"])
		# landing dot disabled for now (still needs scale/position tuning)
		# _draw_minimap_dot(processHandle, clientBaseAddress, Offsets, color)

		for i in range(64):
			try:
				ListEntry = memfuncs.ProcMemHandler.ReadPointer(processHandle, EntityList + (8 * (i & 0x7FFF) >> 9) + 16)
				if not ListEntry:
					continue
				identity = ListEntry + 112 * (i & 0x1FF)
				entity = memfuncs.ProcMemHandler.ReadPointer(processHandle, identity)
				if not entity:
					continue
				class_name_ptr = memfuncs.ProcMemHandler.ReadPointer(processHandle, identity + Offsets.offset.m_designerName)
				if not class_name_ptr:
					continue
				class_name = memfuncs.ProcMemHandler.ReadString(processHandle, class_name_ptr, 64)
				if not _is_grenade_class(class_name):
					continue
				sceneNode = memfuncs.ProcMemHandler.ReadPointer(processHandle, entity + Offsets.offset.m_pGameSceneNode)
				if not sceneNode:
					continue
				pos = memfuncs.ProcMemHandler.ReadVec(processHandle, sceneNode + Offsets.offset.m_vecAbsOrigin)
				vel = memfuncs.ProcMemHandler.ReadVec(processHandle, entity + Offsets.offset.m_vecVelocity)
				if abs(vel.x) + abs(vel.y) + abs(vel.z) < 5.0:
					continue
				_draw_arc(viewMatrix, _simulate(pos, vel, world, floor_z, phys["gravity"], phys["elasticity"]), color)
			except Exception:
				continue
	except Exception:
		pass
