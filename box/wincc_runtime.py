"""Read-only WinCC Runtime tag discovery, sampling, and callback canary.

The public helpers in this module deliberately accept an injected API object so
the selection and payload logic can be tested without WinCC or 32-bit Python.
"""
import argparse
import ctypes
from ctypes import wintypes
import datetime
import json
import math
import ntpath
import os
import re
import sys
import threading
import time


NUMERIC_TYPE_CODES = frozenset(range(1, 10))
MAX_DM_NAME = 128


class CMNErrorW(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("dwError1", ctypes.c_ulong),
        ("dwError2", ctypes.c_ulong),
        ("dwError3", ctypes.c_ulong),
        ("dwError4", ctypes.c_ulong),
        ("dwError5", ctypes.c_ulong),
        ("szErrorText", ctypes.c_wchar * 512),
    ]


class DMVarKeyW(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwKeyType", ctypes.c_ulong),
        ("dwID", ctypes.c_ulong),
        ("szName", ctypes.c_wchar * (MAX_DM_NAME + 1)),
        # This module only loads WinCC from 32-bit Python.  Keep LPVOID fixed
        # at its Win32 width so the public packed ABI is testable on x64 hosts.
        ("lpvUserData", ctypes.c_uint32),
    ]


class DMTypeRefW(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwType", ctypes.c_ulong),
        ("dwSize", ctypes.c_ulong),
        ("szTypeName", ctypes.c_wchar * (MAX_DM_NAME + 1)),
    ]


class VariantData(ctypes.Union):
    _fields_ = [
        ("llVal", ctypes.c_longlong),
        ("ullVal", ctypes.c_ulonglong),
        ("lVal", ctypes.c_long),
        ("ulVal", ctypes.c_ulong),
        ("intVal", ctypes.c_int),
        ("uintVal", ctypes.c_uint),
        ("iVal", ctypes.c_short),
        ("uiVal", ctypes.c_ushort),
        ("cVal", ctypes.c_byte),
        ("bVal", ctypes.c_ubyte),
        ("fltVal", ctypes.c_float),
        ("dblVal", ctypes.c_double),
        ("boolVal", ctypes.c_short),
        ("ptr", ctypes.c_void_p),
    ]


class Variant(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("data", VariantData),
    ]


class DMVarUpdateW(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dmTypeRef", DMTypeRefW),
        ("dmVarKey", DMVarKeyW),
        ("dmValue", Variant),
        ("dwState", ctypes.c_ulong),
    ]


class DMVarUpdateExW(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("dmTypeRef", DMTypeRefW),
        ("dmVarKey", DMVarKeyW),
        ("dmValue", Variant),
        ("dwState", ctypes.c_uint32),
        ("dwQualityCode", ctypes.c_uint32),
    ]


DMEnumVarProcW = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.POINTER(DMVarKeyW),
    ctypes.c_void_p,
)
DMNotifyProcW = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_ulong,
    ctypes.c_void_p,
)
DMNotifyVariableExProcW = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_uint32,
    ctypes.POINTER(DMVarUpdateExW),
    ctypes.c_uint32,
    ctypes.c_void_p,
)


class DMVarSubscription:
    """Pins WinCC callback memory until Stop and Disconnect have completed."""

    def __init__(self, taid, keys, callback, stats):
        self.taid = int(taid)
        self.keys = keys
        self.callback = callback
        self.stats = stats
        self.active = False


def _registry_install_paths():
    try:
        import winreg
    except ImportError:
        return []
    paths = []
    key_names = (
        r"SOFTWARE\WOW6432Node\Siemens\WinCC\Setup",
        r"SOFTWARE\Siemens\WinCC\Setup",
    )
    for key_name in key_names:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as key:
                index = 0
                while True:
                    try:
                        _name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if isinstance(value, str) and value.strip():
                        paths.append(value.strip())
        except OSError:
            continue
    return paths


def locate_wincc_bin(explicit=None):
    """Find a directory containing both WinCC Runtime API DLLs."""
    roots = [explicit, os.environ.get("WINCC_BIN")]
    roots.extend(_registry_install_paths())
    roots.extend([
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Siemens", "WinCC", "bin"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Siemens", "WinCC", "bin"),
    ])
    candidates = []
    for root in roots:
        if not root:
            continue
        root = os.path.abspath(os.path.expandvars(str(root).strip('"')))
        candidates.extend([root, os.path.join(root, "bin")])
    seen = set()
    for candidate in candidates:
        folded = candidate.lower()
        if folded in seen:
            continue
        seen.add(folded)
        if os.path.isfile(os.path.join(candidate, "dmclient.dll")):
            return candidate
    raise RuntimeError("WinCC bin not found (need dmclient.dll)")

_VARIANT_NUMERIC_FIELDS = {
    2: "iVal",       # VT_I2
    3: "lVal",       # VT_I4
    4: "fltVal",     # VT_R4
    5: "dblVal",     # VT_R8
    11: "boolVal",   # VT_BOOL
    16: "cVal",      # VT_I1
    17: "bVal",      # VT_UI1
    18: "uiVal",     # VT_UI2
    19: "ulVal",     # VT_UI4
    20: "llVal",     # VT_I8
    21: "ullVal",    # VT_UI8
    22: "intVal",    # VT_INT
    23: "uintVal",   # VT_UINT
}

_VALUABLE_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:"
    r"n(?:p|q|pf|f|u(?:12|23|31|1n|2n|3n)|i[123]|eng|gv)|"
    r"i(?:a|b|c|tb|[123])|u(?:ab|bc|ca|ptb|12|23|31)|"
    r"p|q|f|kw|kvar|kva|kwh|kvah|hz|pf|power|curr(?:ent)?|"
    r"volt(?:age)?|freq(?:uency)?|"
    r"temp(?:erature)?|spd|speed|eng|gv|guide|flow|level|pressure|"
    r"vibration|bearing|winding|oil|water|rain|alarm|trip|status"
    r")(?:$|[^a-z0-9])",
    re.IGNORECASE,
)
_EVENT_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:alarm|trip|status)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)

# The Phase 4 tag promotion is evidence-bound to this exact Dakrosa2 Runtime
# project.  Keep the filename normalized because WinCC returns a full path with
# installation-specific casing.
DAKROSA2_RUNTIME_PROJECT_FILES = frozenset((
    "wincc_backup_30_10_2020.mcp",
))


