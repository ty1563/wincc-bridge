import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bridge import config, collect, poster

cfg = config.load()
print("Collecting tu winccbox...")
snap = collect.collect(cfg)
print("  -> tags:", len(snap.get("tags", {})), "| catalog:", snap.get("catalog"))
payload = {"source": "wincc-bridge", "test": True}
payload.update(snap)
print("POST len n8n...")
status, body = poster.post(cfg, payload)
print("  -> HTTP", status)
print("  -> response:", body[:300])
