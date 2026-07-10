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
# QUAN TRONG: default PHAI la 'MAINPC\WINCC' (KHONG doi) - day la gia tri da
# chay on dinh tren box Dakrosa1 (remote/SSH mode) tu dau. File nay duoc OTA
# day sang CA box Dakrosa1 (qua _sync_box trong updater.py), va SSH KHONG
# forward env var WINCC_DSN tu may DELL sang box -> box luon dung fallback nay.
# Tung doi thanh '.\WINCC' (v1.3.3) lam Dakrosa1 mat ket noi - da revert.
# Tram khac (vd Dakrosa2, mode=local) TU dat WINCC_DSN qua [station].dsn trong
# config.local.toml -> khong dung fallback nay, khong bi anh huong.
DSN = _os.environ.get("WINCC_DSN") or r"MAINPC\WINCC"
PROJECT_LIKE = _os.environ.get("WINCC_PROJECT_LIKE") or "CC[_]Dakrosa1[_]%R"
# QUAN TRONG: default PHAI la fallback goc cua Dakrosa1 (KHONG doi thanh "").
# Cung ly do nhu DSN o tren: SSH remote mode (Dakrosa1) khong forward env var,
# nen luon roi vao nhanh default nay. Tung doi thanh "" (v1.3.3) lam mat luoi
# an toan cuoi cung khi LIKE-match khong ra ket qua tren Dakrosa1 - da revert.
_cfb_env = _os.environ.get("WINCC_CATALOG_FALLBACK")
CATALOG_FALLBACK = _cfb_env if _cfb_env else "CC_Dakrosa1_23_10_10_10_26_33R"
STATION_NAME = _os.environ.get("WINCC_STATION_NAME") or "Dakrosa1"
# READ_MODE = "raw" -> giai ma thang bang TagCompressed (khong dung WinCCOLEDBProvider).
# Dung cho may co project WinCC lech ten (archive mo coi) khien provider tra 0 du data co that.
READ_MODE = (_os.environ.get("WINCC_READ_MODE") or "").lower()
# DUMP_RAW: thay vi doc tag thuong, DUMP block TagCompressed tho (base64) + ban
# do ten tag de gui len server decode -> khai thac DU tag, va tai ve may khac
# phan tich offline. Van READ-ONLY (chi SELECT). Bat bang ENV WINCC_DUMP_RAW=1
# (mode local) HOAC argv --dump-raw (mode remote: SSH KHONG forward env var).
DUMP_RAW = (_os.environ.get("WINCC_DUMP_RAW") or "") == "1" or "--dump-raw" in _sys.argv
# Runtime probe la kenh chan doan rieng, chi bat khi service goi raw-dump voi
# --probe-runtime. Snapshot archive 30s khong bi anh huong neu Native API loi.
PROBE_RUNTIME = ((_os.environ.get("WINCC_RUNTIME_PROBE") or "") == "1" or
                 "--probe-runtime" in _sys.argv)
WINDOW_MIN = 5
# Timeout de reader khong treo mai (ADODB mac dinh khong timeout khi Open/Execute).
CONN_TIMEOUT_SEC = 5
CMD_TIMEOUT_SEC = 15


def _dbg(msg):
    """Print tien trinh ra stderr - stdout danh cho JSON output."""
    print(f"[dbg] {msg}", file=_sys.stderr, flush=True)

