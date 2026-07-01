"""Lay snapshot tu may WinCC: ssh -> py32 OLE-DB reader -> JSON. Co retry (APIPA flaky)."""
import os
import json
import time
import subprocess

from bridge import detect

_key_secured = False


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


def collect(cfg):
    w = cfg["winccbox"]
    # Che do LOCAL: chay OLE-DB reader ngay tren may nay (khong SSH).
    # Dung cho may co ca WinCC va internet.
    if (w.get("mode") or "").lower() == "local":
        return _collect_local(cfg)
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
    cmd = ssh + [target, w["python32"], w["reader"]]
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
