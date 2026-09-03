from dataclasses import dataclass
import os
import sys
import json
import requests

from ext import paths

REMOTE_REPO = "sukkaphat1/CS2pySukk"
REMOTE_BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REMOTE_REPO}/{REMOTE_BRANCH}"

@dataclass
class Offset:
	dwViewMatrix: int
	dwLocalPlayerPawn: int
	dwEntityList: int
	dwLocalPlayerController: int
	dwViewAngles: int
	dwGameRules: int
	dwGlobalVars: int
	dwSensitivity_sensitivity: int
	dwSensitivity: int 


	ButtonJump: int
	
	m_hPlayerPawn: int
	m_iHealth: int
	m_lifeState: int
	m_iTeamNum: int
	m_vOldOrigin: int
	m_pGameSceneNode: int
	m_modelState: int
	m_boneArray: int
	m_nodeToWorld: int
	m_sSanitizedPlayerName: int
	m_iIDEntIndex: int
	m_flFlashMaxAlpha: int
	m_fFlags: int
	m_iFOV: int
	m_pCameraServices: int
	m_bIsScoped: int

	m_vecViewOffset: int
	m_entitySpottedState: int 
	m_bSpotted: int 
	m_bBombPlanted: int
	m_vMinimapMins: int
	m_vMinimapMaxs: int
	
	m_iShotsFired: int
	m_pAimPunchServices: int
	m_unpredictableBaseTick: int
	
	m_bSpottedByMask: int
	m_vecVelocity: int

	m_pWeaponServices: int
	m_hActiveWeapon: int
	m_AttributeManager: int
	m_Item: int
	m_iItemDefinitionIndex: int
	m_nFallbackPaintKit: int
	m_nFallbackSeed: int
	m_flFallbackWear: int
	m_nFallbackStatTrak: int
	m_iEntityQuality: int
	m_iItemIDHigh: int
	m_iItemIDLow: int
	m_iItemID: int
	m_iAccountID: int
	m_bDisallowSOC: int
	m_bInitialized: int
	m_bRestoreCustomMaterialAfterPrecache: int
	m_OriginalOwnerXuidLow: int
	m_OriginalOwnerXuidHigh: int
	m_AttributeList: int
	m_hMyWearables: int
	m_designerName: int
	m_vecAbsOrigin: int
	v_angle: int
	m_angEyeAngles: int
	m_vecAbsVelocity: int
	


def _dump_dir():
	"""Find the output dump folder: writable copy first (freshly pulled or
	user-updated), then the bundled PyInstaller data."""
	candidate = os.path.join(paths.writable_dir(), 'output', 'offsets.json')
	if os.path.exists(candidate):
		return os.path.join(paths.writable_dir(), 'output')
	meipass = getattr(sys, '_MEIPASS', None)
	if meipass:
		candidate = os.path.join(meipass, 'output', 'offsets.json')
		if os.path.exists(candidate):
			return os.path.join(meipass, 'output')
	return None


def _download(url, dest):
	r = requests.get(url, timeout=8)
	r.raise_for_status()
	with open(dest, 'wb') as f:
		f.write(r.content)


def try_pull_updates():
	"""Best-effort: pull a newer offsets dump from our GitHub repo into cwd/output.
	Compares the latest commit that touched output/ against a local marker and only
	downloads when it changed. Never raises - any failure falls back to the
	local/bundled dump."""
	try:
		local_dir = os.path.join(paths.writable_dir(), 'output')
		os.makedirs(local_dir, exist_ok=True)
		marker = os.path.join(paths.writable_dir(), '.offsets_sha')

		api = f'https://api.github.com/repos/{REMOTE_REPO}/commits?path=output&per_page=1'
		r = requests.get(api, timeout=8)
		r.raise_for_status()
		commits = r.json()
		if not isinstance(commits, list) or not commits:
			return False
		remote_sha = commits[0].get('sha')
		if not remote_sha:
			return False

		local_sha = None
		if os.path.exists(marker):
			with open(marker, 'r') as f:
				local_sha = f.read().strip()
		if local_sha == remote_sha:
			return True  # already up to date

		for name in ('offsets.json', 'client_dll.json', 'buttons.json'):
			_download(f'{RAW_BASE}/output/{name}', os.path.join(local_dir, name))

		with open(marker, 'w') as f:
			f.write(remote_sha)
		print('Offsets updated from GitHub')
		return True
	except Exception as e:
		print(f'Offsets update check failed (using local dump): {e}')
		return False


