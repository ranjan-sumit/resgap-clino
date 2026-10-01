"""One-off E2E helper: poll /api/jobs for the 'WSL E2E Test' job and append progress
to /app/e2e_status.txt (repo-root, readable from the host). Exits 0 on success,
1 on failure, 2 on timeout. Not part of the app -- safe to delete."""
import json
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("/app/e2e_status.txt")
DEADLINE = time.time() + 60 * 60


def log(msg: str) -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def fetch_jobs():
    with urllib.request.urlopen("http://localhost:8000/api/jobs", timeout=15) as r:
        return json.load(r)


job = None
while time.time() < DEADLINE:
    try:
        jobs = fetch_jobs()
        matches = [j for j in jobs if j.get("name") == "WSL E2E Test"]
        if matches:
            job = matches[-1]
            log(f"{time.strftime('%H:%M:%S')} state={job['state']} pct={job.get('percent')} msg={job.get('message')}")
            if job["state"] in ("succeeded", "failed", "error"):
                log("FINAL " + json.dumps(job))
                sys.exit(0 if job["state"] == "succeeded" else 1)
    except Exception as exc:  # keep polling through transient API hiccups
        log(f"poll_error: {exc}")
    time.sleep(20)

log("TIMEOUT after 60m")
sys.exit(2)