def _station2_curated_specs():
    """Small, validated Runtime set used by the adaptive snapshot.

    The WinCC archive exposes longer symbolic paths, while DMCLIENT exposes
    these flat process-tag aliases.  Bounds are deliberately physical rather
    than merely numeric so a bad state/placeholder never replaces archive
    fallback data.
    """
    specs = []
    unit_metrics = (
        ("Hz", "F", 45.0, 55.0),
        ("IA", "I1", 0.0, 10000.0),
        ("IB", "I2", 0.0, 10000.0),
        ("IC", "I3", 0.0, 10000.0),
        ("Itb", "I_avg", 0.0, 10000.0),
        ("KVA", "S", 0.0, 10000.0),
        ("KVAh", "KVAh", 0.0, 1.0e9),
        ("KVAr", "Q", -10000.0, 10000.0),
        ("KW", "P", -10000.0, 10000.0),
        ("KWh", "KWh", 0.0, 1.0e9),
        ("PF", "PF", -1.05, 1.05),
        ("Speed", "speed", 0.0, 1000.0),
        ("UAB", "U12", 0.0, 1000.0),
        ("UBC", "U23", 0.0, 1000.0),
        ("UCA", "U31", 0.0, 1000.0),
        ("Uptb", "U_avg", 0.0, 1000.0),
    )
    for unit_number in (1, 2, 3):
        source_prefix = "H%d" % unit_number
        key_prefix = "u%d_" % unit_number
        for source_suffix, key_suffix, low, high in unit_metrics:
            specs.append({
                "name": "%s-%s" % (source_prefix, source_suffix),
                "keys": (key_prefix + key_suffix,),
                "min": low,
                "max": high,
            })
        for sensor in range(1, 11):
            specs.append({
                "name": "%s_temp%d" % (source_prefix, sensor),
                "keys": ("%stemp%d" % (key_prefix, sensor),),
                "min": 5.0,
                "max": 150.0,
            })

    # HV is the approximately 400 V generator/common bus in this project.
    # The source power names say kW/kVA/kVAr, but their live scale is
    # MW/MVA/MVAr, matching the existing bus power contract.  Keep this group
    # isolated from bus_* because bus_* already means the 22 kV export meter.
    generator_bus_metrics = (
        ("Hz", "hv_F", 45.0, 55.0),
        ("IA", "hv_I1", 0.0, 10000.0),
        ("IB", "hv_I2", 0.0, 10000.0),
        ("IC", "hv_I3", 0.0, 10000.0),
        ("Itb", "hv_I_avg", 0.0, 10000.0),
        ("KVA", "hv_S", 0.0, 100.0),
        ("KVAh", "hv_KVAh", 0.0, 1.0e9),
        ("KVAr", "hv_Q", -100.0, 100.0),
        ("KW", "hv_P", -100.0, 100.0),
        ("KWh", "hv_KWh", 0.0, 1.0e9),
        ("PF", "hv_PF", -1.05, 1.05),
        ("UA", "hv_U1N", 0.0, 1000.0),
        ("UB", "hv_U2N", 0.0, 1000.0),
        ("UC", "hv_U3N", 0.0, 1000.0),
        ("UAB", "hv_U12", 0.0, 1000.0),
        ("UBC", "hv_U23", 0.0, 1000.0),
        ("UCA", "hv_U31", 0.0, 1000.0),
        ("Uptb", "hv_U_avg", 0.0, 1000.0),
        ("Utb", "hv_U_ln_avg", 0.0, 1000.0),
    )
    for source_suffix, key, low, high in generator_bus_metrics:
        spec = {
            "name": "HV-%s" % source_suffix,
            "keys": (key,),
            "min": low,
            "max": high,
            "required": False,
        }
        if source_suffix == "PF":
            spec["absolute"] = True
        specs.append(spec)

    # LV is the 22 kV/export meter in this project.  Its live P/Q/S values are
    # MW/MVAr/MVA (matching the existing bus contract), while current is A.
    # Voltage is retained as lv_* until its project scaling is verified live.
    bus_metrics = (
        ("Hz", ("bus_F", "lv_F"), 45.0, 55.0),
        ("IA", ("bus_I1", "lv_I1"), 0.0, 1000.0),
        ("IB", ("bus_I2", "lv_I2"), 0.0, 1000.0),
        ("IC", ("bus_I3", "lv_I3"), 0.0, 1000.0),
        ("Itb", ("bus_I_avg", "lv_I_avg"), 0.0, 1000.0),
        ("KVA", ("bus_S", "lv_S"), 0.0, 100.0),
        ("KVAh", ("bus_KVAh", "lv_KVAh"), 0.0, 1.0e9),
        ("KVAr", ("bus_Q", "lv_Q"), -100.0, 100.0),
        ("KW", ("bus_P", "lv_P"), -100.0, 100.0),
        ("KWh", ("bus_KWh", "lv_KWh"), 0.0, 1.0e9),
        ("PF", ("bus_PF", "lv_PF"), -1.05, 1.05),
        ("UAB", ("bus_U12", "lv_U12"), 0.0, 50000.0),
        ("UBC", ("bus_U23", "lv_U23"), 0.0, 50000.0),
        # UCA (bus_U31/lv_U31) is demoted to the exact diagnostic probe in
        # 1.5.27: the spec had requested LV-UCA since 1.5.16 without one
        # published sample while LV-UAB/LV-UBC deliver live values.  See
        # EXPORT_METER_DIAGNOSTIC_TAGS and docs/phase12.
        ("Uptb", ("bus_U_avg", "lv_U_avg"), 0.0, 50000.0),
        ("UA", ("bus_U1N", "lv_U1N"), 0.0, 50.0),
        ("UB", ("bus_U2N", "lv_U2N"), 0.0, 50.0),
        ("UC", ("bus_U3N", "lv_U3N"), 0.0, 50.0),
        ("Utb", ("bus_U_ln_avg", "lv_U_ln_avg"), 0.0, 50.0),
    )
    for source_suffix, keys, low, high in bus_metrics:
        spec = {
            "name": "LV-%s" % source_suffix,
            "keys": keys,
            "min": low,
            "max": high,
        }
        if source_suffix in ("UA", "UB", "UC", "Utb"):
            spec["required"] = False
        if source_suffix == "PF":
            # This export meter encodes power-flow direction in PF's sign;
            # canonical cos(phi) is the magnitude, while P/Q retain direction.
            spec["absolute"] = True
        specs.append(spec)

    # Read-only A_22kV.PDL fields verified live through the isolated exact
    # probe in 1.5.15.  Keep raw suffixes where engineering units or bit
    # semantics are not yet independently proven.  All are optional so an
    # auxiliary/status failure can never demote the established fast snapshot.
    scada_metrics = (
        ("471close", "scada_471_close_raw", 0.0, 1.0),
        ("H1QFclose", "u1_qf_close_raw", 0.0, 1.0),
        ("H2QFclose", "u2_qf_close_raw", 0.0, 1.0),
        ("H3QFclose", "u3_qf_close_raw", 0.0, 1.0),
        ("H1comgroup1", "u1_comgroup_raw", 0.0, 65535.0),
        ("H2comgroup1", "u2_comgroup_raw", 0.0, 65535.0),
        ("H3comgroup0", "u3_comgroup_raw", 0.0, 65535.0),
        ("AUX_LCU41_IW0", "scada_aux_lcu41_iw0_raw", 0.0, 65535.0),
        ("OpenFull", "scada_open_full_raw", 0.0, 1.0),
        ("CloseFull", "scada_close_full_raw", 0.0, 1.0),
        ("MotorStatus", "scada_motor_status_raw", 0.0, 1.0),
        ("Quatai", "scada_overload_raw", 0.0, 1.0),
        ("Loipha", "scada_phase_fault_raw", 0.0, 1.0),
        ("remoterlocal", "scada_remote_local_raw", 0.0, 1.0),
        # Production returned 110.925926 with state=0, above the prior guard.
        # Keep a temporary 120 ceiling so the observed sample is not dropped;
        # the configured engineering maximum is not independently confirmed.
        ("Domo", "scada_opening_raw", 0.0, 120.0),
        ("Apsuat1", "scada_pressure_1_raw", -100.0, 100.0),
        ("Apsuat2", "scada_pressure_2_raw", -100.0, 100.0),
        ("Apsuatcao", "scada_high_pressure_raw", 0.0, 1.0),
        ("apKTH1", "u1_excitation_voltage_raw", 0.0, 1000.0),
        ("apKTH2", "u2_excitation_voltage_raw", 0.0, 1000.0),
        ("apKTH3", "u3_excitation_voltage_raw", 0.0, 1000.0),
        ("dongKTH1", "u1_excitation_current_raw", 0.0, 1000.0),
        ("dongKTH2", "u2_excitation_current_raw", 0.0, 1000.0),
        ("dongKTH3", "u3_excitation_current_raw", 0.0, 1000.0),
    )
    for source_name, key, low, high in scada_metrics:
        specs.append({
            "name": source_name,
            "keys": (key,),
            "min": low,
            "max": high,
            "required": False,
        })

    # Runtime sources proven healthy in two consecutive Phase 4 shipments.
    # Every field is optional and source-preserving.  Do not alias H2/H3-Frequ
    # to H2/H3-Hz, or realopeningN to the established guide-vane contract.
    phase4_runtime_metrics = (
        ("ACfrequency", "mhy2_ac_frequency_raw", 0.0, 100.0),
        ("outfrequency", "mhy2_output_frequency_raw", 0.0, 100.0),
        ("Outvoltage", "mhy2_output_voltage_raw", 0.0, 1000.0),
        ("DCinput", "mhy2_dc_input_raw", 0.0, 1000.0),
        ("ACviltagein", "mhy2_ac_input_voltage_raw", 0.0, 1000.0),
        ("powerout", "mhy2_output_power_raw", 0.0, 100.0),
        ("Outcurent", "mhy2_output_current_raw", 0.0, 1000.0),
        ("tempin", "mhy2_input_temperature_raw", -50.0, 200.0),
        ("tempout", "mhy2_output_temperature_raw", -50.0, 200.0),
        ("DCfault", "mhy2_dc_fault_raw", 0.0, 1.0),
        ("H1Spare19", "mhy2_h1_spare19_raw", 0.0, 1.0),
        ("Warning", "mhy2_warning_raw", 0.0, 65535.0),
        ("H1comgroup2", "u1_start_secondary_group_raw", 0.0, 65535.0),
        ("H2comgroup2", "u2_start_secondary_group_raw", 0.0, 65535.0),
        ("H3comgroup1", "u3_start_secondary_group_raw", 0.0, 65535.0),
        ("H1Brakeoff", "u1_brake_off_raw", 0.0, 1.0),
        ("H2Brakeoff", "u2_brake_off_raw", 0.0, 1.0),
        ("H3Brakeoff", "u3_brake_off_raw", 0.0, 1.0),
        ("H1local", "u1_local_raw", 0.0, 1.0),
        ("H2local", "u2_local_raw", 0.0, 1.0),
        ("H3local", "u3_local_raw", 0.0, 1.0),
        ("H1remote", "u1_remote_raw", 0.0, 1.0),
        ("H2remote", "u2_remote_raw", 0.0, 1.0),
        ("H3remote", "u3_remote_raw", 0.0, 1.0),
        ("H1Spare7", "u1_spare7_raw", 0.0, 1.0),
        ("H2Spare7", "u2_spare7_raw", 0.0, 1.0),
        ("H3Spare7", "u3_spare7_raw", 0.0, 1.0),
        ("H1DeExcitff", "u1_de_excitff_raw", 0.0, 1.0),
        ("H2DeExcitff", "u2_de_excitff_raw", 0.0, 1.0),
        ("H3DeExcitff", "u3_de_excitff_raw", 0.0, 1.0),
        ("H2Brakeopen", "u2_brake_open_raw", 0.0, 1.0),
        ("H3Brakeopen", "u3_brake_open_raw", 0.0, 1.0),
        ("H1Startsyn", "u1_start_syn_raw", 0.0, 1.0),
        ("H2Startsyn", "u2_start_syn_raw", 0.0, 1.0),
        ("H3Startsyn", "u3_start_syn_raw", 0.0, 1.0),
        ("H1Spristore", "u1_spri_store_raw", 0.0, 1.0),
        ("H2Spristore", "u2_spri_store_raw", 0.0, 1.0),
        ("H3Spristore", "u3_spri_store_raw", 0.0, 1.0),
        ("H1Springcharg", "u1_spring_charg_raw", 0.0, 1.0),
        ("H2Springcharg", "u2_spring_charg_raw", 0.0, 1.0),
        ("H3Springcharg", "u3_spring_charg_raw", 0.0, 1.0),
        ("H1MVopen", "u1_mv_open_raw", 0.0, 1.0),
        ("H2MVopen", "u2_mv_open_raw", 0.0, 1.0),
        ("H3MVopen", "u3_mv_open_raw", 0.0, 1.0),
        ("H1MVclose", "u1_mv_close_raw", 0.0, 1.0),
        ("H2MVclose", "u2_mv_close_raw", 0.0, 1.0),
        ("H3MVclose", "u3_mv_close_raw", 0.0, 1.0),
        ("realopening1", "u1_real_opening_raw", 0.0, 120.0),
        ("realopening2", "u2_real_opening_raw", 0.0, 120.0),
        ("realopening3", "u3_real_opening_raw", 0.0, 120.0),
        ("H2-Frequ", "u2_start_frequency_raw", 0.0, 100.0),
        ("H3-Frequ", "u3_start_frequency_raw", 0.0, 100.0),
    )
    for source_name, key, low, high in phase4_runtime_metrics:
        specs.append({
            "name": source_name,
            "keys": (key,),
            "min": low,
            "max": high,
            "required": False,
            "project_files": DAKROSA2_RUNTIME_PROJECT_FILES,
        })

    # Exact parameter-picture sources proven healthy in two consecutive
    # Phase 8 Runtime shipments.  Preserve the native phase values as raw
    # fields: KW1/KW3 are PA/PC in kW, while KWA1/KWA3 are QA/QC in kVAr
    # despite the native KWA spelling.  Keep signed Q values and do not infer
    # a scale for the KVArh counter.
    parameter_metrics = (
        ("H1_temp11", "u1_temp11", 5.0, 150.0),
    )
    for unit_number in (1, 2, 3):
        source_prefix = "H%d" % unit_number
        key_prefix = "u%d_" % unit_number
        parameter_metrics += (
            (source_prefix + "-KW1",
             key_prefix + "phase_a_active_power_raw",
             -10000.0, 10000.0),
            (source_prefix + "-KWA1",
             key_prefix + "phase_a_reactive_power_raw",
             -10000.0, 10000.0),
            (source_prefix + "-KW3",
             key_prefix + "phase_c_active_power_raw",
             -10000.0, 10000.0),
            (source_prefix + "-KWA3",
             key_prefix + "phase_c_reactive_power_raw",
             -10000.0, 10000.0),
            (source_prefix + "-KVArh",
             key_prefix + "reactive_energy_raw",
             0.0, 1.0e9),
        )
    for source_name, key, low, high in parameter_metrics:
        specs.append({
            "name": source_name,
            "keys": (key,),
            "min": low,
            "max": high,
            "required": False,
            "project_files": DAKROSA2_RUNTIME_PROJECT_FILES,
        })

    # Connect is preserved as a neutral raw binary.  Two Phase 5 production
    # shipments proved type/state/value transport, but not process semantics.
    specs.append({
        "name": "Connect",
        "keys": ("scada_connect_raw",),
        "min": 0.0,
        "max": 1.0,
        "allowed_values": (0.0, 1.0),
        "required": False,
        "project_files": DAKROSA2_RUNTIME_PROJECT_FILES,
    })
    return tuple(specs)


