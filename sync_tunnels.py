#!/usr/bin/env python3
"""Daemon that watches PM2 tunnel logs, verifies live /api/health,
self-heals hung tunnels via PM2, and pushes live URLs to a GitHub Gist
(zero GitHub Pages rebuilds, zero email spam).
"""

import datetime
import json
import re
import subprocess
import time
from pathlib import Path
import httpx

PORTAL_DIR = Path("/data/data/com.termux/files/home/sereh-portal")
TUNNELS_FILE = PORTAL_DIR / "tunnels.json"
GIST_ID = "9161466418d74799402ec422d1811153"

TSE_LOG = Path("/data/data/com.termux/files/home/.pm2/logs/tunnel-tse-out.log")
CRYPTO_LOG = Path("/data/data/com.termux/files/home/.pm2/logs/tunnel-crypto-out.log")
URL_RE = re.compile(r"https://[a-z0-9]+\.lhr\.life")


def get_gh_token() -> str:
    try:
        res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    hosts = Path.home() / ".config" / "gh" / "hosts.yml"
    if hosts.exists():
        m = re.search(r"oauth_token:\s*(\S+)", hosts.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1).strip()
    return ""


def latest_url(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")[-16000:]
        matches = URL_RE.findall(text)
        return matches[-1] if matches else ""
    except Exception:
        return ""


def check_health(url: str) -> bool:
    if not url:
        return False
    try:
        r = httpx.get(f"{url}/api/health", timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            return data.get("status") == "ok"
    except Exception:
        pass
    return False


def local_server_up(port: int) -> bool:
    return check_health(f"http://127.0.0.1:{port}")


def push_gist(payload: dict) -> bool:
    token = get_gh_token()
    if not token:
        print("[portal-sync] missing GitHub token", flush=True)
        return False
    body = {
        "description": "Sereh Portal live tunnel URLs (auto-synced)",
        "files": {
            "tunnels.json": {
                "content": json.dumps(payload, indent=2, ensure_ascii=False)
            }
        },
    }
    try:
        r = httpx.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "sereh-portal-sync",
            },
            json=body,
            timeout=10.0,
        )
        if r.status_code == 200:
            return True
        print(f"[portal-sync] gist update HTTP {r.status_code}: {r.text[:150]}", flush=True)
    except Exception as err:
        print(f"[portal-sync] gist update error: {err}", flush=True)
    return False


def restart_pm2(name: str) -> None:
    try:
        subprocess.run(["pm2", "restart", name], capture_output=True, timeout=15)
        print(f"[portal-sync] restarted hung tunnel: {name}", flush=True)
    except Exception as err:
        print(f"[portal-sync] failed to restart {name}: {err}", flush=True)


def main() -> None:
    last_pushed = ("", "")
    fail_streak = {"tse": 0, "crypto": 0}
    last_health_check = 0.0

    while True:
        tse = latest_url(TSE_LOG)
        crypto = latest_url(CRYPTO_LOG)
        now = time.time()

        # Verify health when URL changes or every 60s
        urls_changed = (tse, crypto) != last_pushed
        periodic_check = (now - last_health_check) >= 60.0

        if urls_changed or periodic_check:
            last_health_check = now
            tse_ok = check_health(tse)
            crypto_ok = check_health(crypto)

            if tse and not tse_ok and local_server_up(8765):
                fail_streak["tse"] += 1
                if fail_streak["tse"] >= 3:
                    restart_pm2("tunnel-tse")
                    fail_streak["tse"] = 0
            else:
                fail_streak["tse"] = 0

            if crypto and not crypto_ok and local_server_up(8766):
                fail_streak["crypto"] += 1
                if fail_streak["crypto"] >= 3:
                    restart_pm2("tunnel-crypto")
                    fail_streak["crypto"] = 0
            else:
                fail_streak["crypto"] = 0

            live_tse = tse if tse_ok else ""
            live_crypto = crypto if crypto_ok else ""

            if (live_tse or live_crypto) and (live_tse, live_crypto) != last_pushed:
                payload = {
                    "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "tse_url": live_tse,
                    "crypto_url": live_crypto,
                }
                TUNNELS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                if push_gist(payload):
                    last_pushed = (live_tse, live_crypto)
                    print(
                        f"[portal-sync] synced Gist: TSE={live_tse or 'DOWN'} CRYPTO={live_crypto or 'DOWN'}",
                        flush=True,
                    )

        time.sleep(15)


if __name__ == "__main__":
    main()
