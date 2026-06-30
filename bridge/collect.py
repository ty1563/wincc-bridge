"""Lay snapshot tu may WinCC: ssh -> py32 OLE-DB reader -> JSON. Co retry (APIPA flaky)."""
import json
import time
import subprocess


def collect(cfg):
    w = cfg["winccbox"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        ssh += ["-i", w["key"]]
    target = w.get("target") or f'{w["user"]}@{w["host"]}'
    cmd = ssh + [target, w["python32"], w["reader"]]
    last = ""
    for attempt in range(3):
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
