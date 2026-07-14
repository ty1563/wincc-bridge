# Phase 5: Dakrosa2 operator-screen exact diagnostics

Release version: `1.5.20`.

This release adds four native names to the bounded, read-only
`runtime_probe.exact` payload for Dakrosa2:

- `Connect`
- `EVENT_TYPE_MH1`
- `EVENT_TYPE_MH2`
- `EVENT_TYPE_MH3`

They are diagnostic-only. The release does not create canonical keys, change
the normal snapshot, write to WinCC, or infer a state from station online
status. The complete Dakrosa2 exact list increases from 83 to 87 names.

## Evidence and current uncertainty

`Connect` is an exact native source in recovered `CUA DAP.PDL` (SHA-256
`A6A8A54E8CFA769D29437713336B26C4AB8AB3244D78E08332735AFE36BB5002`).
Its native lamp uses red for true and light gray for false, so true represents
the displayed connection-fault state. This polarity is recorded for later
review but is not promoted in this release.

`EVENT_TYPE_MH1` is the fourth, blue curve in recovered `PA5_bld04.PDL`
(SHA-256
`88F334E83362ECDA93219B93B112C2F228C29D2DB0CB7DB2C0413F3F7E981898`).
The archive metadata also identifies the three exact names as ValueIDs 40,
308, and 375. Their archive blocks are fresh, but the current analog decoder
returns no decoded samples. Runtime type/state/value evidence is therefore
required before any trend or event mapping.

## Isolation boundary

- The default exact list is enabled only when the configured station identity
  is `Dakrosa2` and the active Runtime project basename is exactly
  `WInCC_Backup_30_10_2020.mcp` (case-insensitive).
- Dakrosa1 and every mismatched or unknown project request zero default exact
  diagnostics.
- `Click*` and every name containing `command` remain hard-denied.
- `STATION2_CURATED_SPECS` is unchanged; none of the four names can enter the
  public canonical snapshot in this release.
- The updater, OTA interval, service registration, installer, reader mode,
  callback canary, and WinCC binaries are unchanged. `version.txt` is the only
  fleet release trigger.

## Post-OTA evidence gate

After both stations report `1.5.20`:

1. Confirm Dakrosa1 remains healthy with its existing source-tag count and no
   new default Runtime exact reads.
2. Confirm Dakrosa2 remains healthy and reports
   `runtime_probe.exact.requested == 87` with no denied channels.
3. Capture at least two fresh Dakrosa2 raw shipments and record found/missing,
   type, state, value, and per-tag error for all four names.
4. Keep a source diagnostic-only if it is missing, stale, non-numeric,
   type-mismatched, non-finite, or has a nonzero Runtime state.
5. Promote a source only in a later, separately reviewed bridge and portal
   release with exact native semantics and freshness handling.

If either station regresses, revert the diagnostic change, publish a higher
version, and verify both stations again. Never downgrade `version.txt` or
modify the OTA/service installation in place.
