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
        return tomllib.load(f)
