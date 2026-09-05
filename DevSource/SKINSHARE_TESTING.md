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
   reconnects, and disabling sharing. Gloves are disabled and removed from the menu.

Logs are in the Windows user profile:

- cs2py_skinshare_debug.log: `mapped player=... slot=... def=... paint_kit=...`
  confirms a fresh relay selection was mapped to receiver-local equipment.
- cs2py_dll.log: `skin-share renderer: version=5` confirms the new DLL loaded;
  `remote apply: player=... slot=... kind=... def=... paint=...` confirms the
  native identity checks passed and the apply functions were called.
- `received selection` includes the receiver's paint/mesh lookup;
  `remote skipped` identifies an ownership, visibility, or weapon-switch check
  that delayed applying a selection.

Neither log alone proves the intended model/material rendered successfully.
The renderer does not modify another person's computer or the game server.

## Implementation and boundaries

- All 54 supported gun/knife entries use their local model path. Knife paint
  compatibility comes from the same preview map used by the skin menu.
- Match roster SteamIDs resolve to local controller, pawn and active-weapon
  handles. The native code rechecks SteamID, pawn/controller linkage, full
  active handle, owner handle, health and weapon type before applying.
- Gloves are blocked in the menu, local config writer, sender, receiver, and
  native renderer. Old saved glove settings are ignored, not deleted.
- Selected loadouts renew every two seconds. Remote state expires after five
  seconds. The local bridge expires after three seconds if its writer stops.
- Relay sessions distinguish sequence resets. Relay state is ephemeral memory,
  refreshed after Durable Object hibernation, without per-update database writes.
- Render changes are capped at four target updates per 250 ms pass. Original
  cosmetic fields are restored when a target expires or is no longer selected,
  provided it still resolves to the same player and entity. Dropped/transferred
  entities are not written through their old owner mapping; the game's own
  refresh may be needed to remove their previous client-side appearance.
- Version 3 shares the exact local attribute/composite-material routine with
  remote weapons. Mesh updates also reach the ownership-checked weapon attachment
  and matched pawn's HUD children, as in the local rendering path.
- Repeated scheduled material rebuilds were removed. Network fallback-field
  resets are repaired with field writes; heavy refreshes are limited to selection,
  scene replacement, or detected attribute changes. Owned holstered weapons have
  separate caches, preventing a restore/reapply cycle on each weapon switch.
- Brief sampling gaps get a 1.5 second restoration grace period; invalid/expired
  bridge sessions still stop applying immediately.
- Regression tests cover USP-S, AWP, M4A1-S, and Desert Eagle Printstream's
  distinct mesh settings. Retest both third-person USP-S and AWP Printstream
  after switching from a working skin, holding each weapon for three seconds.
- Knives follow the working local materials/model/HUD/subclass/viewmodel-update
  sequence, including an attachment refresh request. Missing required refresh
  functions block a remote knife swap. No guessed hand transforms are written.
- Third-person hand placement and UV correctness still require visual validation
  on this game build. First-person spectator behavior and ragdolls are not verified.
- The relay's shared token does not verify ownership of a claimed SteamID.
  Entity matching prevents accidental cross-player application, but authenticated
  Steam identity would be needed before trusting arbitrary third-party clients.

## Version 4: weapon transfers and integrity checks

- After a verified local/shared application, the receiver remembers that physical
  weapon's paint, seed, wear, mesh and knife model. A different holder's loadout
  cannot replace it. The original selecting player can update it when holding it
  again. This works in both directions; a different AWP still uses its own skin.
- Bindings use receiver-local full handles, entity/identity pointers and original
  owner XUID, and are discarded on an observed map/entity-list transition or slot
  serial change. Before applying, the current owner's controller/pawn relationship,
  full active handle, owner handle, health and non-dormant scene are checked again.
  Cached ground-weapon pointers are never used to write while a gun is dropped.
- Both testers must have observed the donor's shared weapon before it was dropped.
  This is per-client, in-match memory, not persistent inventory or a relay item
  history. A late joiner/restarted client cannot recover an unseen gun's old skin.
  The bounded cache holds up to 256 observed weapons and does not evict live ones.
- Previously observed donor bindings survive a temporary relay gap in the same
  match; no new peer updates are applied from an expired bridge. Restarting CS2
  clears the history. No Worker/protocol update is required for this version.
- Local and remote attribute integrity is checked every 250 ms (previously the
  remote attribute check waited two seconds; local only re-poked fallback fields).
  Missing paint/seed/wear attributes count as incorrect, even if fallback fields
  are correct. Heavy reset repairs have a 750 ms cooldown; the remote batch still
  has a four-target budget. Selection/context changes are applied promptly.
