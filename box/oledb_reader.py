"""Chay bang Python 32-bit TREN may WinCC (MAINPC). READ-ONLY.
Doc gia tri tag da giai nen qua WinCC OLE-DB Provider, tinh thong ke cua so 5 phut,
xuat JSON ra stdout. Tu dong bo qua tag khong archive.
"""
import sys
import json
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import win32com.client

DSN = r"MAINPC\WINCC"
PROJECT_LIKE = "CC[_]Dakrosa1[_]%R"           # runtime DB pattern
CATALOG_FALLBACK = "CC_Dakrosa1_23_10_10_10_26_33R"
WINDOW_MIN = 5

# ValueID -> ten than thien (lay tu bang Archive)
MAP = {
    # 22kV bus / line to DAKTO
    1: "bus_U1N", 2: "bus_U2N", 3: "bus_U3N", 4: "bus_U12", 5: "bus_U23",
    6: "bus_U31", 7: "bus_I1", 8: "bus_I2", 9: "bus_I3", 10: "bus_P",
    11: "bus_Q", 12: "bus_F", 13: "bus_PF",
    # Unit 1
    14: "u1_U12", 15: "u1_I1", 16: "u1_P", 17: "u1_Q", 26: "u1_GV", 27: "u1_speed",
    # Unit 2
    18: "u2_U12", 19: "u2_I1", 20: "u2_P", 21: "u2_Q", 31: "u2_GV", 35: "u2_speed",
    # Unit 3
    22: "u3_U12", 23: "u3_I1", 24: "u3_P", 25: "u3_Q", 39: "u3_GV", 43: "u3_speed",
}


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.000")


def resolve_catalog():
    """Resolve runtime DB name dong (doi moi lan re-activate). Fallback hardcoded."""
    for prov in ("MSOLEDBSQL", "SQLOLEDB"):
        try:
            c = win32com.client.Dispatch("ADODB.Connection")
            c.ConnectionString = (
                f"Provider={prov};Data Source={DSN};Initial Catalog=master;"
                f"Integrated Security=SSPI;TrustServerCertificate=yes"
            )
            c.Open()
            rs = c.Execute(
                f"SELECT TOP 1 name FROM sys.databases WHERE name LIKE '{PROJECT_LIKE}' "
                f"ORDER BY create_date DESC")
            name = rs.Fields(0).Value if not rs.EOF else None
            c.Close()
            if name:
                return str(name)
        except Exception:
            continue
    return CATALOG_FALLBACK


def read_stats(conn, vid, beg, end):
    rs = win32com.client.Dispatch("ADODB.Recordset")
    rs.Open(f"TAG:R,{vid},'{beg}','{end}'", conn, 3, 1)  # adOpenStatic, adLockReadOnly
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
    return {
        "count": int(cnt),
        "last": float(last) if last is not None else None,
        "min": min(vals),
        "max": max(vals),
        "avg": sum(vals) / len(vals),
        "last_ts": last_ts,
    }


def main():
    catalog = resolve_catalog()
    conn = win32com.client.Dispatch("ADODB.Connection")
    conn.ConnectionString = f"Provider=WinCCOLEDBProvider.1;Catalog={catalog};Data Source={DSN}"
    conn.CursorLocation = 3  # adUseClient
    conn.Open()
    now = datetime.datetime.utcnow()
    beg = fmt(now - datetime.timedelta(minutes=WINDOW_MIN))
    end = fmt(now + datetime.timedelta(minutes=1))
    out = {
        "snapshot_utc": now.replace(microsecond=0).isoformat() + "Z",
        "catalog": catalog,
        "window_min": WINDOW_MIN,
        "tags": {},
    }
    for vid, name in MAP.items():
        try:
            s = read_stats(conn, vid, beg, end)
            if s:
                out["tags"][name] = s
        except Exception as e:
            out["tags"][name] = {"error": str(e)[:120]}
    conn.Close()
    # nang luong xap xi tu cong suat tac dung trung binh (MW * h)
    energy = {}
    for unit_p in ("bus_P", "u1_P", "u2_P", "u3_P"):
        t = out["tags"].get(unit_p)
        if t and t.get("avg") is not None:
            energy[unit_p.replace("_P", "_MWh_5min")] = round(t["avg"] * WINDOW_MIN / 60.0, 6)
    out["energy_5min"] = energy
    print(json.dumps(out, ensure_ascii=False, default=str))


main()
