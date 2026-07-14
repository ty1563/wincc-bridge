# Phase 4: Dakrosa2 MHY_2 and start-sequence diagnostic canary

Released version: `1.5.18`, commit `c6af40f`.

This release expands only the bounded, read-only `runtime_probe.exact`
diagnostic payload for `Dakrosa2`. It does not publish a new canonical tag,
does not change the normal Runtime snapshot, and does not write to WinCC.

## Release boundary

- `probe_runtime()` enables the default exact list only when both the configured
  `WINCC_STATION_NAME` identity passed to the reader and the active Runtime
  project filename match the reviewed Dakrosa2 identity. The current production
  project allowlist contains only `WInCC_Backup_30_10_2020.mcp`
  (case-insensitive). A mismatch fails closed with zero default exact
  diagnostic tags.
- Dakrosa1 continues to request zero default exact diagnostic tags.
- The same fleet release also activates the already-merged Phase 3 Dakrosa1
  OLEDB ValueName canary. That is a separate, archive-polling diagnostic for
  D1 frequency and guide-vane gaps; it never uses this Dakrosa2 allowlist and
  never merges results into canonical tags.
- The existing updater, OTA interval, NSSM service, installer, reader mode,
  callback canary, and WinCC binaries are unchanged.
- `Click*` and every name containing `command` are hard-denied at the exact
  probe boundary. No setpoint or mouse-event tag is included.
- The 59 new names remain diagnostic-only. A later reviewed release may
  promote only sources that pass the runtime evidence gates below.
- The existing full-raw HTTP endpoint is unauthenticated within the current
  public telemetry architecture, so these 59 operational values will be
  visible there during this operator-authorized canary. This accepted exposure
  contains no command or setpoint channel and does not expand write access.

The complete diagnostic list becomes 83 exact names: 24 already-live SCADA
diagnostics, 13 MHY_2 sources, and 46 start-sequence sources.

## Authoritative PDL evidence

MHY_2 source:

`outputs/dakrosa2_dump_carve/pdl/MHY_2.PDL`

SHA-256:

`59468B80C9805C9EE1FEAE31E77EDB4A7A40D5BD7DA3E816799A2CA64F62F80A`

The older extractor stopped after record 14. Direct inspection of the full
DynamicsStream plus `AP_INPROC_ADMIN` and `AP_INPROC_SCODE` proves records
17-20 and 27-34 below. The V11 result order was independently cross-checked
against the known set/clear expression pairs in `A_H2_chart_kd.PDL`.

### MHY_2 visible states

| Visible state | Exact source | Active condition |
| --- | --- | --- |
| Lỗi nguồn AC | `DCfault` | set / true |
| Lỗi nguồn DC | `H1Spare19` | set / true |
| Lỗi chỉnh lưu | `H1Spare19` | set / true |
| Lỗi chung hệ thống một chiều | `DCfault` | set / true |
| Máy cắt TD41 đóng | `H1Spare19` | set / true |
| Máy cắt TD46 đóng | `H1Spare19` | set / true |
| Inverter bypass | `Warning` | bit 0 set |
| Inverter | `Warning` | bit 0 clear |
| Overload | `Warning` | bit 6 set |
| Inverter quá nhiệt | `Warning` | bit 8 set |
| Inverter lỗi | `Warning` | bit 3 set |
| Quạt chạy | `Warning` | bit 1 set |

The repeated wiring is intentional evidence from the recovered PDL:
`H1Spare19` drives four visible lamps and `DCfault` drives two. Do not split
these into invented aliases. `AUX_LCU41_IW0` has no proven relationship to
the three sources above.

### MHY_2 missing numeric slots

| Native slot | Exact source | Unit |
| --- | --- | --- |
| IOField1 | `ACfrequency` | Hz |
| IOField2 | `outfrequency` | Hz |
| IOField3 | `Outvoltage` | V |
| IOField4 | `DCTC-` | A |
| IOField5 and IOField8 | `DCinput` | V |
| IOField6 | `ACviltagein` | V |
| IOField7 | `powerout` | % |
| IOField9 | `Outcurent` | A |
| IOField13 | `tempin` | °C |
| IOField14 | `tempout` | °C |

All use native `WinCC digital 1` formatting. The two spellings
`ACviltagein` and `Outcurent` are native project names and must not be fixed
or normalized at the Runtime boundary.

## Start-sequence evidence

Sources come from the recovered `A_H1_chart_kd.PDL`,
`A_H2_chart_kd.PDL`, and `A_H3_chart_kd.PDL` action streams.

### Direct state groups

| Meaning | H1 | H2 | H3 | Active condition |
| --- | --- | --- | --- | --- |
| secondary group word | `H1comgroup2` | `H2comgroup2` | `H3comgroup1` | bit 2 set |
| brake released | `H1Brakeoff` | `H2Brakeoff` | `H3Brakeoff` | true |
| local selection | `H1local` | `H2local` | `H3local` | true |
| remote selection | `H1remote` | `H2remote` | `H3remote` | true |
| no unit fault | `H1Spare7` | `H2Spare7` | `H3Spare7` | true; false is red |
| main valve command word | `H1OpMvalve` | `H2OpMvalve` | `H3OpMvalve` | bit 6 set |
| valve command word | `H1Opvalve` | `H2Opvalve` | `H3Opvalve` | bit 6 set |
| excitation breaker state | `H1DeExcitff` | `H2DeExcitff` | `H3DeExcitff` | set and clear drive paired lamps |
| brake open | excluded | `H2Brakeopen` | `H3Brakeopen` | true |
| synchronizing start | `H1Startsyn` | `H2Startsyn` | `H3Startsyn` | true |
| spring restore | `H1Spristore` | `H2Spristore` | `H3Spristore` | true |
| spring charged | `H1Springcharg` | `H2Springcharg` | `H3Springcharg` | true |

