# Phase 5 specification: Dakrosa1 OPC capability preflight

Status: **draft for operator review; no implementation or OTA release yet**.

Current fleet release: `1.5.19`. This specification branch does not change
`version.txt`. If Phase 5A is approved, implemented, tested, and reviewed, its
preflight-only fleet release is expected to be `1.5.20`. It will still perform
zero OPC item reads.

## Assumptions requiring operator approval

1. Phase 5A is diagnostic-only. It must not merge values into the normal
   Dakrosa1 snapshot, canonical `tags`, or dashboard.
2. It may run only after the existing raw dump has parsed successfully and
   configured/observed identity, when present, agrees exactly on `Dakrosa1`.
3. It performs read-only capability checks only. It must not call
   `Dispatch`, `CoCreateInstance`, `CoGetClassObject`, `GetActiveObject`, or any
   other COM activation API.
4. It must never start, stop, pause, continue, restart, register, or reconfigure
   `OPCServer.WinCC` or another Windows/WinCC service.
5. It runs under the existing 32-bit Python. A target-local supervisor enforces
   an eight-second worker deadline; the bridge also keeps its outer SSH timeout.
   Every error is additive and leaves the already-parsed raw payload intact.
6. It must not change updater logic, service cadence, reader selection,
   `box/oledb_reader.py`, NSSM, installers, WinCC binaries, or OTA scheduling.

Implementation does not begin until these assumptions and this specification
are approved.

## Objective

Dakrosa1 still lacks fresh bus frequency, H1/H2/H3 frequency, and H2 guide-vane
opening. The Phase 3 OLEDB canary proved the archive path cannot safely supply
them: `bus_F` has no current row, `u2_GV` is stale/bad-quality, and the three
unit frequency queries fail.

The preferred next source is the already-running local WinCC OPC DA server.
However, offline evidence proves only the custom Siemens OPC DA server; it does
not prove that the target has the separate 32-bit OPC Automation wrapper needed
by Python. Guessing `Dispatch("OPCServer.WinCC")` could fail or activate a
service, which is outside the safety boundary.

Phase 5 is therefore split:

- **Phase 5A — capability preflight:** collect redacted, read-only evidence from
  the actual Dakrosa1 target. No COM object is instantiated and no OPC item is
  read.
- **Phase 5B — cache-read canary:** out of scope for this document. It requires
  production evidence from 5A, a verified Automation/type-library contract, a
  separate specification, operator approval, implementation review, and a
  later version bump.

Success for 5A means the portal can distinguish whether the target has a
running WinCC OPC service and a usable 32-bit Automation registration without
changing any service or process state.

## Source and platform baseline

### Detected stack

- Bridge code: Python compatible with Python 3.7 grammar.
- Target runtime: existing 32-bit Python configured by
  `[winccbox].python32`; the example path is `C:/Python311x86/python.exe`.
- Existing COM dependency: `pywin32` is already used by the OLEDB reader, but
  its deployed version is not pinned. Phase 5A must not install or upgrade it.
- Dakrosa1 reference root:
  `C:/Users/vanty/Documents/IDA/WinCC/WinCC`.
- Dakrosa2/recovered DLLs must never be copied into Dakrosa1 production.

The current analysis workstation is not a WinCC-installed host: both registry
views lack `OPCServer.WinCC` and `OPC.Automation(.1)`, the service/process is
absent, and no x86 Python is installed. The copied Dakrosa1 Siemens tree has a
signed x86 `sopcsrvrwincc.exe` but no OPC Automation wrapper or OPC DA server
TYPELIB. Therefore the actual target's 32-bit registry is the only acceptable
source for wrapper capability.

### Authoritative evidence

- Siemens documents the WinCC V7 OPC DA server ProgID as
  `OPCServer.WinCC` and identifies the client reference as
  `Siemens OPC DAAutomation 2.0`:
  https://support.industry.siemens.com/cs/attachments/109736225/WinCC_Communication_en-US_en-US.pdf
- The recovered Dakrosa1 `SOPCSRVR.ini` declares
  `SymbolicName = OPCServer.WinCC`, OPC DA 2.05A/3.00,
  `ExtendedInitialUpdate = 1`, and `NoAccessPath = 1`.
