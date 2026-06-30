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


def collect(cfg):
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