# MAP mac dinh = Dakrosa1 (ValueID -> ten tag). Tram khac (vd Dakrosa2) co
# ValueID hoan toan khac -> nap tu ENV WINCC_TAG_MAP (JSON {ten: valueid}) do
# service truyen tu [tags] trong config.local.toml. KHONG doi code cho tram moi.
DEFAULT_MAP = {
    1: "bus_U1N", 2: "bus_U2N", 3: "bus_U3N", 4: "bus_U12", 5: "bus_U23",
    6: "bus_U31", 7: "bus_I1", 8: "bus_I2", 9: "bus_I3", 10: "bus_P",
    11: "bus_Q", 12: "bus_F", 13: "bus_PF",
    14: "u1_U12", 15: "u1_I1", 16: "u1_P", 17: "u1_Q", 26: "u1_GV", 27: "u1_speed",
    18: "u2_U12", 19: "u2_I1", 20: "u2_P", 21: "u2_Q", 31: "u2_GV", 35: "u2_speed",
    22: "u3_U12", 23: "u3_I1", 24: "u3_P", 25: "u3_Q", 39: "u3_GV", 43: "u3_speed",
}
_tagmap_env = _os.environ.get("WINCC_TAG_MAP")
if _tagmap_env:
    try:
        _m = json.loads(_tagmap_env)          # {ten: valueid} tu config [tags]
        MAP = {int(v): str(k) for k, v in _m.items()}
    except Exception as _e:
        _dbg(f"WINCC_TAG_MAP loi parse ({_e}) -> dung DEFAULT_MAP")
        MAP = dict(DEFAULT_MAP)
else:
    MAP = dict(DEFAULT_MAP)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.000")


def _query_all_dbs(conn, prov):
    """Liet ke TAT CA database (khong loc pattern) - de user thay ten thuc te."""
    try:
        rs = conn.Execute("SELECT name FROM sys.databases WHERE name NOT IN "
                          "('master','tempdb','model','msdb') ORDER BY create_date DESC")
        if isinstance(rs, tuple):
            rs = rs[0]
        names = []
        while not rs.EOF and len(names) < 20:
            names.append(str(rs.Fields(0).Value))
            rs.MoveNext()
        return names
    except Exception:
        return []


def resolve_catalogs():
    """Tra ve (cats, errs, working_dsn, all_dbs) - de bao cao chi tiet qua JSON.
    all_dbs = liet ke moi DB thuc te tren SQL instance de user biet dat project_like."""
    cats, errs, all_dbs = [], [], []
    host = _socket.gethostname()
    dsn_cands = [DSN]
    for extra in (r".\WINCC", r".\SQLEXPRESS", f"{host}\\WINCC", f"{host}\\SQLEXPRESS", host):
        if extra not in dsn_cands:
            dsn_cands.append(extra)
    for dsn in dsn_cands:
        for prov in ("MSOLEDBSQL", "SQLOLEDB"):
            try:
                _dbg(f"resolve_catalogs: DSN={dsn} provider={prov}")
                c = win32com.client.Dispatch("ADODB.Connection")
                c.ConnectionTimeout = CONN_TIMEOUT_SEC
                c.CommandTimeout = CMD_TIMEOUT_SEC
                c.ConnectionString = (f"Provider={prov};Data Source={dsn};Initial Catalog=master;"
                                      f"Integrated Security=SSPI;TrustServerCertificate=yes")
                c.Open()
                rs = c.Execute(f"SELECT name FROM sys.databases WHERE name LIKE '{PROJECT_LIKE}' "
                              f"ORDER BY create_date DESC")
                if isinstance(rs, tuple):
                    rs = rs[0]
                matched = 0
                while not rs.EOF:
                    n = str(rs.Fields(0).Value)
                    if n not in cats:
                        cats.append(n)
                    matched += 1
                    rs.MoveNext()
                # Truong hop Open+Execute OK nhung 0 rows: LOG ro cho user biet.
                # Dong thoi liet ke moi DB de user thay ten thuc te.
                if not matched and not all_dbs:
                    all_dbs = _query_all_dbs(c, prov)
                    errs.append(f"{dsn}/{prov}: SQL OK, 0 DB khop '{PROJECT_LIKE}'. "
                                f"DB thuc te: {all_dbs[:5]}")
                c.Close()
                _dbg(f"resolve_catalogs: {dsn}/{prov} OK, matched={matched}")
                if cats:
                    return cats, errs, dsn, all_dbs
            except Exception as e:
                errs.append(f"{dsn}/{prov}: {str(e)[:100]}")
                _dbg(f"resolve_catalogs: {dsn}/{prov} loi -> {str(e)[:120]}")
                continue
    if CATALOG_FALLBACK and CATALOG_FALLBACK not in cats:
        cats.append(CATALOG_FALLBACK)
    return cats, errs, DSN, all_dbs


