#!/usr/bin/env python3
"""
Reverse geocoding via Nominatim (OpenStreetMap)
=================================================
Converts lat/lng coordinates to city + country using the free
Nominatim API. No API key required; rate limited to 1 req/sec.

Cache is stored in data/geo_cache.json. Coordinates are rounded
to 2 decimal places (~1 km) before lookup so nearby points share
the same cache entry.

Usage:
    from geocode import Geocoder
    gc = Geocoder("./data")
    result = gc.lookup(37.77, -122.42)
    # → {"city": "San Francisco", "country": "United States", "country_code": "US"}
"""

import json
import os
import time
import urllib.parse
import urllib.request

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
RATE_LIMIT     = 1.1    # seconds between requests
COORD_DECIMALS = 2      # round to ~1 km precision for cache key
USER_AGENT     = "musicbrain/1.0 (https://github.com/yourusername/musicbrain)"


def _round_coord(lat, lng):
    return (round(float(lat), COORD_DECIMALS), round(float(lng), COORD_DECIMALS))


def _extract_city(address):
    """
    Nominatim address dicts use different keys depending on the
    type of place. Walk through them in order of specificity.
    """
    for key in ("city", "town", "township", "village", "suburb",
                "municipality", "county", "state_district", "state"):
        val = address.get(key)
        if val:
            return val
    return ""


def _extract_country_code(address):
    code = address.get("country_code", "")
    return code.upper() if code else ""


def _extract_country(address):
    return address.get("country", "")


class Geocoder:
    def __init__(self, data_dir="./data"):
        self._cache_path  = os.path.join(data_dir, "geo_cache.json")
        self._cache       = self._load_cache()
        self._last_req    = 0.0

    def _load_cache(self):
        if os.path.exists(self._cache_path):
            with open(self._cache_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_cache(self):
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _cache_key(self, lat, lng):
        lat_r, lng_r = _round_coord(lat, lng)
        return f"{lat_r},{lng_r}"

    def lookup(self, lat, lng):
        """
        Return {"city": ..., "country": ..., "country_code": ...} for
        the given coordinates. Returns a dict with empty strings on failure.
        """
        key = self._cache_key(lat, lng)
        if key in self._cache:
            return self._cache[key]

        # Rate limiting
        elapsed = time.time() - self._last_req
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)

        lat_r, lng_r = _round_coord(lat, lng)
        params = urllib.parse.urlencode({
            "lat":    lat_r,
            "lon":    lng_r,
            "format": "jsonv2",
            "zoom":   10,          # city level
            "addressdetails": 1,
        })
        url = f"{NOMINATIM_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent":      USER_AGENT,
            "Accept-Language": "en",
        })

        result = {"city": "", "country": "", "country_code": ""}
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            address = data.get("address", {})
            result = {
                "city":         _extract_city(address),
                "country":      _extract_country(address),
                "country_code": _extract_country_code(address),
            }
        except Exception as e:
            print(f"    ⚠  Geocode error ({lat_r},{lng_r}): {e}")

        self._last_req = time.time()
        self._cache[key] = result
        return result

    def batch(self, coords, save_every=50, progress=True):
        """
        Geocode a list of (lat, lng) tuples. Returns a list of result dicts.
        Skips already-cached coordinates without API calls.
        Saves cache every `save_every` new lookups.
        """
        results = []
        new_lookups = 0
        total = len(coords)

        for i, (lat, lng) in enumerate(coords):
            key = self._cache_key(lat, lng)
            if key in self._cache:
                results.append(self._cache[key])
                continue

            result = self.lookup(lat, lng)
            results.append(result)
            new_lookups += 1

            if progress and new_lookups % 10 == 0:
                pct = (i + 1) / total * 100
                print(f"  Geocoded {new_lookups} new locations ({pct:.0f}% done) — "
                      f"last: {result.get('city', '?')}, {result.get('country_code', '?')}")

            if new_lookups % save_every == 0:
                self.save_cache()

        if new_lookups > 0:
            self.save_cache()
            if progress:
                print(f"  Geocoding complete: {new_lookups} new lookups, "
                      f"{len(self._cache)} total cached")

        return results
