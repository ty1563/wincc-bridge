"""Supervise the read-only Dakrosa2 WinCC callback canary.

The existing snapshot and OTA paths remain authoritative.  This module only
keeps a four-tag 32-bit observer alive and exposes its health in normal payloads.
"""
import copy
import datetime
import json
import os
import subprocess
import threading
import time


RESTART_FLOOR_SEC = 60.0
_lock = threading.Lock()
_status = {}
_thread = None
_process = None
_stop_event = threading.Event()


def _bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def enabled(cfg):
    """Phase-1 gate: exact Dakrosa2/local/raw only; explicit false kills it."""
    station = cfg.get("station", {})
    winccbox = cfg.get("winccbox", {})
    if str(station.get("name", "")).strip().lower() != "dakrosa2":
        return False
    if str(winccbox.get("mode", "")).strip().lower() != "local":
        return False
    if str(station.get("read_mode", "")).strip().lower() != "raw":
        return False
    return _bool(station.get("runtime_callback_canary"), default=True)


def command(cfg):
    winccbox = cfg["winccbox"]
    python32 = str(winccbox["python32"])
    reader = os.path.abspath(str(winccbox["reader"]))
    helper = os.path.join(os.path.dirname(reader), "wincc_runtime.py")
    station_cfg = cfg.get("station", {})
    station = str(station_cfg.get("name", "Dakrosa2"))
    mode = str(winccbox.get("mode", ""))
    read_mode = str(station_cfg.get("read_mode", ""))
    return [
        python32,
        "-u",
        helper,
        "--callback-canary",
        "--station",
        station,
        "--mode",
        mode,
        "--read-mode",
        read_mode,
        "--watch-stdin",
    ]


def _utc_now():
    return (datetime.datetime.now(datetime.timezone.utc)
            .isoformat().replace("+00:00", "Z"))


def record(message):
    if not isinstance(message, dict):
        return
    allowed = {
        "event", "session", "tags_requested", "cycle_index", "cycle_ms",
        "taid", "first_latency_ms", "tags_seen", "callbacks", "items",
        "callback_errors", "oversized_callbacks", "last_callback_utc",
        "last_age_sec", "tags", "ok", "error_type", "error", "returncode",
        "restart_in_sec",
    }
    clean = {key: copy.deepcopy(value) for key, value in message.items()
             if key in allowed}
    clean["mode"] = "dmclient-callback-canary"
    clean["recorded_utc"] = _utc_now()
    with _lock:
        _status.clear()
        _status.update(clean)


def status():
    with _lock:
        return copy.deepcopy(_status)


def _log_event(log_fn, event, **fields):
    payload = {"event": event}
    payload.update(fields)
    log_fn("runtime-canary " + json.dumps(
        payload, ensure_ascii=False, sort_keys=True))


def _supervise(cfg, log_fn, popen_factory):
    global _process
    while not _stop_event.is_set():
        launched = time.monotonic()
        try:
            cmd = command(cfg)
            workdir = os.path.dirname(cmd[2]) or None
            process = popen_factory(
                cmd,
                cwd=workdir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            record({
                "event": "launch_error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
                "restart_in_sec": RESTART_FLOOR_SEC,
            })
            _log_event(log_fn, "launch_error", error=str(exc)[:200])
            _stop_event.wait(RESTART_FLOOR_SEC)
            continue
        with _lock:
            _process = process
        _log_event(log_fn, "launched", pid=getattr(process, "pid", None))
        try:
            while not _stop_event.is_set():
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    _log_event(log_fn, "child_output", text=str(line).strip()[:200])
                    continue
                record(message)
                event = str(message.get("event", ""))
                if event in ("start", "connected", "subscribed", "first_callback",
                             "error", "stop", "disconnect"):
                    fields = {key: message.get(key) for key in (
                        "session", "taid", "first_latency_ms", "tags_seen",
                        "ok", "error_type", "error") if key in message}
                    _log_event(log_fn, event, **fields)
            returncode = process.wait()
        except Exception as exc:
            returncode = getattr(process, "returncode", None)
            _log_event(log_fn, "supervisor_error", error=str(exc)[:200])
        finally:
            with _lock:
                if _process is process:
                    _process = None
        if _stop_event.is_set():
            break
        elapsed = time.monotonic() - launched
        delay = max(0.0, RESTART_FLOOR_SEC - elapsed)
        record({
            "event": "exited",
            "returncode": returncode,
            "restart_in_sec": round(delay, 1),
        })
        _log_event(log_fn, "exited", returncode=returncode,
                   restart_in_sec=round(delay, 1))
        _stop_event.wait(delay)


def start(cfg, log_fn=print, thread_factory=threading.Thread,
          popen_factory=subprocess.Popen):
    global _thread
    if not enabled(cfg):
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop_event.clear()
        _thread = thread_factory(
            target=_supervise,
            args=(cfg, log_fn, popen_factory),
            daemon=True,
            name="wincc-runtime-canary",
        )
        thread = _thread
    thread.start()
    return True


def stop(log_fn=print):
    global _thread, _process
    _stop_event.set()
    with _lock:
        process = _process
        thread = _thread
    if process is not None:
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=8)
    with _lock:
        _process = None
        _thread = None
    _log_event(log_fn, "supervisor_stopped")


def _reset_for_tests():
    global _thread, _process
    _stop_event.set()
    with _lock:
        _status.clear()
        _thread = None
        _process = None
    _stop_event.clear()