STATION2_CURATED_SPECS = _station2_curated_specs()
CALLBACK_CANARY_TAGS = ("LV-KW", "H1-KW", "H2-KW", "H3-KW")
# Read-only names recovered from Dakrosa2 PDLs.  Diagnostic tags stay separate
# from the curated snapshot until live type/state/value evidence has been
# reviewed.  Never add Click*, command, or setpoint channels here.
BASE_SCADA_DIAGNOSTIC_TAGS = (
    "471close",
    "H1QFclose",
    "H2QFclose",
    "H3QFclose",
    "H1comgroup1",
    "H2comgroup1",
    "H3comgroup0",
    "AUX_LCU41_IW0",
    "OpenFull",
    "CloseFull",
    "MotorStatus",
    "Quatai",
    "Loipha",
    "remoterlocal",
    "Domo",
    "Apsuat1",
    "Apsuat2",
    "Apsuatcao",
    "apKTH1",
    "apKTH2",
    "apKTH3",
    "dongKTH1",
    "dongKTH2",
    "dongKTH3",
)

# MHY_2.PDL inventory remains in the exact probe for regression evidence.
# Twelve healthy sources are also promoted through the project-gated curated
# specs above; DCTC- stays diagnostic because Runtime did not expose it.
MHY2_DIAGNOSTIC_TAGS = (
    "ACfrequency",
    "outfrequency",
    "Outvoltage",
    "DCTC-",
    "DCinput",
    "ACviltagein",
    "powerout",
    "Outcurent",
    "tempin",
    "tempout",
    "DCfault",
    "H1Spare19",
    "Warning",
)

