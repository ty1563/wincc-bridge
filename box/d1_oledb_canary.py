"""Bounded read-only WinCC OLE DB canary for five Dakrosa1 gaps.

This helper is deliberately separate from oledb_reader.py. Dakrosa1 keeps its
pinned legacy reader, while bridge.collect launches this file only after a
valid raw dump has already been captured. The output is diagnostic only and
never contains canonical ``tags``.
"""
import datetime
import json
import math
import os
import sys
import time


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


DSN = os.environ.get("WINCC_DSN") or r"MAINPC\WINCC"
CATALOG = (os.environ.get("WINCC_CATALOG_FALLBACK") or
           "CC_Dakrosa1_23_10_10_10_26_33R")
CONNECTION_TIMEOUT_SEC = 5
COMMAND_TIMEOUT_SEC = 3
TOTAL_BUDGET_SEC = 10
WINDOW_HOURS = 24
TIMESTEP_SEC = 300

# Confirmed archive members are queried first so a slow candidate namespace
# cannot consume the diagnostic budget before the two highest-value signals.
VALUE_SPECS = (
    {
        "key": "bus_F",
        "value_name": r"22kV\22kV_db_Unit_st22kV_nF",
        "unit": "Hz",
        "min": 45.0,
        "max": 55.0,
        "membership": "confirmed_fast",
    },
    {
        "key": "u2_GV",
        "value_name": r"U2\LCU2_db_Unit_stGov_nGV",
        "unit": "%",
        "min": 0.0,
        "max": 110.0,
        "membership": "confirmed_fast",
    },
    {
        "key": "u1_F",
        "value_name": r"U1\LCU1_db_Unit_stAlt_nF",
        "unit": "Hz",
        "min": 45.0,
        "max": 55.0,
        "membership": "candidate_namespace",
    },
    {
        "key": "u2_F",
        "value_name": r"U2\LCU2_db_Unit_stAlt_nF",
        "unit": "Hz",
        "min": 45.0,
        "max": 55.0,
        "membership": "candidate_namespace",
    },
    {
        "key": "u3_F",
        "value_name": r"U3\LCU3_db_Unit_stAlt_nF",
        "unit": "Hz",
        "min": 45.0,
        "max": 55.0,
        "membership": "candidate_namespace",
    },
)


