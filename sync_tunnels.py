#!/usr/bin/env python3
"""Daemon that watches PM2 tunnel logs and pushes any new lhr.life URLs to GitHub Pages (sereh-portal)."""

import datetime
import json
import os
import re
import subprocess
import time
from pathlib import Path

PORTAL_DIR = Path("/data/data/com.termux/files/home/sereh-portal")
TUNNELS_FILE = PORTAL_DIR / "tunnels.json"
TSE_LOG = Path("/data/data/com.termux/files/home/.pm2/logs/tunnel-tse-out.log")
CRYPTO_LOG = Path("/data/data/com.termux/files/home/.pm2/logs/tunnel-crypto-out.log")
URL_RE = re.compile(r"https://[a-z0-9]+\.lhr\.life")


def latest_url(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")[-16000:]
        matches = URL_RE.findall(text)
        return matches[-1] if matches else ""
    except Exception:
        return ""


def main() -> None:
    last_pushed = ("", "")
    while True:
        tse = latest_url(TSE_LOG)
        crypto = latest_url(CRYPTO_LOG)
        if tse and crypto and (tse, crypto) != last_pushed:
            payload = {
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "tse_url": tse,
                "crypto_url": crypto,
            }
            try:
                TUNNELS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                subprocess.run(["git", "add", "tunnels.json", "index.html"], cwd=PORTAL_DIR, check=False)
                subprocess.run(
                    ["git", "commit", "-m", f"chore: auto-sync tunnel URLs ({payload['updated_at']})"],
                    cwd=PORTAL_DIR,
                    check=False,
                    capture_output=True,
                )
                res = subprocess.run(["git", "push", "origin", "master"], cwd=PORTAL_DIR, capture_output=True)
                if res.returncode == 0:
                    last_pushed = (tse, crypto)
                    print(f"[portal-sync] pushed new URLs: TSE={tse} CRYPTO={crypto}", flush=True)
            except Exception as err:
                print(f"[portal-sync] error: {err}", flush=True)
        time.sleep(15)


if __name__ == "__main__":
    main()
