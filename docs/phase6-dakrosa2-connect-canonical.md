# Phase 6: Dakrosa2 neutral Connect canonical raw

Release version: `1.5.21`.

This release promotes the native Dakrosa2 Runtime source `Connect` to the
single additive canonical key `scada_connect_raw`. The value is deliberately
preserved as a neutral binary raw signal. It is not named or described as an
online, offline, healthy, fault, or communications state.

## Production evidence

Release `1.5.20` collected two independent post-OTA diagnostic shipments from
the exact active project `WInCC_Backup_30_10_2020.mcp`:

| Received | Dump time | Runtime type | Size | Value | State |
| --- | --- | --- | --- | --- | --- |
| `2026-07-14T14:45:38.415Z` | `2026-07-14T14:44:48Z` | Binary (`1`) | 1 | 0 | 0 |
| `2026-07-14T14:50:42.949Z` | `2026-07-14T14:49:50Z` | Binary (`1`) | 1 | 0 | 0 |

The recovered `CUA DAP.PDL` renders `Connect=true` as red and `false` as light
gray. This proves the display polarity only. The process meaning remains
unresolved, so downstream consumers must show the raw value and must not infer
a fault or connectivity state.

## Canonical contract

- Native source: `Connect`.
- Canonical key: `scada_connect_raw`.
- Accepted values: exactly finite `0` or `1`; fractional values are rejected.
- Runtime state must be zero; rejected samples are omitted.
- The source is optional and cannot fail the normal snapshot when absent.
- No semantic alias such as `scada_connect_fault_raw` is created.

## Isolation and release boundary

- The source is requested only for configured station `Dakrosa2` when the
  active Runtime project basename matches
  `WInCC_Backup_30_10_2020.mcp` case-insensitively.
- Dakrosa1 and unknown or mismatched projects request none of this source.
- `EVENT_TYPE_MH1`, `EVENT_TYPE_MH2`, and `EVENT_TYPE_MH3` remain diagnostic
  only because both production shipments returned Runtime state `257`.
- `Connect` leaves the exact diagnostic list when it becomes canonical, so the
  default exact diagnostic request count returns from `87` to `86` and no
  source is read twice by the two paths.
- No WinCC write path is added. The reader, service loop, updater, OTA polling,
  installer, callback canary, and WinCC binaries are unchanged.
- `version.txt` is the existing fleet OTA trigger; the release advances only
  from `1.5.20` to `1.5.21`.

## Post-OTA verification

1. Confirm both stations report `1.5.21` through the existing OTA path.
2. Confirm Dakrosa1 remains healthy with its established published-tag count,
   no `scada_connect_raw`, and zero Dakrosa2 curated attempts.
3. Confirm Dakrosa2 remains in Runtime mode without snapshot or callback
   errors.
4. Confirm a fresh state-zero sample publishes `scada_connect_raw` with value
   `0` or `1`, realtime freshness metadata, and no semantic fault alias.
5. Confirm the portal renders raw `0` as gray and raw `1` as red, labels the
   field `Connect (tín hiệu raw)`, and states that process meaning is unknown.

If either station regresses, publish a separately reviewed higher version.
Never downgrade `version.txt` or modify the installed OTA/service mechanism in
place.
