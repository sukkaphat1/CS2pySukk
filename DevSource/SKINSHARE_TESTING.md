# Skin sharing: renderer test build

This build connects received loadouts to the native renderer. It is ready for
in-game testing; automated mapping tests do not prove rendering on every CS2 build.

## Install and test

1. Both testers exit CS2 and CS2py. Restarting Python alone does not replace the
   native DLL already loaded into the game.
2. Launch CS2 again, then run CS2pyDev.exe to download this DevSource build.
   For a source checkout, run main.py after pulling the updated source and DLL.
3. Enable SkinShare and use the existing relay settings. Enable SkinChanger
   when broadcasting your own selections. Join the same match.
4. Test an AWP, Glock, SSG08, and two different knives. Both testers should
   choose different paints for the same gun to check player separation.
5. Check third-person weapon appearance, weapon switches, deaths, respawns,
   reconnects, and disabling sharing. Test gloves separately.

Logs are in the Windows user profile:

- cs2py_skinshare_debug.log: `mapped player=... slot=... def=... paint_kit=...`
  confirms a fresh relay selection was mapped to receiver-local equipment.
- cs2py_dll.log: `skin-share renderer: version=2` confirms the new DLL loaded;
  `remote apply: player=... slot=... kind=... def=... paint=...` confirms the
  native identity checks passed and the apply functions were called.
- `received selection` includes the receiver's paint/mesh lookup;
  `remote skipped` identifies an ownership, visibility, or weapon-switch check
  that delayed applying a selection.

Neither log alone proves the intended model/material rendered successfully.
The renderer does not modify another person's computer or the game server.

## Implementation and boundaries

- All 64 bundled item entries use their local model path. Knife/glove paint
  compatibility comes from the same preview map used by the skin menu.
- Match roster SteamIDs resolve to local controller, pawn and active-weapon
  handles. The native code rechecks SteamID, pawn/controller linkage, full
  active handle, owner handle, health and weapon type before applying.
- Gloves use the pawn's inline glove item view and its reapply flag, without
  creating a second wearable or replacing the pawn's model.
- Selected loadouts renew every two seconds. Remote state expires after five
  seconds. The local bridge expires after three seconds if its writer stops.
- Relay sessions distinguish sequence resets. Relay state is ephemeral memory,
  refreshed after Durable Object hibernation, without per-update database writes.
- Render changes are capped at four target updates per 250 ms pass. Original
  cosmetic fields are restored when a target expires or is no longer selected,
  provided it still resolves to the same player and entity. Dropped/transferred
  entities are not written through their old owner mapping; the game's own
  refresh may be needed to remove their previous client-side appearance.
- Version 2 reapplies the mesh after material refresh, repairs later mesh resets,
  and allows two follow-up refreshes at 500 ms intervals after selection/scene
  changes. Brief sampling gaps get a 1.5 second restoration grace period;
  invalid/expired bridge sessions still stop applying immediately.
- Regression tests cover USP-S, AWP, M4A1-S, and Desert Eagle Printstream's
  distinct mesh settings. Retest both third-person USP-S and AWP Printstream
  after switching from a working skin, holding each weapon for three seconds.
- This build targets third-person equipment. Spectator first-person viewmodels
  and ragdolls do not have a separate applier. Glove refresh and knife animation
  behavior need visual validation on the installed game version.
- The relay's shared token does not verify ownership of a claimed SteamID.
  Entity matching prevents accidental cross-player application, but authenticated
  Steam identity would be needed before trusting arbitrary third-party clients.

## Automated checks

Run `python -m unittest discover -s tests -p test_skinshare_mapping.py -v`.
Run `node --test cloudflare/skinshare-relay/test/relay.test.js`.
Native fixture: compile dll/remote_mapping_tests.cpp CRT-free with kernel32.lib,
/GS-, /NODEFAULTLIB, /ENTRY:RemoteTestMain, /SUBSYSTEM:CONSOLE; exit code 0 passes.
The fixture uses allocated fake entities and never opens the game process.
