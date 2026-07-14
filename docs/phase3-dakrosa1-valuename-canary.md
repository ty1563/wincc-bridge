# Phase 3: Dakrosa1 OLEDB ValueName canary

Candidate bridge release: `1.5.18` (**deployment HOLD**).

## Release evidence and deployment hold

The checked local Dakrosa1 reference config uses the legacy shape and has no
`[station].name`. Fresh production raw output contains `runtime_probe`, a field
that does not exist in the pinned `c945766...` reader, so the current reader
path is active on D1. This is behavioral evidence, not a remote file hash.

The release keeps `box/oledb_reader.py` identical to the `1.5.17` main blob and
has no semantic change in updater, service, installer, OTA schedule, or reader
selection. This proves the release artifact introduces no new reader logic, but
does not prove the remote reader has the same blob. The existing updater may
upload either `c945766...` or the current main reader according to deployed
config, so a bump could still replace the reader currently running on D1.

Keep `version.txt = 1.5.17` until a read-only remote reader hash, or equivalent
config plus successful sync-log evidence, identifies the exact deployed and
next-selected reader. A bounded read-only SSH check from the development machine
timed out without connecting, so it provided no such evidence and made no remote
change. Do not infer station identity from remote mode, IP, reader defaults,
paths, or aliases, and do not modify production config merely to release this
canary.

## Purpose

Dakrosa1 production still lacks `bus_F`, `u1_F`, `u2_F`, `u3_F`, and
`u2_GV`. The raw inventory proves the exact archive membership of `bus_F` and
`u2_GV`, but the shipped fast-archive blocks do not contain their ValueIDs.
Changing the numeric map therefore cannot fill these gaps.

This release adds a diagnostic-only OLEDB query by exact `ValueName`. It never
merges a result into the normal snapshot or canonical `tags`. Production
evidence from this canary is required before a later release may promote any
value.

## Exact read-only allowlist

The two confirmed archive members are queried first so an unresolved namespace
cannot consume the budget before the highest-value signals.

| Order | Candidate | WinCC OLEDB ValueName | Unit | Guard | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | `bus_F` | `22kV\22kV_db_Unit_st22kV_nF` | Hz | 45..55 | confirmed in live fast Archive map |
| 2 | `u2_GV` | `U2\LCU2_db_Unit_stGov_nGV` | % | 0..110 | confirmed in live fast Archive map |
| 3 | `u1_F` | `U1\LCU1_db_Unit_stAlt_nF` | Hz | 45..55 | exact process tag; archive namespace candidate |
| 4 | `u2_F` | `U2\LCU2_db_Unit_stAlt_nF` | Hz | 45..55 | exact process tag; archive namespace candidate |
| 5 | `u3_F` | `U3\LCU3_db_Unit_stAlt_nF` | Hz | 45..55 | exact process tag; archive namespace candidate |

Dakrosa2 aliases such as `realopening2` or `H2-GV` are intentionally excluded.
The two station namespaces must not be mixed.

## Execution boundary

The canary does not modify or import either reader variant. It is implemented
in the standalone `box/d1_oledb_canary.py` helper:

1. `bridge.collect.collect_rawdump()` first runs and successfully parses the
   existing reader output.
2. Exact identity may come from `station.name = Dakrosa1` or from the already
   parsed raw payload's exact `station = Dakrosa1`. This supports the deployed
   legacy config, which has no `[station]` section, without inferring identity
   from remote mode, IP address, reader path, or any station alias. Conflicting
   config/payload identities or two missing identities fail closed.
3. The helper requires both `--station Dakrosa1` and `--raw-canary` and uses the
   same 32-bit Python as the reader.
4. The helper is a second process with a 15-second hard parent timeout. A
   timeout, nonzero exit, malformed/non-object JSON, or non-standard numeric
   constant becomes an additive diagnostic; the already-parsed rawdump remains
   intact.
5. If a future reader already returns `oledb_value_probe`, the collector does
   not overwrite it or launch a duplicate helper.

The existing updater already copies every current `box/*.py` and conditionally
substitutes only `oledb_reader.py` when its exact Dakrosa1 config gate is true.
The helper therefore reaches the remote box on either existing branch without
changing updater, reader selection, service, NSSM, installer, or WinCC binaries.

The optional kill switch is:

```toml
[station]
d1_oledb_value_probe = false
```

It is default-on only for exact Dakrosa1 raw shipping. Dakrosa2 never launches
the helper.

## Query and validation semantics

- One isolated query per candidate:
  `TAG:R,'<ValueName>','<absolute begin>','<absolute end>','TIMESTEP=300,2'`.
- The window is 24 hours; aggregation `2` is LAST without interpolation.
- Connection timeout is 5 seconds, command timeout is 3 seconds, the helper's
  soft budget is 10 seconds, and the parent hard timeout is 15 seconds.
- `RealValue` is preferred; `VariantValue` is the compatibility fallback.
- The last returned row wins, including a latest bad-quality row.
- Good quality requires `(Quality & 0xC0) == 0xC0`.
- `NaN` and positive/negative infinity are rejected as `invalid_value`, stored
  with `last = null`, and strict `allow_nan=false` JSON is enforced.
- Out-of-range and bad-quality values remain diagnostics only.
- Every result is marked `realtime: false`; OLEDB is archive polling, not a
  native runtime callback.
- Raw COM exception messages are never emitted, preventing connection-string
  material from leaking into the public raw diagnostic.

The only additive field is `oledb_value_probe`; it contains no canonical
`tags` map.

## Promotion gate

Do not publish a candidate into the normal Dakrosa1 snapshot until production
shows all of the following:

1. `available=true`, per-tag `status=ok`, `quality_good=true`, and
   `in_range=true`.
2. A plausible timestamp/age and engineering unit.
3. At least two independent raw-dump cycles with fresh timestamps or a value
   change consistent with plant state.
4. No regression in the existing reader rawdump, Dakrosa1 snapshot, Dakrosa2
   runtime snapshot, or callback canary.
5. A separate reviewed release promotes only proven candidates. No stale,
   bad-quality, unknown-quality, or out-of-range fallback is allowed.

OLEDB remains archive polling. If true live data is required after the archive
canary, the next diagnostic is the local `OPCServer.WinCC` cache path with its
own registry preflight and hard process timeout.

## OTA and station safety

`version.txt` on `main` is a fleet-wide release trigger, so both stations must
be monitored after `1.5.18` appears:

- Dakrosa1 snapshot stays healthy at its existing cadence and source-tag count.
- Dakrosa1 full raw payload remains present even when the canary reports an
  error or timeout.
- Dakrosa2 remains on its native runtime path with unchanged tag count,
  callback counters moving, and callback/oversized errors at zero.
- `oledb_value_probe` appears only in Dakrosa1 full raw output. Raw shipping is
  normally every 300 seconds, so its first appearance may lag OTA by one cycle.

Do not change reader selection, updater, OTA schedule, service, NSSM, installer,
or WinCC binaries to make this canary appear.

## Verification

- Focused helper, raw collector, and station-sync suite: 32 tests.
- Python 3.7 grammar and byte compilation cover the helper and integration.
- Full non-environment unit suite: 100 tests. Diff safety audit, review, and
  production monitoring are required before promotion.
- `test_e2e.py` remains environment-dependent because the isolated worktree has
  no production `config.local.toml`.