- Recovered `ssc_wincc_opc.xml` declares AppID
  `{75D00BBB-DDA5-11D1-B944-9E614D000000}` with
  `localService="OPCServer.WinCC"` and `serviceParameters="-Service"`.
- Microsoft documents read-only retrieval of current service state/PID,
  configured service image, and running process image through
  `QueryServiceStatusEx`, `QueryServiceConfigW`, and
  `QueryFullProcessImageNameW`:
  https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryservicestatusex
  and
  https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceconfigw
  and
  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew
- Microsoft documents `CheckTokenMembership` as a read-only enabled-group
  membership check and `LookupAccountNameW` as the local account-name to SID
  resolver:
  https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-checktokenmembership
  and
  https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-lookupaccountnamew
- Microsoft documents assigning a process to a Job Object and that
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates associated processes when the
  last job handle closes:
  https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
  and
  https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
- OPC Foundation identifies OPC Classic as COM/DCOM-based and labels its
  legacy Automation Wrapper obsolete/unmaintained. Phase 5A therefore only
  inventories an already-installed target registration; it never ships or
  installs a wrapper:
  https://opcfoundation.org/developer-tools/samples-and-tools-classic
  and
  https://opcfoundation.org/developer-tools/samples-and-tools-classic/automation-wrapper

## Commands

These are the complete verification commands for a future Phase 5A
implementation. They are not authorization to invoke anything on production
before operator review.

```powershell
# Focused tests from the isolated feature worktree
python -m unittest test_d1_opc_preflight.py test_collect_runtime.py test_updater_station_reader.py

# Full non-environment bridge suite; test_e2e.py requires production config
python -m unittest test_collect_runtime.py test_d1_oledb_canary.py test_d1_opc_preflight.py test_rawdump_multiblock.py test_runtime_canary.py test_service_raw_worker.py test_updater_station_reader.py test_wincc_runtime.py

# Python 3.7 grammar check for touched Python files
python -c "import ast, pathlib; files=['box/d1_opc_preflight.py','bridge/collect.py','test_d1_opc_preflight.py','test_collect_runtime.py','test_updater_station_reader.py']; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8'), filename=f, feature_version=(3,7)) for f in files]"

# Patch hygiene
git diff --check
git status --short
```

Production evidence is obtained only through the normal OTA/raw-shipping path.
No manual SSH invocation is part of the release procedure.

## Project structure

Future Phase 5A implementation is constrained to:

```text
box/d1_opc_preflight.py      standalone 32-bit read-only capability child
bridge/collect.py            fail-closed launch after valid Dakrosa1 raw dump
test_d1_opc_preflight.py     unit tests with fake registry/service/process data
test_collect_runtime.py      identity, timeout, and payload-preservation tests
test_updater_station_reader.py  helper-delivery and pinned-reader regression test
docs/phase5-...md            this specification and later release evidence
version.txt                  separate final release commit only
```

No other file is expected to change. In particular, Phase 5A must not edit
`bridge/service.py`, `bridge/updater.py`, `box/oledb_reader.py`, installers,
NSSM configuration, or station configuration.

## CLI and payload contract

The helper CLI is intentionally narrow:

```text
d1_opc_preflight.py --station Dakrosa1 --raw-canary
```

Both flags are mandatory. Any other station, omitted guard, non-Windows host,
or 64-bit process exits nonzero before registry/service inspection.

The collector adds at most one top-level field:

```json
{
  "opc_cache_preflight": {
    "available": false,
    "backend": "wincc-opc-da-preflight",
    "status": "known_automation_contract_absent",
    "python_x86": true,
    "pywin32_available": true,
    "server_registered_32": true,
    "server_registration_matches_reference": true,
    "known_automation_progid_registered_32": false,
    "siemens_automation_typelib_registered_32": null,
    "service_installed": true,
    "service_running": true,
    "service_pid_present": true,
    "service_image_matches_registration": true,
    "server_process_image_matches_service": null,
    "server_process_x86": null,
    "simatic_hmi_group": null,
    "com_activation_attempted": false,
    "item_reads_attempted": 0
  }
}
```

Only booleans, `null` for unknown/unreadable checks, bounded status enums,
expected reference identifiers, and counts may be emitted. `false` means a
check completed and disproved the condition; access denial, timeout, or an
unreadable source must produce `null` plus an appropriate status. Raw registry
paths, executable paths, account/group names,
hostnames, usernames, command lines, DLL versions, raw exception messages,
credentials, and connection material are never sent.

