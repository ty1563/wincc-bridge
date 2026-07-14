"""Lay snapshot tu may WinCC: ssh -> py32 OLE-DB reader -> JSON. Co retry (APIPA flaky)."""
import os
import json
import time
import subprocess

from bridge import detect

_key_secured = False
D1_OLEDB_HELPER = "d1_oledb_canary.py"
D1_OLEDB_TIMEOUT_SEC = 15


def _secure_key(key):
    """OpenSSH tu choi private key neu user thuong (vd DELL) doc duoc -> 'Bad permissions'.
    Service chay LocalSystem (toan quyen) nen TU icacls khoa key chi cho SYSTEM + Administrators.
    Nho vay chi can OTA cap nhat code la tu lanh, KHONG can chay icacls tay tren may tram.
      /reset           -> bo cac ACE tuong minh thua (vd DELL:R do setup cu cap)
      /inheritance:r   -> bo quyen thua ke tu profile (profile cho DELL full control)
      /grant:r SID     -> chi con SYSTEM(S-1-5-18) + Administrators(S-1-5-32-544)
    Best-effort, chay 1 lan moi process, nuot loi (vd chay khong du quyen)."""
    global _key_secured
    if _key_secured or not key or os.name != "nt" or not os.path.exists(key):
        _key_secured = True
        return
    for c in (
        ["icacls", key, "/reset"],
        ["icacls", key, "/inheritance:r", "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"],
        ["icacls", key, "/setowner", "*S-1-5-32-544"],
    ):
        try:
            subprocess.run(c, capture_output=True, text=True, timeout=30)
        except Exception:
            pass
    _key_secured = True


