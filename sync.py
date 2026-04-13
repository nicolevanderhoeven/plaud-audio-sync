#!/usr/bin/env python3
"""Daily Plaud audio sync.

Lists files via the Plaud API, downloads any audio not already recorded in
``state.json`` into ``./audio/``. Safe to run repeatedly (idempotent).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_DOMAIN = "https://api.plaud.ai"
SCRIPT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = SCRIPT_DIR / "audio"
STATE_FILE = SCRIPT_DIR / "state.json"
ENV_FILE = SCRIPT_DIR / ".env"

MAX_ATTEMPTS = 5
BASE_BACKOFF = 1.0  # seconds; doubles each retry with jitter
MAX_BACKOFF = 60.0
# HTTP statuses that are worth retrying (rate-limit + transient server errors).
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _sleep_for_retry(attempt: int, retry_after: str | None) -> None:
    """Sleep before the next retry. Honors Retry-After if the server sent one."""
    if retry_after:
        try:
            delay = float(retry_after)
            time.sleep(min(delay, MAX_BACKOFF))
            return
        except ValueError:
            pass  # fall through to exponential backoff
    delay = min(BASE_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
    delay += random.uniform(0, delay * 0.25)  # jitter
    time.sleep(delay)


def _open_with_retry(req: urllib.request.Request, timeout: int, label: str):
    """urlopen wrapper with exponential backoff on 429/5xx and transient network errors."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            print(
                f"  retry {attempt}/{MAX_ATTEMPTS - 1} for {label}: HTTP {exc.code}",
                file=sys.stderr,
            )
            _sleep_for_retry(attempt, retry_after)
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                raise
            print(
                f"  retry {attempt}/{MAX_ATTEMPTS - 1} for {label}: {exc.reason}",
                file=sys.stderr,
            )
            _sleep_for_retry(attempt, None)
    # Defensive: loop above always returns or raises.
    assert last_exc is not None
    raise last_exc


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_get_json(url: str, token: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    label = url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1].split("?")[0]
    with _open_with_retry(req, timeout, label) as resp:
        return json.loads(resp.read())


def list_files(token: str) -> list[dict]:
    data = api_get_json(f"{API_DOMAIN}/file/simple/web", token)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("payload", "data_file_list", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    raise RuntimeError(f"Unexpected list response shape: {str(data)[:200]}")


def get_file_detail(token: str, file_id: str) -> dict:
    data = api_get_json(f"{API_DOMAIN}/file/detail/{urllib.parse.quote(file_id)}", token)
    if isinstance(data, dict):
        for key in ("data", "payload"):
            val = data.get(key)
            if isinstance(val, dict):
                return val
        return data
    return {}


def get_temp_url(token: str, file_id: str) -> str:
    data = api_get_json(f"{API_DOMAIN}/file/temp-url/{urllib.parse.quote(file_id)}", token)
    url = data.get("temp_url") if isinstance(data, dict) else None
    if not url:
        raise RuntimeError(f"No temp_url in response for {file_id}: {str(data)[:200]}")
    return url


def sanitize(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "_", name).strip().strip(".")
    return (cleaned[:120] or "untitled")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print(f"WARN: {STATE_FILE} is corrupt; starting fresh.", file=sys.stderr)
    return {"downloaded": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)


def download(url: str, dest: Path) -> int:
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    req = urllib.request.Request(url)
    with _open_with_retry(req, 300, f"download {dest.name}") as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)
    tmp.replace(dest)
    return total


def format_date(start_time_ms: int | None) -> str:
    if not start_time_ms:
        return "unknown"
    try:
        return datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Plaud audio files.")
    parser.add_argument("--dry-run", action="store_true", help="List pending downloads without fetching.")
    parser.add_argument("--force", action="store_true", help="Re-download files already in state.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N downloads (0 = no limit).")
    args = parser.parse_args()

    load_env(ENV_FILE)
    token = os.environ.get("PLAUD_TOKEN", "").strip()
    if not token:
        print("ERROR: PLAUD_TOKEN not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2

    AUDIO_DIR.mkdir(exist_ok=True)
    state = load_state()
    downloaded: dict = state.setdefault("downloaded", {})

    try:
        files = list_files(token)
    except urllib.error.HTTPError as exc:
        print(f"ERROR listing files: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return 3

    non_trash = [f for f in files if isinstance(f, dict) and not f.get("is_trash")]
    pending = [
        f for f in non_trash
        if args.force or (f.get("id") or f.get("file_id")) not in downloaded
    ]
    print(f"Found {len(non_trash)} non-trash file(s); {len(pending)} new.")

    errors = 0
    done = 0
    for entry in pending:
        if args.limit and done >= args.limit:
            break

        file_id = entry.get("id") or entry.get("file_id")
        if not file_id:
            continue

        try:
            detail = get_file_detail(token, file_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[detail-fail] {file_id}: {exc}", file=sys.stderr)
            errors += 1
            continue

        file_name = detail.get("file_name") or entry.get("file_name") or file_id
        start_ms = detail.get("start_time") or entry.get("start_time")
        dest = AUDIO_DIR / f"{format_date(start_ms)}_{sanitize(str(file_name))}_{file_id}.mp3"

        if args.dry_run:
            print(f"[dry] {file_id} -> {dest.name}")
            continue

        if dest.exists() and not args.force:
            downloaded[file_id] = {
                "path": dest.name,
                "file_name": file_name,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "note": "already on disk",
            }
            save_state(state)
            print(f"[skip] {dest.name}")
            done += 1
            continue

        try:
            url = get_temp_url(token, file_id)
            size = download(url, dest)
        except Exception as exc:  # noqa: BLE001
            print(f"[download-fail] {file_id}: {exc}", file=sys.stderr)
            errors += 1
            continue

        downloaded[file_id] = {
            "path": dest.name,
            "file_name": file_name,
            "size": size,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        save_state(state)
        print(f"[ok]   {dest.name}  ({size:,} bytes)")
        done += 1

    print(f"Done. Downloaded/skipped: {done}. Errors: {errors}.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
