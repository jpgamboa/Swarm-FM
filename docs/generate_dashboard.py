#!/usr/bin/env python3
"""
Step 4: Generate Foursquare dashboard
=======================================
Reads data/scrobbles.json, data/checkins.json, and data/correlated.json,
computes the data needed for the Foursquare tab, and generates
data/dashboard.html from foursquare_template.html.

Usage:
    python musicbrain.py dashboard
Or standalone:
    python generate_dashboard.py
"""

import json
import os
import re
from collections import Counter
from datetime import datetime


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _parse_ts(ts):
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' to datetime."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def _normalize_trips(raw_trips):
    """
    Normalize correlate.py trip output into the shape the template expects.
    Filters out trips with zero scrobbles.
    """
    out = []
    for t in raw_trips:
        duration = t.get("duration_days", 0)
        plays = t.get("scrobble_count", 0)
        if plays == 0:
            continue
        top_artists = [{"artist": a["artist"], "count": a["plays"]}
                       for a in t.get("top_artists", [])]
        tracks = t.get("top_tracks", [])
        top_track = f"{tracks[0]['artist']} \u2014 {tracks[0]['track']}" if tracks else None
        ccs = [c["country_code"] for c in t.get("countries", [])]
        score = t.get("music_intensity", round(plays / max(duration, 1), 1))
        out.append({
            "start":        t["start"],
            "end":          t["end"],
            "days":         duration,
            "plays":        plays,
            "checkins":     t.get("checkins", 0),
            "destination":  t.get("destination", ""),
            "ccs":          ccs,
            "trip_type":    t.get("trip_type", "flight"),
            "music_score":  score,
            "top_artists":  top_artists,
            "top_track":    top_track,
        })
    return out


def run(data_dir="./data", template_path=None):
    if template_path is None:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "foursquare_template.html",
        )

    scrobbles_path  = os.path.join(data_dir, "scrobbles.json")
    checkins_path   = os.path.join(data_dir, "checkins.json")
    correlated_path = os.path.join(data_dir, "correlated.json")
    out_path        = os.path.join(data_dir, "dashboard.html")

    print("Loading data...")

    # ── Scrobbles ─────────────────────────────────────────────────────────────
    if not os.path.exists(scrobbles_path):
        print(f"  \u2717  scrobbles.json not found at {scrobbles_path}. Aborting.")
        return

    scrobbles = _load(scrobbles_path, [])
    checkins  = _load(checkins_path, [])
    print(f"  {len(scrobbles):,} scrobbles, {len(checkins):,} checkins")

    # ── plays_by_month ────────────────────────────────────────────────────────
    month_counter = Counter()
    dow_counter   = Counter()
    date_counter  = Counter()

    for s in scrobbles:
        ts = s.get("timestamp", "")
        try:
            dt = _parse_ts(ts)
            month_counter[dt.strftime("%Y-%m")] += 1
            dow_counter[dt.weekday()] += 1
            date_counter[dt.date().isoformat()] += 1
        except Exception:
            pass

    plays_by_month = [{"month": m, "count": c} for m, c in sorted(month_counter.items())]
    plays_by_dow   = [dow_counter.get(i, 0) for i in range(7)]
    plays_by_date  = dict(date_counter)
    total_plays    = len(scrobbles)

    # ── Foursquare basics from checkins.json ─────────────────────────────────
    fs_by_month = Counter()
    fs_by_dow   = Counter()
    fs_by_date  = Counter()
    fs_venues   = Counter()

    for c in checkins:
        ts  = c.get("timestamp", "")
        try:
            dt = _parse_ts(ts)
            fs_by_month[dt.strftime("%Y-%m")] += 1
            fs_by_dow[dt.weekday()]            += 1
            fs_by_date[dt.date().isoformat()]  += 1
        except Exception:
            pass
        fs_venues[c.get("venue_name", "Unknown")] += 1

    date_range = []
    if fs_by_date:
        sorted_dates = sorted(fs_by_date)
        date_range = [sorted_dates[0][:7], sorted_dates[-1][:7]]

    # Find first checkin timestamp for attributed_pct denominator
    first_checkin_ts = None
    if checkins:
        try:
            first_checkin_ts = _parse_ts(
                min(c["timestamp"] for c in checkins if c.get("timestamp"))
            )
        except Exception:
            pass

    plays_since_checkins = total_plays
    if first_checkin_ts:
        plays_since_checkins = sum(
            1 for s in scrobbles
            if s.get("timestamp") and s["timestamp"] >= first_checkin_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    # ── correlated.json ───────────────────────────────────────────────────────
    if not os.path.exists(correlated_path):
        print(f"  correlated.json not found — running correlate.run({data_dir!r})...")
        try:
            import correlate
            correlate.run(data_dir)
        except Exception as e:
            print(f"  \u2717  Could not run correlate.run(): {e}")
    correlated = _load(correlated_path, {})

    home_obj   = correlated.get("home", {})
    home_city  = home_obj.get("city", "")
    home_cc    = home_obj.get("country_code", "")
    home_label = f"{home_city}, {home_cc}" if home_city and home_cc else home_city or home_cc or "unknown"
    print(f"  Home: {home_label}")

    attributed_plays = correlated.get("attributed", 0)
    attributed_pct   = round(
        attributed_plays / max(plays_since_checkins, 1) * 100, 1
    ) if plays_since_checkins else 0.0

    raw_trips      = correlated.get("trips", [])
    normalized_trips = _normalize_trips(raw_trips)

    # ── Assemble foursquare block ─────────────────────────────────────────────
    foursquare = {
        "total":            len(checkins),
        "unique_venues":    len(fs_venues),
        "date_range":       date_range,
        "home":             home_label,
        "by_month":         [{"month": m, "count": c} for m, c in sorted(fs_by_month.items())],
        "by_dow":           [fs_by_dow.get(i, 0) for i in range(7)],
        "by_date":          dict(fs_by_date),
        "top_venues":       [{"name": n, "count": c} for n, c in fs_venues.most_common(30)],
        "venue_plays":      correlated.get("venue_plays", []),
        "by_category":      correlated.get("by_category", []),
        "by_city":          correlated.get("by_city", []),
        "by_country":       correlated.get("by_country", []),
        "attributed_plays": attributed_plays,
        "attributed_pct":   attributed_pct,
        "all_checkin_cities": correlated.get("all_checkin_cities", []),
        "travel_artists":   correlated.get("travel_artists", []),
        "trips":            normalized_trips,
    }

    data = {
        "total_plays":    total_plays,
        "plays_by_month": plays_by_month,
        "plays_by_dow":   plays_by_dow,
        "plays_by_date":  plays_by_date,
        "foursquare":     foursquare,
    }

    # ── Inject into template ──────────────────────────────────────────────────
    if not os.path.exists(template_path):
        print(f"  \u2717  Template not found: {template_path}")
        return

    with open(template_path, encoding="utf-8") as f:
        html = f.read()

    data_js  = f"const DASHBOARD_DATA = {json.dumps(data, ensure_ascii=False)};"
    html = re.sub(
        r"/\* DATA_INJECT_POINT \*/.*?/\* END_DATA_INJECT \*/",
        f"/* DATA_INJECT_POINT */\n{data_js}\n/* END_DATA_INJECT */",
        html,
        flags=re.DOTALL,
    )

    print(f"Writing dashboard \u2192 {out_path}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\u2713  Open {out_path} in a browser")


if __name__ == "__main__":
    try:
        import config
    except ImportError:
        print("Error: config.py not found.")
        raise SystemExit(1)
    run(config.DATA_DIR)
