#!/usr/bin/env python3
"""Run from hosting cron; write only errors/stale heartbeat to cron email."""
import base64
import datetime as dt
import json
from pathlib import Path
import sys
import urllib.request

API = "https://api.github.com/repos/Rkperdana/gempa-bumi-bmkg"
WORKFLOW = "/actions/workflows/dataloka-wp-cuaca.yml"


def request(path, token, body=None):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "User-Agent": "Dataloka-weather-cron", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, headers=headers, data=data)
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def main():
    token = (Path.home() / ".config/dataloka/actions-token").read_text().strip()
    runs = json.loads(request(WORKFLOW + "/runs?branch=main&per_page=10", token))
    if not any(r["status"] != "completed" and r["event"] != "pull_request"
               for r in runs["workflow_runs"]):
        request(WORKFLOW + "/dispatches", token, {"ref": "main", "inputs": {"mode": "live"}})
    doc = json.loads(request("/contents/data/dataloka-cuaca-state.json?ref=main", token))
    last = json.loads(base64.b64decode(doc["content"])).get("last_checked_at")
    if not last or dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last) > dt.timedelta(minutes=30):
        sys.exit(f"Dataloka: tidak ada pengambilan BMKG lengkap dalam 30 menit. Terakhir: {last}")


if __name__ == "__main__":
    main()