Strict JSON is required (`allow_nan=False`).

The optional kill switch is:

```toml
[station]
d1_opc_preflight = false
```

It defaults on only after exact Dakrosa1 identity is established from config or
the already-parsed raw payload. Dakrosa2 never launches the helper.

## Code style

The implementation follows the existing injected-adapter style so behavior is
testable without WinCC:

```python
EXPECTED_SERVER = {
    "progid": "OPCServer.WinCC",
    "appid": "{75D00BBB-DDA5-11D1-B944-9E614D000000}",
    "service": "OPCServer.WinCC",
}


def run_preflight(registry_api, service_api, process_api, runtime_api):
    result = base_result()
    result.update(check_capabilities(
        registry_api, service_api, process_api, runtime_api))
    result["com_activation_attempted"] = False
    result["item_reads_attempted"] = 0
    return result
```

Rules:

- Python 3.7-compatible syntax only.
- No import or call that can activate an OPC COM server.
- Registry/service/process/runtime adapters are injected for tests.
- Every exception becomes a bounded status/type; no raw message is emitted.
- Reference identifiers are constants; no station alias or fuzzy matching.
- The public guarded CLI is a target-local supervisor. It launches the same
  module in private `--worker` mode inside a Windows Job Object configured with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, waits at most eight seconds, then
  terminates and reaps the worker with a two-second grace. The bridge's outer
  timeout is 25 seconds, exceeding the 12-second SSH connect timeout plus the
  worker/grace budget. If SSH kills the supervisor first, closing its last job
  handle still terminates the worker. The worker cannot accept a station other
  than exact Dakrosa1.

## Exact read-only preflight

Exact CLI, Windows, station, and x86 checks are structural gates. Failure there
returns before inspection. After those gates pass, the worker collects every
independent check so one missing wrapper does not hide useful service evidence.
When a parent result is unavailable, only its dependent fields become `null`.
For example, a missing known Automation ProgID leaves its CLSID/InprocServer
fields `null`, while the independent Siemens TypeLib and service checks still
run.

1. Confirm exact CLI guards, Windows platform, and a 32-bit Python process.
2. Confirm `win32com.client` and `pythoncom` can be imported, without calling
   `Dispatch`, `GetActiveObject`, or another activation function.
3. Read **Registry32 only** for:
   - `OPCServer.WinCC -> CLSID`;
   - server `CLSID -> LocalServer32/LocalService/AppID`;
   - AppID `LocalService`;
   - known wrapper ProgIDs `OPC.Automation.1` and `OPC.Automation`;
   - their `CLSID -> InprocServer32/TypeLib` links when present;
   - the exact Registry32 TypeLib display name
     `Siemens OPC DAAutomation 2.0` and its registered Win32 path.
   This bounded inventory does not claim that the two known ProgIDs are every
   possible Siemens wrapper ProgID.
4. Compare only normalized identifiers against the known Siemens reference.
   Paths are used locally for validation but never emitted.
5. Verify registered executable/DLL files exist, remain inside station-local
   installed roots, and have x86 PE machine type. A standalone `.tlb` is
   checked only for a valid registration and existing bounded file; it is not
   required to be a PE image. Do not load a DLL or execute a binary.
6. Use read-only `QueryServiceStatusEx` for exact service name
   `OPCServer.WinCC`. Require `SERVICE_RUNNING` and a positive PID. No service
   control verb/API is called.
7. Read the configured service image using read-only `QueryServiceConfigW`. If
   SCM query-config access is denied, return `null`; do not fall back to the
   service registry. Compare a successful result with the server registration,
   then attempt read-only
   `QueryFullProcessImageName` for the PID. An access-denied process-image check
   is `null/unknown`, not false. No process is opened for write/control access.
8. Use `CheckTokenMembership` to test whether the current token is already in
   the exact SIMATIC HMI access group. Do not add/remove users or alter DCOM
   permissions.
9. Emit the redacted JSON result and exit. `com_activation_attempted` is always
   false and `item_reads_attempted` is always zero.

