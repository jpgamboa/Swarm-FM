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
import re
import time
import urllib.parse
import urllib.request


def _is_airport_venue(name):
    """Check if a venue name looks like an airport."""
    nl = name.lower()
    return ("airport" in nl or "aeropuerto" in nl or "aéroport" in nl
            or (re.search(r'\b[A-Z]{3}\b', name) is not None
                and ("terminal" in nl or "gate" in nl)))

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL  = "https://nominatim.openstreetmap.org/search"
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

    def _nominatim_reverse(self, lat_r, lng_r):
        """Raw Nominatim reverse geocode (no cache, no rate-limit guard).
        If the result is a village/town/suburb, attempts to find the parent
        city in the same county (e.g. West Lake Hills → Austin)."""
        params = urllib.parse.urlencode({
            "lat":    lat_r,
            "lon":    lng_r,
            "format": "jsonv2",
            "zoom":   10,
            "addressdetails": 1,
        })
        url = f"{NOMINATIM_REVERSE_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent":      USER_AGENT,
            "Accept-Language": "en",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        address = data.get("address", {})
        city = _extract_city(address)
        result = {
            "city":         city,
            "country":      _extract_country(address),
            "country_code": _extract_country_code(address),
        }

        # If result is a village/town/suburb/district (not a city), try
        # broader zoom to get the parent city (e.g. Liuli → Shanghai).
        if not address.get("city"):
            self._rate_wait()
            try:
                broad_params = urllib.parse.urlencode({
                    "lat": lat_r, "lon": lng_r,
                    "format": "jsonv2", "zoom": 5, "addressdetails": 1,
                })
                broad_url = f"{NOMINATIM_REVERSE_URL}?{broad_params}"
                broad_req = urllib.request.Request(broad_url, headers={
                    "User-Agent": USER_AGENT, "Accept-Language": "en",
                })
                with urllib.request.urlopen(broad_req, timeout=10) as resp:
                    broad_data = json.loads(resp.read().decode("utf-8"))
                self._last_req = time.time()
                broad_addr = broad_data.get("address", {})
                if broad_addr.get("city"):
                    result["city"] = broad_addr["city"]
                elif address.get("county") and address.get("state"):
                    parent = self._find_parent_city(
                        address["county"], address["state"],
                        address.get("country", ""), lat_r, lng_r
                    )
                    if parent:
                        result["city"] = parent
            except Exception:
                # Fallback to county search
                if address.get("county") and address.get("state"):
                    parent = self._find_parent_city(
                        address["county"], address["state"],
                        address.get("country", ""), lat_r, lng_r
                    )
                    if parent:
                        result["city"] = parent
        return result

    def _find_parent_city(self, county, state, country, lat, lng):
        """Search for the main city in a county and return its name if the
        given coordinates fall within its bounding box."""
        self._last_req = time.time()
        self._rate_wait()
        query = f"city in {county} {state}"
        params = urllib.parse.urlencode({
            "q":      query,
            "format": "jsonv2",
            "limit":  1,
            "addressdetails": 1,
        })
        url = f"{NOMINATIM_SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent":      USER_AGENT,
            "Accept-Language": "en",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._last_req = time.time()
            if not data:
                return None
            hit = data[0]
            addr = hit.get("address", {})
            city = addr.get("city", "")
            if not city:
                return None
            # Check if coordinates fall within the city's bounding box
            bbox = hit.get("boundingbox")
            if bbox:
                south, north, west, east = (float(b) for b in bbox)
                if south <= float(lat) <= north and west <= float(lng) <= east:
                    return city
        except Exception:
            pass
        return None

    def _nominatim_search(self, query):
        """Search Nominatim by name and return the city from the first result."""
        params = urllib.parse.urlencode({
            "q":      query,
            "format": "jsonv2",
            "limit":  1,
            "addressdetails": 1,
        })
        url = f"{NOMINATIM_SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent":      USER_AGENT,
            "Accept-Language": "en",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data:
            address = data[0].get("address", {})
            city = _extract_city(address)
            if city:
                return {
                    "city":         city,
                    "country":      _extract_country(address),
                    "country_code": _extract_country_code(address),
                }
        return None

    def _rate_wait(self):
        elapsed = time.time() - self._last_req
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)

    def lookup(self, lat, lng, venue_name=""):
        """
        Return {"city": ..., "country": ..., "country_code": ...} for
        the given coordinates. For airport venues, searches by name to
        get the correct city instead of the small municipality at the
        airport's coordinates. Returns a dict with empty strings on failure.
        """
        key = self._cache_key(lat, lng)
        if key in self._cache:
            return self._cache[key]

        self._rate_wait()
        lat_r, lng_r = _round_coord(lat, lng)
        result = {"city": "", "country": "", "country_code": ""}

        try:
            # For airports, search by venue name to get the served city
            if venue_name and _is_airport_venue(venue_name):
                searched = self._nominatim_search(venue_name)
                if searched:
                    result = searched
                    self._last_req = time.time()
                    self._cache[key] = result
                    return result
                # If search failed, fall through to reverse geocode
                self._last_req = time.time()
                self._rate_wait()

            result = self._nominatim_reverse(lat_r, lng_r)
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
