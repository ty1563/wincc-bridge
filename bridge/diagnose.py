"""Tu detect may + kiem tra toan bo + DOAN NGUYEN NHAN loi. Ghi logs/diagnose.log.
Chay: python -m bridge.diagnose   (tren may tram)
"""
import os
import sys
import json
import time
import socket
import struct
import shutil
import platform
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bridge import config as cfgmod
from bridge import detect

LINES = []


def L(sym, name, detail):
    msg = f"[{sym}] {name}: {detail}"
    print(msg)
    LINES.append(msg)


def _ssh_cmd(cfg, host, remote):
    w = cfg["winccbox"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        ssh += ["-i", w["key"]]
    target = w.get("target") or f'{w.get("user", "dell")}@{host}'
    return ssh + [target] + remote


def _run(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def main():
    LINES.append("==== WinCC Bridge DIAGNOSE @ " + time.strftime("%Y-%m-%d %H:%M:%S") + " ====")
    # --- May ---
    L("i", "may", f"{platform.node()} | {platform.system()} {platform.release()} | user={os.environ.get('USERNAME')}")
    bits = struct.calcsize("P") * 8
    L("i", "python", f"{platform.python_version()} {bits}-bit")
    # --- Tools ---
    for t in ("ssh", "scp", "git"):
        p = shutil.which(t)
        if p:
            L("OK", t, p)
        else:
            L("!" if t == "git" else "X", t,
              "KHONG CO -> " + ("OTA dung HTTP-zip (van ok)" if t == "git" else "THIEU OpenSSH client!"))
    # --- Config ---
    try:
        cfg = cfgmod.load()
    except Exception as e:
        L("X", "config", f"{e} -> tao config.local.toml tu config.local.example.toml")
        return _flush()
    w = cfg["winccbox"]
    mode = (w.get("mode") or "remote").lower()
    cfg_host = w.get("host") or w.get("target")
    L("OK", "config", f"mode={mode} host={cfg_host} user={w.get('user')} reader={w.get('reader')}")
    # --- Che do LOCAL: bo qua het check SSH, chay reader NGAY tai cho ---
    if mode == "local":
        py32 = w.get("python32", "")
        reader = w.get("reader", "")
        if not os.path.exists(py32):
            L("X", "python32", f"khong ton tai: {py32} -> cai Python 3.11 32-bit va sua config")
            return _flush()
        L("OK", "python32", py32)
        if not os.path.exists(reader):
            L("X", "reader", f"khong ton tai: {reader}")
            return _flush()
        L("OK", "reader", reader)
        rc, out, err = _run([py32, reader], 150)
        try:
            d = json.loads(out.strip())
            n = len(d.get("tags", {}))
            if n > 0:
                L("OK", "OLE-DB reader", f"{n} tag, catalog={d.get('catalog')}")
            else:
                L("!", "OLE-DB reader", f"0 tag -> WinCC Runtime chua active / archive trong. err={d.get('error','')[:120]}")
        except json.JSONDecodeError:
            low = ((out or "") + " " + (err or "")).lower()
            if "no module named 'win32" in low:
                pred = "Python 32-bit thieu pywin32 (pip install pywin32)"
            elif "class not registered" in low or "80040154" in low:
                pred = "Bitness SAI (Python phai la 32-bit) hoac WinCCOLEDBProvider chua dang ky"
            else:
                pred = "Xem out ben duoi"
            L("X", "OLE-DB reader", f"loi -> {pred}. out={(out or err)[:160]}")
            return _flush()
        # webhook check
        try:
            from urllib.parse import urlparse
            u = urlparse(cfg["webhook"]["url"])
            port = u.port or (443 if u.scheme == "https" else 80)
            s = socket.create_connection((u.hostname, port), timeout=8)
            s.close()
            L("OK", "webhook host", f"{u.hostname}:{port} toi duoc")
        except Exception as e:
            L("X", "webhook host", f"khong toi -> may THIEU INTERNET? ({e})")
        return _flush()
    # --- Che do REMOTE (mac dinh): tu detect box qua APIPA ---
    host, changed = detect.resolve_host(cfg)
    if not host:
        L("X", "detect box", "khong co host trong config")
        return _flush()
    if changed:
        L("!", "detect box", f"IP config ({w.get('host')}) khong toi duoc -> TU DO RA {host} (APIPA da doi - cap nhat config.local host={host})")
    else:
        L("OK", "detect box", f"{host}")
    # --- Port 22 (retry vi APIPA chap chon) ---
    ok22 = False
    for _ in range(5):
        if detect.port_open(host, 22):
            ok22 = True
            break
        time.sleep(2)
    if ok22:
        L("OK", "TCP 22", "OPEN")
    else:
        L("X", "TCP 22", "TIMEOUT sau 5 lan -> box khong toi duoc: SAI IP (chay 'arp -a'), CHUA CAM CAP, hoac sshd TAT. Khuyen dat IP tinh.")
        return _flush()
    # --- ssh echo ---
    rc, out, err = _run(_ssh_cmd(cfg, host, ["echo", "ok"]), 30)
    if out.strip() == "ok":
        L("OK", "ssh", "dang nhap key OK")
    else:
        L("X", "ssh", f"that bai -> KEY chua duoc cap quyen tren box (administrators_authorized_keys), hoac sai user. err={(err or out)[:120]}")
        return _flush()
    # --- OLE-DB reader ---
    rc, out, err = _run(_ssh_cmd(cfg, host, [w["python32"], w["reader"]]), 150)
    snap = out.strip()
    try:
        d = json.loads(snap)
        n = len(d.get("tags", {}))
        if n > 0:
            L("OK", "OLE-DB reader", f"{n} tag, catalog={d.get('catalog')}")
        else:
            L("!", "OLE-DB reader", "0 tag -> project WinCC chua active / archive trong")
    except json.JSONDecodeError:
        low = (snap + " " + err).lower()
        if "no module named 'win32" in low or "modulenotfound" in low:
            pred = "Python 32-bit THIEU pywin32 (pip install pywin32)"
        elif "class not registered" in low or "80040154" in low:
            pred = "Bitness SAI (phai Python 32-bit) hoac WinCCOLEDBProvider chua dang ky"
        elif "provider" in low and "cannot" in low:
            pred = "Provider OLE-DB loi / project chua active"
        elif "no such file" in low or "can't open file" in low:
            pred = f"Reader chua co tren box: {w['reader']} (service se day khi OTA, hoac scp tay)"
        else:
            pred = "Khong ro - xem out ben duoi"
        L("X", "OLE-DB reader", f"loi -> {pred}. out={(snap or err)[:160]}")
        return _flush()
    # --- Webhook host ---
    try:
        from urllib.parse import urlparse
        u = urlparse(cfg["webhook"]["url"])
        port = u.port or (443 if u.scheme == "https" else 80)
        s = socket.create_connection((u.hostname, port), timeout=8)
        s.close()
        L("OK", "webhook host", f"{u.hostname}:{port} toi duoc")
    except Exception as e:
        L("X", "webhook host", f"khong toi -> may tram THIEU INTERNET? ({e})")
    _flush()


def _flush():
    try:
        d = os.path.join(cfgmod.REPO_ROOT, "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "diagnose.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(LINES) + "\n\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