def local_version():
    try:
        from bridge.config import REPO_ROOT
        with open(os.path.join(REPO_ROOT, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        return f"err:{e}"


def _run_txt(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return f"rc={p.returncode} {((p.stdout or '') + (p.stderr or '')).strip()[:300]}"
    except Exception as e:
        return f"EXC:{e}"


def diagnostics(cfg):
    """Thong tin chan doan gui kem len webhook (user theo doi qua n8n, khong can terminal):
    version dang chay, service chay account nao, ACL key truoc/sau khi self-heal + output icacls."""
    import platform
    w = cfg.get("winccbox", {})
    mode = (w.get("mode") or "remote").lower()
    d = {"version": local_version(), "node": platform.node(),
         "whoami": _run_txt(["whoami"]), "mode": mode}
    if mode == "local":
        # Che do local: khong co SSH key -> chi report python32 + reader
        py32 = w.get("python32", "")
        reader = w.get("reader", "")
        d["python32"] = f"exists={os.path.exists(py32)} path={py32}"
        d["reader"] = f"exists={os.path.exists(reader)} path={reader}"
        return d
    key = w.get("key", "")
    d["key"] = key
    d["key_acl_before"] = _run_txt(["icacls", key])
    heal = []
    for c in (["icacls", key, "/reset"],
              ["icacls", key, "/inheritance:r", "/grant:r", "*S-1-5-18:F", "*S-1-5-32-544:F"],
              ["icacls", key, "/setowner", "*S-1-5-32-544"]):
        heal.append(" ".join(c[2:]) + " | " + _run_txt(c))
    d["heal"] = heal
    d["key_acl_after"] = _run_txt(["icacls", key])
    return d


def _station_env(cfg):
    """Truyen cau hinh tram sang reader qua ENV var (khong dung CLI arg de tuong thich cu).
    [station] name / project_like / catalog_fallback / dsn -> WINCC_* env cho reader."""
    env = os.environ.copy()
    s = cfg.get("station", {})
    if s.get("name"):             env["WINCC_STATION_NAME"] = str(s["name"])
    if s.get("project_like"):     env["WINCC_PROJECT_LIKE"] = str(s["project_like"])
    if s.get("catalog_fallback"): env["WINCC_CATALOG_FALLBACK"] = str(s["catalog_fallback"])
    if s.get("dsn"):              env["WINCC_DSN"] = str(s["dsn"])
    if s.get("read_mode"):        env["WINCC_READ_MODE"] = str(s["read_mode"])
    # [tags] = {ten: valueid} -> JSON qua WINCC_TAG_MAP cho reader (tram khac ValueID khac).
    tags = cfg.get("tags")
    if tags:
        try:
            env["WINCC_TAG_MAP"] = json.dumps(tags)
        except Exception:
            pass
    return env


def _collect_local(cfg):
    """Chay Python 32-bit + reader NGAY TREN MAY NAY (khong SSH).
    Dung khi may vua chay WinCC vua co internet -> khong can bridge remote.
    Config: [winccbox] mode = 'local', python32 = ..., reader = ..."""
    w = cfg["winccbox"]
    cmd = [w["python32"], w["reader"]]
    env = _station_env(cfg)
    last = ""
    for _ in range(2):  # noi bo, retry 2 lan la du
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                               env=env,
                               encoding="utf-8", errors="replace")
            if p.returncode == 0 and p.stdout.strip():
                try:
                    return json.loads(p.stdout)
                except json.JSONDecodeError:
                    last = "JSON loi: " + p.stdout[:200]
            else:
                last = (p.stderr or p.stdout or "rong")[:200]
        except subprocess.TimeoutExpired:
            last = "reader timeout"
        time.sleep(1)
    raise RuntimeError(f"collect local that bai: {last}")


def _ssh_base(cfg):
    """Phan dau lenh SSH toi box (ke ca target da resolve). Tach rieng de
    collect() va collect_rawdump() dung chung, hanh vi giu NGUYEN nhu cu."""
    w = cfg["winccbox"]
    if w.get("key"):
        _secure_key(w["key"])  # tu khoa quyen key truoc khi ssh (OpenSSH kho tinh)
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        ssh += ["-i", w["key"]]
    if w.get("target"):
        target = w["target"]
    else:
        host, changed = detect.resolve_host(cfg)  # chiu duoc APIPA doi IP
        if changed:
            print(f"[detect] box IP doi -> dung {host}", flush=True)
        target = f'{w["user"]}@{host}'
    return ssh + [target]


def _runtime_probe_args(cfg):
    """Keep native Runtime API discovery isolated inside the raw worker."""
    station = cfg.get("station", {})
    if "runtime_probe" in station:
        value = station.get("runtime_probe")
        explicit = True
    else:
        mode = str(cfg.get("winccbox", {}).get("mode") or "remote").lower()
        value = mode == "local"
        explicit = False
    if isinstance(value, str):
        enabled = value.strip().lower() not in ("0", "false", "no", "off", "")
    else:
        enabled = bool(value)
    if enabled:
        return ["--probe-runtime"]
    if not explicit:
        # Remote stations enumerate names/types only.  No DMGetValue calls are
        # made until an explicit station allow-list has been reviewed.
        return ["--probe-runtime-metadata"]
    return []


def _config_enabled(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def _d1_oledb_probe_enabled(cfg, observed_station=None):
    station = cfg.get("station", {})
    configured = str(station.get("name") or "").strip().lower()
    observed = str(observed_station or "").strip().lower()
    if configured and observed and configured != observed:
        return False
    if (configured or observed) != "dakrosa1":
        return False
    return _config_enabled(station.get("d1_oledb_value_probe"), default=True)


def _d1_oledb_helper_path(reader):
    normalized = str(reader).replace("\\", "/")
    parent = normalized.rsplit("/", 1)[0]
    return "%s/%s" % (parent, D1_OLEDB_HELPER)


def _d1_probe_failure(status, returncode=None, error_type=None):
    result = {
        "available": False,
        "backend": "wincc-oledb-valuename",
        "status": status,
    }
    if returncode is not None:
        result["returncode"] = int(returncode)
    if error_type:
        result["error"] = str(error_type)[:80]
    return result


def _reject_json_constant(value):
    raise ValueError("non-standard JSON constant: %s" % value)


def _collect_d1_oledb_probe(cfg, remote_base=None, observed_station=None):
    """Run the D1 canary after raw capture; every failure returns diagnostics."""
    if not _d1_oledb_probe_enabled(cfg, observed_station=observed_station):
        return None
    w = cfg["winccbox"]
    helper = _d1_oledb_helper_path(w["reader"])
    mode = str(w.get("mode") or "remote").lower()
    if mode == "local":
        cmd = [w["python32"], helper, "--station", "Dakrosa1", "--raw-canary"]
        env = _station_env(cfg)
    else:
        cmd = list(remote_base or _ssh_base(cfg)) + [
            w["python32"], helper, "--station", "Dakrosa1", "--raw-canary"]
        env = None
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=D1_OLEDB_TIMEOUT_SEC,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return _d1_probe_failure("timeout")
    except Exception as error:
        return _d1_probe_failure("launch_error", error_type=type(error).__name__)
    if p.returncode != 0:
        return _d1_probe_failure("process_error", returncode=p.returncode)
    try:
        payload = json.loads(
            p.stdout or "", parse_constant=_reject_json_constant)
        if not isinstance(payload, dict):
            raise ValueError("canary root is not an object")
        if payload.get("backend") != "wincc-oledb-valuename":
            raise ValueError("unexpected canary backend")
        return payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return _d1_probe_failure("invalid_output")


def collect_rawdump(cfg):
    """Chay reader o che do DUMP RAW: tra JSON chua block TagCompressed tho
    (b64) + ban do ten tag, de service POST len server decode.
    - mode=local (Dakrosa2): chay tai cho, bat bang ENV WINCC_DUMP_RAW=1
    - mode=remote (Dakrosa1): SSH sang box, bat bang argv --dump-raw
      (SSH KHONG forward env var -> phai dung CLI flag).
    Dump nang hon snapshot thuong -> timeout 150s, 1 lan (chu ky sau tu thu lai)."""
    w = cfg["winccbox"]
    remote_base = None
    if (w.get("mode") or "").lower() == "local":
        env = _station_env(cfg)
        env["WINCC_DUMP_RAW"] = "1"
        cmd = [w["python32"], w["reader"], "--dump-raw"] + _runtime_probe_args(cfg)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=150,
                           env=env, encoding="utf-8", errors="replace")
    else:
        remote_base = _ssh_base(cfg)
        cmd = (remote_base + [w["python32"], w["reader"], "--dump-raw"] +
               _runtime_probe_args(cfg))
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=150,
                           encoding="utf-8", errors="replace")
    if p.returncode == 0 and p.stdout.strip():
        dump = json.loads(p.stdout)
        if not isinstance(dump, dict):
            raise ValueError("rawdump root is not an object")
        if "oledb_value_probe" not in dump:
            probe = _collect_d1_oledb_probe(
                cfg, remote_base=remote_base,
                observed_station=dump.get("station"))
            if probe is not None:
                dump["oledb_value_probe"] = probe
        return dump
    raise RuntimeError(f"rawdump that bai: {(p.stderr or p.stdout or 'rong')[:200]}")


def collect(cfg):
    w = cfg["winccbox"]
    # Che do LOCAL: chay OLE-DB reader ngay tren may nay (khong SSH).
    # Dung cho may co ca WinCC va internet.
    if (w.get("mode") or "").lower() == "local":
        return _collect_local(cfg)
    cmd = _ssh_base(cfg) + [w["python32"], w["reader"]]
    last = ""
    # Gioi han tong thoi gian < chu ky 5 phut: 3 lan x (90s timeout + 2s) ~ 276s.
    # Box unreachable thi ConnectTimeout=12 fail nhanh (~42s) -> loop giu nhip ~5p.
    for attempt in range(3):  # link APIPA chap chon -> retry
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                               encoding="utf-8", errors="replace")
            if p.returncode == 0 and p.stdout.strip():
                try:
                    return json.loads(p.stdout)
                except json.JSONDecodeError:
                    last = "JSON loi: " + p.stdout[:200]
            else:
                last = (p.stderr or p.stdout or "rong")[:200]
        except subprocess.TimeoutExpired:
            last = "ssh timeout"
        time.sleep(2)
    raise RuntimeError(f"collect that bai sau 3 lan: {last}")
