"""POST snapshot len n8n webhook. Thuan stdlib (urllib). Co retry."""
import json
import time
import urllib.request
import urllib.error


def post(cfg, payload):
    url = cfg["webhook"]["url"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "wincc-bridge"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.status, r.read(500).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(500).decode("utf-8", "replace")
        except Exception as e:
            last = str(e)[:160]
            time.sleep(3)
    raise RuntimeError(f"POST that bai sau 3 lan: {last}")
