# Phase 8: Dakrosa2 parameter-screen diagnostic canary

Release version: `1.5.23`.

This release adds the 16 currently blank native sources from the three unit
parameter pictures to the bounded, read-only `runtime_probe.exact` diagnostic
payload.  They do not enter the canonical snapshot or portal in this release.

## Exact diagnostic sources

- `H1_temp11`
- `H1-KW1`, `H1-KWA1`, `H1-KW3`, `H1-KWA3`, `H1-KVArh`
- `H2-KW1`, `H2-KWA1`, `H2-KW3`, `H2-KWA3`, `H2-KVArh`
- `H3-KW1`, `H3-KWA1`, `H3-KW3`, `H3-KWA3`, `H3-KVArh`

The complete Dakrosa2 exact request count increases from 90 to 106.

## PDL and archive evidence

The sources are direct `OutputValue` links recovered from
`A_H1_chart_par.PDL`, `A_H2_chart_par.PDL`, and `A_H3_chart_par.PDL`.  Their
reviewed source SHA-256 values are:

- H1: `A813F5789D2E653CC7CF536BE2352FABE77A359AD9357BA8C046E01512F35E3B`
- H2: `3E44968B1495A12010601AA1B501022E5FEF3DCAC3508C7C00ACD589821906CD`
- H3: `A5064A659FAC196129562C665E334B93524E8401E4718E5E6124422424A46CBF`

The twelve `KW1/KW3/KWA1/KWA3` sources also appeared in two independent raw
archive shipments received at `2026-07-14T15:29:01Z` and `15:34:04Z`.  Their
values were finite and moved plausibly between shipments.  Examples include
H1 `KW1` 368.799 to 371.011, H2 `KW3` 433.600 to 437.976, and H3 `KWA1`
241.399 to 243.241.

That archive evidence does not contain DMCLIENT type or state, so it supports
an exact Runtime canary only.  It is not authorization to publish canonical
values.

Important native-name boundaries:

- `KWA1/KWA3` are native tag names, but the PDL labels the fields QA/QC and
  displays kVAr.  They must not be renamed or interpreted as apparent power
  kVA.
- `H1_temp11` is referenced independently by the H1 parameter, unit, and
  turbine pictures, but historical WinCC diagnostics report data-type error
  `c0040004`.  It remains diagnostic-only even if the name is found.
- `Hn-KVArh` is an exact source string in each parameter picture, but the raw
  archive supplied no sample and the recovered display metadata is not
  sufficient to authorize a scale or unit.

## Isolation and release boundary

- The default exact list runs only for configured station `Dakrosa2` when the
  active Runtime project basename is exactly
  `WInCC_Backup_30_10_2020.mcp` case-insensitively.
- Dakrosa1 and every unknown or mismatched project request zero default exact
  diagnostics.
- All 16 names are disjoint from `STATION2_CURATED_SPECS`.
- `Click*` and every name containing `command` remain hard-denied.
- The portal remains unchanged and continues to show these fields as
  unavailable instead of deriving or inventing values.
- The reader, service loop, updater, OTA polling, installer, callback canary,
  and WinCC binaries are unchanged.  `version.txt` is the existing fleet OTA
  trigger and advances only from `1.5.22` to `1.5.23`.

## Pre-release production baseline

Before release, both stations were healthy on `1.5.22`:

- Dakrosa1: 29 published tags and no snapshot error.
- Dakrosa2: 208 published tags in Runtime mode; 193 curated attempts, 190
  accepted; zero callback errors.
- Dakrosa2 exact diagnostics: 90 requested, 89 found, no denied names, and
  only the already-known `DCTC-` missing.

## Post-OTA evidence gate

1. Confirm both stations advance to `1.5.23` through the existing OTA path.
2. Confirm Dakrosa1 retains 29 tags, no error, and zero default exact reads.
3. Confirm Dakrosa2 remains in Runtime mode without snapshot or callback
   regression and reports `runtime_probe.exact.requested == 106`.
4. Review at least two fresh raw shipments.  For every new source, record
   found/missing, Runtime type and size, value, state, quality, and error.
5. Promote only finite numeric sources with state zero and plausible values in
   a later separately reviewed bridge and portal release.  Keep
   `H1_temp11`/`Hn-KVArh` diagnostic if type, state, scale, or units remain
   unresolved.

If either station regresses, publish a separately reviewed higher version.
Never downgrade `version.txt` or modify the installed OTA/service mechanism in
place.
