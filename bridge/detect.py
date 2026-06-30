"""Tu dong do IP may WinCC (box) - chiu duoc APIPA doi IP.
Neu host trong config khong toi duoc, quet arp 169.254.x.x tim host co port 22 + ssh ok.
"""
import re
import socket
import subprocess


def port_open(host, port=22, timeout=2.5):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _arp_169():
    hosts = set()
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10).stdout or ""
        for m in re.finditer(r"169\.254\.\d+\.\d+", out):
            hosts.add(m.group(0))
    except Exception:
        pass
    return hosts


def _ssh_echo(cfg, host):
    w = cfg["winccbox"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
           "-o", "StrictHostKeyChecking=accept-new"]
    if w.get("key"):
        ssh += ["-i", w["key"]]
    user = w.get("user", "dell")
    try:
        p = subprocess.run(ssh + [f"{user}@{host}", "echo wbok"],
                           capture_output=True, text=True, timeout=20)
        return "wbok" in (p.stdout or "")
    except Exception:
        return False


def resolve_host(cfg):
    """Tra ve (host, changed). host = IP dung de ket noi; changed=True neu khac config."""
    w = cfg["winccbox"]
    cur = w.get("host")
    if cur and port_open(cur):
        return cur, False
    for h in sorted(_arp_169()):
        if h == cur:
            continue
        if port_open(h) and _ssh_echo(cfg, h):
            return h, True
    return cur, False  # khong tim duoc -> giu config (se loi voi thong bao ro)
