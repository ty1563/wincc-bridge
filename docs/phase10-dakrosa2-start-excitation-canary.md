# Phase 10: Dakrosa2 start-excitation diagnostic canary

Release version: `1.5.25`.

This release adds `H2Excit` and `H3Excit` to the bounded, read-only Runtime
exact probe.  The two native values remain diagnostic-only until at least two
independent fresh raw shipments establish their Runtime type, state, quality,
value range, and display meaning.  No canonical snapshot key or portal field
is added in this release.

## Recovered source evidence

The reviewed station-2 project contains matching excitation sources on the H2
and H3 start pictures:

| Picture | SHA-256 | Recovered object evidence |
| --- | --- | --- |
| `A_H2_chart_kd.PDL` | `D5FF5F26BB2E8818BB8FED27B2BDB5BC7AC098E47971FCD167C3555762CCA370` | `Button1` at recovered object offset `0x53ee`, caption `ĐÓNG KÍCH TỪ`, `apicf.dll/GetTagDouble`, value source and `CTrigger` both `H2Excit` |
| `A_H3_chart_kd.PDL` | `2F777989AC744F85461EE34444337D391308A50F6B141C6CFD4703B340EC9F63` | `Button1` at recovered object offset `0x53e8`, caption `ĐÓNG KÍCH TỪ`, `apicf.dll/GetTagDouble`, value source and `CTrigger` both `H3Excit` |

The recovered PDL establishes exact tag identity and a read-only display path;
it does not by itself establish type, scale, polarity, or the semantic mapping
of the returned numeric value.  `H1Excit` is deliberately excluded because
the H1 object reads `H1Excit` but its recovered trigger references `H2Excit`,
which is a cross-unit ambiguity.

## Runtime contract

- The exact diagnostic request increases from 90 to 92 names.
- The two names are requested only for configured station `Dakrosa2` when the
  active Runtime project basename is exactly
  `WInCC_Backup_30_10_2020.mcp`, case-insensitively.
- Dakrosa1 and every mismatched project request zero Phase 10 names.
- The names stay disjoint from curated canonical specs, so they cannot enter a
  station snapshot or the portal by accident.
- The probe only enumerates, resolves type, and reads values.  It never writes
  a WinCC tag.

## Release boundary

- Reader, archive decode, service loop, callback subscription, updater, OTA
  polling, installer, and WinCC binaries are unchanged.
- No station host is contacted directly.  Both stations receive the higher
  `version.txt` only through the existing OTA mechanism.
- `DCTC-`, `EVENT_TYPE_MH1`, `H1Excit`, `H1-Frequ`, the three `Hn-Speed`
  candidates, the six type-mismatched valve sources, and `H1Brakeopen` remain
  diagnostic or hold items rather than being promoted.
- `Click*`, command, setpoint, and other write-capable channels remain excluded
  or hard-denied.

## Pre-release production baseline

Immediately before release, Dakrosa1 and Dakrosa2 both reported `1.5.24` and
were online.  Dakrosa1 retained 29 published tags.  Dakrosa2 retained 224
published tags, attempted 209 curated Runtime sources, accepted 206, rejected
the same three optional samples, and reported zero callback errors.

The latest complete Dakrosa2 raw shipment requested 90 exact diagnostic names,
found 89, and missed only `DCTC-`.  It decoded 359 of 359 shipped ValueIDs from
1,107 blocks without truncation.

## Post-OTA evidence gate

After both stations report `1.5.25` through the public API:

1. Confirm Dakrosa1 retains its existing published contract and has no new
   Phase 10 attempts.
2. Confirm Dakrosa2 remains in Runtime mode, keeps 209 curated attempts and
   zero callback regression, and requests exactly 92 diagnostic names.
3. Capture at least two independent fresh raw shipments and record, for both
   names, whether they are found plus their type, size, value, state, quality,
   and error fields.
4. Keep the names diagnostic-only if either sample is absent, nonzero-state,
   unstable, or semantically ambiguous.  A later reviewed release is required
   before any canonical or portal mapping.

## Production result for 1.5.25

The GitHub raw `main` endpoint was observed exposing `1.5.25` by
`2026-07-14T17:09:41Z`.  Both stations then advanced through their existing
OTA path without direct host access:

- Dakrosa2 was first observed reporting `1.5.25` at `17:11:56.193Z`, retained
  224 published tags, remained in Runtime mode, attempted 209 curated specs,
  accepted 206, rejected the same three optional samples, and retained zero
  callback errors.
- Dakrosa1 was first observed reporting `1.5.25` at `17:13:17.061Z`, retained
  its existing 21 source tags and 29-tag server-enriched contract, and reported
  no snapshot error.  No Dakrosa1 reader, curated mapping, service, or OTA
  behavior changed.

Two independent fresh Dakrosa2 raw shipments confirmed the new exact contract:

| Received UTC | Dump UTC | Exact result | `H2Excit` | `H3Excit` |
| --- | --- | --- | --- | --- |
| `17:12:52.868Z` | `17:12:00Z` | 92 requested, 91 found; only `DCTC-` missing; none denied | ID 1776, Binary type 1, size 1, value 0, state 0, quality null | ID 1867, Binary type 1, size 1, value 0, state 0, quality null |
| `17:17:51.874Z` | `17:17:02Z` | 92 requested, 91 found; only `DCTC-` missing; none denied | ID 1776, Binary type 1, size 1, value 0, state 0, quality null | ID 1867, Binary type 1, size 1, value 0, state 0, quality null |

The public portal contract remained stable at 91 of 92 allowlisted raw values
and all 100 readouts; the unrelated optional
`scada_aux_lcu41_iw0_raw` remained the only absent raw value.  Both stations
continued to report online without API errors.

The two samples confirm consistent tag identity and binary type, with Runtime
state zero in both samples, but both values were also zero.  They do not yet
prove polarity or whether the source represents excitation status versus
command availability.  Both names therefore remain diagnostic-only and no
portal mapping is introduced.
