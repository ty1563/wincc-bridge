# Phase 2 spec: Dakrosa2 tags, 3-minute OTA check, and workstation SCADA view

Bridge candidate release: `1.5.16`.

## Objective

Prioritize Dakrosa2, expose additional useful WinCC telemetry through the existing
read-only bridge, reduce the effective OTA check interval from 15 minutes to no
more than 3 minutes, and render the workstation's original SCADA drawing on the
production dashboard with live values overlaid in the same positions.

The bridge source is `C:\Users\vanty\Documents\IDA\WinCC\wincc-bridge`.
The dashboard source is `C:\Users\vanty\Documents\Dakrosa`.
The copied Dakrosa2 WinCC installation is
`C:\Users\vanty\Desktop\dawkrosa\WinCC`.

## Evidence and assumptions

- Dakrosa2 currently returns a healthy native Runtime snapshot: 93 source tags
  attempted, 91 accepted, 105 canonical keys, and the four-tag callback canary
  updates every 500 ms with `state=0` and `quality=192`.
- The current raw summary contains 23/23 proposed electrical tags with recent,
  physically plausible values.
- `HV-*` is the plant's approximately 400 V generator/common bus group. `LV-*`
  is the approximately 22 kV export bus group, despite the counter-intuitive
  source prefixes.
- “3 minutes” means the OTA code check interval, not the telemetry snapshot
  interval. Dakrosa2 keeps its current 10-second Runtime snapshot path.
- The original workstation process overview is `A_22kV.PDL`, displayed inside
  `@SCREEN.PDL` / `@1001.PDL` at 1920 x 847. This comes from the PDL Runtime dump,
  not from a generic WinCC template.
- A full-memory `pdlrt` dump identifies the active historical path as
  `D:\DAKROSA2\GraCS\A_22kV.pdl`. The recovered A_22kV compound file is 602,112
  bytes with SHA-256
  `D4420676362F0DAA785F992369EB05C9A14E4C7F1B442A91ADDF38DCBA7A324E`.
- Static extraction currently accounts for 278 picture objects, 99/99 dynamic
  records, 68 tag references, and the complete 1920 x 847 object coordinate
  system. The old `D:\BACKUP2023` path was an unverified lead and is no longer
  treated as the source of truth.

## Success criteria

### Slice A — additional Dakrosa2 telemetry

1. The exact allow-list adds the following active source aliases:
   `HV-Hz`, `HV-IA`, `HV-IB`, `HV-IC`, `HV-Itb`, `HV-KVA`, `HV-KVAh`,
   `HV-KVAr`, `HV-KW`, `HV-KWh`, `HV-PF`, `HV-UA`, `HV-UB`, `HV-UC`,
   `HV-UAB`, `HV-UBC`, `HV-UCA`, `HV-Uptb`, `HV-Utb`, `LV-UA`, `LV-UB`,
   `LV-UC`, and `LV-Utb`.
2. New canonical names use isolated namespaces and do not overwrite the current
   22 kV `bus_*` contract incorrectly:
   - `hv_F`, `hv_I1`, `hv_I2`, `hv_I3`, `hv_I_avg`, `hv_S`, `hv_KVAh`,
     `hv_Q`, `hv_P`, `hv_KWh`, `hv_PF`, `hv_U1N`, `hv_U2N`, `hv_U3N`,
     `hv_U12`, `hv_U23`, `hv_U31`, `hv_U_avg`, `hv_U_ln_avg`.
   - The four `LV-U*` sources map to both `bus_U*N` / `bus_U_ln_avg` and their
     `lv_*` equivalents because `bus_*` already represents the LV/export meter.
3. Only finite samples with Data Manager `state=0` and physical bounds are
   accepted. Missing/bad samples remain rejected without breaking archive
   fallback.
4. The 23 new aliases are optional for the Runtime completeness ratio, so a
   missing auxiliary alias cannot demote the already-complete 93-source core
   snapshot from its 10-second fast path.
5. Existing 105 canonical keys remain compatible; no current key changes units.
6. Unit tests cover the exact alias/key contract, good samples, bad state, and
   out-of-range samples before production code is changed.

### Slice B — OTA cadence

1. An existing station config containing `ota_sec=900` is effectively capped at
   180 seconds after the release restarts.
2. Missing/default installer config uses 180 seconds.
3. An explicitly faster interval remains allowed down to the 60-second safety
   floor; lower values are raised to 60 seconds to avoid hammering GitHub.
4. The `[ota].enabled` gate, version comparison, git/zip updater, pinned station
   files, and NSSM restart behavior remain unchanged.
