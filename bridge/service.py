"""Service chinh tren may tram: vong lap snapshot + OTA. NSSM boc thanh Windows service."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bridge import config, collect, poster, updater


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def hint(err):
    e = err.lower()
    if "timeout" in e or "timed out" in e:
        return "box khong toi duoc - APIPA doi IP (collect se tu detect) / chua cam cap / nen dat IP tinh"
    if "permission denied" in e or "publickey" in e:
        return "SSH key chua duoc cap quyen tren box (administrators_authorized_keys)"
    if "win32" in e and "module" in e:
        return "Python 32-bit tren box thieu pywin32"
    if "class not registered" in e or "80040154" in e:
        return "bitness sai (can py 32-bit) hoac OLE-DB provider chua dang ky"
    if "json" in e:
        return "reader khong tra JSON - kiem tra reader tren box"
    if "post" in e or "urlopen" in e or "http" in e:
        return "POST n8n loi - may tram thieu internet / webhook sai"
    return "chay 'python -m bridge.diagnose' de chan doan chi tiet"


def one_snapshot(cfg):
    snap = collect.collect(cfg)
    payload = {"source": "wincc-bridge"}
    payload.update(snap)
    status, _ = poster.post(cfg, payload)
    log(f"snapshot {len(snap.get('tags', {}))} tags -> HTTP {status}")


def main():
    cfg = config.load()
    snap_iv = int(cfg["intervals"]["snapshot_sec"])
    ota_iv = int(cfg["intervals"].get("ota_sec", 900))
    ota_on = bool(cfg.get("ota", {}).get("enabled"))
    log(f"WinCC Bridge start | snapshot={snap_iv}s ota={ota_iv}s ota_enabled={ota_on}")
    last_ota = time.time()
    while True:
        t0 = time.time()
        try:
            one_snapshot(cfg)
        except Exception as e:
            log(f"snapshot ERR: {e}")
            log(f"  hint: {hint(str(e))}")
        if ota_on and (time.time() - last_ota) >= ota_iv:
            last_ota = time.time()
            try:
                if updater.check_and_update(cfg):
                    log("OTA: co code moi -> thoat de NSSM khoi dong lai voi code moi")
                    sys.exit(0)
            except Exception as e:
                log(f"OTA ERR: {e}")
        time.sleep(max(5, snap_iv - (time.time() - t0)))


if __name__ == "__main__":
    main()
