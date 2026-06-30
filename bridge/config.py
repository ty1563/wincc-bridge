"""Doc config.local.toml (secrets + endpoints). Thuan stdlib (tomllib)."""
import os
import tomllib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path():
    return os.environ.get("WINCC_BRIDGE_CONFIG") or os.path.join(REPO_ROOT, "config.local.toml")


def load():
    path = config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Khong thay config: {path} (copy tu config.local.example)")
    with open(path, "rb") as f:
        data = f.read()
    # PowerShell 5.1 'Set-Content -Encoding utf8' them BOM -> tomllib loi.
    # Notepad cung hay them BOM. Bo BOM truoc khi parse cho chac.
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    return tomllib.loads(data.decode("utf-8"))
