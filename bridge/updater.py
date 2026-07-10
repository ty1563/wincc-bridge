"""OTA bao moi truong hop:
  1) Check version.txt remote (raw URL, public) so voi local.
  2) Neu khac -> cap nhat: uu tien `git pull` (neu co git+.git), fallback tai ZIP qua HTTPS.
  3) Day script box-side sang may WinCC (box khong co internet).
Khong can gh, khong can token (repo public), git la tuy chon.
"""
import os
import io
import hashlib
import ssl
import shutil
import tempfile
import zipfile
import subprocess
import urllib.request
import urllib.error

from bridge.config import REPO_ROOT

OWNER_REPO = "ty1563/wincc-bridge"
BRANCH = "main"
RAW_VERSION = f"https://raw.githubusercontent.com/{OWNER_REPO}/{BRANCH}/version.txt"
ZIP_URL = f"https://github.com/{OWNER_REPO}/archive/refs/heads/{BRANCH}.zip"
PROTECT = {"config.local.toml"}
CACERT = os.path.join(REPO_ROOT, "bridge", "cacert.pem")
# Dakrosa1 stays on the last archive-only reader (v1.4.9).  Dakrosa2 keeps the
# current raw/native reader.  Pin both commit and digest so future main changes
# cannot silently alter the station-specific rollback payload.
DAKROSA1_LEGACY_READER_COMMIT = "c9457663f677be8bd3b671f62a5b73518aacccda"
DAKROSA1_LEGACY_READER_URL = (
    "https://raw.githubusercontent.com/%s/%s/box/oledb_reader.py" %
    (OWNER_REPO, DAKROSA1_LEGACY_READER_COMMIT)
)
DAKROSA1_LEGACY_READER_SHA256 = (
    "b26cedf3586d729204a9c92a67a8a6ee60d19d52064439ad4f16d003cfd4892f"
)


def _ssl_ctx():
    """Win7/Py3.7 thieu Root CA moi trong OS store -> CERTIFICATE_VERIFY_FAILED.
    Uu tien CA bundle DONG GOI trong repo (bridge/cacert.pem), roi certifi, roi OS."""
    if os.path.exists(CACERT):
        try:
            return ssl.create_default_context(cafile=CACERT)
        except Exception:
            pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ssl.create_default_context()


def _urlopen(url, timeout=30):
    """urlopen co xac minh cert (CA bundle bundled). Neu VAN loi cert (OS/CA qua
    cu, khong the verify) -> fallback UNVERIFIED (repo public, LAN noi bo). Log ro."""
    try:
        return urllib.request.urlopen(url, timeout=timeout, context=_ssl_ctx())
    except urllib.error.URLError as e:
        if "CERTIFICATE" in str(e).upper() or isinstance(getattr(e, "reason", None), ssl.SSLError):
            unv = ssl.create_default_context()
            unv.check_hostname = False
            unv.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(url, timeout=timeout, context=unv)
        raise


def _local_version():
    p = os.path.join(REPO_ROOT, "version.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _remote_version():
    with _urlopen(RAW_VERSION, timeout=20) as r:
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
            _http_update(log=_log)
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


def _http_update(log=None):
    with _urlopen(ZIP_URL, timeout=90) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    prefix = names[0].split("/")[0] + "/"   # vd "wincc-bridge-main/"
    skipped = []
    for n in names:
        if n.endswith("/"):
            continue
        rel = n[len(prefix):]
        if not rel or rel in PROTECT or rel.split("/")[0] == ".git":
            continue
        # tools/nssm.exe DANG chay (service wrapper) -> bi khoa, khong ghi de duoc.
        # No hiem khi doi -> bo qua. Cac file .py van cap nhat binh thuong.
        if rel.replace("\\", "/").lower() == "tools/nssm.exe":
            continue
        dst = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(n) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
        except (PermissionError, OSError) as e:
            # File dang bi khoa (dang chay/mo) -> bo qua file do, KHONG chan ca update.
            skipped.append(f"{rel} ({type(e).__name__})")
    if skipped and log:
        log(f"HTTP-zip: bo qua {len(skipped)} file bi khoa: {skipped[:5]}")


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


def _uses_dakrosa1_legacy_reader(cfg):
    station = str(cfg.get("station", {}).get("name") or "").strip().lower()
    return station == "dakrosa1"


def _stage_dakrosa1_legacy_reader():
    with _urlopen(DAKROSA1_LEGACY_READER_URL, timeout=30) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != DAKROSA1_LEGACY_READER_SHA256:
        raise RuntimeError("Dakrosa1 legacy reader checksum mismatch")
    fd, staged = tempfile.mkstemp(prefix="dakrosa1-reader-", suffix=".py")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise
    return staged


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
    legacy_reader = None
    if _uses_dakrosa1_legacy_reader(cfg):
        legacy_reader = _stage_dakrosa1_legacy_reader()
    try:
        for fn in os.listdir(local_box):
            if not fn.endswith(".py"):
                continue
            source = os.path.join(local_box, fn)
            if legacy_reader and fn.lower() == "oledb_reader.py":
                source = legacy_reader
            result = subprocess.run(
                scp + [source, f"{target}:{box_dir}/{fn}"],
                capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RuntimeError(
                    "scp %s failed: %s" %
                    (fn, (result.stderr or result.stdout or "unknown")[:160]))
    finally:
        if legacy_reader:
            try:
                os.unlink(legacy_reader)
            except OSError:
                pass


def sync_pinned_station_files(cfg):
    """Re-apply station-specific files after restart, even without a new OTA."""
    if not _uses_dakrosa1_legacy_reader(cfg):
        return False
    _sync_box(cfg)
    return True
