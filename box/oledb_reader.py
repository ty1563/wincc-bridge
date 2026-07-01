"""Chay bang Python 32-bit TREN may WinCC (MAINPC). READ-ONLY.
Doc gia tri tag da giai nen qua WinCC OLE-DB Provider, tinh thong ke cua so 5 phut,
LUON xuat JSON hop le ra stdout (loi cung dua vao field 'error' -> service khong ket).
"""
import sys
import json
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import win32com.client

# Config qua ENV var (service truyen khi goi reader). Default = Dakrosa1 (tuong thich nguoc).
# Tram khac: setup dat ENV WINCC_PROJECT_LIKE / WINCC_CATALOG_FALLBACK / WINCC_STATION_NAME.
import os as _os
import sys as _sys
import socket as _socket
# DSN mac dinh = .\WINCC (SQL Server local instance) - hoat dong tren MOI may
# co WinCC cai san, khong phu thuoc hostname. Truoc day hardcode 'MAINPC\WINCC'
# nen may khac tram (vd DAKROSA2-PC) treo vi resolve host MAINPC that bai.
DSN = _os.environ.get("WINCC_DSN") or r".\WINCC"
PROJECT_LIKE = _os.environ.get("WINCC_PROJECT_LIKE") or "CC[_]Dakrosa1[_]%R"
# Fix: ENV="" (user de trong trong config) van coi la "khong co fallback".
_cfb_env = _os.environ.get("WINCC_CATALOG_FALLBACK")
CATALOG_FALLBACK = _cfb_env if _cfb_env else ""
STATION_NAME = _os.environ.get("WINCC_STATION_NAME") or "Dakrosa1"
WINDOW_MIN = 5
# Timeout de reader khong treo mai (ADODB mac dinh khong timeout khi Open/Execute).
CONN_TIMEOUT_SEC = 5
CMD_TIMEOUT_SEC = 15


def _dbg(msg):
    """Print tien trinh ra stderr - stdout danh cho JSON output."""
    print(f"[dbg] {msg}", file=_sys.stderr, flush=True)

MAP = {
    1: "bus_U1N", 2: "bus_U2N", 3: "bus_U3N", 4: "bus_U12", 5: "bus_U23",
    6: "bus_U31", 7: "bus_I1", 8: "bus_I2", 9: "bus_I3", 10: "bus_P",
    11: "bus_Q", 12: "bus_F", 13: "bus_PF",
    14: "u1_U12", 15: "u1_I1", 16: "u1_P", 17: "u1_Q", 26: "u1_GV", 27: "u1_speed",
    18: "u2_U12", 19: "u2_I1", 20: "u2_P", 21: "u2_Q", 31: "u2_GV", 35: "u2_speed",
    22: "u3_U12", 23: "u3_I1", 24: "u3_P", 25: "u3_Q", 39: "u3_GV", 43: "u3_speed",
}


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.000")


def resolve_catalogs():
    """Tra ve danh sach catalog ung vien (runtime DB ...R), moi nhat truoc, + fallback (neu co)."""
    cats = []
    for prov in ("MSOLEDBSQL", "SQLOLEDB"):
        try:
            _dbg(f"resolve_catalogs: thu provider {prov}")
            c = win32com.client.Dispatch("ADODB.Connection")
            c.ConnectionTimeout = CONN_TIMEOUT_SEC
            c.CommandTimeout = CMD_TIMEOUT_SEC
            c.ConnectionString = (f"Provider={prov};Data Source={DSN};Initial Catalog=master;"
                                  f"Integrated Security=SSPI;TrustServerCertificate=yes")
            c.Open()
            _dbg(f"resolve_catalogs: {prov} Open OK")
            rs = c.Execute(f"SELECT name FROM sys.databases WHERE name LIKE '{PROJECT_LIKE}' "
                          f"ORDER BY create_date DESC")
            while not rs.EOF:
                n = str(rs.Fields(0).Value)
                if n not in cats:
                    cats.append(n)
                rs.MoveNext()
            c.Close()
            _dbg(f"resolve_catalogs: found {len(cats)} catalog(s): {cats[:3]}")
            if cats:
                break
        except Exception as e:
            _dbg(f"resolve_catalogs: {prov} loi -> {str(e)[:120]}")
            continue
    # CHI append fallback neu co gia tri (khong empty)
    if CATALOG_FALLBACK and CATALOG_FALLBACK not in cats:
        cats.append(CATALOG_FALLBACK)
    return cats


def connect(catalog):
    _dbg(f"connect: {catalog}")
    conn = win32com.client.Dispatch("ADODB.Connection")
    conn.ConnectionTimeout = CONN_TIMEOUT_SEC
    conn.CommandTimeout = CMD_TIMEOUT_SEC
    conn.ConnectionString = f"Provider=WinCCOLEDBProvider.1;Catalog={catalog};Data Source={DSN}"
    conn.CursorLocation = 3
    conn.Open()
    _dbg(f"connect: {catalog} Open OK")
    return conn


def read_stats(conn, vid, beg, end):
    rs = win32com.client.Dispatch("ADODB.Recordset")
    rs.Open(f"TAG:R,{vid},'{beg}','{end}'", conn, 3, 1)
    cnt = rs.RecordCount
    if not cnt or cnt <= 0:
        rs.Close()
        return None
    vals = []
    rs.MoveFirst()
    while not rs.EOF:
        v = rs.Fields("VariantValue").Value
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
        rs.MoveNext()
    rs.MoveLast()
    last = rs.Fields("VariantValue").Value
    last_ts = str(rs.Fields("Timestamp").Value)
    rs.Close()
    if not vals:
        return None
    return {"count": int(cnt), "last": float(last) if last is not None else None,
            "min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals), "last_ts": last_ts}


def main():
    now = datetime.datetime.utcnow()
    out = {"snapshot_utc": now.replace(microsecond=0).isoformat() + "Z",
           "window_min": WINDOW_MIN, "station": STATION_NAME, "tags": {}}
    # Ket noi: thu lan luot cac catalog
    conn = None
    last_err = ""
    try:
        cands = resolve_catalogs()
    except Exception as e:
        cands = [CATALOG_FALLBACK]
        last_err = str(e)[:160]
    for c in cands:
        try:
            conn = connect(c)
            out["catalog"] = c
            break
        except Exception as e:
            last_err = str(e)[:200]
    if conn is None:
        out["error"] = "Khong ket noi duoc OLE-DB provider. Kiem tra WinCC Runtime co ACTIVE khong. " + last_err
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    beg = fmt(now - datetime.timedelta(minutes=WINDOW_MIN))
    end = fmt(now)
    out["window_utc"] = [beg, end]
    n_err = 0
    for vid, name in MAP.items():
        try:
            s = read_stats(conn, vid, beg, end)
            if s:
                out["tags"][name] = s
        except Exception as e:
            out["tags"][name] = {"error": str(e)[:120]}
            n_err += 1
    try:
        conn.Close()
    except Exception:
        pass
    if len(out["tags"]) == 0:
        out["error"] = "0 tag co du lieu (WinCC Runtime co dang archive khong? Project active?)"
    if n_err:
        out["tag_errors"] = n_err
    energy = {}
    for up in ("bus_P", "u1_P", "u2_P", "u3_P"):
        t = out["tags"].get(up)
        if isinstance(t, dict) and t.get("avg") is not None:
            energy[up.replace("_P", "_MWh_5min")] = round(t["avg"] * WINDOW_MIN / 60.0, 6)
    out["energy_5min"] = energy
    print(json.dumps(out, ensure_ascii=False, default=str))


main()
