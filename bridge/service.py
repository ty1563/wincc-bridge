"""Service chinh tren may tram: vong lap snapshot + OTA. NSSM boc thanh Windows service."""
import atexit
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bridge import config, collect, poster, runtime_canary, updater

# Chu ky gui snapshot (giay). Code la TRAN toi da -> OTA doi duoc ma khong can
# sua config tren tung may tram. Config [intervals] snapshot_sec chi lam NHANH
# hon (vd 15s), KHONG cham hon tran. Floor 10s de khong don dap may WinCC.
SNAPSHOT_SEC_MAX = 30
DAKROSA2_RUNTIME_SNAPSHOT_SEC_MAX = 10
# Chu ky gui RAW DUMP (blob TagCompressed b64) len server decode - chay o MOI
# tram (ke ca tram provider nhu Dakrosa1: dump la kenh phu doc lap, khai thac
# du tag ma provider khong tra - tan so, nhiet do, cong to...). Config
# [intervals] rawship_sec ghi de; 0 = tat.
RAW_SHIP_SEC = 300
_raw_thread = None


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


def effective_snap_iv(cfg, runtime_active=False):
    """Use 10s only after Dakrosa2 confirms a native Runtime payload."""
    want = int(cfg.get("intervals", {}).get("snapshot_sec", SNAPSHOT_SEC_MAX))
    station = cfg.get("station", {})
    native_runtime = (bool(runtime_active) and
                      str(station.get("name", "")).strip().lower() == "dakrosa2" and
                      str(station.get("read_mode", "")).strip().lower() == "raw")
    ceiling = DAKROSA2_RUNTIME_SNAPSHOT_SEC_MAX if native_runtime else SNAPSHOT_SEC_MAX
    return max(10, min(want, ceiling))


def _raw_ship_once(cfg):
    """Heavy raw/probe job. Runs outside the 30-second snapshot loop."""
    try:
        dump = collect.collect_rawdump(cfg)
        st3, body = poster.post_raw(cfg, dump)
        log(f"rawdump {dump.get('shipped_vids', 0)}/{dump.get('total_vids', '?')} vid "
            f"{dump.get('shipped_blocks', len(dump.get('blocks', [])))} blocks "
            f"({dump.get('dump_bytes', 0) // 1024}KB) -> HTTP {st3} {body[:80]}")
    except Exception as e:
        log(f"rawdump loi (bo qua): {str(e)[:150]}")


def start_raw_ship(cfg, thread_factory=threading.Thread):
    """Start at most one daemon raw job and return immediately."""
    global _raw_thread
    if raw_ship_active():
        return False
    _raw_thread = thread_factory(
        target=_raw_ship_once,
        args=(cfg,),
        daemon=True,
        name="wincc-raw-ship",
    )
    _raw_thread.start()
    return True


def raw_ship_active():
    return _raw_thread is not None and _raw_thread.is_alive()


def run_due_maintenance(cfg, ota_due, raw_due,
                        check_update=updater.check_and_update,
                        raw_starter=start_raw_ship,
                        active_check=raw_ship_active,
                        log_fn=log):
    """Run OTA before raw so a slow/offline station cannot starve updates."""
    result = {"ota_checked": False, "raw_started": False, "updated": False}
    if ota_due:
        if active_check():
            log_fn("OTA: rawdump dang chay -> doi xong roi cap nhat")
        else:
            result["ota_checked"] = True
            if check_update(cfg, log=log_fn):
                result["updated"] = True
                return result
    if raw_due:
        if raw_starter(cfg):
            result["raw_started"] = True
        else:
            log_fn("rawdump truoc van dang chay -> khong tao job chong lan")
    return result


def sync_station_files_on_start(
        cfg, sync=updater.sync_pinned_station_files, log_fn=log):
    """Best-effort station file self-heal after the new updater is loaded."""
    try:
        changed = sync(cfg)
        if changed:
            station = cfg.get("station", {}).get("name", "Dakrosa1")
            log_fn("station sync: da up reader legacy rieng cho %s" % station)
        return bool(changed)
    except Exception as exc:
        log_fn("station sync loi (bo qua): %s" % str(exc)[:160])
        return False


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
    canary_status = runtime_canary.status()
    if canary_status:
        payload["runtime_canary"] = canary_status
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
    return payload


def once(cfg):
    """Smoke-test luc setup: post 1 snapshot roi thoat."""
    log("PING setup (--once): gui 1 snapshot len webhook roi thoat")
    one_snapshot(cfg, ping="setup")


def main():
    cfg = config.load()
    sync_station_files_on_start(cfg)
    if "--once" in sys.argv:
        once(cfg)
        return
    if runtime_canary.start(cfg, log_fn=log):
        atexit.register(runtime_canary.stop, log_fn=log)
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
        cycle_iv = snap_iv
        try:
            payload = one_snapshot(cfg)
            cycle_iv = effective_snap_iv(
                cfg, runtime_active=payload.get("read_mode") == "runtime")
        except Exception as e:
            log(f"snapshot ERR: {e}")
            log(f"  hint: {hint(str(e))}")
        # OTA is checked before starting another raw job.  On a station whose
        # snapshot nearly consumes rawship_sec, the opposite order can defer
        # every OTA indefinitely.
        try:
            maintenance = run_due_maintenance(
                cfg,
                ota_due=ota_on and (time.time() - last_ota) >= ota_iv,
                raw_due=bool(raw_iv and (time.time() - last_raw) >= raw_iv),
            )
            if maintenance["ota_checked"]:
                last_ota = time.time()
            if maintenance["raw_started"]:
                last_raw = time.time()
            if maintenance["updated"]:
                log("OTA: co code moi -> thoat de NSSM khoi dong lai voi code moi")
                sys.exit(0)
        except Exception as e:
            log(f"OTA/maintenance ERR: {e}")
        time.sleep(max(5, cycle_iv - (time.time() - t0)))


if __name__ == "__main__":
    main()