def _local_version():
	"""Read the local version.txt: bundled copy first (exe), then cwd (source)."""
	for base in (getattr(sys, '_MEIPASS', None), os.getcwd()):
		if not base:
			continue
		p = os.path.join(base, 'version.txt')
		if os.path.exists(p):
			try:
				with open(p, 'r', encoding='utf-8') as f:
					return f.read().strip()
			except Exception:
				return None
	return None


def _version_tuple(v):
	try:
		return tuple(int(x) for x in str(v).strip().split('.'))
	except ValueError:
		return ()


def _remote_message():
	"""Fetch the optional announcement the dev wrote in update_message.txt."""
	try:
		r = requests.get(f'{RAW_BASE}/update_message.txt', timeout=6)
		r.raise_for_status()
		return r.text.strip()
	except Exception:
		return None


def check_version():
	"""Print the local version and whether a newer one is on GitHub. Best-effort."""
	local = _local_version()
	print(f'cs2py version: {local or "unknown"}')
	try:
		r = requests.get(f'{RAW_BASE}/version.txt', timeout=6)
		r.raise_for_status()
		remote = r.text.strip()
	except Exception as e:
		print(f'Version check failed: {e}')
		return
	if _version_tuple(remote) > _version_tuple(local or ''):
		msg = _remote_message()
		if msg:
			print(msg)
		else:
			print(f'New version available: {remote} - https://github.com/{REMOTE_REPO}/releases')
	else:
		print('You are up to date')


class Client:
	def __init__(self, manual_dump=False):
		if not manual_dump:
			self._load_from_url()
		else:
			self._load_from_file()

	def _load_from_url(self):
		try:
			self.offsets = self._get_json_from_url(f'{RAW_BASE}/output/offsets.json')
			self.clientdll = self._get_json_from_url(f'{RAW_BASE}/output/client_dll.json')
			self.buttons = self._get_json_from_url(f'{RAW_BASE}/output/buttons.json')
		except Exception as e:
			print(f'Unable to get offsets: {e}')
			exit()

	def _get_json_from_url(self, url):
		return requests.get(url).json()

	def _load_from_file(self):
		try:
			base_path = _dump_dir()
			if base_path is None:
				raise FileNotFoundError('No local output dump found')
			self.offsets = self._load_json_from_file(base_path, 'offsets.json')
			self.clientdll = self._load_json_from_file(base_path, 'client_dll.json')
			self.buttons = self._load_json_from_file(base_path, 'buttons.json')
		except Exception as e:
			print(f'Unable to load data from file: {e}')
			exit()

	def _load_json_from_file(self, base_path, filename):
		with open(os.path.join(base_path, filename), 'r') as f:
			return json.load(f)

	def offset(self, a):
		return self._get_value_from_dict(self.offsets, ['client.dll', a], f'Offset {a} not found.')

	def get(self, a, b):
		try:
			return self.clientdll["client.dll"]['classes'][a]['fields'][b]
		except KeyError as e:
			print(f"Error with getting offset for {a} -> {b}: {e}")
			exit()

	def button(self, a):
		return self._get_value_from_dict(self.buttons, ['client.dll', a], f'Button {a} not found.')

	def _get_value_from_dict(self, data, keys, error_message):
		try:
			for key in keys:
				data = data[key]
			return data
		except KeyError:
			print(error_message)
			exit()


