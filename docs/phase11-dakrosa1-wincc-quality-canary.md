# Phase 11: Dakrosa1 native WinCC quality correction

Release version: `1.5.26`.

This release corrects the read-only Dakrosa1 OLE DB canary's interpretation of
native WinCC quality codes.  It does not add a snapshot tag, promote a
diagnostic source, or change the portal contract.

## Root cause

The canary previously treated only quality values whose QQ bits were `11` as
good:

```text
(quality & 0xC0) == 0xC0
```

That is the narrower OPC representation, not the complete native WinCC
representation.  Siemens documents the native WinCC QQ bits as:

| QQ bits | Native WinCC meaning | Canary result |
| --- | --- | --- |
| `00` | Bad | not good |
| `01` | Uncertain | not good |
| `10` | Good (Non-Cascade) | good |
| `11` | Good (Cascade) | good |

Siemens also documents that native WinCC quality values from `0x80` through
`0xD4` are converted to OPC `0xC0`.  Therefore the production `u2_GV` quality
`0x80` (decimal 128) is Good (Non-Cascade), not bad.

Authoritative sources:

- [Siemens WinCC Professional V13 SP2 Programming Reference, sections 2.2.1.3 and Quality Codes in Communication with OPC, pages 195-199](https://cache.industry.siemens.com/dl/files/968/109747968/att_920887/v1/WCC_Professional_V13_SP2_Prog_enUS_en-US.pdf)
- [Siemens ASM System Manual, Quality Codes, page 146](https://cache.industry.siemens.com/dl/files/513/109768513/att_989333/v1/ASMSystemManual.pdf)

The corrected helper accepts native QQ values `10` and `11` while continuing
to reject Bad and Uncertain values.  Substatus and limit bits do not affect the
QQ mask.

## Production evidence before release

Dakrosa1 `1.5.25` was first observed publishing `u2_GV` through its unchanged
archive reader at `2026-07-15T00:01:01.502Z`.  In the next 84 consecutive
retained snapshots, the source contract contained 22 tags rather than 21, with
`u2_GV` as the only addition.

Three consecutive snapshots contained approximately 98.47%, 98.41%, and
98.70%.  A recent OLE DB ValueName canary independently resolved exact source
`U2\LCU2_db_Unit_stGov_nGV`, ValueID 31, in-range value 98.41%, and native
quality `0x80`.  Its previous `bad_quality` status was the classification bug
fixed by this release.  The five-minute apparent canary age is consistent with
its configured `TIMESTEP=300` aggregate and does not alter its diagnostic-only
transport flag.

The public production UI already consumes the unchanged snapshot source and
was observed rendering:

- MAIN: 28 of 37 native positions, with H2 guide vane filled.
- H2: 14 of 16 reviewed fields, leaving only native frequency and PF blank.
- AUX: 30 of 30 mapped readouts, while the three separate gate-state groups
  remain explicitly unknown.

## Release boundary

- Only `box/d1_oledb_canary.py`, its tests, this document, and `version.txt`
  change.
- Reader, archive decoder, Runtime probe, service loop, updater, OTA polling,
  installer, callback code, portal, and station mappings are unchanged.
- The canary remains read-only, diagnostic-only, authorized only for exact
  `Dakrosa1 --raw-canary` invocation, and never injects snapshot tags.
- Dakrosa2 never runs this canary and retains the exact request contract from
  `1.5.25`.
- No station host is contacted directly; both stations receive the release
  only through the existing OTA mechanism.

## Frequency hold

This correction does not make any Dakrosa1 frequency source usable.  Current
public raw evidence still shows:

- `bus_F`: confirmed fast-archive member but no data returned.
- `u1_F`, `u2_F`, `u3_F`: candidate namespaces only; each ValueName query
  returns COM error `0x80020009`.
- Speed-to-frequency conversion remains an inference and is not published as
  native frequency.

## Post-OTA verification gate

After both stations report `1.5.26` through the public API:

1. Confirm Dakrosa1 retains its existing 22-source-tag contract and no snapshot
   error.
2. Confirm its next raw canary reports `u2_GV` as `status=ok`,
   `quality=128`, `quality_good=true`, and increments `good` to one while
   keeping `realtime=false`.
3. Confirm all four frequency gaps retain their prior diagnostic result and no
   frequency tag enters the snapshot.
4. Confirm Dakrosa2 remains at 224 published tags, Runtime 209 attempted / 206
   accepted, exact diagnostics 92 requested / 91 found, and zero callback
   errors.

## Production result for 1.5.26

GitHub's raw `main` endpoint was observed exposing `1.5.26` at
`2026-07-15T01:10:44Z`.  Both stations then advanced through their existing
OTA path without direct host access:

- Dakrosa2 was first observed reporting `1.5.26` at `01:12:39.506Z`.
- Dakrosa1 was first observed reporting `1.5.26` at `01:13:54.519Z`.

The first retained Dakrosa1 raw shipment after the update was received at
`01:13:59.236Z`.  Its canary, recorded at `01:13:10Z`, attempted five exact
sources, observed one, and classified one as good.  The `u2_GV` result was
`98.1500015`, native quality `128`, `quality_good=true`, `status=ok`, and
`realtime=false`.  The snapshot contract retained 22 source tags and 30 tags
after server derivation, with no station error.

All frequency holds remained unchanged in the same canary: `bus_F` returned
`no_data`, while `u1_F`, `u2_F`, and `u3_F` each returned a fail-closed COM
`query_error`.  No frequency value entered the snapshot contract.

Dakrosa2 retained 224 source tags, Runtime mode, 209 attempted / 206 accepted /
3 rejected curated sources, 93 attempted / 91 accepted required sources, and
zero callback errors.  Its post-update raw shipment, received at
`01:14:10.099Z`, retained the exact diagnostic contract at 92 requested / 91
found, with only `DCTC-` missing and no denied source.  `H2Excit` and
`H3Excit` both remained Binary values of zero with state zero, so their
diagnostic-only hold was unchanged.

The post-OTA verification gate passed.  No reader, service, updater, OTA,
canonical mapping, or portal behavior changed in this release.