5. Tests prove the interval behavior independently from the live network updater.

### Slice C — workstation-identical SCADA view

1. The source-of-truth canvas is the actual Dakrosa2 `A_22kV.PDL` and all assets
   it references, not `Options\PDL\@Overview1.PDL` or an invented mimic.
2. The rendered process area preserves the original 1920 x 847 coordinate
   system. Responsive layouts scale the whole canvas uniformly; they do not
   rearrange objects.
3. Live read-only values are overlaid at the original object positions. No
   command/setpoint controls are sent to WinCC.
4. A reference screenshot and browser render are compared at the same viewport;
   completion requires a zero unexplained structural difference and a reviewed
   pixel diff. A functional approximation is not reported as “100%”.
5. Dashboard telemetry refresh is no slower than the 10-second Dakrosa2 bridge
   snapshot while the SCADA view is open.

### Slice D — recovered SCADA tag diagnostics

1. Only `station_name=Dakrosa2` enables `runtime_probe.exact`; the generic and
   Dakrosa1 probe defaults remain empty. The bounded read-only allow-list was
   recovered from `A_22kV.PDL` and covers breaker states, auxiliary states,
   pressure/opening values, and unit current/voltage fields.
2. This evidence channel remains separate from the curated snapshot until each
   live type, Data Manager state, and physical range has been reviewed.
3. Command/event tags `Click22`, `ClickH1`, `ClickH2`, and `ClickH3` are excluded
   by contract. The exact-probe boundary also hard-denies every `Click*` name,
   even if a future caller passes one explicitly.
4. The probe does not change updater, NSSM, station pinning, callback canary, or
   the production snapshot merge path.
5. Production canary `1.5.15` returned 24/24 exact names with no missing or
   denied entries. Twenty-three samples had Data Manager `state=0`; only
   `AUX_LCU41_IW0` had `state=257` and is therefore rejected from snapshots.
6. Release `1.5.16` promotes the 24 names into the Dakrosa2 curated reader as
   optional, bounded fields. Names retain a `_raw` suffix when engineering unit
   or bit semantics are not independently proven; no status is interpreted as
   open/closed merely from its numeric value.

## Recovered and still-required original project files

The copied WinCC installation does not contain the Dakrosa2 project GraCS
folder, but the full-memory dump has yielded verified copies of `A_22kV.PDL`,
`@SCREEN.PDL`, `@1001.PDL`, and 37 additional PDL files. If the live project
folder becomes available, preserve a read-only copy of:

- `A_22kV.PDL`, `@SCREEN.PDL`, and `@1001.PDL`;
- referenced process screens such as `A_H1.PDL`, `A_H2.PDL`, and `A_H3.PDL`;
- all referenced bitmap/JPEG/PNG files, fonts, and project symbol libraries;
- one 1920 x 847 runtime screenshot of `A_22kV.PDL` for pixel verification.

Known referenced assets still missing as standalone project files include
`quat1..10.png`, `12-0_turbin4.png`, `logo_new.jpg`, and `captureqwsx.bmp`.

## Commands

Bridge verification:

```powershell
cd C:\Users\vanty\Documents\IDA\WinCC\wincc-bridge
python -m unittest test_wincc_runtime.py test_service_raw_worker.py
python -m unittest test_collect_runtime.py test_rawdump_multiblock.py test_runtime_canary.py test_updater_station_reader.py
python -m py_compile box\oledb_reader.py box\wincc_runtime.py bridge\service.py bridge\updater.py
@'
import ast
from pathlib import Path
for name in ('box/oledb_reader.py', 'box/wincc_runtime.py', 'bridge/service.py', 'bridge/updater.py'):
    ast.parse(Path(name).read_text(encoding='utf-8'), filename=name, feature_version=(3, 7))
print('Python 3.7 grammar OK')
'@ | python -
git diff --check
```

Dashboard verification:

```powershell
cd C:\Users\vanty\Documents\Dakrosa
pnpm test
pnpm exec tsc --noEmit
pnpm build
git diff --check
```

## Project structure

- `box/wincc_runtime.py`: exact Data Manager aliases, bounds, native reads.
- `box/oledb_reader.py`: Runtime completeness gate and archive fallback.
- `bridge/service.py`: service scheduling; updater itself stays separate.
- `installer/*.ps1` and `config.local.example.toml`: install/default cadence.
- `src/app/dakrosa/wincc/`: dashboard and SCADA canvas components.
- `src/lib/dakrosa-mobile-api.ts`: canonical telemetry to view-model mapping.
- `src/app/globals.css`: existing dashboard styles and scaled SCADA canvas.

