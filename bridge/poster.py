"""POST snapshot len webhook. Thuan stdlib (urllib). Co retry.

Fan-out: luong CHINH la n8n ([webhook] url trong config.local.toml).
Ngoai ra gui them 1 ban sao sang dashboard DAKROSA portal (EXTRA_URL).
EXTRA_URL nam trong CODE (khong phai config) de doi duoc qua OTA ma khong
phai so vao may tram; ghi de bang [webhook] extra_url trong config neu can.
Loi ben dashboard KHONG duoc anh huong luong n8n (caller tu try/except).
"""
import json
import ssl
import time
import urllib.request
import urllib.error

EXTRA_URL = "https://dakrosa.svnagentic.site/api/dakrosa/wincc/webhook"


def _post_one(url, data, timeout=25, retries=3, context=None):
    last = ""
    for _ in range(retries):
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "wincc-bridge"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
                return r.status, r.read(500).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(500).decode("utf-8", "replace")
        except Exception as e:
            last = str(e)[:160]
            time.sleep(3)
    raise RuntimeError(f"POST that bai sau {retries} lan: {last}")


def post(cfg, payload):
    # Luong chinh (n8n): giu NGUYEN hanh vi cu (default SSL context, 3 retry).
    url = cfg["webhook"]["url"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _post_one(url, data)


def post_extra(cfg, payload):
    """POST ban sao sang dashboard. Best-effort, 1 lan, khong retry storm.
    Tra (status, body); tra (None, "") neu khong co URL phu / trung URL chinh.
    Win7/Py3.7 thieu Root CA -> dung CA bundle cua updater; van loi cert thi
    fallback khong verify (giong updater._urlopen, du lieu khong nhay cam)."""
    url = (cfg.get("webhook", {}).get("extra_url") or EXTRA_URL).strip()
    if not url or url == cfg["webhook"]["url"]:
        return None, ""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        from bridge.updater import _ssl_ctx
        ctx = _ssl_ctx()
    except Exception:
        ctx = None
    try:
        return _post_one(url, data, timeout=20, retries=1, context=ctx)
    except RuntimeError as e:
        if "CERTIFICATE" not in str(e).upper():
            raise
        unv = ssl.create_default_context()
        unv.check_hostname = False
        unv.verify_mode = ssl.CERT_NONE
        return _post_one(url, data, timeout=20, retries=1, context=unv)
