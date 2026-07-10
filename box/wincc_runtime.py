"""Read-only WinCC Runtime tag discovery and value sampling.

The public helpers in this module deliberately accept an injected API object so
the selection and payload logic can be tested without WinCC or 32-bit Python.
"""
import ctypes
import math
import ntpath
import os
import re


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
        ("lpvUserData", ctypes.c_void_p),
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


class WinCCRuntimeAPI:
    """Thin adapter over WinCC's external 32-bit DMCLIENT API."""

    def __init__(self, dmclient=None, configure=True, bin_dir=None):
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
        self._connected = False
        self._notify_callback = None
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

    def connect(self):
        @DMNotifyProcW
        def notify(_notify_class, _notify_code, _data, _items, _user):
            return 1

        error = CMNErrorW()
        ok = self.dmclient.DMConnectW(
            "wincc-bridge", notify, None, ctypes.byref(error))
        if not ok:
            self._raise_dm_error("DMConnectW", error)
        self._notify_callback = notify
        self._connected = True

    def disconnect(self):
        if not self._connected:
            return
        error = CMNErrorW()
        ok = self.dmclient.DMDisConnectW(ctypes.byref(error))
        self._connected = False
        self._notify_callback = None
        if not ok:
            self._raise_dm_error("DMDisConnectW", error)

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


def build_probe(api, inventory_limit=4000, candidate_limit=512):
    """Build a bounded JSON-safe diagnostic payload from a WinCC API adapter."""
    try:
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
                if type_code in NUMERIC_TYPE_CODES:
                    item.update(api.read_numeric(name, type_code))
            except Exception as exc:
                item["error"] = str(exc)[:200]
            result["candidates"].append(item)
        return result
    except Exception as exc:
        return {
            "available": False,
            "backend": "wincc-dmclient",
            "error": str(exc)[:300],
        }


def probe_runtime(inventory_limit=4000, candidate_limit=512,
                  api_factory=WinCCRuntimeAPI):
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
        return build_probe(api, inventory_limit=inventory_limit,
                           candidate_limit=candidate_limit)
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
