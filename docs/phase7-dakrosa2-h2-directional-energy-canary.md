# Phase 7: Dakrosa2 H2 directional-energy diagnostic canary

Release version: `1.5.22`.

This release adds four exact native names from the complete
`BangkwhH2.PDL` child picture to the bounded, read-only
`runtime_probe.exact` diagnostic payload:

- `MWHPX_INTER_MH2` (`AP+`)
- `MWHNX_INTER_MH2` (`AP-`)
- `MVARHPX_INTER_MH2` (`AQ+`)
- `MVARHNX_INTER_MH2` (`AQ-`)

They remain diagnostic-only.  This release does not add canonical keys,
change the normal Runtime snapshot, populate the portal, or write to WinCC.
The complete Dakrosa2 exact request count increases from 86 to 90.

## PDL evidence

The only complete recovered directional-energy child is:

`outputs/dakrosa2_dump_carve/pdl/BangkwhH2.PDL`

Its SHA-256 is:

`E7538B40AA77B1D41988E9ED6AE3E433DBFE9FB0149C3A8B600CEC7CA8EE5FAD`

The four visible rows have direct `OutputValue` links to the four exact names
above.  This proves the native names, row direction, and display purpose.  It
does not prove that the active Runtime currently exposes the tags, nor their
current type, state, engineering scale, or freshness.

The incomplete H1 and H3 child fragments are not used.  No inferred
`*_MH1` or `*_MH3` names are requested.

## Isolation and release boundary

- The default exact list is enabled only when configured station identity is
  `Dakrosa2` and the active Runtime project basename is exactly
  `WInCC_Backup_30_10_2020.mcp` case-insensitively.
- Dakrosa1 and every unknown or mismatched project request zero default exact
  diagnostics.
- The four names are disjoint from `STATION2_CURATED_SPECS`; they cannot enter
  the public canonical snapshot in this release.
- `Click*` and every name containing `command` remain hard-denied.
- `H1_temp11` is deliberately excluded because historical WinCC diagnostics
  repeatedly report data-type error `c0040004`; it remains blank.
- `EVENT_TYPE_MH1/2/3` remain diagnostic-only because production returned
  Runtime state 257.
- The reader, service loop, updater, OTA polling, installer, callback canary,
  and WinCC binaries are unchanged.  `version.txt` is the existing fleet OTA
  trigger and advances only from `1.5.21` to `1.5.22`.

## Pre-release production baseline

Observed on `2026-07-14` before the release:

- Dakrosa1 reported `1.5.21` at `15:25:30.792Z`, published 29 tags, and had no
  snapshot error.
- Dakrosa2 reported `1.5.21` at `15:25:43.999Z`, remained in Runtime mode,
  published 208 tags, and had no snapshot error.
- The latest Dakrosa2 raw shipment was received at `15:24:00.132Z`, used
  project `WInCC_Backup_30_10_2020.mcp`, requested 86 exact names, found 85,
  denied none, and missed only the already-known `DCTC-`.

## Post-OTA evidence gate

After both stations report `1.5.22`:

1. Confirm Dakrosa1 retains 29 published tags, no snapshot error, no Dakrosa2
   curated source attempts, and zero default exact diagnostics.
2. Confirm Dakrosa2 remains in Runtime mode with no snapshot or callback
   regression and reports `runtime_probe.exact.requested == 90`.
3. Capture at least two fresh raw shipments and record found/missing, type,
   type size, value, Runtime state, and per-tag error for all four names.
4. Keep a source diagnostic-only if it is missing, stale, non-numeric,
   non-finite, type-mismatched, state-nonzero, or physically implausible.
5. Promote only in a later separately reviewed bridge and portal release.
   Preserve AP+/AP-/AQ+/AQ- direction and raw units; do not derive one row
   from another counter.

If either station regresses, publish a separately reviewed higher version.
Never downgrade `version.txt` or modify the installed OTA/service mechanism in
place.

## Production result for 1.5.22

Both stations advanced through the existing OTA path without direct host
access.  Dakrosa2 first reported `1.5.22` at `2026-07-14T15:37:31.805Z`;
Dakrosa1 reported it at `15:38:07.905Z`.

- Dakrosa1 retained 29 published tags and no snapshot error.
- Dakrosa2 retained 208 published tags in Runtime mode, with 193 curated
  attempts, 190 accepted samples, and zero callback errors.
- The exact list increased to 90 as designed, found 89 names, denied none,
  and continued to miss only `DCTC-`.

Two independent post-OTA raw shipments were reviewed:

| Received | Dump time | Exact result | Four H2 sources |
| --- | --- | --- | --- |
| `15:39:01.938Z` | `15:38:10Z` | 90 requested, 89 found | UInt32, size 4, value 0, state 0 |
| `15:44:00.560Z` | `15:43:10Z` | 90 requested, 89 found | UInt32, size 4, value 0, state 0 |

All four sources pass the Runtime availability, type, and state transport
gate.  They remain diagnostic-only: both samples are unchanged zero, while
the parallel archive evidence for the directional-energy family is not an
independent corroboration because multiple names decoded from identical
blocks and values.  A zero is therefore not yet treated as a trustworthy
operator counter or rendered in the portal.  No canonical key is authorized
by this result.
