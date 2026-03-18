#!/usr/bin/env python3
"""
Import Last.fm scrobble data from a local CSV export
=====================================================
Reads a CSV exported from https://benjaminbenben.com/lastfm-to-csv/
and saves the result as data/scrobbles.json.

Expected columns (benjaminbenben format):
    artist, album, name, date

Where `date` is formatted as "15 Mar 2025, 14:30" (UTC).

Also accepts the official Last.fm GDPR export format:
    uts, utc_time, artist, artist_mbid, album, album_mbid, track, track_mbid

Usage:
    from import_lastfm import parse
    parse("/path/to/scrobbles.csv", "./data")

Or standalone:
    python import_lastfm.py
"""

import csv
import json
import os
from datetime import datetime, timezone


# Date formats used by the benjaminbenben exporter
_DATE_FORMATS = [
    "%d %b %Y, %H:%M",   # "15 Mar 2025, 14:30"
    "%d %b %Y %H:%M",    # "15 Mar 2025 14:30"
    "%Y-%m-%dT%H:%M:%SZ", # ISO fallback
    "%Y-%m-%d %H:%M:%S",
]


def _parse_date(date_str):
    """Parse a Last.fm date string to a UTC ISO 8601 timestamp."""
    date_str = date_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def _parse_row(row):
    """
    Parse one CSV row. Returns {timestamp, artist, track, album} or None.

    Supports:
      - benjaminbenben format: artist, album, name, date
      - Official Last.fm GDPR format: uts, utc_time, artist, ..., track, ...
    """
    # ── benjaminbenben format ────────────────────────────────────────────────
    if "name" in row:
        date_raw = (row.get("date") or "").strip()
        if not date_raw:
            return None  # now-playing marker
        timestamp = _parse_date(date_raw)
        if not timestamp:
            return None
        artist = (row.get("artist") or "").strip()
        track  = (row.get("name") or "").strip()
        album  = (row.get("album") or "").strip()

    # ── ISO timestamp format (e.g. "2025-03-15T14:30:00Z") ───────────────────
    elif "timestamp" in row:
        ts_raw = (row.get("timestamp") or "").strip()
        if not ts_raw:
            return None
        timestamp = ts_raw if ts_raw.endswith("Z") else ts_raw + "Z"
        artist = (row.get("artist") or "").strip()
        track  = (row.get("track") or "").strip()
        album  = (row.get("album") or "").strip()

    # ── Official Last.fm GDPR export ─────────────────────────────────────────
    elif "uts" in row:
        uts_raw = (row.get("uts") or "").strip()
        if not uts_raw:
            return None  # now-playing marker
        try:
            dt = datetime.fromtimestamp(int(uts_raw), tz=timezone.utc)
            timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError, OverflowError):
            return None
        artist = (row.get("artist") or "").strip()
        track  = (row.get("track") or "").strip()
        album  = (row.get("album") or "").strip()

    else:
        return None

    if not artist or not track:
        return None

    return {"timestamp": timestamp, "artist": artist, "track": track, "album": album}


def parse(export_file, data_dir="./data"):
    """
    Read a Last.fm CSV export and write data/scrobbles.json.
    """
    out_path = os.path.join(data_dir, "scrobbles.json")

    if not os.path.exists(export_file):
        print(f"  ✗  Last.fm export not found: {export_file}")
        return

    print(f"Reading Last.fm export: {export_file}")

    scrobbles = []
    skipped = 0

    with open(export_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                record = _parse_row(row)
                if record:
                    scrobbles.append(record)
                else:
                    skipped += 1
            except Exception:
                skipped += 1

    if not scrobbles:
        print(f"  ✗  No valid scrobbles found in {export_file}")
        print(f"     Expected columns: artist, album, name, date")
        print(f"     Export your history at: https://benjaminbenben.com/lastfm-to-csv/")
        return

    scrobbles.sort(key=lambda s: s["timestamp"])

    os.makedirs(data_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scrobbles, f, ensure_ascii=False, indent=2)

    print(f"  {len(scrobbles):,} scrobbles imported"
          + (f" ({skipped} skipped)" if skipped else ""))
    print(f"  Date range: {scrobbles[0]['timestamp'][:10]} → {scrobbles[-1]['timestamp'][:10]}")
    print(f"✓  Saved → {out_path}")


if __name__ == "__main__":
    try:
        import config
    except ImportError:
        print("Error: config.py not found.")
        raise SystemExit(1)
    parse(config.LASTFM_EXPORT_FILE, config.DATA_DIR)
