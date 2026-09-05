# Renderer v6: disabled writes, radar overhead and teardown

## Evidence and changes

- The supplied console log contains unhandled error-299 memory reads in the
  combined update and FOV worker after game teardown. The initial reads are now
  guarded; FOV periodically reacquires its process/module and closes handles.
- Disabled anti-flash previously wrote 255.0 every overlay frame. Disabled FOV
  forced 90. Both now perform no game writes when off, including restoration.
  Enabled updates compare current fields and revalidate the living local pawn.
- Radar previously traversed 64 slots and wrote spotted fields every frame.
  It now polls at most 10 Hz, skips unchanged fields and rechecks identity before
  writing. Disabled radar returns before reading game memory. Slot 64 is included;
  the entity-list chunk-address precedence error was also corrected in ESP.
- The overlay snapshots offsets/options once per frame instead of repeatedly
  accessing Manager proxies per player/field. Skeletons use one 716-byte bone
  read instead of 17 individual reads. Life state is read as one byte.
- Both cosmetic toggles off now clear the local config and publish a stop once.
  No injection occurs. The retired direct external attribute writer cannot bypass
  the native control path. Sharing's disabled bridge is cleared only once.
- The native renderer requires PID-matched permission refreshed every 250 ms,
  expiring after 1.5 seconds. It independently checks full engine sign-on, rules,
  entity-list and local-pawn roots. Toggle changes, expiry and session changes
  invalidate bookkeeping without chasing old entities to restore cosmetics.
- Local loadout off does not prevent shared donor-weapon pickup rendering if
  sharing remains on. Both toggles must be off to stop all cosmetic writes.
- Native root globals are copied with ReadProcessMemory rather than directly
  dereferencing an unloaded module. Client/engine loader references are held only
  during a pass. A changed/reacquired module causes function resolution again.
- Match diagnostics avoid traversing players outside a live connection.

## What is and is not verified

38 Python regression tests pass with fake process memory. They cover disabled
writes, teardown errors, changed-only updates, stale identity rejection, radar
polling/slot 64, one-read bones, control publication and disabled config clearing.
The optimized CRT-free native fixture passes checks 1–74, including existing skin
mapping/pickup/model tests and new disable, expiry, sign-on and invalid-root cases.
The shipping DLL builds successfully with the same optimized flags.

The latest native dump (September 5, 11:30) faults in animation cleanup, reading
an invalid pointer. That identifies the crash site, not the writer that caused
the corruption. An earlier dump also exposed an unloaded-client global access.
No dump or automated fixture proves the animation crash eliminated.

Important remaining limitation: cosmetic calls still run on a background thread.
Loader references protect module code, not engine-owned entities or render jobs;
identity checks do not lock object lifetime. Engine-safe scheduling requires a
separate design if crashes persist. Adding more frequent forced refreshes is not
a demonstrated solution. Existing trigger-click/bhop sleeps can also stall the
overlay while those actions run; they are separate from radar's frame workload.

## Retest

1. Fully exit CS2 and the tool, then launch the updated build. A Python-only
   restart can retain an older native renderer. Both testers need renderer v6.
2. Start a local match with anti-flash, FOV, radar and both cosmetic toggles off.
   Observe skeleton smoothness, then end/rejoin the match several times.
3. Compare radar off/on in the same map and roster. Try anti-flash separately.
4. Enable local/shared skins and test spawn, switch, pickup and match exit.
5. If a native crash recurs, keep its timestamp and fresh dump plus both logs.

Disabling a feature stops writes; it does not immediately undo an already applied
FOV, flash-alpha or cosmetic value. Engine refresh, respawn or a fresh game start
may be necessary to reset those values. No new runtime match test was performed
while preparing this build. No crash dumps, tokens or settings were uploaded.