def connect(catalog, dsn=None):
    dsn = dsn or DSN
    _dbg(f"connect: catalog={catalog} DSN={dsn}")
    conn = win32com.client.Dispatch("ADODB.Connection")
    conn.ConnectionTimeout = CONN_TIMEOUT_SEC
    conn.CommandTimeout = CMD_TIMEOUT_SEC
    conn.ConnectionString = f"Provider=WinCCOLEDBProvider.1;Catalog={catalog};Data Source={dsn}"
    conn.CursorLocation = 3
    conn.Open()
    _dbg(f"connect: {catalog} Open OK")
    return conn


def read_stats(conn, vid, beg, end):
    rs = win32com.client.Dispatch("ADODB.Recordset")
    ret = rs.Open(f"TAG:R,{vid},'{beg}','{end}'", conn, 3, 1)
    # An toan cho pywin32 3.7 (tra tuple)
    if isinstance(ret, tuple) and ret and hasattr(ret[0], "EOF"):
        rs = ret[0]
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


# ============================================================
# RAW-DECODE mode: doc thang TagCompressed, giai ma float32 theo marker '00 00'.
# WinCC nen gia tri dang float32, moi gia tri that dung SAU 2 byte 00 00 (byte
# truoc do la delta != 0). Gia tri 0.0/-0.0 xen giua la marker "khong doi" -> bo.
# Da kiem chung: tan so ra ~50Hz, cong suat H3 ~560kW khop HMI.
# ============================================================
import struct as _struct
import math as _math
import base64 as _base64


def _sql_master():
    """Ket noi SQLOLEDB toi master, thu nhieu DSN (khong dung WinCCOLEDBProvider)."""
    host = _socket.gethostname()
    cands = [DSN]
    for x in (r".\WINCC", f"{host}\\WINCC", r".\SQLEXPRESS", host):
        if x not in cands:
            cands.append(x)
    for dsn in cands:
        for prov in ("SQLOLEDB", "MSOLEDBSQL"):
            try:
                c = win32com.client.Dispatch("ADODB.Connection")
                c.ConnectionTimeout = CONN_TIMEOUT_SEC
                c.CommandTimeout = 30
                c.ConnectionString = (f"Provider={prov};Data Source={dsn};Initial Catalog=master;"
                                      f"Integrated Security=SSPI;TrustServerCertificate=yes")
                c.Open()
                return c, dsn
            except Exception:
                continue
    return None, None


def _exec_rows(c, sql):
    rs = c.Execute(sql)
    if isinstance(rs, tuple):
        rs = rs[0]
    out = []
    while not rs.EOF:
        out.append([rs.Fields(i).Value for i in range(rs.Fields.Count)])
        rs.MoveNext()
    return out


def _find_live_archive(c, like="%TLG[_]F%"):
    """Archive (theo pattern) co du lieu MOI NHAT (tu bam theo du reboot shuffle).
    Mac dinh TLG_F (Fast); truyen '%TLG[_]S%' de tim TagLogging SLOW (nhiet do,
    tan so... thuong duoc ghi o archive Slow voi chu ky phut/gio)."""
    dbs = [str(r[0]) for r in _exec_rows(c, f"SELECT name FROM sys.databases WHERE name LIKE '{like}'")]
    best, best_t = None, None
    for db in dbs:
        try:
            r = _exec_rows(c, f"SELECT MAX(Timeend) FROM [{db}].dbo.TagCompressed")
            t = r[0][0] if r else None
            if t is not None and (best_t is None or t > best_t):
                best_t, best = t, db
        except Exception:
            continue
    return best, best_t