def _format_time(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.000")


def _dispatch(name):
    import win32com.client
    return win32com.client.Dispatch(name)


def _connect(catalog, dsn):
    connection = _dispatch("ADODB.Connection")
    connection.ConnectionTimeout = CONNECTION_TIMEOUT_SEC
    connection.CommandTimeout = COMMAND_TIMEOUT_SEC
    connection.ConnectionString = (
        "Provider=WinCCOLEDBProvider.1;Catalog=%s;Data Source=%s" %
        (catalog, dsn)
    )
    connection.CursorLocation = 3
    connection.Open()
    return connection


def _error_details(error):
    """Return useful categories/codes without echoing connection strings."""
    lowered = str(error).lower()
    if "class not registered" in lowered or "80040154" in lowered:
        category = "provider_not_registered"
    elif "timeout" in lowered or "timed out" in lowered:
        category = "timeout"
    elif "login" in lowered or "authentication" in lowered:
        category = "authentication_failed"
    else:
        category = type(error).__name__
    details = {"error": category}
    code = getattr(error, "hresult", None)
    if code is None and getattr(error, "args", None):
        if isinstance(error.args[0], int):
            code = error.args[0]
    if isinstance(code, int):
        details["error_code"] = "0x%08X" % (code & 0xFFFFFFFF)
    return details


def _field_value(recordset, name):
    try:
        return recordset.Fields(name).Value
    except Exception:
        return None


def _timestamp_age(timestamp, now_utc):
    if timestamp is None:
        return None
    try:
        if isinstance(timestamp, datetime.datetime):
            parsed = timestamp
        else:
            text = str(timestamp).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        if now_utc.tzinfo is not None:
            now_utc = now_utc.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return round((now_utc - parsed).total_seconds(), 3)
    except Exception:
        return None


def _empty_result(spec, status="no_data"):
    return {
        "value_name": spec["value_name"],
        "membership": spec["membership"],
        "status": status,
        "value_id": None,
        "last": None,
        "last_ts": None,
        "age_sec": None,
        "quality": None,
        "quality_good": None,
        "in_range": None,
        "unit": spec["unit"],
        "value_field": None,
        "source": "wincc-oledb-valuename",
        "realtime": False,
        "sample_count": 0,
    }


def _read_value(recordset_factory, connection, spec, begin, end, now_utc):
    result = _empty_result(spec)
    recordset = recordset_factory()
    query = "TAG:R,'%s','%s','%s','TIMESTEP=%d,2'" % (
        spec["value_name"], begin, end, TIMESTEP_SEC)
    try:
        opened = recordset.Open(query, connection, 3, 1)
        if isinstance(opened, tuple) and opened and hasattr(opened[0], "EOF"):
            recordset = opened[0]
        latest = None
        count = 0
        while not recordset.EOF:
            real_value = _field_value(recordset, "RealValue")
            variant_value = _field_value(recordset, "VariantValue")
            if real_value is not None:
                value = real_value
                value_field = "RealValue"
            else:
                value = variant_value
                value_field = "VariantValue" if variant_value is not None else None
            latest = {
                "value_id": _field_value(recordset, "ValueID"),
                "timestamp": _field_value(recordset, "Timestamp"),
                "value": value,
                "value_field": value_field,
                "quality": _field_value(recordset, "Quality"),
            }
            count += 1
            recordset.MoveNext()
        result["sample_count"] = count
        if latest is None:
            return result

        try:
            value = float(latest["value"])
        except (TypeError, ValueError, OverflowError):
            value = None
        finite = value is not None and math.isfinite(value)
        if not finite:
            value = None

        try:
            value_id = int(latest["value_id"])
        except (TypeError, ValueError, OverflowError):
            value_id = None
        try:
            quality = int(latest["quality"])
        except (TypeError, ValueError, OverflowError):
            quality = None
        quality_good = None if quality is None else (quality & 0xC0) == 0xC0
        in_range = None if value is None else spec["min"] <= value <= spec["max"]
        if value is None:
            status = "invalid_value"
        elif quality is None:
            status = "unknown_quality"
        elif not quality_good:
            status = "bad_quality"
        elif not in_range:
            status = "out_of_range"
        else:
            status = "ok"

        timestamp = latest["timestamp"]
        result.update({
            "status": status,
            "value_id": value_id,
            "last": value,
            "last_ts": str(timestamp) if timestamp is not None else None,
            "age_sec": _timestamp_age(timestamp, now_utc),
            "quality": quality,
            "quality_good": quality_good,
            "in_range": in_range,
            "value_field": latest["value_field"],
        })
        return result
    finally:
        try:
            recordset.Close()
        except Exception:
            pass


def probe(connect_fn=None, recordset_factory=None, now_utc=None,
          monotonic=None, budget_sec=TOTAL_BUDGET_SEC,
          command_timeout_sec=COMMAND_TIMEOUT_SEC):
    """Query the exact allowlist; every failure remains diagnostic-only."""
    connect_fn = connect_fn or _connect
    recordset_factory = recordset_factory or (
        lambda: _dispatch("ADODB.Recordset"))
    now_utc = now_utc or datetime.datetime.utcnow()
    monotonic = monotonic or time.monotonic
    started = monotonic()
    begin = _format_time(now_utc - datetime.timedelta(hours=WINDOW_HOURS))
    end = _format_time(now_utc)
    payload = {
        "available": False,
        "backend": "wincc-oledb-valuename",
        "status": "connect_error",
        "catalog": CATALOG,
        "window_hours": WINDOW_HOURS,
        "timestep_sec": TIMESTEP_SEC,
        "command_timeout_sec": int(command_timeout_sec),
        "elapsed_ms": 0,
        "attempted": 0,
        "observed": 0,
        "good": 0,
        "recorded_utc": now_utc.replace(microsecond=0).isoformat() + "Z",
        "results": {},
    }
    connection = None
    try:
        connection = connect_fn(CATALOG, DSN)
        connection.CommandTimeout = int(command_timeout_sec)
        payload["available"] = True
        payload["status"] = "complete"
        for index, spec in enumerate(VALUE_SPECS):
            if monotonic() - started >= budget_sec:
                payload["status"] = "budget_exhausted"
                for remaining in VALUE_SPECS[index:]:
                    payload["results"][remaining["key"]] = _empty_result(
                        remaining, status="budget_exhausted")
                break
            payload["attempted"] += 1
            try:
                result = _read_value(
                    recordset_factory, connection, spec, begin, end, now_utc)
            except Exception as error:
                result = _empty_result(spec, status="query_error")
                result.update(_error_details(error))
            payload["results"][spec["key"]] = result
            if result.get("last") is not None:
                payload["observed"] += 1
            if result.get("status") == "ok":
                payload["good"] += 1
    except Exception as error:
        payload.update(_error_details(error))
    finally:
        if connection is not None:
            try:
                connection.Close()
            except Exception:
                pass
        payload["elapsed_ms"] = int(max(0.0, monotonic() - started) * 1000)
    return payload


def _authorized(argv):
    if "--raw-canary" not in argv:
        return False
    try:
        station = argv[argv.index("--station") + 1]
    except (ValueError, IndexError):
        return False
    return str(station).strip().lower() == "dakrosa1"


def main(argv=None, probe_fn=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not _authorized(argv):
        print(json.dumps({
            "available": False,
            "backend": "wincc-oledb-valuename",
            "status": "not_authorized",
        }, separators=(",", ":")))
        return
    probe_fn = probe_fn or probe
    try:
        payload = probe_fn()
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except Exception as error:
        fallback = {
            "available": False,
            "backend": "wincc-oledb-valuename",
            "status": "internal_error",
        }
        fallback.update(_error_details(error))
        encoded = json.dumps(fallback, ensure_ascii=False, allow_nan=False)
    print(encoded)


if __name__ == "__main__":
    main()