def get_offsets() -> Offset:
	# Report version and pull fresh offsets from our GitHub repo (both best-effort),
	# then load the local/bundled dump - which now includes any files just downloaded.
	check_version()
	try_pull_updates()
	oc = Client(manual_dump=_dump_dir() is not None)
	offsets_obj = Offset(
		dwViewMatrix=oc.offset("dwViewMatrix"),
		dwLocalPlayerPawn=oc.offset("dwLocalPlayerPawn"),
		dwEntityList=oc.offset("dwEntityList"),
		dwLocalPlayerController=oc.offset("dwLocalPlayerController"),
		dwViewAngles = oc.offset("dwViewAngles"),
		dwGameRules = oc.offset("dwGameRules"),
		dwGlobalVars = oc.offset("dwGlobalVars"),
		dwSensitivity_sensitivity = oc.offset("dwSensitivity_sensitivity"),
		dwSensitivity = oc.offset("dwSensitivity"),
		

		ButtonJump=oc.button("jump"),
		
		m_hPlayerPawn=oc.get("CCSPlayerController", "m_hPlayerPawn"),
		m_iHealth=oc.get("C_BaseEntity", "m_iHealth"),
		m_lifeState=oc.get("C_BaseEntity", "m_lifeState"),
		m_iTeamNum=oc.get("C_BaseEntity", "m_iTeamNum"),
		m_vOldOrigin=oc.get("C_BasePlayerPawn", "m_vOldOrigin"),
		m_pGameSceneNode=oc.get("C_BaseEntity", "m_pGameSceneNode"),
		m_modelState=oc.get("CSkeletonInstance", "m_modelState"),
		m_boneArray=128,
		m_nodeToWorld=oc.get("CGameSceneNode", "m_nodeToWorld"),
		m_sSanitizedPlayerName=oc.get("CCSPlayerController", "m_sSanitizedPlayerName"),
		m_iIDEntIndex=oc.get("C_CSPlayerPawn", "m_iIDEntIndex"),
		m_flFlashMaxAlpha=oc.get("C_CSPlayerPawnBase", "m_flFlashMaxAlpha"),
		m_fFlags=oc.get("C_BaseEntity", "m_fFlags"),
		m_iFOV=oc.get("CCSPlayerBase_CameraServices", "m_iFOV"),
		m_pCameraServices=oc.get("C_BasePlayerPawn", "m_pCameraServices"),
		m_bIsScoped=oc.get("C_CSPlayerPawn", "m_bIsScoped"),
		m_vecViewOffset = oc.get("C_BaseModelEntity", "m_vecViewOffset"),
		m_entitySpottedState = oc.get("C_CSPlayerPawn", "m_entitySpottedState"),
		m_bSpotted = oc.get("EntitySpottedState_t", "m_bSpotted"),
		m_bBombPlanted = oc.get("C_CSGameRules", "m_bBombPlanted"),
		m_vMinimapMins = oc.get("C_CSGameRules", "m_vMinimapMins"),
		m_vMinimapMaxs = oc.get("C_CSGameRules", "m_vMinimapMaxs"),
		m_iShotsFired = oc.get("C_CSPlayerPawn", "m_iShotsFired"),
		m_pAimPunchServices = oc.get("C_CSPlayerPawn", "m_pAimPunchServices"),
		m_unpredictableBaseTick = oc.get("CCSPlayer_AimPunchServices", "m_unpredictableBaseTick"),
		
		m_bSpottedByMask = oc.get("EntitySpottedState_t", "m_bSpottedByMask"),
		m_vecVelocity = oc.get("C_BaseEntity", "m_vecVelocity"),

		m_pWeaponServices = oc.get("C_BasePlayerPawn", "m_pWeaponServices"),
		m_hActiveWeapon = oc.get("CPlayer_WeaponServices", "m_hActiveWeapon"),
		m_AttributeManager = oc.get("C_EconEntity", "m_AttributeManager"),
		m_Item = oc.get("C_AttributeContainer", "m_Item"),
		m_iItemDefinitionIndex = oc.get("C_EconItemView", "m_iItemDefinitionIndex"),
		m_nFallbackPaintKit = oc.get("C_EconEntity", "m_nFallbackPaintKit"),
		m_nFallbackSeed = oc.get("C_EconEntity", "m_nFallbackSeed"),
		m_flFallbackWear = oc.get("C_EconEntity", "m_flFallbackWear"),
		m_nFallbackStatTrak = oc.get("C_EconEntity", "m_nFallbackStatTrak"),
		m_iEntityQuality = oc.get("C_EconItemView", "m_iEntityQuality"),
		m_iItemIDHigh = oc.get("C_EconItemView", "m_iItemIDHigh"),
		m_iItemIDLow = oc.get("C_EconItemView", "m_iItemIDLow"),
		m_iItemID = oc.get("C_EconItemView", "m_iItemID"),
		m_iAccountID = oc.get("C_EconItemView", "m_iAccountID"),
		m_bDisallowSOC = oc.get("C_EconItemView", "m_bDisallowSOC"),
		m_bInitialized = oc.get("C_EconItemView", "m_bInitialized"),
		m_bRestoreCustomMaterialAfterPrecache = oc.get("C_EconItemView", "m_bRestoreCustomMaterialAfterPrecache"),
		m_OriginalOwnerXuidLow = oc.get("C_EconEntity", "m_OriginalOwnerXuidLow"),
		m_OriginalOwnerXuidHigh = oc.get("C_EconEntity", "m_OriginalOwnerXuidHigh"),
		m_AttributeList = oc.get("C_EconItemView", "m_AttributeList"),
		m_hMyWearables = oc.get("C_BaseCombatCharacter", "m_hMyWearables"),
		m_designerName = oc.get("CEntityIdentity", "m_designerName"),
		m_vecAbsOrigin = oc.get("CGameSceneNode", "m_vecAbsOrigin"),
		v_angle = oc.get("C_BasePlayerPawn", "v_angle"),
		m_angEyeAngles = oc.get("C_CSPlayerPawn", "m_angEyeAngles"),
		m_vecAbsVelocity = oc.get("C_BaseEntity", "m_vecAbsVelocity"),
		
	)
	return offsets_obj

