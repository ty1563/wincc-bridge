"""OTA: git pull tu GitHub private (token), neu code moi thi dong bo script box-side."""
import os
import subprocess

from bridge.config import REPO_ROOT


def _git(*args, timeout=90):
    return subprocess.run(["git", "-C", REPO_ROOT, *args],
                          capture_output=True, text=True, timeout=timeout)


def _head():
    p = _git("rev-parse", "HEAD")
    return p.stdout.strip()


def check_and_update(cfg):
    ota = cfg.get("ota", {})
    if not ota.get("enabled"):
        return False
    branch = ota.get("branch", "main")
    before = _head()
    _git("fetch", "--quiet", "origin", branch)
    _git("reset", "--hard", "--quiet", f"origin/{branch}")
    after = _head()
    if after and after != before:
        try:
            _sync_box(cfg)
        except Exception:
            pass
        return True
    return False


def _sync_box(cfg):
    """Day script box-side moi sang may WinCC (box khong co internet)."""
    w = cfg["winccbox"]
    reader = w["reader"].replace("\\", "/")
    box_dir = reader.rsplit("/", 1)[0]
    target = w.get("target") or f'{w["user"]}@{w["host"]}'
    scp = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12"]
    if w.get("key"):
        scp += ["-i", w["key"]]
    local_box = os.path.join(REPO_ROOT, "box")
    for fn in os.listdir(local_box):
        if fn.endswith(".py"):
            src = os.path.join(local_box, fn)
            subprocess.run(scp + [src, f"{target}:{box_dir}/{fn}"],
                           capture_output=True, text=True, timeout=60)