def _decode_block(raw):
    """Giai ma 1 block TagCompressed -> list gia tri that (float32 sau marker 00 00)."""
    vals = []
    n = len(raw)
    # den n-4 BAO GOM (n-3 exclusive): float cuoi block co the cham dung mep buffer
    for o in range(3, n - 3):
        if raw[o - 1] == 0 and raw[o - 2] == 0 and raw[o - 3] != 0:
            f = _struct.unpack("<f", raw[o:o + 4])[0]
            # giu gia tri that (>=1e-6, <1e6); bo marker 0.0/-0.0 va denormal misalign
            if not (_math.isnan(f) or _math.isinf(f)) and 1e-6 < abs(f) < 1e6:
                vals.append(f)
    return vals


def _robust(vals):
    """Bo outlier (spike rac do doc float lech): giu gia tri quanh median, giu thu tu."""
    s = sorted(vals)
    mid = s[len(s) // 2]
    band = max(abs(mid) * 0.5, 1e-3)
    kept = [v for v in vals if abs(v - mid) <= band]
    return kept or vals


def _stale_sec(te, live_t):
    """So giay block nay cu hon du lieu moi nhat archive (te, live_t la datetime)."""
    try:
        return (live_t - te).total_seconds()
    except Exception:
        return 0


def _read_raw_tag(c, db, vid, live_t=None):
    """Doc block moi nhat cua ValueID -> thong ke. None neu khong co block."""
    rs = c.Execute(f"SELECT TOP 1 Timeend, BinValues FROM [{db}].dbo.TagCompressed "
                   f"WHERE ValueID={vid} AND DATALENGTH(BinValues) > 300 ORDER BY Timeend DESC")
    if isinstance(rs, tuple):
        rs = rs[0]
    if rs.EOF:
        return None
    te_raw = rs.Fields(0).Value
    te = str(te_raw)
    raw = bytes(rs.Fields(1).Value)
    rs.Close()
    # Block cu hon 15 phut so voi du lieu moi nhat -> tag khong con cap nhat (vd to may dung) -> 0
    if live_t is not None and _stale_sec(te_raw, live_t) > 900:
        return {"count": 0, "last": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0,
                "last_ts": te, "stale": True}
    vals = _decode_block(raw)
    if not vals:
        return {"count": 0, "last": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0, "last_ts": te}
    vals = _robust(vals)
    return {"count": len(vals), "last": vals[-1], "min": min(vals), "max": max(vals),
            "avg": sum(vals) / len(vals), "last_ts": te}


def _main_raw(out):
    c, dsn = _sql_master()
    if c is None:
        out["error"] = "RAW: khong ket noi SQL (SQLOLEDB) - kiem tra .\\WINCC"
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    out["read_mode"] = "raw"
    out["dsn_used"] = dsn
    db, live_t = _find_live_archive(c)
    if not db:
        out["error"] = "RAW: khong tim thay archive TLG_F co du lieu"
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    out["archive"] = db
    out["archive_latest"] = str(live_t)
    n_err = 0
    for vid, name in MAP.items():
        try:
            s = _read_raw_tag(c, db, vid, live_t)
            if s is not None:
                out["tags"][name] = s
        except Exception as e:
            out["tags"][name] = {"error": str(e)[:120]}
            n_err += 1
    try:
        c.Close()
    except Exception:
        pass
    if n_err:
        out["tag_errors"] = n_err
    if len(out["tags"]) == 0:
        out["error"] = "RAW: 0 tag doc duoc"
    energy = {}
    for up in ("bus_P", "u1_P", "u2_P", "u3_P"):
        t = out["tags"].get(up)
        if isinstance(t, dict) and t.get("avg") is not None:
            energy[up.replace("_P", "_MWh_5min")] = round(t["avg"] * WINDOW_MIN / 60.0, 6)
    out["energy_5min"] = energy
    print(json.dumps(out, ensure_ascii=False, default=str))


# Gioi han dump de payload gon va khong don dap may tram (READ-ONLY, chi SELECT):
DUMP_MAX_TOTAL = 4 * 1024 * 1024   # tong blob tho toi da ~4MB (b64 ~5.3MB)
DUMP_MAX_BLOB = 256 * 1024         # bo blob don le > 256KB (bat thuong)
DUMP_ACTIVE_HOURS = 2              # chi lay tag co block moi trong N gio (tag dang song)
DUMP_MAX_NAMES = 8000              # tran so dong ban do ten tag
# Tram provider/remote (Dakrosa1) giu payload cu: 1 block/VID. Tram raw/local
# (Dakrosa2) lui toi 6 block deadband de tim gia tri moi nhat co that.
_dump_blocks_default = 6 if READ_MODE == "raw" else 1
try:
    DUMP_BLOCKS_PER_VID = max(1, min(6, int(
        _os.environ.get("WINCC_DUMP_BLOCKS_PER_VID", _dump_blocks_default))))
except (TypeError, ValueError):
    DUMP_BLOCKS_PER_VID = _dump_blocks_default


def _dump_names(c, db):
    """Ban do ValueID->ValueName tu bang Archive cua db."""
    names = {}
    for r in _exec_rows(c, f"SELECT TOP {DUMP_MAX_NAMES} ValueID, ValueName "
                           f"FROM [{db}].dbo.Archive"):
        names[str(int(r[0]))] = str(r[1])
    return names


def _dump_blocks(c, db, live_t, hours, cap):
    """Moi ValueID dang hoat dong lay toi da N block moi nhat de server co the
    lui qua block deadband (chi header/timestamp, khong co gia tri). Xep rn=1 cua
    tat ca tag truoc, roi rn=2... de neu cham cap van giu do phu tag hien tai.
    ROW_NUMBER co tu SQL Server 2005. Tra (blocks, total_vids, total_bytes,
    truncated); trong tung ValueID, block moi luon dung truoc block cu."""
    try:
        cutoff = fmt(live_t - datetime.timedelta(hours=hours))
    except Exception:
        cutoff = fmt(datetime.datetime.utcnow() - datetime.timedelta(hours=hours))
    try:
        r = _exec_rows(c, f"SELECT COUNT(DISTINCT ValueID) FROM [{db}].dbo.TagCompressed "
                          f"WHERE Timeend >= '{cutoff}'")
        total_vids = int(r[0][0]) if r else None
    except Exception:
        total_vids = None
    sql = (f"SELECT vid, tb, te, ln, bv, rn FROM ("
           f"SELECT ValueID vid, Timebegin tb, Timeend te, DATALENGTH(BinValues) ln, "
           f"BinValues bv, ROW_NUMBER() OVER (PARTITION BY ValueID ORDER BY Timeend DESC) rn "
           f"FROM [{db}].dbo.TagCompressed WHERE Timeend >= '{cutoff}' "
           f"AND DATALENGTH(BinValues) > 16) t WHERE rn <= {DUMP_BLOCKS_PER_VID} "
           f"ORDER BY rn ASC, te DESC")
    blocks = []
    total = 0
    truncated = False
    rs = c.Execute(sql)
    if isinstance(rs, tuple):
        rs = rs[0]
    while not rs.EOF:
        try:
            ln = int(rs.Fields(3).Value or 0)
            if 16 < ln <= DUMP_MAX_BLOB:
                if total + ln > cap:
                    truncated = True
                    break
                raw = bytes(rs.Fields(4).Value)
                blocks.append({"vid": int(rs.Fields(0).Value),
                               "tb": str(rs.Fields(1).Value),
                               "te": str(rs.Fields(2).Value),
                               "b64": _base64.b64encode(raw).decode("ascii")})
                total += ln
        except Exception:
            pass  # 1 block loi khong chan ca dump
        rs.MoveNext()
    try:
        rs.Close()
    except Exception:
        pass
    return blocks, total_vids, total, truncated


def _find_live_slow(c):
    """TLG_S (TagLogging SLOW) luu du lieu o bang TagUncompressed (KHONG nen,
    hang tho: ValueID/Timestamp/RealValue) -> tim db co Timestamp moi nhat.
    (TagCompressed trong TLG_S rong nen khong dung _find_live_archive.)"""
    dbs = [str(r[0]) for r in _exec_rows(
        c, "SELECT name FROM sys.databases WHERE name LIKE '%TLG[_]S%'")]
    best, best_t = None, None
    for db in dbs:
        try:
            r = _exec_rows(c, f"SELECT MAX(Timestamp) FROM [{db}].dbo.TagUncompressed")
            t = r[0][0] if r else None
            if t is not None and (best_t is None or t > best_t):
                best_t, best = t, db
        except Exception:
            continue
    return best, best_t


def _dump_slow_values(c, db, live_t, hours=48, top=5000):
    """Doc TRUC TIEP gia tri tu TagUncompressed (khong can decode): moi ValueID
    lay gia tri MOI NHAT + thong ke (count/min/max/avg) trong cua so `hours`."""
    try:
        cutoff = fmt(live_t - datetime.timedelta(hours=hours))
    except Exception:
        cutoff = fmt(datetime.datetime.utcnow() - datetime.timedelta(hours=hours))
    agg = {}
    for r in _exec_rows(c, f"SELECT ValueID, COUNT(*), MIN(RealValue), MAX(RealValue), "
                           f"AVG(RealValue) FROM [{db}].dbo.TagUncompressed "
                           f"WHERE Timestamp >= '{cutoff}' GROUP BY ValueID"):
        agg[int(r[0])] = (int(r[1]), r[2], r[3], r[4])
    vals = []
    sql = (f"SELECT vid, ts, val FROM (SELECT ValueID vid, Timestamp ts, RealValue val, "
           f"ROW_NUMBER() OVER (PARTITION BY ValueID ORDER BY Timestamp DESC) rn "
           f"FROM [{db}].dbo.TagUncompressed WHERE Timestamp >= '{cutoff}') t WHERE rn = 1")
    for r in _exec_rows(c, sql):
        vid = int(r[0])
        n, mn, mx, av = agg.get(vid, (1, None, None, None))
        vals.append({"vid": vid, "ts": str(r[1]), "last": r[2],
                     "n": n, "min": mn, "max": mx, "avg": av})
        if len(vals) >= top:
            break
    return vals


def _attach_runtime_probe(out, probe=None):
    """Attach bounded process-tag inventory without ever breaking raw archive."""
    try:
        if probe is None:
            from wincc_runtime import probe_runtime as probe
        out["runtime_probe"] = probe(inventory_limit=4000, candidate_limit=256)
    except Exception as e:
        out["runtime_probe"] = {
            "available": False,
            "backend": "wincc-apicf",
            "error": str(e)[:300],
        }


def _main_rawdump(out):
    """DUMP block TagCompressed tho (base64) + ban do ten tag; server decode.
    Quet CA TagLogging Fast (TLG_F) lan Slow (TLG_S - nhiet do/tan so thuong
    ghi o day voi chu ky cham). Liet ke all_tlg_dbs de biet may co archive gi."""
    c, dsn = _sql_master()
    if c is None:
        out["error"] = "RAWDUMP: khong ket noi SQL (SQLOLEDB)"
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    out["raw_dump"] = True
    out["dsn_used"] = dsn
    try:
        out["all_tlg_dbs"] = [str(r[0]) for r in _exec_rows(
            c, "SELECT name FROM sys.databases WHERE name LIKE '%TLG%'")][:25]
    except Exception:
        pass
    db, live_t = _find_live_archive(c)
    if not db:
        out["error"] = "RAWDUMP: khong tim thay archive TLG_F co du lieu"
        print(json.dumps(out, ensure_ascii=False, default=str))
        return
    out["archive"] = db
    out["archive_latest"] = str(live_t)
    try:
        out["names"] = _dump_names(c, db)
    except Exception as e:
        out["names"] = {}
        out["names_error"] = str(e)[:150]
    blocks, total_vids, total, trunc = _dump_blocks(c, db, live_t, DUMP_ACTIVE_HOURS,
                                                    DUMP_MAX_TOTAL)
    out["blocks"] = blocks
    out["total_vids"] = total_vids
    out["shipped_vids"] = len({b["vid"] for b in blocks})
    out["shipped_blocks"] = len(blocks)
    out["truncated"] = trunc
    out["dump_bytes"] = total
    # TagLogging SLOW (neu co): du lieu o TagUncompressed -> doc TRUC TIEP gia
    # tri (khong can decode block). Cua so 48h vi chu ky ghi cham (phut/gio).
    try:
        db_s, live_s = _find_live_slow(c)
        if db_s:
            out["archive_slow"] = db_s
            out["archive_slow_latest"] = str(live_s)
            try:
                out["names_slow"] = _dump_names(c, db_s)
            except Exception as e:
                out["names_slow"] = {}
                out["names_slow_error"] = str(e)[:150]
            out["slow_values"] = _dump_slow_values(c, db_s, live_s)
            out["total_vids_slow"] = len(out["slow_values"])
    except Exception as e:
        out["slow_error"] = str(e)[:150]
    try:
        c.Close()
    except Exception:
        pass
    if PROBE_RUNTIME:
        _attach_runtime_probe(out)
    print(json.dumps(out, ensure_ascii=False, default=str))


def main():
    now = datetime.datetime.utcnow()
    out = {"snapshot_utc": now.replace(microsecond=0).isoformat() + "Z",
           "window_min": WINDOW_MIN, "station": STATION_NAME, "tags": {}}
    # RAW mode / RAW DUMP: doc thang TagCompressed, khong dung WinCCOLEDBProvider.
    # DUMP_RAW chay duoc o MOI tram (ke ca tram provider nhu Dakrosa1) vi la
    # kenh phu doc lap; READ_MODE=raw chi anh huong duong snapshot chinh.
    if READ_MODE == "raw" or DUMP_RAW:
        try:
            if DUMP_RAW:
                del out["tags"]  # dump khong co tags decode; server tu decode
                out["dump_utc"] = out.pop("snapshot_utc")
                _main_rawdump(out)
            else:
                _main_raw(out)
        except Exception as e:
            out["error"] = "RAW loi: " + str(e)[:200]
            print(json.dumps(out, ensure_ascii=False, default=str))
        return
    # Ket noi: thu lan luot cac catalog
    conn = None
    last_err = ""
    resolve_errs = []
    all_dbs = []
    working_dsn = DSN
    try:
        cands, resolve_errs, working_dsn, all_dbs = resolve_catalogs()
    except Exception as e:
        cands = [CATALOG_FALLBACK] if CATALOG_FALLBACK else []
        last_err = str(e)[:160]
    connect_errs = []
    for c in cands:
        try:
            conn = connect(c, working_dsn)
            out["catalog"] = c
            break
        except Exception as e:
            msg = f"{c}: {str(e)[:120]}"
            connect_errs.append(msg)
            last_err = str(e)[:200]
    if conn is None:
        out["error"] = "Khong ket noi duoc OLE-DB provider. Kiem tra WinCC Runtime co ACTIVE khong."
        out["resolve_errs"] = resolve_errs[:8]     # loi tim catalog (DSN + provider)
        out["connect_errs"] = connect_errs[:6]     # loi mo WinCCOLEDBProvider tren catalog
        out["candidates"] = cands[:6]              # catalog thu ket noi
        out["dsn_used"] = working_dsn              # DSN cuoi cung dung
        out["all_dbs"] = all_dbs[:15]              # ten DB thuc te tren SQL instance
        out["project_like"] = PROJECT_LIKE         # pattern dang tim
        out["hostname"] = _socket.gethostname()
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