- Fallback fields and mesh-only resets use lightweight repairs. Pawn/full-handle,
  scene and attachment changes force presentation refreshes. Local respawns also
  get one delayed settle refresh, not a permanent material-refresh timer.
- The checks inspect item/material inputs, not rendered pixels. A blank texture
  with all inspected state correct cannot be detected reliably by these checks.
  Rendering, knife animations and gameplay performance still need live testing.

Restart **CS2 and the tool on both PCs** before testing (restarting only the Python
tool can leave the previous injected DLL loaded). Confirm `version=4` in the log.

1. Choose different AWP paints, let each player hold theirs for three seconds,
   then drop and exchange them. Each gun should retain its donor's paint. Switch
   away/back, drop it again and return it. Also test a separately bought AWP.
2. Repeat with USP-S Printstream and inspect both first- and third-person views.
   Move, switch weapons, and check whether any blank or flashing material returns.
3. Select Butterfly Gamma Doppler with seed 400. Die/respawn several times, then
   inspect after one second. Confirm paint **and seed 400**, not only knife model.
4. If it fails, collect both DLL and skin-share logs with the exact gun, paint,
   seed, pickup/respawn event and viewing perspective. `local apply` reports
   `inherited=1` for a remembered donor gun and the refresh reason.

## Version 5: selection settling, switch stability and diagnostics

The reviewed version-4 logs showed the same remote knife/entity repeatedly
applied with `reason=selection`, with bridge target gaps between updates. Local
weapon switches also triggered full applications of unchanged selections. These
are confirmed refresh/cache issues, not proof that the relay lost a seed.

- Local weapons now have separate bounded caches. Switching back, or briefly
  seeing an invalid active handle, does not by itself rebuild an unchanged skin.
- A verified remote holstered weapon retains its cache even when the newly held
  gun has no selected/shared skin and therefore produces no bridge target.
  Active-target sampling gaps have a three-second grace period. Expired bridge
  sessions stop peer applications; restoration only calls game functions for a
  currently active, living, non-dormant, ownership-verified target.
- Every new selection or presentation context schedules one material-only
  finalization after 750 ms. This covers model initialization clearing materials
  while paint/seed attributes remain correct. Neither this finalization nor a
  paint-only change resets a correct knife world model. Repeated timer-based
  finalizations are not scheduled for a stable weapon.
- HUD child recreation is tracked as well as weapon scene/attachment changes.
  This detects more viewmodel lifecycle changes without guessing transforms.
- Local config updates are atomic, can commit changes every 100 ms, and retry
  failed replacements. The native parser commits only complete valid loadouts.
  Remote bridge writes/reads use 250 ms cadence; network and roster-sampling
  latency still exist. This is not a guarantee of instantaneous presentation.
- Entity-list pointer reads have additional readability guards. A process-scoped
  singleton prevents two **version-5** cosmetic loops after restarting the tool.
  It cannot stop an already loaded older renderer: a full CS2 restart is required.
- The optimized fake-memory test exposed recursive compiler optimization of a
  CRT replacement copy helper. Volatile byte accesses prevent that recursion.
  This was reproduced and fixed in testing; it does not establish the cause of
  a reported crash on another PC. Concurrent game lifecycle races remain possible.
- Refresh begin/completion logs now include paint and seed, and distinguish
  `material_finalize` from selection/state repairs. Bridge logs include seeds.
  A begin line without completion helps narrow a crash but is not a stack trace.

**Testing:** restart CS2 and the Dev launcher on both PCs, confirm `version=5`,
then choose Butterfly Gamma Doppler/seed 400 before joining. Hold it for two
seconds, inspect both views, respawn and retest. Change AWP Printstream while
the other tester watches; switch to a gun with no selected skin and back; repeat
the donor drop/pickup checks. Gloves remain disabled.

Pixels are not inspected by the integrity checks. Do not call a blank material
fixed, or a crash resolved, based only on correct attributes or passing fixtures.
For a crash, provide the console traceback (if any), both cosmetic logs and the
crash time; a game crash dump/faulting module is needed for native stack analysis.

## Automated checks (current)

Run `python -m unittest discover -s tests -p test_skinshare_mapping.py -v`.
With the installed application Python runtime/dependencies, run
`python -m unittest discover -s tests -p "test_skin*.py" -v` to include the atomic
writer/retry tests. Native fixtures also simulate model setup clearing materials
while attributes remain correct, material-only finalization, cache retention across
unconfigured weapons, local switch reuse, and incomplete config rejection.
Run `node --test cloudflare/skinshare-relay/test/relay.test.js`.
Native fixture: compile dll/remote_mapping_tests.cpp CRT-free with kernel32.lib,
/GS-, /NODEFAULTLIB, /ENTRY:RemoteTestMain, /SUBSYSTEM:CONSOLE; exit code 0 passes.
The fixture uses allocated fake entities and never opens the game process.
