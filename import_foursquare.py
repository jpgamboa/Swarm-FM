#!/usr/bin/env python3
"""
Step 2: Import Foursquare checkins
====================================
Parses all checkins*.json files from a Foursquare data export, reverse-
geocodes each checkin's coordinates to city + country via Nominatim
(OpenStreetMap, free, no API key required), and saves a clean sorted
checkin list to data/checkins.json.

Each checkin includes:
  - timestamp      ISO 8601 UTC
  - local_time     ISO 8601 with UTC offset (using Foursquare's timeZoneOffset)
  - tz_offset_min  minutes offset from UTC (e.g. -360 = UTC-6)
  - venue_name     venue name string
  - lat / lng      coordinates
  - city           city name (from reverse geocoding)
  - country        country name
  - country_code   ISO 3166-1 alpha-2 (e.g. "US", "GB")

Geocoding is cached in data/geo_cache.json — each unique location is
only looked up once. At 1 req/sec, geocoding ~1,400 unique locations
takes about 25 minutes on first run; subsequent runs are instant.

Usage (via musicbrain.py):
    python musicbrain.py foursquare

Or standalone:
    python import_foursquare.py
"""

import glob
import json
import os
from datetime import datetime, timezone, timedelta


def _parse_foursquare_ts(created_at):
    """
    Parse Foursquare's createdAt field (e.g. '2024-01-15 20:30:00.000000')
    into a UTC ISO 8601 string. Foursquare stores times in UTC.
    """
    # Strip microseconds if present
    ts = created_at.split(".")[0]
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _local_iso(utc_ts, tz_offset_min):
    """Return ISO 8601 timestamp with UTC offset (e.g. '2024-01-15T14:30:00-06:00')."""
    try:
        dt = datetime.strptime(utc_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        offset = timedelta(minutes=tz_offset_min)
        local  = dt + offset
        sign   = "+" if tz_offset_min >= 0 else "-"
        h, m   = divmod(abs(tz_offset_min), 60)
        return local.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{h:02d}:{m:02d}"
    except Exception:
        return None


def parse(export_dir, data_dir="./data"):
    os.makedirs(data_dir, exist_ok=True)

    pattern = os.path.join(export_dir, "checkins*.json")
    files   = sorted(glob.glob(pattern))
    if not files:
        print(f"  ✗  No checkins*.json files found in: {export_dir}")
        return []

    checkins = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", []) if isinstance(data, dict) else data
        for item in items:
            ts = _parse_foursquare_ts(item.get("createdAt", ""))
            if not ts:
                continue

            tz_min = item.get("timeZoneOffset", 0)
            venue  = item.get("venue", {})
            checkins.append({
                "timestamp":     ts,
                "local_time":    _local_iso(ts, tz_min),
                "tz_offset_min": tz_min,
                "venue_name":    venue.get("name", ""),
                "venue_id":      venue.get("id", ""),
                "lat":           item.get("lat"),
                "lng":           item.get("lng"),
                "city":          "",
                "country":       "",
                "country_code":  "",
            })

    checkins.sort(key=lambda c: c["timestamp"])

    # Reverse-geocode all coordinates
    coords_with_latlon = [(c, c["lat"], c["lng"]) for c in checkins if c.get("lat") and c.get("lng")]
    if coords_with_latlon:
        print(f"Reverse geocoding {len(coords_with_latlon):,} checkins "
              f"(~{len(set((round(lat,2),round(lng,2)) for _,lat,lng in coords_with_latlon)):,} "
              f"unique locations)...")
        from geocode import Geocoder
        gc = Geocoder(data_dir)
        unique_coords = list(set((round(float(lat), 2), round(float(lng), 2))
                                 for _, lat, lng in coords_with_latlon))
        gc.batch(unique_coords, progress=True)  # warm the cache

        for checkin, lat, lng in coords_with_latlon:
            geo = gc.lookup(lat, lng)
            checkin["city"]         = geo.get("city", "")
            checkin["country"]      = geo.get("country", "")
            checkin["country_code"] = geo.get("country_code", "")

    out_path = os.path.join(data_dir, "checkins.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(checkins, f, ensure_ascii=False, indent=2)

    # Summary
    geocoded = sum(1 for c in checkins if c.get("country_code"))
    countries = len(set(c["country_code"] for c in checkins if c.get("country_code")))
    print(f"✓  Imported {len(checkins):,} checkins, "
          f"{geocoded:,} geocoded across {countries} countries → {out_path}")
    return checkins


if __name__ == "__main__":
    try:
        import config
    except ImportError:
        print("Error: config.py not found. Copy config.py.example → config.py.")
        raise SystemExit(1)

    if not config.FOURSQUARE_EXPORT_DIR:
        print("FOURSQUARE_EXPORT_DIR not set in config.py — skipping.")
    else:
        parse(config.FOURSQUARE_EXPORT_DIR, config.DATA_DIR)
