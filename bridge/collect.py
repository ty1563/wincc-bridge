"""Lay snapshot tu may WinCC: ssh -> py32 OLE-DB reader -> JSON. Co retry (APIPA flaky)."""
import json
import time
import subprocess

from bridge import detect


def collect(cfg):
    w = cfg["winccbox"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        ssh += ["-i", w["key"]]
    if w.get("target"):
        target = w["target"]
    else:
        host, changed = detect.resolve_host(cfg)  # chiu duoc APIPA doi IP
        if changed:
            print(f"[detect] box IP doi -> dung {host}", flush=True)
        target = f'{w["user"]}@{host}'
    cmd = ssh + [target, w["python32"], w["reader"]]
    last = ""
    for attempt in range(5):  # link APIPA chap chon -> retry nhieu
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=150,
                               encoding="utf-8", errors="replace")
            if p.returncode == 0 and p.stdout.strip():
                try:
                    return json.loads(p.stdout)
                except json.JSONDecodeError:
                    last = "JSON loi: " + p.stdout[:200]
            else:
                last = (p.stderr or p.stdout or "rong")[:200]
        except subprocess.TimeoutExpired:
            last = "ssh timeout"
        time.sleep(3)
    raise RuntimeError(f"collect that bai sau 3 lan: {last}")
