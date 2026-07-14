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
