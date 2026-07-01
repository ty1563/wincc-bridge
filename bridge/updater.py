"""OTA bao moi truong hop:
  1) Check version.txt remote (raw URL, public) so voi local.
  2) Neu khac -> cap nhat: uu tien `git pull` (neu co git+.git), fallback tai ZIP qua HTTPS.
  3) Day script box-side sang may WinCC (box khong co internet).
Khong can gh, khong can token (repo public), git la tuy chon.
"""
import os
import io
import shutil
import zipfile
import subprocess
import urllib.request

from bridge.config import REPO_ROOT

OWNER_REPO = "ty1563/wincc-bridge"
BRANCH = "main"
RAW_VERSION = f"https://raw.githubusercontent.com/{OWNER_REPO}/{BRANCH}/version.txt"
ZIP_URL = f"https://github.com/{OWNER_REPO}/archive/refs/heads/{BRANCH}.zip"
PROTECT = {"config.local.toml"}


def _local_version():
    p = os.path.join(REPO_ROOT, "version.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _remote_version():
    with urllib.request.urlopen(RAW_VERSION, timeout=20) as r:
        return r.read().decode("utf-8", "replace").strip()


def check_and_update(cfg, log=None):
    """log: callback(msg) tuy chon - de service.py in ra service.log, tranh
    OTA fail am tham (truoc day loi mang/TLS/DNS bi nuot, khong co dau vet nao)."""
    def _log(m):
        if log:
            log(f"OTA: {m}")
    if not cfg.get("ota", {}).get("enabled"):
        return False
    try:
        remote = _remote_version()
    except Exception as e:
        _log(f"khong lay duoc version.txt tu GitHub - {type(e).__name__}: {str(e)[:200]}")
        return False
    local = _local_version()
    if remote == local:
        _log(f"da la ban moi nhat ({local})")
        return False
    _log(f"co ban moi {local} -> {remote}, dang cap nhat...")
    # Co ban moi
    used_git = _git_update()
    if not used_git:
        try:
            _http_update()
        except Exception as e:
            _log(f"HTTP-zip update loi - {type(e).__name__}: {str(e)[:200]}")
            return False
    try:
        _sync_box(cfg)
    except Exception as e:
        _log(f"sync box loi (khong chan update) - {str(e)[:150]}")
    return True


def _has_git():
    return os.path.isdir(os.path.join(REPO_ROOT, ".git")) and shutil.which("git") is not None


def _git_update():
    if not _has_git():
        return False
    try:
        subprocess.run(["git", "-C", REPO_ROOT, "fetch", "-q", "origin", BRANCH],
                       timeout=120, check=False)
        r = subprocess.run(["git", "-C", REPO_ROOT, "reset", "--hard", "-q", f"origin/{BRANCH}"],
                           timeout=120, check=False)
        return r.returncode == 0
    except Exception:
        return False


def _http_update():
    with urllib.request.urlopen(ZIP_URL, timeout=90) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    prefix = names[0].split("/")[0] + "/"   # vd "wincc-bridge-main/"
    for n in names:
        if n.endswith("/"):
            continue
        rel = n[len(prefix):]
        if not rel or rel in PROTECT or rel.split("/")[0] == ".git":
            continue
        dst = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with z.open(n) as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out)


def _remote_scp_dir(w):
    """Return an scp-safe remote directory.

    Windows OpenSSH/SFTP can reject targets like user@host:C:/Users/... with
    "invalid segment". When the reader lives under the SSH user's home, use a
    relative path so scp resolves it from that home directory.
    """
    reader = w["reader"].replace("\\", "/")
    box_dir = reader.rsplit("/", 1)[0]
    user = w.get("user", "")
    home_prefix = f"C:/Users/{user}/"
    if user and reader.lower().startswith(home_prefix.lower()):
        rel = reader[len(home_prefix):].rsplit("/", 1)[0]
        return rel or "."
    return box_dir


def _sync_box(cfg):
    w = cfg["winccbox"]
    # Che do local: reader nam ngay tren may nay -> git da cap nhat, khong can scp
    if (w.get("mode") or "").lower() == "local":
        return
    box_dir = _remote_scp_dir(w)
    target = w.get("target") or f'{w["user"]}@{w["host"]}'
    scp = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        scp += ["-i", w["key"]]
    local_box = os.path.join(REPO_ROOT, "box")
    for fn in os.listdir(local_box):
        if fn.endswith(".py"):
            subprocess.run(scp + [os.path.join(local_box, fn), f"{target}:{box_dir}/{fn}"],
                           capture_output=True, text=True, timeout=60)