H1 `Brakeopen` is intentionally excluded: the H1 picture references
`H2Brakeopen`, which is a recovered copy artifact and cannot be canonicalized
as an H1 state.

### Script state groups

- `HnMVopen == 1 && HnMVclose == 0` drives the main-valve-open state.
- `12 <= realopeningN <= 16` drives one guide-vane condition.
- `8 <= realopeningN <= 16` drives the adjacent guide-vane condition.
- H2/H3 use exact `H2-Frequ` / `H3-Frequ` for the `>49 Hz` condition.
- The recovered `49.5 <= Hn-Speed <= 50.5` script conflicts with live Runtime
  evidence: `Hn-Speed` is approximately 501 rpm, not 50 Hz. Those display
  conditions remain unresolved and must not be derived from the curated speed
  source.

Never alias `realopeningN` to `uN_GV`, or `Hn-Frequ` to another frequency
source, without fresh same-snapshot equality evidence.

## Pre-release production baseline

Observed at `2026-07-14T09:50Z` before the candidate release:

- Dakrosa1 `1.5.17`: online, no snapshot error.
- Dakrosa1 baseline: 21 source tags, 29 after server-side derivation, raw
  21/21 ValueIDs, `runtime_probe.available=false`, no `oledb_value_probe`.
- Dakrosa2 `1.5.17`: online with 155 canonical tags, Runtime snapshot healthy,
  callback errors 0, oversized callbacks 0.
- Existing Dakrosa2 raw diagnostic: 24 requested, 24 found, no missing names.
- Its fresh pre-release Runtime identity was
  `WInCC_Backup_30_10_2020.mcp`; this exact basename is the project-side gate.
- Full process inventory is intentionally suppressed from the public raw
  payload; the 13 MHY_2 sources were not in the top-128 heuristic candidate
  subset. That absence is not evidence that the tags are missing.
- Direct inbound access to the historical Dakrosa2 host was unavailable from
  the current network, so no one-off remote command was used.

## Runtime evidence gate after OTA

Wait for a fresh Dakrosa2 raw shipment whose `received_at` is later than the
`1.5.18` OTA event, then inspect `runtime_probe.exact`.

For every source record:

1. Exact name must appear in `tags`, not `missing`.
2. Type must match the recovered use: binary for direct booleans, an integer
   word for bit expressions, and a finite numeric type for IO fields.
3. Runtime state must be `0` in at least two fresh shipments.
4. Numeric values must remain finite and physically plausible. Stable binary
   states are allowed; a witnessed transition is stronger evidence but is not
   required when PDL polarity is already exact.
5. Failed, missing, stale, or type-mismatched sources remain diagnostic-only.

Promotion must preserve raw source semantics first. Bit decoding and display
labels belong in a separately reviewed bridge/portal release.

## Fleet OTA verification

Changing `version.txt` is a fleet-wide trigger. After pushing `1.5.18`:

1. Confirm Dakrosa1 advances to `1.5.18`, keeps receiving snapshots, retains
   its prior tag count, and has no error. It must not gain DMCLIENT Runtime
   reads; the separate `oledb_value_probe` may appear in its full raw payload.
2. Confirm Dakrosa2 advances to `1.5.18`, keeps 155 canonical tags and healthy
   callback counters, then wait for the fresh raw diagnostic shipment.
3. Confirm `runtime_probe.exact.requested == 83`, with no denied command tags.
4. Record found/missing/type/state/value results before any canonical mapping.

If a regression appears, revert the diagnostic commit, publish a higher
version, and verify both stations again. Never downgrade `version.txt` or
modify the updater, service registration, or WinCC installation in place.

## Production result for 1.5.18

Both stations reported `1.5.18` by `2026-07-14T10:18:31Z`. Dakrosa1 retained
21 source tags, 29 tags after server derivation, and no snapshot error.
Dakrosa2 retained 155 canonical tags and no snapshot error. In the snapshot
received at `10:45:50.892Z`, its restarted callback session had advanced to
3,337 callbacks and 13,348 items with zero callback errors, zero oversized
callbacks, and a latest callback age of 0.125 seconds.

Two fresh Dakrosa2 diagnostic shipments were reviewed:

| Received | Dump time | Exact result | Archive result |
| --- | --- | --- | --- |
| `10:19:28Z` | `10:18:37Z` | 83 requested, 82 found | 359/359 ValueIDs, 1,103 blocks |
| `10:44:48Z` | `10:43:57Z` | 83 requested, 82 found | 360/360 ValueIDs, 1,096 blocks |

Both shipments used project `WInCC_Backup_30_10_2020.mcp`, were not truncated,
had no denied names, and missed only `DCTC-`. Of the 59 new exact names, the
other 58 retained identical type and type size, `state=0`, finite values, and
no per-tag error in both shipments. Four values moved plausibly between the
two samples: `realopening1`, `realopening3`, `H2-Frequ`, and `H3-Frequ`.

Six start-sequence sources fail the recovered-use type gate:
`H1OpMvalve`, `H2OpMvalve`, `H3OpMvalve`, `H1Opvalve`, `H2Opvalve`, and
`H3Opvalve` are Runtime Binary Tags, while the PDL expressions test bit 6 as
if they were integer words. They remain diagnostic-only together with the
missing `DCTC-`. The other 52 sources passed the two-cycle type/state/value
gate and are candidates for a separate canonical-mapping review; this release
does not promote them automatically.