## Code style

Keep the existing explicit tuple/dictionary contracts and Python 3.7-compatible
syntax. TypeScript stays strict, data shaping remains in `src/lib`, and the SCADA
component remains presentation-only.

```python
{"name": "HV-KW", "keys": ("hv_P",), "min": -100.0, "max": 100.0}
```

```tsx
<ScadaReadout tag="hv_P" x={412} y={128} unit="MW" />
```

## New canonical unit and bound contract

| Source group | Canonical keys | Unit kept in payload | Accepted live range |
|---|---|---:|---:|
| `HV-Hz` | `hv_F` | Hz | 45..55 |
| `HV-IA/IB/IC/Itb` | `hv_I1/I2/I3/I_avg` | A | 0..10,000 |
| `HV-KW/KVAr/KVA` | `hv_P/hv_Q/hv_S` | MW/MVAr/MVA | -100..100 (`S`: 0..100) |
| `HV-PF` | `hv_PF` | ratio, absolute | -1.05..1.05 before absolute |
| `HV-UA/UB/UC/Utb` | `hv_U1N/U2N/U3N/U_ln_avg` | V | 0..1,000 |
| `HV-UAB/UBC/UCA/Uptb` | `hv_U12/U23/U31/U_avg` | V | 0..1,000 |
| `HV-KWh/KVAh` | `hv_KWh/hv_KVAh` | source counter scale; no derived use yet | 0..1e9 |
| `LV-UA/UB/UC/Utb` | `bus_*` plus `lv_*` phase-neutral keys | kV | 0..50 |

The `HV-*` power values are live-scaled MW/MVAr/MVA despite their source names.
The energy counters preserve source naming but are not used in energy arithmetic
until their engineering scale is separately verified.

### Recovered A_22kV raw contract

| Source names | Canonical keys | Accepted live range |
|---|---|---:|
| `471close`, `H1/2/3QFclose` | `scada_471_close_raw`, `u1/2/3_qf_close_raw` | 0..1 |
| `H1/2comgroup1`, `H3comgroup0` | `u1/2/3_comgroup_raw` | 0..65,535 |
| `AUX_LCU41_IW0` | `scada_aux_lcu41_iw0_raw` | 0..65,535 and state=0 |
| `OpenFull`, `CloseFull`, `MotorStatus` | `scada_*_raw` feedback keys | 0..1 |
| `Quatai`, `Loipha`, `Apsuatcao` | overload/phase/high-pressure raw keys | 0..1 |
| `remoterlocal` | `scada_remote_local_raw` | 0..1 |
| `Domo` | `scada_opening_raw` | 0..110 |
| `Apsuat1`, `Apsuat2` | `scada_pressure_1/2_raw` | -100..100 |
| `apKTH1/2/3` | `u1/2/3_excitation_voltage_raw` | 0..1,000 |
| `dongKTH1/2/3` | `u1/2/3_excitation_current_raw` | 0..1,000 |

These names are read-only observations. The `_raw` suffix is intentional until
the original labels, units, and bit semantics are confirmed from the PDL object
properties and at least two live operating states.

## Testing strategy

- Small Python unit tests for alias/key/bounds and OTA interval selection.
- Existing bridge suite for archive fallback, callback lifecycle, and updater
  station pinning.
- TypeScript unit tests for tag-to-view-model units and missing-value behavior.
- Production build and real-browser checks for runtime, console, network, and
  responsive scaling.
- Pixel comparison against the workstation screenshot only after the original
  GraCS assets are available.

## Boundaries

- Always: read-only WinCC access; exact station allow-lists; preserve fallbacks;
  keep Dakrosa1 and Dakrosa2 DLL/tag contracts separate; preserve untracked
  `test_updater_paths.py` and dashboard `.omx/`.
- Ask first: adding any write/control/setpoint path, changing credentials,
  replacing the updater mechanism, or uploading unrelated workstation files.
- Never: mix station DLLs, expose commands such as `H1setP`, treat inferred
  breaker state as a real digital input, or claim pixel identity without the
  original PDL/assets/reference screenshot.

## Open evidence gap

Exact visual completion is pending static-property reconstruction for all
object classes, recovery or faithful replacement of the remaining referenced
images, and a full-resolution runtime reference screenshot. The recovered
thumbnail is a structural reference, not sufficient evidence for a 100% pixel
identity claim. The `1.5.16` snapshot can expose only the recovered fields that
pass live `state=0` and physical-bound validation; rendering semantics still
follow the original PDL expressions rather than invented status labels.