# A_H1/H2/H3_chart_kd.PDL inventory remains in the exact probe.  Forty healthy
# sources are also project-gated above.  H1Brakeopen is intentionally absent
# because H1 references H2Brakeopen; the six type-mismatched valve sources stay
# diagnostic, and all Click*/command actions stay excluded.
START_SEQUENCE_DIAGNOSTIC_TAGS = (
    "H1comgroup2", "H2comgroup2", "H3comgroup1",
    "H1Brakeoff", "H2Brakeoff", "H3Brakeoff",
    "H1local", "H2local", "H3local",
    "H1remote", "H2remote", "H3remote",
    "H1Spare7", "H2Spare7", "H3Spare7",
    "H1OpMvalve", "H2OpMvalve", "H3OpMvalve",
    "H1Opvalve", "H2Opvalve", "H3Opvalve",
    "H1DeExcitff", "H2DeExcitff", "H3DeExcitff",
    "H2Brakeopen", "H3Brakeopen",
    "H1Startsyn", "H2Startsyn", "H3Startsyn",
    "H1Spristore", "H2Spristore", "H3Spristore",
    "H1Springcharg", "H2Springcharg", "H3Springcharg",
    "H1MVopen", "H2MVopen", "H3MVopen",
    "H1MVclose", "H2MVclose", "H3MVclose",
    "realopening1", "realopening2", "realopening3",
    "H2-Frequ", "H3-Frequ",
)

# Exact read-only excitation values recovered from the H2/H3 start pictures.
# Both Button1 objects call GetTagDouble for the matching source and have a
# matching CTrigger.  Keep them diagnostic-only until two fresh Runtime
# shipments establish type, state, value, and scale.  H1Excit is deliberately
# excluded because its recovered CTrigger references H2Excit.
START_EXCITATION_DIAGNOSTIC_TAGS = (
    "H2Excit",
    "H3Excit",
)

# Exact native event names recovered from the trend operator screen.  Keep
# these diagnostic-only until fresh Runtime shipments establish a healthy
# state and station-2 semantics.  Connect graduated to the curated canonical
# specs in 1.5.21 and must not be read a second time through this list.
OPERATOR_DIAGNOSTIC_TAGS = (
    "EVENT_TYPE_MH1",
    "EVENT_TYPE_MH2",
    "EVENT_TYPE_MH3",
)

# Exact read-only OutputValue links recovered from the complete BangkwhH2.PDL
# child picture.  Keep these directional energy counters diagnostic-only until
# two fresh Runtime shipments establish availability, type, state, and scale.
H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS = (
    "MWHPX_INTER_MH2",
    "MWHNX_INTER_MH2",
    "MVARHPX_INTER_MH2",
    "MVARHNX_INTER_MH2",
)

# Exact read-only 22 kV export-meter line-line voltage UCA.  The curated
# LV-UCA spec (bus_U31/lv_U31) requested this source on every snapshot cycle
# since 1.5.16 without one published sample, while the sibling LV-UAB and
# LV-UBC sources deliver live values.  Demoted from the curated specs to this
# exact probe in 1.5.27 so fresh shipments show the concrete failure mode
# (name missing from the Data Manager vs bad state vs out-of-bounds value).
# A name must not sit in both lists, mirroring the Connect precedent.
EXPORT_METER_DIAGNOSTIC_TAGS = (
    "LV-UCA",
)

SCADA_DIAGNOSTIC_TAGS = (
    BASE_SCADA_DIAGNOSTIC_TAGS +
    MHY2_DIAGNOSTIC_TAGS +
    START_SEQUENCE_DIAGNOSTIC_TAGS +
    START_EXCITATION_DIAGNOSTIC_TAGS +
    OPERATOR_DIAGNOSTIC_TAGS +
    H2_DIRECTIONAL_ENERGY_DIAGNOSTIC_TAGS +
    EXPORT_METER_DIAGNOSTIC_TAGS
)