Registry, SCM, token, process, and PE inspection use direct bounded file/Win32
API reads; no `sc.exe`, `reg.exe`, PowerShell, WMI, or `whoami` subprocess is
launched. The supervisor creates the worker suspended, assigns it to the
kill-on-close Job Object, and only then resumes it. On older Windows, it uses
the documented breakaway creation flag; if process creation, breakaway, Job
Object setup, or assignment fails, the suspended worker is terminated and no
inspection runs. The target-local Job Object, rather than the SSH timeout,
prevents repeated raw cycles from accumulating workers.

Registry disagreement, no known wrapper/type-library contract, missing files,
64-bit executable/DLL PE,
stopped/pending service, PID mismatch, access denial, timeout, or unknown state
all fail closed. No fallback registration, PATH mutation, DLL preload, COM
activation, or item read is allowed in Phase 5A.

### Result completion and status precedence

After structural gates pass, every independent field is attempted once. The
single top-level status is chosen after collection in this order:

1. `preflight_internal_error`
2. `supervisor_setup_failed`
3. `worker_timeout`
4. `server_registration_unreadable`
5. `server_registration_mismatch`
6. `service_not_running`
7. `service_identity_unverified`
8. `hmi_access_absent`
9. `hmi_access_unverified`
10. `python_com_runtime_unavailable`
11. `known_automation_contract_absent`
12. `automation_contract_unverified`
13. `capability_ready`

This status is deterministic but does not erase lower-priority fields. `false`
means a completed negative check; denied, timed-out, or unreadable checks are
`null`. `known_automation_contract_absent` means neither a known ProgID nor the
exact Siemens TypeLib was found. A partial TypeLib/ProgID/CLSID relationship is
`automation_contract_unverified`. `available=true` is reserved for
`capability_ready`, which also requires `simatic_hmi_group=true`.

## Reserved initial item allowlist for a future Phase 5B

Phase 5A does not read these items. They are recorded only to prevent a later
cache canary from expanding scope without review.

| Future diagnostic key | Exact local OPC ItemID | Unit | Plausible range |
| --- | --- | --- | --- |
| `bus_F` | `22kV_db_Unit_st22kV_nF` | Hz | 45..55 |
| `u1_F` | `LCU1_db_Unit_stAlt_nF` | Hz | 45..55 |
| `u2_F` | `LCU2_db_Unit_stAlt_nF` | Hz | 45..55 |
| `u3_F` | `LCU3_db_Unit_stAlt_nF` | Hz | 45..55 |
| `u2_GV` | `LCU2_db_Unit_stGov_nGV` | % | 0..110 |

The three proven gate-position names remain out of the initial cache canary
until their engineering ranges are known. They stay semantically separate and
none is an alias for Dakrosa2 `scada_opening_raw`.

## Testing strategy

### Helper unit tests

- exact CLI/station/Windows/x86 gates occur before inspection;
- only Registry32 is queried;
- exact ProgID/CLSID/AppID/LocalService relationships;
- missing/malformed/conflicting registration paths;
- known wrapper ProgID absent, Siemens TypeLib present/absent/unknown, in-proc
  server missing, and broken ProgID/CLSID/TypeLib relationships;
- registered executable/DLL missing/outside station-local root/non-x86;
- standalone TypeLib files are never rejected merely for not being PE images;
- service absent/stopped/paused/pending/denied/unreadable;
- service `RUNNING` with zero PID, configured-image mismatch, process-image
  mismatch, or process-image access denied/unknown;
- SIMATIC HMI group true/false/unknown without membership changes;
- HMI false maps to `hmi_access_absent`, unknown maps to
  `hmi_access_unverified`, and readiness requires true;
- target-local supervisor terminates a hung worker and repeated calls do not
  accumulate workers;
- worker creation is suspended; Job Object assignment/kill-on-close, two-second
  terminate-and-reap grace, supervisor-crash cleanup, and outer 25-second
  timeout are verified;
- no external OS utility is launched (the only subprocess is the guarded
  same-Python worker) and no test path invokes COM;
- deterministic status precedence and dependent-field null propagation;
- strict, bounded, redacted JSON;
- AST/source forbidden-call checks and runtime trap adapters fail if COM
  activation or item reading is added or attempted.

### Collector integration tests

