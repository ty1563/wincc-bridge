# Phase 9: Dakrosa2 parameter-screen canonical contract

Release version: `1.5.24`.

This release promotes the 16 parameter-picture sources proven healthy by two
independent `1.5.23` Runtime shipments.  They move from the bounded exact
diagnostic probe into the project-gated canonical snapshot and public portal
contract.

## Canonical mapping

`H1_temp11` maps to the temperature readout `u1_temp11`, with accepted bounds
5 to 150 degrees Celsius.

For each unit `n` from 1 through 3:

| Native source | Canonical key | Bounds | Portal meaning |
| --- | --- | --- | --- |
| `Hn-KW1` | `un_phase_a_active_power_raw` | -10000..10000 | PA, kW |
| `Hn-KWA1` | `un_phase_a_reactive_power_raw` | -10000..10000 | QA, kVAr |
| `Hn-KW3` | `un_phase_c_active_power_raw` | -10000..10000 | PC, kW |
| `Hn-KWA3` | `un_phase_c_reactive_power_raw` | -10000..10000 | QC, kVAr |
| `Hn-KVArh` | `un_reactive_energy_raw` | 0..1e9 | raw counter, blank unit |

In the key names above, `n` is replaced by the unit number.  The `_raw`
suffix is deliberate.  The PDL proves PA/QA/PC/QC display semantics, but the
native `KWA` spelling must never be treated as kVA and the `KVArh` scale is not
independently proven.  Signed reactive values are preserved without absolute
value conversion; the counter is published without scaling or an invented
engineering unit.

All 16 specs are optional and enabled only for configured station Dakrosa2
when the active Runtime project basename is exactly
`WInCC_Backup_30_10_2020.mcp` case-insensitively.

## Contract changes

- Dakrosa2 curated specs increase from 193 to 209.
- Canonical key slots increase from 212 to 228.
- Project-gated specs increase from 53 to 69.
- The 16 promoted sources are removed from `SCADA_DIAGNOSTIC_TAGS`, reducing
  the exact request from 106 to 90 and preventing duplicate reads.
- Dakrosa1 and every mismatched project retain zero Phase 9 attempts.
- The portal adds 15 raw values plus `u1_temp11`, fills all 32 fields on each
  unit parameter picture when samples are fresh, and fills the H1 turbine
  `temp11` field from the same public readout.

The portal continues to apply its freshness and Runtime-state gates.  It does
not synthesize missing values, backfill one phase from another, or display a
stale/nonzero-state sample.

## Release boundary

- Reader, archive decode, service loop, callback subscription, updater, OTA
  polling, installer, and WinCC binaries are unchanged.
- No station host is contacted directly.  Both stations receive the higher
  `version.txt` only through the existing OTA mechanism.
- `DCTC-` remains the known missing exact tag.
- `EVENT_TYPE_MH1/2/3`, the six type-mismatched valve sources, and the four
  H2 directional-energy counters remain diagnostic-only.
- `Click*`, command, and setpoint channels remain excluded or hard-denied.

## Production verification gate

After both stations report `1.5.24` through the public API:

1. Confirm Dakrosa1 retains 29 published tags, no snapshot error, and no new
   curated attempts.
2. Confirm Dakrosa2 remains in Runtime mode with no callback regression,
   attempts the 209 curated specs, and publishes all 16 new canonical keys.
3. Confirm the exact request returns to 90, has no denied names, and still
   misses only `DCTC-`.
4. Confirm the portal exposes fresh values with correct bucket separation:
   `u1_temp11` as a readout and the 15 phase/counter fields as raw values.
5. Verify negative QA/QC values retain their sign and every `KVArh` field has
   a blank unit and no scale conversion.

If either station regresses, publish a separately reviewed higher version.
Never downgrade `version.txt` or modify the installed OTA/service mechanism in
place.

## Production result for 1.5.24

The GitHub raw release endpoint exposed `1.5.24` at
`2026-07-14T16:19:36Z`.  Both stations then advanced through their existing
OTA path without direct host access:

- Dakrosa1 first reported `1.5.24` at `16:20:24.041Z`, retained 29 published
  tags, and exposed none of the 16 Dakrosa2 Phase 9 keys.
- Dakrosa2 first reported `1.5.24` at `16:22:33.620Z`, remained in Runtime
  mode, published 224 tags, attempted 209 curated specs, accepted 206, rejected
  the same three optional samples, and retained zero callback errors.

All 16 promoted samples were present in the next public Dakrosa2 snapshot,
were realtime, and had Runtime state zero.  `u1_temp11` was approximately
46.6 degrees Celsius.  Each phase A/C value was finite, all three phase C
reactive values retained their negative sign, and the three raw reactive-
energy counters remained near 2260.07, 2262.42, and 2226.80 without scaling.

The raw shipment received at `16:22:39.092Z` (dump `16:21:48Z`) returned to 90
exact requests, found 89, denied none, and continued to miss only `DCTC-`.
None of the 16 promoted sources remained in the exact payload, confirming that
the release did not duplicate their Runtime reads.

The deployed public mobile API exposed all 100 readouts and 91 of the 92
allowlisted raw values; the only absent raw value was the unrelated optional
`scada_aux_lcu41_iw0_raw`.  All 16 Phase 9 fields were present.  Production
browser verification showed 32/32 live positions on H1, H2, and H3 parameter
screens and 20/20 on the H1 turbine screen.  `H1_temp11` rendered as 46.50
degrees Celsius, `KWA1/KWA3` rendered in kVAr with negative QC preserved, and
`KVArh` rendered as an unscaled value with no unit.  The browser console had
no warning or error.