class WinCCRuntimeAPI:
    """Thin adapter over WinCC's external 32-bit DMCLIENT API."""

    def __init__(self, dmclient=None, configure=True, bin_dir=None,
                 application_name="wincc-bridge"):
        self._dll_dir_handle = None
        if dmclient is None:
            if ctypes.sizeof(ctypes.c_void_p) != 4:
                raise RuntimeError("WinCC Runtime API requires 32-bit Python")
            bin_dir = locate_wincc_bin(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                self._dll_dir_handle = os.add_dll_directory(bin_dir)
            elif hasattr(ctypes, "windll"):
                ctypes.windll.kernel32.SetDllDirectoryW(str(bin_dir))
            dmclient = ctypes.WinDLL(os.path.join(bin_dir, "dmclient.dll"))
        self.dmclient = dmclient
        self._application_name = str(application_name)
        self._connected = False
        self._notify_callback = None
        self._subscriptions = []
        self._retired_subscriptions = []
        if configure:
            self._configure_dmclient()

    def _configure_dmclient(self):
        connect = self.dmclient.DMConnectW
        connect.restype = ctypes.c_int
        connect.argtypes = [
            ctypes.c_wchar_p, DMNotifyProcW, ctypes.c_void_p,
            ctypes.POINTER(CMNErrorW),
        ]
        disconnect = self.dmclient.DMDisConnectW
        disconnect.restype = ctypes.c_int
        disconnect.argtypes = [ctypes.POINTER(CMNErrorW)]
        runtime_project = self.dmclient.DMGetRuntimeProjectW
        runtime_project.restype = ctypes.c_int
        runtime_project.argtypes = [
            ctypes.POINTER(ctypes.c_wchar), ctypes.c_ulong,
            ctypes.POINTER(CMNErrorW),
        ]
        enum_variables = self.dmclient.DMEnumVariablesW
        enum_variables.restype = ctypes.c_int
        enum_variables.argtypes = [
            ctypes.c_wchar_p, ctypes.c_void_p, DMEnumVarProcW,
            ctypes.c_void_p, ctypes.POINTER(CMNErrorW),
        ]
        get_var_type = self.dmclient.DMGetVarTypeW
        get_var_type.restype = ctypes.c_int
        get_var_type.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(DMVarKeyW), ctypes.c_ulong,
            ctypes.POINTER(DMTypeRefW), ctypes.POINTER(CMNErrorW),
        ]
        get_value = self.dmclient.DMGetValueW
        get_value.restype = ctypes.c_int
        get_value.argtypes = [
            ctypes.POINTER(DMVarKeyW), ctypes.c_ulong,
            ctypes.POINTER(DMVarUpdateW), ctypes.POINTER(CMNErrorW),
        ]
        begin_updates = self.dmclient.DMBeginStartVarUpdateW
        begin_updates.restype = ctypes.c_int
        begin_updates.argtypes = [
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(CMNErrorW),
        ]
        start_updates = self.dmclient.DMStartVarUpdateExW
        start_updates.restype = ctypes.c_int
        start_updates.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(DMVarKeyW), ctypes.c_uint32,
            ctypes.c_uint32, DMNotifyVariableExProcW, ctypes.c_void_p,
            ctypes.POINTER(CMNErrorW),
        ]
        end_updates = self.dmclient.DMEndStartVarUpdateW
        end_updates.restype = ctypes.c_int
        end_updates.argtypes = [ctypes.c_uint32, ctypes.POINTER(CMNErrorW)]
        stop_updates = self.dmclient.DMStopVarUpdateW
        stop_updates.restype = ctypes.c_int
        stop_updates.argtypes = [ctypes.c_uint32, ctypes.POINTER(CMNErrorW)]

    def connect(self):
        @DMNotifyProcW
        def notify(_notify_class, _notify_code, _data, _items, _user):
            return 1

        error = CMNErrorW()
        ok = self.dmclient.DMConnectW(
            self._application_name, notify, None, ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMConnectW", error)
        self._notify_callback = notify
        self._connected = True

    def disconnect(self):
        if not self._connected:
            return
        for subscription in list(self._subscriptions):
            try:
                self.stop_updates(subscription)
            except Exception:
                pass
        error = CMNErrorW()
        ok = self.dmclient.DMDisConnectW(ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMDisConnectW", error)
        self._connected = False
        self._notify_callback = None
        self._subscriptions = []
        self._retired_subscriptions = []

    def read_numeric(self, name, type_code):
        try:
            numeric_type = int(type_code)
        except (TypeError, ValueError):
            numeric_type = 0
        if numeric_type not in NUMERIC_TYPE_CODES:
            raise ValueError("unsupported numeric type: %s" % type_code)
        key = DMVarKeyW()
        key.dwKeyType = 2
        key.szName = str(name)
        update = DMVarUpdateW()
        error = CMNErrorW()
        ok = self.dmclient.DMGetValueW(
            ctypes.byref(key), 1, ctypes.byref(update), ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMGetValueW", error)
        return self._numeric_update(name, update)

    @staticmethod
    def _numeric_update(name, update):
        variant_type = int(update.dmValue.vt) & 0x0FFF
        field = _VARIANT_NUMERIC_FIELDS.get(variant_type)
        if not field:
            raise ValueError("unsupported VARIANT type %s for %s" %
                             (variant_type, name))
        value = float(getattr(update.dmValue, field))
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("non-finite WinCC value for %s" % name)
        return {
            "value": value,
            "state": int(update.dwState),
            "quality": None,
        }

    def read_numerics(self, names, type_code):
        """Read a bounded exact-name list in one DMGetValueW call."""
        try:
            numeric_type = int(type_code)
        except (TypeError, ValueError):
            numeric_type = 0
        if numeric_type not in NUMERIC_TYPE_CODES:
            raise ValueError("unsupported numeric type: %s" % type_code)
        names = [str(name) for name in names]
        if not names:
            return {}
        if len(names) > 256:
            raise ValueError("too many WinCC values in one batch")
        keys = (DMVarKeyW * len(names))()
        updates = (DMVarUpdateW * len(names))()
        for index, name in enumerate(names):
            keys[index].dwKeyType = 2
            keys[index].szName = name
        error = CMNErrorW()
        ok = self.dmclient.DMGetValueW(
            keys, len(names), updates, ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMGetValueW", error)
        result = {}
        for index, name in enumerate(names):
            try:
                result[name] = self._numeric_update(name, updates[index])
            except (TypeError, ValueError):
                continue
        return result

    def start_updates(self, names, on_updates, cycle=2):
        """Subscribe to exact numeric names through the public Ex callback API."""
        names = [str(name) for name in names]
        if not names or len(names) > 256:
            raise ValueError("WinCC subscription requires 1..256 names")
        cycle = int(cycle)
        if cycle < 0 or cycle >= 16:
            raise ValueError("WinCC update cycle must be an index from 0 to 15")
        if not callable(on_updates):
            raise TypeError("on_updates must be callable")

        taid = ctypes.c_uint32()
        error = CMNErrorW()
        ok = self.dmclient.DMBeginStartVarUpdateW(
            ctypes.byref(taid), ctypes.byref(error))
        if not ok or not taid.value:
            self._raise_dm_error("DMBeginStartVarUpdateW", error)

        keys = (DMVarKeyW * len(names))()
        expected = set(names)
        for index, name in enumerate(names):
            keys[index].dwKeyType = 2
            keys[index].szName = name
        stats = {"callbacks": 0, "items": 0, "errors": 0, "oversized": 0}

        @DMNotifyVariableExProcW
        def receive(_taid, updates, items, _user):
            try:
                stats["callbacks"] += 1
                stats["items"] += int(items)
                if not updates:
                    return 1
                safe_items = min(int(items), len(names))
                if int(items) > len(names):
                    stats["oversized"] += 1
                batch = {}
                for index in range(safe_items):
                    try:
                        update = updates[index]
                        name = str(update.dmVarKey.szName or "")
                        if name not in expected:
                            continue
                        sample = self._numeric_update(name, update)
                        sample["quality"] = int(update.dwQualityCode)
                        sample["variant_type"] = int(update.dmValue.vt) & 0x0FFF
                        batch[name] = sample
                    except Exception:
                        stats["errors"] += 1
                if batch:
                    on_updates(batch)
            except BaseException:
                # Never let Python exceptions cross WinCC's native callback ABI.
                stats["errors"] += 1
            return 1

        subscription = DMVarSubscription(taid.value, keys, receive, stats)
        # Start/End can still leave a late native callback.  Pin first, and
        # release only after DMDisConnectW succeeds.
        self._retired_subscriptions.append(subscription)
        started = False
        try:
            error = CMNErrorW()
            ok = self.dmclient.DMStartVarUpdateExW(
                taid.value, keys, len(names), cycle,
                receive, None, ctypes.byref(error))
            if not ok:
                self._raise_dm_error("DMStartVarUpdateExW", error)
            started = True
            error = CMNErrorW()
            ok = self.dmclient.DMEndStartVarUpdateW(
                taid.value, ctypes.byref(error))
            if not ok:
                self._raise_dm_error("DMEndStartVarUpdateW", error)
        except Exception:
            if started or taid.value:
                try:
                    self._stop_taid(taid.value)
                except Exception:
                    pass
            raise

        self._retired_subscriptions.remove(subscription)
        subscription.active = True
        self._subscriptions.append(subscription)
        return subscription

    def _stop_taid(self, taid):
        error = CMNErrorW()
        ok = self.dmclient.DMStopVarUpdateW(int(taid), ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMStopVarUpdateW", error)

    def stop_updates(self, subscription):
        if not subscription or not subscription.active:
            return
        self._stop_taid(subscription.taid)
        subscription.active = False
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)
        # A late callback may race Stop.  Release these only after Disconnect.
        self._retired_subscriptions.append(subscription)

    @staticmethod
    def _raise_dm_error(operation, error):
        text = str(error.szErrorText or "").strip()
        codes = [error.dwError1, error.dwError2, error.dwError3,
                 error.dwError4, error.dwError5]
        detail = text or "/".join("0x%08X" % int(code) for code in codes)
        raise RuntimeError("%s failed: %s" % (operation, detail))

    def runtime_project(self):
        buffer = ctypes.create_unicode_buffer(1024)
        error = CMNErrorW()
        ok = self.dmclient.DMGetRuntimeProjectW(
            buffer, len(buffer), ctypes.byref(error))
        if not ok or not buffer.value:
            self._raise_dm_error("DMGetRuntimeProjectW", error)
        return buffer.value

    def enumerate_tags(self, project):
        tags = []

        @DMEnumVarProcW
        def receive(key_ptr, _user):
            if key_ptr:
                key = key_ptr.contents
                name = str(key.szName or "")
                if name:
                    tags.append({"id": int(key.dwID), "name": name})
            return 1

        error = CMNErrorW()
        ok = self.dmclient.DMEnumVariablesW(
            str(project), None, receive, None, ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMEnumVariablesW", error)
        seen = set()
        unique = []
        for tag in tags:
            name = tag["name"].lower()
            if name not in seen:
                seen.add(name)
                unique.append(tag)
        return unique

    def tag_type(self, project, tag):
        key = DMVarKeyW()
        key.dwID = int(tag.get("id", 0))
        key.szName = str(tag.get("name", ""))
        key.dwKeyType = 3 if key.dwID else 2
        type_ref = DMTypeRefW()
        error = CMNErrorW()
        ok = self.dmclient.DMGetVarTypeW(
            str(project), ctypes.byref(key), 1,
            ctypes.byref(type_ref), ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMGetVarTypeW", error)
        return {
            "code": int(type_ref.dwType),
            "size": int(type_ref.dwSize),
            "name": str(type_ref.szTypeName or ""),
        }


def _candidate_score(name):
    # WinCC projects commonly use camel-case fragments such as BearingTemp.
    name = str(name)
    if name.startswith("@"):
        return 0
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    valuable = len(_VALUABLE_TOKEN.findall(normalized))
    events = len(_EVENT_TOKEN.findall(normalized))
    telemetry = max(0, valuable - events)
    return telemetry * 10 + events


def select_candidate_tags(tags, limit=512):
    """Return likely operational tags, highest-signal names first."""
    ranked = []
    for tag in tags:
        score = _candidate_score(tag.get("name", ""))
        if score:
            ranked.append((-score, str(tag.get("name", "")).lower(), tag))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:max(0, int(limit))]]


def _exact_probe(api, project, tags, names, read_values):
    requested = []
    denied = []
    seen = set()
    for value in names or ():
        name = str(value).strip()
        folded = name.lower()
        if name and folded not in seen:
            seen.add(folded)
            if folded.startswith("click") or "command" in folded:
                denied.append(name)
            else:
                requested.append(name)
    by_name = {
        str(tag.get("name", "")).lower(): tag
        for tag in tags
        if str(tag.get("name", ""))
    }
    found = []
    missing = []
    for requested_name in requested:
        tag = by_name.get(requested_name.lower())
        if tag is None:
            missing.append(requested_name)
            continue
        name = str(tag.get("name", ""))
        item = {"id": int(tag.get("id", 0)), "name": name}
        try:
            type_info = api.tag_type(project, tag)
            type_code = int(type_info.get("code", 0))
            item.update({
                "type_code": type_code,
                "type_name": str(type_info.get("name", "")),
                "type_size": int(type_info.get("size", 0)),
            })
            if read_values and type_code in NUMERIC_TYPE_CODES:
                item.update(api.read_numeric(name, type_code))
        except Exception as exc:
            item["error"] = str(exc)[:200]
        found.append(item)
    return {
        "requested": len(requested) + len(denied),
        "found": len(found),
        "missing": missing,
        "denied": denied,
        "tags": found,
    }


def build_probe(api, inventory_limit=4000, candidate_limit=512,
                read_values=True, exact_names=(), project=None):
    """Build a bounded JSON-safe diagnostic payload from a WinCC API adapter."""
    try:
        if project is None:
            project = api.runtime_project()
        tags = list(api.enumerate_tags(project))
        inventory_cap = max(0, int(inventory_limit))
        result = {
            "available": True,
            "backend": "wincc-dmclient",
            "project": ntpath.basename(project),
            "total_tags": len(tags),
            "inventory": [
                {"id": int(tag.get("id", 0)), "name": str(tag.get("name", ""))}
                for tag in tags[:inventory_cap]
            ],
            "inventory_truncated": len(tags) > inventory_cap,
            "candidates": [],
        }
        for tag in select_candidate_tags(tags, candidate_limit):
            name = str(tag.get("name", ""))
            item = {"id": int(tag.get("id", 0)), "name": name}
            try:
                type_info = api.tag_type(project, tag)
                type_code = int(type_info.get("code", 0))
                item.update({
                    "type_code": type_code,
                    "type_name": str(type_info.get("name", "")),
                    "type_size": int(type_info.get("size", 0)),
                })
                if read_values and type_code in NUMERIC_TYPE_CODES:
                    item.update(api.read_numeric(name, type_code))
            except Exception as exc:
                item["error"] = str(exc)[:200]
            result["candidates"].append(item)
        result["exact"] = _exact_probe(
            api, project, tags, exact_names, read_values)
        return result
    except Exception as exc:
        return {
            "available": False,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
        }


def probe_runtime(inventory_limit=4000, candidate_limit=512,
                  api_factory=WinCCRuntimeAPI, read_values=True,
                  exact_names=None, station_name=""):
    """Create the real adapter at the boundary and always return diagnostics."""
    try:
        api = api_factory()
    except Exception as exc:
        return {
            "available": False,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
        }
    connected = False
    try:
        if hasattr(api, "connect"):
            api.connect()
            connected = True
        project = api.runtime_project()
        if exact_names is None:
            station = str(station_name or "").strip().lower()
            project_file = ntpath.basename(
                str(project or "")).strip().lower()
            if (station == "dakrosa2" and
                    project_file in DAKROSA2_RUNTIME_PROJECT_FILES):
                exact_names = SCADA_DIAGNOSTIC_TAGS
            else:
                exact_names = ()
        return build_probe(api, inventory_limit=inventory_limit,
                           candidate_limit=candidate_limit,
                           read_values=read_values,
                           exact_names=exact_names,
                           project=project)
    except Exception as exc:
        return {
            "available": False,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
        }
    finally:
        if connected and hasattr(api, "disconnect"):
            try:
                api.disconnect()
            except Exception:
                pass


def _snapshot_stat(value, snapshot_utc):
    value = float(value)
    return {
        "count": 1,
        "last": value,
        "min": value,
        "max": value,
        "avg": value,
        "last_ts": str(snapshot_utc),
        "source": "wincc-dmclient",
        "realtime": True,
        "quality": None,
        "state": 0,
    }


def _project_eligible_specs(api, specs):
    """Fail closed for specs whose production evidence is project-bound."""
    gated = tuple(spec for spec in specs if spec.get("project_files"))
    if not gated:
        return tuple(specs), 0

    project_file = ""
    if hasattr(api, "runtime_project"):
        try:
            project_file = ntpath.basename(
                str(api.runtime_project() or "")).strip().lower()
        except Exception:
            project_file = ""

    eligible = []
    skipped = 0
    for spec in specs:
        allowed = spec.get("project_files")
        if allowed and project_file not in allowed:
            skipped += 1
            continue
        eligible.append(spec)
    return tuple(eligible), skipped


def read_curated_snapshot(station_name, snapshot_utc,
                          api_factory=WinCCRuntimeAPI, specs=None):
    """Read an exact, bounded tag allow-list without enumerating the project.

    Archive values remain the caller's fallback.  Only state=0, finite values
    inside a metric-specific physical range are returned for merging.
    """
    station = str(station_name or "").strip().lower()
    if specs is None:
        specs = STATION2_CURATED_SPECS if station == "dakrosa2" else ()
    specs = tuple(specs)
    required_attempted = sum(
        1 for spec in specs if spec.get("required", True))
    if not specs:
        return {
            "available": False,
            "supported": False,
            "backend": "wincc-dmclient",
            "attempted": 0,
            "accepted": 0,
            "rejected": 0,
            "required_attempted": 0,
            "required_accepted": 0,
            "tags": {},
        }
    try:
        api = api_factory()
    except Exception as exc:
        return {
            "available": False,
            "supported": True,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
            "attempted": 0,
            "accepted": 0,
            "rejected": len(specs),
            "required_attempted": required_attempted,
            "required_accepted": 0,
            "tags": {},
        }
    connected = False
    tags = {}
    accepted = 0
    rejected = 0
    required_accepted = 0
    project_gated_skipped = 0
    try:
        if hasattr(api, "connect"):
            api.connect()
            connected = True
        specs, project_gated_skipped = _project_eligible_specs(api, specs)
        required_attempted = sum(
            1 for spec in specs if spec.get("required", True))
        batch_samples = None
        if hasattr(api, "read_numerics"):
            try:
                batch_samples = api.read_numerics(
                    [spec["name"] for spec in specs], 8)
            except Exception:
                # Compatibility fallback for older Runtime/Data Manager builds.
                batch_samples = None
        for spec in specs:
            try:
                if batch_samples is None:
                    sample = api.read_numeric(spec["name"], 8)
                else:
                    sample = batch_samples[spec["name"]]
                value = float(sample["value"])
                if spec.get("absolute"):
                    value = abs(value)
                state = sample.get("state", -1)
                allowed_values = spec.get("allowed_values")
                if (isinstance(state, bool) or state != 0 or
                        not math.isfinite(value) or
                        value < float(spec["min"]) or
                        value > float(spec["max"]) or
                        (allowed_values is not None and
                         value not in allowed_values)):
                    rejected += 1
                    continue
                stat = _snapshot_stat(value, snapshot_utc)
                for key in spec["keys"]:
                    tags[str(key)] = dict(stat)
                accepted += 1
                if spec.get("required", True):
                    required_accepted += 1
            except Exception:
                rejected += 1
        result = {
            "available": accepted > 0,
            "supported": True,
            "backend": "wincc-dmclient",
            "attempted": len(specs),
            "accepted": accepted,
            "rejected": rejected,
            "required_attempted": required_attempted,
            "required_accepted": required_accepted,
            "project_gated_skipped": project_gated_skipped,
            "tags": tags,
        }
        if not accepted:
            result["error"] = "no curated Runtime values passed validation"
        return result
    except Exception as exc:
        return {
            "available": False,
            "supported": True,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
            "attempted": len(specs),
            "accepted": accepted,
            "rejected": len(specs) - accepted,
            "required_attempted": required_attempted,
            "required_accepted": required_accepted,
            "project_gated_skipped": project_gated_skipped,
            "tags": {},
        }
    finally:
        if connected and hasattr(api, "disconnect"):
            try:
                api.disconnect()
            except Exception:
                pass


def _utc_now():
    return (datetime.datetime.now(datetime.timezone.utc)
            .isoformat().replace("+00:00", "Z"))


def _pump_windows_messages(max_messages=256):
    """Dispatch DMCLIENT's hidden-window messages on the owner thread."""
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return 0
    user32 = ctypes.windll.user32
    peek = user32.PeekMessageW
    peek.restype = ctypes.c_int
    peek.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
        wintypes.UINT, wintypes.UINT,
    ]
    translate = user32.TranslateMessage
    translate.restype = ctypes.c_int
    translate.argtypes = [ctypes.POINTER(wintypes.MSG)]
    dispatch = user32.DispatchMessageW
    dispatch.restype = ctypes.c_ssize_t
    dispatch.argtypes = [ctypes.POINTER(wintypes.MSG)]
    message = wintypes.MSG()
    pumped = 0
    while pumped < int(max_messages) and peek(
            ctypes.byref(message), None, 0, 0, 1):  # PM_REMOVE
        translate(ctypes.byref(message))
        dispatch(ctypes.byref(message))
        pumped += 1
    return pumped


def run_callback_canary(emit, stop_event, api_factory=None,
                        heartbeat_sec=5.0, callback_timeout_sec=15.0,
                        poll_sec=0.05, message_pump=None):
    """Observe four Dakrosa2 power tags without changing snapshot values."""
    session = "%s-%s" % (os.getpid(), int(time.time()))
    state_lock = threading.Lock()
    tag_state = {}
    callback_state = {
        "last_utc": None,
        "last_monotonic": None,
        "first_latency_ms": None,
    }
    started_at = time.monotonic()
    if message_pump is None:
        message_pump = _pump_windows_messages
    api = None
    subscription = None
    connected = False
    emit({
        "event": "start",
        "session": session,
        "tags_requested": list(CALLBACK_CANARY_TAGS),
        "cycle_index": 2,
        "cycle_ms": 500,
    })

    def accept(batch):
        now_utc = _utc_now()
        now_mono = time.monotonic()
        with state_lock:
            if callback_state["last_monotonic"] is None:
                callback_state["first_latency_ms"] = round(
                    (now_mono - started_at) * 1000.0, 1)
            callback_state["last_utc"] = now_utc
            callback_state["last_monotonic"] = now_mono
            for name, sample in batch.items():
                previous = tag_state.get(name, {})
                tag_state[name] = {
                    "value": sample.get("value"),
                    "state": sample.get("state"),
                    "quality": sample.get("quality"),
                    "variant_type": sample.get("variant_type"),
                    "count": int(previous.get("count", 0)) + 1,
                    "last_utc": now_utc,
                }

    try:
        if api_factory is None:
            api = WinCCRuntimeAPI(application_name="wincc-bridge-canary")
        else:
            api = api_factory()
        api.connect()
        connected = True
        emit({"event": "connected", "session": session})
        subscription = api.start_updates(
            CALLBACK_CANARY_TAGS, accept, cycle=2)
        emit({
            "event": "subscribed",
            "session": session,
            "taid": subscription.taid,
            "tags_requested": len(CALLBACK_CANARY_TAGS),
        })
        first_reported = False
        last_heartbeat = 0.0
        while not stop_event.is_set():
            message_pump()
            if stop_event.wait(max(0.01, float(poll_sec))):
                break
            now = time.monotonic()
            with state_lock:
                last_mono = callback_state["last_monotonic"]
                last_utc = callback_state["last_utc"]
                first_latency = callback_state["first_latency_ms"]
                tags = {name: dict(value) for name, value in tag_state.items()}
            if last_mono is not None and not first_reported:
                emit({
                    "event": "first_callback",
                    "session": session,
                    "first_latency_ms": first_latency,
                    "tags_seen": len(tags),
                })
                first_reported = True
            age = None if last_mono is None else max(0.0, now - last_mono)
            if now - last_heartbeat >= max(0.01, float(heartbeat_sec)):
                emit({
                    "event": "heartbeat",
                    "session": session,
                    "callbacks": subscription.stats["callbacks"],
                    "items": subscription.stats["items"],
                    "callback_errors": subscription.stats["errors"],
                    "oversized_callbacks": subscription.stats["oversized"],
                    "last_callback_utc": last_utc,
                    "last_age_sec": None if age is None else round(age, 3),
                    "tags": tags,
                })
                last_heartbeat = now
            if now - started_at > callback_timeout_sec and (
                    last_mono is None or age > callback_timeout_sec):
                raise RuntimeError("WinCC callback timeout")
    finally:
        if subscription is not None and api is not None:
            try:
                api.stop_updates(subscription)
                emit({"event": "stop", "session": session, "ok": True})
            except Exception as exc:
                emit({
                    "event": "stop",
                    "session": session,
                    "ok": False,
                    "error": str(exc)[:200],
                })
        if connected and api is not None:
            try:
                api.disconnect()
                emit({"event": "disconnect", "session": session, "ok": True})
            except Exception as exc:
                emit({
                    "event": "disconnect",
                    "session": session,
                    "ok": False,
                    "error": str(exc)[:200],
                })


def _watch_parent_stdin(stop_event):
    try:
        sys.stdin.buffer.read(1)
    except Exception:
        pass
    stop_event.set()


def _main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--callback-canary", action="store_true")
    parser.add_argument("--station", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--read-mode", default="")
    parser.add_argument("--watch-stdin", action="store_true")
    args = parser.parse_args(argv)
    if not args.callback_canary:
        parser.error("only --callback-canary is supported when run directly")
    if str(args.station).strip().lower() != "dakrosa2":
        parser.error("callback canary is restricted to Dakrosa2")
    if str(args.mode).strip().lower() != "local":
        parser.error("callback canary requires local WinCC mode")
    if str(args.read_mode).strip().lower() != "raw":
        parser.error("callback canary requires raw snapshot mode")
    if not args.watch_stdin:
        parser.error("callback canary requires --watch-stdin")
    stop_event = threading.Event()
    if args.watch_stdin:
        watcher = threading.Thread(
            target=_watch_parent_stdin, args=(stop_event,), daemon=True)
        watcher.start()

    def emit(payload):
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    try:
        run_callback_canary(emit, stop_event)
        return 0
    except KeyboardInterrupt:
        stop_event.set()
        return 0
    except Exception as exc:
        emit({
            "event": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        })
        return 1


if __name__ == "__main__":
    sys.exit(_main())
