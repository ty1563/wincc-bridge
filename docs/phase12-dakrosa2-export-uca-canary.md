# Phase 12: Dakrosa2 export-meter UCA diagnostic canary

Release version: `1.5.27`.

This release demotes the never-delivering 22 kV export-meter line-line
voltage source `LV-UCA` from the curated Dakrosa2 Runtime specs into the
bounded, read-only `runtime_probe.exact` diagnostic payload.  No canonical
key is added, no portal contract changes, and nothing is written to WinCC.

## Root cause and evidence

The curated spec `("UCA", ("bus_U31", "lv_U31"), 0.0, 50000.0)` has requested
`LV-UCA` on every snapshot cycle since the 22 kV meter aliases landed in
`1.5.16`.  Public production payloads on `2026-07-17` and `2026-07-18`
(`/api/dakrosa/wincc/latest?station=Dakrosa2`, 224 published tags) contain no
`bus_U31` or `lv_U31` sample, while the sibling sources deliver live values:

- `lv_U12`/`bus_U12` (LV-UAB path, with the historical Uptb patch) ~23.7 kV,
- `lv_U23`/`bus_U23` (LV-UBC) ~23.75 kV,
- phase voltages `LV-UA/UB/UC` and `LV-Utb` publish normally.

The curated snapshot path silently drops sources that do not resolve or carry
a bad Data Manager state, so production evidence cannot distinguish between:

1. the tag name being absent from the Data Manager,
2. the tag existing with a permanently bad state or quality, or
3. the tag existing with a value rejected by bounds.

The exact probe reports found/missing per name plus DMCLIENT type, state, and
raw value, which is precisely the missing evidence.  The portal already has
consumer slots waiting on `bus_U31` (bus UCA readout and the three-phase
voltage-imbalance metric), so a future promotion needs no portal work.

## Change list

- `box/wincc_runtime.py`: remove the `UCA` row from the curated 22 kV
  `bus_metrics`; add `EXPORT_METER_DIAGNOSTIC_TAGS = ("LV-UCA",)` and append
  it to `SCADA_DIAGNOSTIC_TAGS` (exact request count 92 to 93).  A name must
  not sit in both the curated specs and the exact list, mirroring the Connect
  precedent from `1.5.21`.
- `test_wincc_runtime.py`: curated-spec contract counts 209/228 to 208/226;
  exact requested count 92 to 93; new contract test asserting the tuple, the
  curated/diagnostic disjointness, and that no curated spec still carries
  `bus_U31`/`lv_U31` keys.
- `docs/phase12-dakrosa2-export-uca-canary.md` (this document) and
  `version.txt` `1.5.26` to `1.5.27`.

## Isolation and release boundary

- The change is Dakrosa2-only (`STATION2_CURATED_SPECS` and the station-2
  exact probe).  Dakrosa1 keeps its pinned legacy reader and is untouched.
- Removing a spec that never published a sample cannot change any published
  canonical value.  It removes one permanently failing request from the
  required-completeness denominator, which can only make the fast-path ratio
  better, never worse.
- The exact probe remains read-only, bounded, and diagnostic-only.  No
  canonical snapshot tag, no OTA schedule change, no config change, no direct
  station contact: both stations receive the release only through the
  existing `version.txt` OTA mechanism.
- Do not synthesize UCA from the phase-neutral voltages (`LV-UA/UB/UC`):
  line-line magnitude requires phase angles the meter does not export.

## Success criteria

1. Two independent production Runtime shipments at `1.5.27` contain the
   `LV-UCA` entry in `runtime_probe.exact` (found or missing).
2. The evidence classifies the failure mode:
   - `missing` in both shipments: the Data Manager does not expose the name;
     the gap is plant-side (meter/PLC/WinCC tag), and a follow-up release
     retires the diagnostic name with that verdict documented.
   - found with `state != 0` or out-of-bounds values: keep diagnostic and
     record the state; promotion stays blocked until healthy.
   - found with `state == 0` and plausible ~23-24 kV values in both
     shipments: a follow-up release re-promotes the curated `UCA` row
     unchanged, and the portal UCA + voltage-imbalance fields light up with
     no portal change.
3. Dakrosa2 keeps its established canonical tag count and fast-path health
   after OTA; Dakrosa1 stays at its current source-tag count with no
   snapshot error.

## Post-OTA verification gate

After both stations report `1.5.27` through the public API:

1. Confirm Dakrosa2 still publishes its established canonical tag set minus
   nothing (the demoted spec never published) and the fast path stays
   healthy.
2. Read two fresh raw shipments and record the `LV-UCA` exact-probe result
   verbatim in this document's addendum before any promotion decision.
3. Confirm Dakrosa1 remains healthy with its existing published-tag count
   and no snapshot error.
