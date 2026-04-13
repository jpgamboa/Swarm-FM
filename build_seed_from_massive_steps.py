#!/usr/bin/env python3
"""
Build geo_seed entries from Massive-STEPS Foursquare check-in dataset.
https://github.com/cruiseresearchgroup/Massive-STEPS

Downloads venue data from HuggingFace (tabular config) for 15 cities,
extracts unique coordinate→city mappings, rounds to our cache grid,
and merges into data/geo_cache.json + docs/geo_seed.json.

No external packages needed — uses HuggingFace rows API (JSON).
"""

import json
import os
import time
import urllib.request
import urllib.parse

CITIES = [
    "Bandung", "Beijing", "Istanbul", "Jakarta", "Kuwait-City",
    "Melbourne", "Moscow", "New-York", "Palembang", "Petaling-Jaya",
    "Sao-Paulo", "Shanghai", "Sydney", "Tangerang", "Tokyo",
]

# Country code → full country name (for the cities in this dataset)
COUNTRY_NAMES = {
    "ID": "Indonesia", "CN": "China", "TR": "Turkey", "KW": "Kuwait",
    "AU": "Australia", "RU": "Russia", "US": "United States",
    "BR": "Brazil", "JP": "Japan", "MY": "Malaysia",
}

SPLITS = ["train", "validation", "test"]
ROWS_API = "https://datasets-server.huggingface.co/rows"
PAGE_SIZE = 100
COORD_DECIMALS_WEB = 1   # web version rounds to 0.1 degree
COORD_DECIMALS_CLI = 2   # CLI version rounds to 0.01 degree

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
CACHE_PATH = os.path.join(DATA_DIR, "geo_cache.json")
SEED_PATH = os.path.join(DOCS_DIR, "geo_seed.json")


def fetch_rows(city, split, offset=0, length=PAGE_SIZE, max_retries=5):
    """Fetch rows from HuggingFace datasets-server API with retry on 429."""
    params = urllib.parse.urlencode({
        "dataset": f"CRUISEResearchGroup/Massive-STEPS-{city}",
        "config": "tabular",
        "split": split,
        "offset": offset,
        "length": length,
    })
    url = f"{ROWS_API}?{params}"
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "checkins-fm-seed-builder/1.0",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2, 4, 8, 16, 32s
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def extract_venues(city):
    """Extract unique venues (by venue_id) from all splits of a city dataset."""
    venues = {}  # venue_id → {lat, lng, city, country_code}

    for split in SPLITS:
        offset = 0
        while True:
            try:
                data = fetch_rows(city, split, offset, PAGE_SIZE)
            except Exception as e:
                print(f"    Warning: {city}/{split} offset={offset}: {e}")
                break

            rows = data.get("rows", [])
            if not rows:
                break

            for item in rows:
                row = item.get("row", {})
                vid = row.get("venue_id")
                lat = row.get("latitude")
                lng = row.get("longitude")
                vcity = row.get("venue_city", "")
                vcc = row.get("venue_country", "")

                if vid and lat is not None and lng is not None and vcity:
                    if vid not in venues:
                        venues[vid] = {
                            "lat": float(lat),
                            "lng": float(lng),
                            "city": vcity,
                            "country_code": vcc.upper() if vcc else "",
                        }

            offset += PAGE_SIZE
            num_rows_total = data.get("num_rows_total", 0)
            if offset >= num_rows_total:
                break

            time.sleep(0.5)  # be polite to the API

    return venues


def build_cache_entries(venues, decimals):
    """Convert venues to cache entries at the given coordinate precision."""
    entries = {}
    for v in venues.values():
        lat_r = round(v["lat"], decimals)
        lng_r = round(v["lng"], decimals)
        key = f"{lat_r},{lng_r}"
        if key not in entries:
            country = COUNTRY_NAMES.get(v["country_code"], "")
            entries[key] = {
                "city": v["city"],
                "country": country,
                "country_code": v["country_code"],
            }
    return entries


def main():
    # Load existing caches
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            cli_cache = json.load(f)
    else:
        cli_cache = {}

    if os.path.exists(SEED_PATH):
        with open(SEED_PATH, encoding="utf-8") as f:
            web_cache = json.load(f)
    else:
        web_cache = {}

    print(f"Existing CLI cache: {len(cli_cache)} entries")
    print(f"Existing web seed:  {len(web_cache)} entries")

    all_venues = {}
    for city in CITIES:
        print(f"\nFetching {city}...")
        venues = extract_venues(city)
        print(f"  {len(venues)} unique venues")
        all_venues.update(venues)

    print(f"\nTotal unique venues across all cities: {len(all_venues)}")

    # Build entries at both precisions
    cli_entries = build_cache_entries(all_venues, COORD_DECIMALS_CLI)
    web_entries = build_cache_entries(all_venues, COORD_DECIMALS_WEB)

    # Count new entries
    new_cli = sum(1 for k in cli_entries if k not in cli_cache)
    new_web = sum(1 for k in web_entries if k not in web_cache)

    print(f"\nNew CLI cache entries (0.01 deg): {new_cli}")
    print(f"New web seed entries (0.1 deg):   {new_web}")

    # Merge — don't overwrite existing entries (our manual corrections take priority)
    for k, v in cli_entries.items():
        if k not in cli_cache:
            cli_cache[k] = v
    for k, v in web_entries.items():
        if k not in web_cache:
            web_cache[k] = v

    # Save
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cli_cache, f, ensure_ascii=False, indent=2)
    with open(SEED_PATH, "w", encoding="utf-8") as f:
        json.dump(web_cache, f, ensure_ascii=False, indent=2)

    print(f"\nUpdated CLI cache: {len(cli_cache)} entries → {CACHE_PATH}")
    print(f"Updated web seed:  {len(web_cache)} entries → {SEED_PATH}")


if __name__ == "__main__":
    main()
