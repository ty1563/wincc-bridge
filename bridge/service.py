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

# Chu ky gui snapshot (giay). Code la TRAN toi da -> OTA doi duoc ma khong can
# sua config tren tung may tram. Config [intervals] snapshot_sec chi lam NHANH
# hon (vd 15s), KHONG cham hon tran. Floor 10s de khong don dap may WinCC.
SNAPSHOT_SEC_MAX = 30
# Chu ky gui RAW DUMP (blob TagCompressed b64) len server decode - chay o MOI
# tram (ke ca tram provider nhu Dakrosa1: dump la kenh phu doc lap, khai thac
# du tag ma provider khong tra - tan so, nhiet do, cong to...). Config
# [intervals] rawship_sec ghi de; 0 = tat.
RAW_SHIP_SEC = 300


def raw_ship_iv(cfg):
    """Chu ky raw-dump (giay); 0 = tat. Mac dinh bat cho moi tram:
    - mode=local (Dakrosa2): reader chay tai cho voi WINCC_DUMP_RAW=1
    - mode=remote (Dakrosa1): SSH sang box voi argv --dump-raw
    Loi dump khong anh huong snapshot chinh (caller try/except)."""
    try:
        return max(0, int(cfg.get("intervals", {}).get("rawship_sec", RAW_SHIP_SEC)))
    except Exception:
        return RAW_SHIP_SEC


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def effective_snap_iv(cfg):
    """Chu ky snapshot thuc te: min(config, SNAPSHOT_SEC_MAX), floor 10s.
    Config cu 'snapshot_sec = 300' se tu bi ep xuong 30s ma khong can sua may."""
    want = int(cfg.get("intervals", {}).get("snapshot_sec", SNAPSHOT_SEC_MAX))
    return max(10, min(want, SNAPSHOT_SEC_MAX))


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


def one_snapshot(cfg, ping=None):
    """LUON post len webhook moi chu ky (heartbeat): box OK thi gui data,
    box loi thi van gui payload co field 'error'. Nho vay n8n nhan ping DEU
    moi chu ky 5 phut thay vi cam khi box chap chon (APIPA)."""
    try:
        snap = collect.collect(cfg)
    except Exception as e:
        log(f"collect ERR: {e}")
        log(f"  hint: {hint(str(e))}")
        snap = {"error": str(e)[:300], "tags": {}}
    payload = {"source": "wincc-bridge", "version": collect.local_version()}
    st = cfg.get("station", {}).get("name")
    if st:
        payload["station"] = st  # de n8n biet snapshot cua tram nao (Dakrosa1 vs Dakrosa2 vs ...)
    if ping:
        payload["ping"] = ping
    payload.update(snap)
    if "error" in snap:
        try:
            payload["diag"] = collect.diagnostics(cfg)
        except Exception as e:
            payload["diag"] = {"diag_err": str(e)[:200]}
    try:
        status, _ = poster.post(cfg, payload)
        log(f"snapshot {len(snap.get('tags', {}))} tags -> HTTP {status}")
    except Exception as e:
        log(f"POST ERR: {e}")
        log(f"  hint: {hint(str(e))}")
    # Fan-out sang dashboard (best-effort): loi o day KHONG anh huong luong n8n.
    try:
        st2, _ = poster.post_extra(cfg, payload)
        if st2 is not None:
            log(f"  -> dashboard HTTP {st2}")
    except Exception as e:
        log(f"  dashboard POST loi (bo qua): {str(e)[:120]}")


def once(cfg):
    """Smoke-test luc setup: post 1 snapshot roi thoat."""
    log("PING setup (--once): gui 1 snapshot len webhook roi thoat")
    one_snapshot(cfg, ping="setup")


def main():
    cfg = config.load()
    if "--once" in sys.argv:
        once(cfg)
        return
    snap_iv = effective_snap_iv(cfg)
    ota_iv = int(cfg["intervals"].get("ota_sec", 900))
    ota_on = bool(cfg.get("ota", {}).get("enabled"))
    raw_iv = raw_ship_iv(cfg)
    log(f"WinCC Bridge start | snapshot={snap_iv}s ota={ota_iv}s "
        f"rawship={raw_iv}s ota_enabled={ota_on}")
    last_ota = time.time()
    last_raw = 0.0  # 0 -> gui raw dump ngay chu ky dau sau khi start
    while True:
        t0 = time.time()
        try:
            one_snapshot(cfg)
        except Exception as e:
            log(f"snapshot ERR: {e}")
            log(f"  hint: {hint(str(e))}")
        # RAW DUMP dinh ky (best-effort): loi khong anh huong snapshot/n8n
        if raw_iv and (time.time() - last_raw) >= raw_iv:
            last_raw = time.time()
            try:
                dump = collect.collect_rawdump(cfg)
                st3, body = poster.post_raw(cfg, dump)
                log(f"rawdump {dump.get('shipped_vids', 0)}/{dump.get('total_vids', '?')} vid "
                    f"{dump.get('shipped_blocks', len(dump.get('blocks', [])))} blocks "
                    f"({dump.get('dump_bytes', 0) // 1024}KB) -> HTTP {st3} {body[:80]}")
            except Exception as e:
                log(f"rawdump loi (bo qua): {str(e)[:150]}")
        if ota_on and (time.time() - last_ota) >= ota_iv:
            last_ota = time.time()
            try:
                if updater.check_and_update(cfg, log=log):
                    log("OTA: co code moi -> thoat de NSSM khoi dong lai voi code moi")
                    sys.exit(0)
            except Exception as e:
                log(f"OTA ERR: {e}")
        time.sleep(max(5, snap_iv - (time.time() - t0)))


if __name__ == "__main__":
    main()
