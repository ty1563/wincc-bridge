"""Doc config.local.toml. Ho tro Python 3.11+ (tomllib) va 3.7-3.10 (mini parser).

Python 3.11 co tomllib stdlib. Windows 7 co the phai dung Python 3.7-3.10 (moi nhat
support Win 7). Truong hop do, fallback sang mini TOML parser du dung cho config
don gian cua chung ta ([section] key = "value" / number / true/false, khong array).
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mini_toml_loads(text):
    """Parser TOML toi gian cho config wincc-bridge. Chi ho tro:
      [section]
      key = "value" | 'value' | number | true | false
    Khong ho tro: array, inline table, multiline string, dotted key, datetime.
    Comment (#) va dong trong duoc bo qua."""
    result = {}
    current = result
    for raw in text.splitlines():
        # Bo comment (chi tach o dau '#' ngoai quotes - don gian nhung du dung)
        line = raw
        if "#" in line and not (line.count('"') % 2 or line.count("'") % 2):
            line = line.split("#", 1)[0]
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            name = s[1:-1].strip()
            if name not in result:
                result[name] = {}
            current = result[name]
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        # Value: string / bool / int / float / string tho
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            # TOML basic string: xu ly escape sequences (giong tomllib)
            v = v[1:-1]
            v = (v.replace("\\\\", "\x00")
                 .replace('\\"', '"').replace("\\n", "\n")
                 .replace("\\r", "\r").replace("\\t", "\t")
                 .replace("\x00", "\\"))
        elif len(v) >= 2 and v[0] == "'" and v[-1] == "'":
            # TOML literal string: khong xu ly escape (raw)
            v = v[1:-1]
        elif v.lower() == "true":
            v = True
        elif v.lower() == "false":
            v = False
        else:
            try:
                v = int(v) if "." not in v and "e" not in v.lower() else float(v)
            except ValueError:
                pass  # giu nguyen string
        current[k] = v
    return result


def config_path():
    return os.environ.get("WINCC_BRIDGE_CONFIG") or os.path.join(REPO_ROOT, "config.local.toml")


def _load_bytes(path):
    with open(path, "rb") as f:
        data = f.read()
    # PowerShell 5.1 'Set-Content -Encoding utf8' them BOM -> tomllib loi.
    # Notepad cung hay them BOM. Bo BOM truoc khi parse cho chac.
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    return data.decode("utf-8")


def load():
    path = config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Khong thay config: {path} (copy tu config.local.example)")
    text = _load_bytes(path)
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        # Python 3.7-3.10: fallback mini parser (du cho config cua chung ta)
        return _mini_toml_loads(text)