- valid Dakrosa1 raw payload attaches `opc_cache_preflight`;
- legacy config without `[station].name` is allowed only when parsed payload is
  exactly Dakrosa1;
- conflicting/missing identities fail closed;
- Dakrosa2, disabled kill switch, invalid raw JSON, child timeout, nonzero exit,
  and malformed output never lose or modify the raw dump;
- existing `opc_cache_preflight` is preserved without duplicate launch;
- OLEDB and OPC preflight diagnostics coexist without overwrite.

### OTA helper-delivery tests

- existing `_sync_box` behavior includes `d1_opc_preflight.py` without an
  updater implementation change;
- Dakrosa1 still receives its pinned legacy `oledb_reader.py` while receiving
  the current helper;
- Dakrosa2 keeps its current reader and never executes the D1 helper.

### Release checks

- focused and full non-E2E tests pass;
- Python 3.7 AST parse passes;
- `git diff --check` passes;
- independent safety review confirms no COM activation/import side effect and
  no updater/service/reader/installer boundary change;
- the release commit changes only `version.txt` after implementation approval.

## Boundaries

### Always

- Preserve existing snapshot/raw output on every preflight error.
- Gate by exact Dakrosa1 identity.
- Enforce the eight-second worker deadline in a target-local 32-bit supervisor;
  use a kill-on-close Job Object and two-second terminate/reap grace; never rely
  on killing the local SSH client to end the remote worker.
- Emit redacted capability booleans/statuses only.
- Commit and push each reviewed increment; keep implementation on the feature
  branch until explicit merge authorization.

### Ask first

- Approve this Phase 5A specification.
- Approve implementation, merge, `version.txt` bump, and fleet OTA rollout.
- After production evidence, approve a separate Phase 5B cache-read spec.
- Approve any dependency, registry access beyond Registry32, COM activation,
  item read, canonical promotion, or dashboard wiring.

### Never

- Activate or instantiate an OPC/COM object in Phase 5A.
- Start, stop, restart, pause, reconfigure, or register a service/component.
- Browse tags, create OPC groups, subscribe callbacks, read items, force device
  reads, or write values in Phase 5A.
- Copy/load Dakrosa2 or recovered DLLs on Dakrosa1.
- Infer station identity from IP, SSH mode, path, username, or reader default.
- Change updater, service cadence, reader selection, NSSM, installer, OTA
  schedule, or `box/oledb_reader.py` to make the preflight pass.

## Success criteria

Phase 5A is complete only when all of the following are true:

1. All tests and release checks above pass.
2. Diff audit proves only the six expected files changed before the separate
   release-version commit.
3. Dakrosa2 tests prove the child is never launched there.
4. Production OTA leaves both stations online at their prior source-tag counts,
   with no new snapshot/raw errors.
5. Dakrosa1 retains 21/21 raw ValueIDs even when preflight fails.
6. Two independent Dakrosa1 raw shipments contain a bounded
   `opc_cache_preflight`, without raw paths/errors/account data.
7. Both shipments assert `com_activation_attempted=false` and
   `item_reads_attempted=0`; these fields are operational assertions, not proof.
   The proof is the reviewed diff, AST/source forbidden-call checks, and runtime
   trap tests executed on the exact release commit.
8. No candidate value is acquired or promoted by Phase 5A.

## Evidence required before a Phase 5B specification

Production 5A must prove all of these without inference:

- exact 32-bit `OPCServer.WinCC` ProgID/CLSID/AppID/LocalService relationship;
- an exact installed 32-bit Automation ProgID/CLSID/InprocServer32/TypeLib
  contract, or a separate reviewed identification step when only the exact
  `Siemens OPC DAAutomation 2.0` TypeLib is found;
- registered executable/DLL files exist and are x86 in station-local installed
  roots; a standalone `.tlb` only needs a valid existing registration;
- service is already `RUNNING`, its configured image matches registration, and
  its process identity is either positively matched or separately resolved;
- target Python is x86, pywin32 imports, and current account has existing HMI
  access membership;
- no snapshot/raw regression across at least two shipments.

Only then may a separate document define the verified Automation method
signature, cache-only semantics, service-activation guard, quality/timestamp
rules, five-item initial allowlist, and promotion gate. Until then the safe state is
preflight-only, no COM activation, no item read, and no version bump.
