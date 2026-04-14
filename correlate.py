#!/usr/bin/env python3
"""
Correlate scrobbles with Foursquare checkins
==============================================
Matches Last.fm scrobbles to Foursquare checkins by timestamp to
figure out where you were listening to music.

Produces:
  - Venue plays: how many scrobbles occurred at each venue
  - Category attribution: listens by venue type (bar, restaurant, etc.)
  - City/country attribution: listens by place
  - Trip detection: away-from-home periods (uses geocoded city data)
  - Travel artists: artists overrepresented during trips vs at home

Attribution logic:
  A scrobble is attributed to a venue if it occurred within a window
  AFTER a checkin at that venue (default: 2 hours). If multiple
  checkins overlap, the most recent one wins.

Trip detection:
  Home is inferred as the most frequently checked-in city over the
  full dataset. Days where ALL checkins are in a non-home city are
  "away days"; consecutive away days (±TRIP_GAP_DAYS) form a trip.

Usage:
    from correlate import run
    result = run("./data")
"""

import bisect
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

TRIP_GAP_DAYS            = 7   # max gap between away-days to merge into one trip
MIN_TRIP_DAYS            = 2   # minimum consecutive away days to call it a trip
MIN_TRIP_SCROBBLES       = 5   # minimum scrobbles during a trip to include it
MIN_TRAVEL_PLAYS         = 5   # min travel plays to include in travel_artists


# ── Venue category keywords ────────────────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "transit":     ["airport", "terminal", "airline", "train station", "metro",
                    "amtrak", "railway", "bus station", "subway", "gare"],
    "coffee":      ["coffee", "café", "cafe", "espresso", "roastery", "starbucks",
                    "blue bottle", "la colombe", "intelligentsia", "teahouse",
                    "tea house", "kopitiam"],
    "bar_brewery": ["bar", " pub", "brewery", "brewing", "taproom", "tap room",
                    "lounge", "saloon", "tavern", "ale house", "alehouse",
                    "bottle shop", "beer garden", "craft beer", "bierhaus",
                    "biergarten", "beer cellar"],
    "restaurant":  ["restaurant", "ramen", "sushi", "kitchen", "grill", "bbq",
                    "deli", "bistro", "eatery", "taco", "pizza", "burger",
                    "diner", "seafood", "barbeque", "noodle", "steakhouse",
                    "kolaches", "beignet", "warung", "hawker"],
    "music_venue": ["music hall", "concert hall", "amphitheater", "amphitheatre",
                    "auditorium", "opera house", "live music", "nightclub",
                    "club"],
    "cinema":      ["cinema", "theater", "theatre", "imax", "drafthouse",
                    "alamo", "cineplex", "movieplex"],
    "hotel":       ["hotel", " inn", "hostel", "motel", "resort", "lodge",
                    "suites", "marriott", "hilton", "hyatt", "sheraton",
                    "airbnb", "bnb"],
    "gym":         ["gym", "fitness", "crossfit", "yoga", "aquatic",
                    "swimming pool", "recreation center", "rec center"],
    "work":        ["office", "coworking", "co-working", "workspace",
                    "headquarters"],
    "outdoor":     ["park", "trail", "beach", "lake", "mountain", "ruins",
                    "botanical", "garden", "river", "creek", "falls",
                    "preserve", "national"],
    "shopping":    ["whole foods", "target", "walmart", "costco", "h-e-b",
                    "heb", "market", "grocery", "mall", " store",
                    "trader joe"],
}

# Per-category attribution windows (seconds).
# A scrobble is attributed to a checkin if it falls within this window AFTER
# the checkin. Different venue types warrant different windows.
_CAT_WINDOW = {
    "transit":      4 * 3600,
    "coffee":       3 * 3600,
    "bar_brewery":  3 * 3600,
    "restaurant":   1.5 * 3600,
    "music_venue":  1.5 * 3600,
    "cinema":       0.5 * 3600,
    "hotel":        4 * 3600,
    "gym":          4 * 3600,
    "work":         4 * 3600,
    "outdoor":      2 * 3600,
    "shopping":     1 * 3600,
    "other":        3 * 3600,
}
# M-F 10am–4pm local time: suppress restaurant attribution (likely work-bleed)
_CAT_WINDOW_WEEKDAY_LUNCH = {
    "restaurant": 0,
}


def _categorize_venue(name):
    name_lower = name.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return cat
    return "other"


def _is_airport_venue(name):
    """Check if a venue name looks like an airport."""
    nl = name.lower()
    return ("airport" in nl or "aeropuerto" in nl or "aéroport" in nl
            or re.search(r'\b[A-Z]{3}\b', name) is not None  # 3-letter IATA code
            and ("terminal" in nl or "gate" in nl or "airport" in nl))


def _is_train_station(name):
    """Check if a venue name looks like a train station."""
    nl = name.lower()
    return ("train station" in nl or "railway" in nl or "amtrak" in nl
            or "gare" in nl or "estación" in nl or "bahnhof" in nl)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(ts):
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' to datetime."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


# ── Home city detection ────────────────────────────────────────────────────────

_HOME_WINDOW_DAYS = 120  # rolling window to detect dominant city
_HOME_MIN_SHARE   = 0.45 # city must be ≥45% of window's checkins to count
_HOME_MIN_MONTHS  = 4    # minimum months for a period to count as "home"


def _infer_home_city(checkins):
    """
    Returns the (city, country_code) tuple that appears most in all checkins.
    Falls back to country_code alone if city is unavailable.
    """
    city_counts = Counter(
        (c.get("city", ""), c.get("country_code", ""))
        for c in checkins
        if c.get("city") and c.get("country_code")
    )
    if not city_counts:
        return ("", "")
    return city_counts.most_common(1)[0][0]


def _is_county_level(city_name):
    """Check if a city name is actually a county, not a real city."""
    lower = city_name.lower()
    return ("county" in lower or "parish" in lower
            or lower.endswith(" township"))


def _infer_home_periods(checkins):
    """
    Detect home city changes over time by finding the dominant city in
    rolling windows. Returns a list of dicts:
      [{"city": ..., "country_code": ..., "start": date, "end": date}, ...]
    sorted chronologically. Each period represents where the user lived.
    """
    # Build daily checkin city counts, filtering out county-level results
    dated = []
    for c in checkins:
        city = c.get("city", "")
        cc = c.get("country_code", "")
        if not city or not cc:
            continue
        if _is_county_level(city):
            continue
        try:
            dt = _parse_ts(c["timestamp"]).date()
            dated.append((dt, city, cc))
        except Exception:
            continue

    if not dated:
        return []

    dated.sort(key=lambda x: x[0])

    # For each month, find the dominant city using a rolling window
    from collections import deque
    window = deque()
    window_counts = Counter()
    monthly_dominant = []  # (month_start_date, city, cc)

    all_dates = sorted(set(d for d, _, _ in dated))
    if not all_dates:
        return []

    # Walk through each day, maintaining a rolling window
    date_idx = 0
    cur = all_dates[0]
    last = all_dates[-1]
    day = timedelta(days=1)
    prev_month = None

    while cur <= last:
        # Add checkins for this day
        while date_idx < len(dated) and dated[date_idx][0] <= cur:
            d, city, cc = dated[date_idx]
            window.append((d, city, cc))
            window_counts[(city, cc)] += 1
            date_idx += 1

        # Remove checkins outside the window
        cutoff = cur - timedelta(days=_HOME_WINDOW_DAYS)
        while window and window[0][0] < cutoff:
            _, city, cc = window.popleft()
            window_counts[(city, cc)] -= 1
            if window_counts[(city, cc)] == 0:
                del window_counts[(city, cc)]

        # Record dominant city at month boundaries
        month_key = (cur.year, cur.month)
        if month_key != prev_month and window_counts:
            top, top_count = window_counts.most_common(1)[0]
            total = sum(window_counts.values())
            if top_count / total >= _HOME_MIN_SHARE:
                monthly_dominant.append((cur, top[0], top[1]))
            prev_month = month_key

        cur += day

    if not monthly_dominant:
        # Fallback to overall most common
        overall = Counter((city, cc) for _, city, cc in dated).most_common(1)[0][0]
        return [{"city": overall[0], "country_code": overall[1],
                 "start": all_dates[0].isoformat(),
                 "end": last.isoformat()}]

    # Collapse consecutive months with the same dominant city into periods
    raw_periods = []
    cur_city, cur_cc = monthly_dominant[0][1], monthly_dominant[0][2]
    cur_start = monthly_dominant[0][0]

    for dt, city, cc in monthly_dominant[1:]:
        if city != cur_city or cc != cur_cc:
            raw_periods.append({
                "city": cur_city, "country_code": cur_cc,
                "start": cur_start, "end": dt,
            })
            cur_city, cur_cc, cur_start = city, cc, dt

    raw_periods.append({
        "city": cur_city, "country_code": cur_cc,
        "start": cur_start, "end": last,
    })

    # Filter out short periods (likely trips, not moves) and merge neighbors
    periods = []
    for p in raw_periods:
        months = (p["end"].year - p["start"].year) * 12 + (p["end"].month - p["start"].month)
        if months >= _HOME_MIN_MONTHS:
            # Merge with previous if same city
            if periods and periods[-1]["city"] == p["city"] and periods[-1]["country_code"] == p["country_code"]:
                periods[-1]["end"] = p["end"]
            else:
                periods.append(dict(p))

    # Validate periods: city must have checkins actually within the period
    # (not just from rolling window spillover from adjacent periods)
    validated = []
    for p in periods:
        actual_checkins = sum(
            1 for d, city, cc in dated
            if city == p["city"] and cc == p["country_code"]
            and p["start"] <= d <= p["end"]
        )
        if actual_checkins >= 3:
            # Merge with previous if same city
            if validated and validated[-1]["city"] == p["city"] and validated[-1]["country_code"] == p["country_code"]:
                validated[-1]["end"] = p["end"]
            else:
                validated.append(p)
    periods = validated

    # If everything got filtered, fall back to overall most common
    if not periods:
        overall = Counter((city, cc) for _, city, cc in dated).most_common(1)[0][0]
        periods = [{"city": overall[0], "country_code": overall[1],
                     "start": all_dates[0], "end": last}]

    # Extend first period to cover all data before it, last to cover all after
    periods[0]["start"] = all_dates[0]
    periods[-1]["end"] = last

    # Convert dates to ISO strings
    for p in periods:
        p["start"] = p["start"].isoformat()
        p["end"] = p["end"].isoformat()

    return periods


def _home_at(home_periods, dt):
    """Return (city, country_code) for the home city active at datetime dt."""
    if not home_periods:
        return ("", "")
    d = dt.date() if hasattr(dt, 'date') else dt
    d_iso = d.isoformat() if hasattr(d, 'isoformat') else str(d)
    for p in home_periods:
        if p["start"] <= d_iso <= p["end"]:
            return (p["city"], p["country_code"])
    # Before first period or after last — use nearest
    if d_iso < home_periods[0]["start"]:
        return (home_periods[0]["city"], home_periods[0]["country_code"])
    return (home_periods[-1]["city"], home_periods[-1]["country_code"])


# ── Attribution ───────────────────────────────────────────────────────────────

def _attribute_scrobbles(checkins, scrobbles, home_periods=None):
    """
    For each scrobble, find the most recent checkin within a per-category
    attribution window. Returns a list of (scrobble, checkin | None) pairs.

    Weekday lunches (M-F 10am–4pm) suppress restaurant attribution only
    when in the home city — you're likely at work. When traveling, keep
    restaurant attribution active.
    """
    home_periods = home_periods or []
    sorted_checkins = sorted(checkins, key=lambda c: c["timestamp"])
    checkin_ts = [_parse_ts(c["timestamp"]) for c in sorted_checkins]
    # Pre-compute local hours (for weekday lunch suppression)
    checkin_local_ts = []
    for c in sorted_checkins:
        utc = _parse_ts(c["timestamp"])
        offset_min = c.get("tz_offset_min", 0) or 0
        checkin_local_ts.append(utc + timedelta(minutes=offset_min))
    # Pre-compute categories and home-city flags
    checkin_cats = [_categorize_venue(c.get("venue_name", "")) for c in sorted_checkins]
    checkin_is_home = []
    for c, ck_ts in zip(sorted_checkins, checkin_ts):
        hc, hcc = _home_at(home_periods, ck_ts)
        checkin_is_home.append(
            c.get("city", "") == hc and c.get("country_code", "") == hcc
        )

    attributed = []

    for scrobble in scrobbles:
        ts = _parse_ts(scrobble["timestamp"])
        # Walk backwards from the most recent checkin before this scrobble
        idx = bisect.bisect_right(checkin_ts, ts) - 1
        matched = None
        while idx >= 0:
            ck_ts = checkin_ts[idx]
            delta = (ts - ck_ts).total_seconds()
            if delta > max(_CAT_WINDOW.values()):
                break  # no checkin can possibly match

            cat = checkin_cats[idx]

            # Suppress restaurants during weekday lunch ONLY in home city
            # Use local time (not UTC) so the 10am-4pm window is correct
            local_ts = checkin_local_ts[idx]
            is_weekday_lunch = (checkin_is_home[idx]
                                and local_ts.weekday() < 5
                                and 10 <= local_ts.hour < 16)
            if is_weekday_lunch and cat in _CAT_WINDOW_WEEKDAY_LUNCH:
                window_sec = _CAT_WINDOW_WEEKDAY_LUNCH[cat]
            else:
                window_sec = _CAT_WINDOW.get(cat, _CAT_WINDOW["other"])

            if delta <= window_sec:
                matched = sorted_checkins[idx]
                break

            idx -= 1

        attributed.append((scrobble, matched))

    return attributed


# ── Trip detection ─────────────────────────────────────────────────────────────

def _detect_trips(checkins, home_periods):
    """
    Returns a list of trip dicts. Each trip has:
      start, end (datetime), duration_days, checkins (count),
      cities (Counter), countries (Counter), destination (str)
    """
    if not home_periods:
        return []

    # Build daily checkin map: date → list of checkins
    by_date = defaultdict(list)
    for c in checkins:
        try:
            dt = _parse_ts(c["timestamp"])
            date = dt.date()
            by_date[date].append(c)
        except Exception:
            pass

    # Away days: days where all checkins are outside the home city for that date
    def _is_away(day_checkins, date):
        home_city, home_cc = _home_at(home_periods, date)
        if not home_cc:
            return False
        for c in day_checkins:
            city = c.get("city", "")
            cc   = c.get("country_code", "")
            # Home if same city+country, or if no geocode data
            if not cc:
                return False
            if city == home_city and cc == home_cc:
                return False
        return True

    sorted_dates = sorted(by_date.keys())
    away_dates   = [d for d in sorted_dates if _is_away(by_date[d], d)]

    if not away_dates:
        return []

    # Merge away_dates into trips (gap tolerance = TRIP_GAP_DAYS)
    trip_ranges = []
    start = end = away_dates[0]
    for d in away_dates[1:]:
        if (d - end).days <= TRIP_GAP_DAYS:
            end = d
        else:
            trip_ranges.append((start, end))
            start = end = d
    trip_ranges.append((start, end))

    trips = []
    for start, end in trip_ranges:
        duration = (end - start).days + 1
        if duration < MIN_TRIP_DAYS:
            continue

        trip_checkins = [c for d in by_date if start <= d <= end for c in by_date[d]]
        cities   = Counter(
            (c.get("city", ""), c.get("country_code", ""))
            for c in trip_checkins if c.get("city")
        )
        countries = Counter(c.get("country_code", "") for c in trip_checkins if c.get("country_code"))

        # Drop countries that represent <20% of the dominant country's checkins
        # (likely geocoding artifacts near borders)
        if countries:
            dominant_count = countries.most_common(1)[0][1]
            countries = Counter({cc: cnt for cc, cnt in countries.items()
                                 if cnt >= max(2, dominant_count * 0.2)})
            # Also drop cities belonging to filtered-out countries
            cities = Counter({(city, cc): cnt for (city, cc), cnt in cities.items()
                              if cc in countries})

        # Destination label: top countries (excl. home if international) or top cities
        _, trip_home_cc = _home_at(home_periods, start)
        top_countries = [cc for cc, _ in countries.most_common(3) if cc != trip_home_cc]
        if not top_countries:
            top_countries = [cc for cc, _ in countries.most_common(1)]

        top_cities = [city for (city, cc), _ in cities.most_common(3)
                      if city and cc in top_countries][:2]

        destination = ", ".join(top_cities) if top_cities else ", ".join(top_countries)

        # Detect trip type: flight, road, or train
        venue_names = [c.get("venue_name", "") for c in trip_checkins]
        has_airport = any(_is_airport_venue(v) for v in venue_names)
        has_train   = any(_is_train_station(v) for v in venue_names)
        if has_airport:
            trip_type = "flight"
        elif has_train:
            trip_type = "train"
        else:
            trip_type = "road"

        trips.append({
            "start":        start.isoformat(),
            "end":          end.isoformat(),
            "duration_days": duration,
            "checkins":     len(trip_checkins),
            "destination":  destination,
            "trip_type":    trip_type,
            "countries":    [{"country_code": cc, "count": cnt}
                             for cc, cnt in countries.most_common(5)],
            "cities":       [{"city": city, "country_code": cc, "count": cnt}
                             for (city, cc), cnt in cities.most_common(5)],
        })

    return trips


# ── Main ──────────────────────────────────────────────────────────────────────

def run(data_dir="./data"):
    checkins_path  = os.path.join(data_dir, "checkins.json")
    scrobbles_path = os.path.join(data_dir, "scrobbles.json")
    manual_home_path = os.path.join(data_dir, "manual_home.json")

    checkins  = _load(checkins_path, [])
    scrobbles = _load(scrobbles_path, [])

    if not checkins:
        print(f"  ✗  No checkins found at {checkins_path}")
        return {}

    print(f"Correlating {len(scrobbles):,} scrobbles with {len(checkins):,} checkins...")

    # ── Home periods: manual override or auto-infer ─────────────────────────
    manual_home = _load(manual_home_path, None)
    if manual_home and isinstance(manual_home, list) and len(manual_home) > 0:
        home_periods = sorted(manual_home, key=lambda p: p.get("start", ""))
        print(f"  Using {len(home_periods)} manual home period(s):")
        for p in home_periods:
            label = f"{p['city']}, {p.get('state', '')}, {p['country_code']}" if p.get('state') else f"{p['city']}, {p['country_code']}"
            print(f"    {label}  ({p['start'][:7]} → {p['end'][:7]})")
    else:
        home_periods = _infer_home_periods(checkins)
        if len(home_periods) == 1:
            p = home_periods[0]
            print(f"  Inferred home: {p['city']}, {p['country_code']}")
        else:
            print(f"  Inferred {len(home_periods)} home periods:")
            for p in home_periods:
                print(f"    {p['city']}, {p['country_code']}  "
                      f"({p['start'][:7]} → {p['end'][:7]})")

    # ── Attribute scrobbles to venues ─────────────────────────────────────────
    attributed = _attribute_scrobbles(checkins, scrobbles, home_periods)
    attributed_count = sum(1 for _, ck in attributed if ck)
    print(f"  Attributed {attributed_count:,}/{len(scrobbles):,} scrobbles to venues "
          f"({attributed_count/max(len(scrobbles),1)*100:.1f}%)")

    # ── Venue plays ───────────────────────────────────────────────────────────
    venue_data = {}
    for scrobble, checkin in attributed:
        if not checkin:
            continue
        vn  = checkin.get("venue_name", "Unknown")
        lat = checkin.get("lat")
        lng = checkin.get("lng")
        if vn not in venue_data:
            venue_data[vn] = {
                "plays":        0,
                "checkins":     0,
                "lat":          lat,
                "lng":          lng,
                "city":         checkin.get("city", ""),
                "country_code": checkin.get("country_code", ""),
                "category":     _categorize_venue(vn),
                "artists":      Counter(),
            }
        venue_data[vn]["plays"] += 1
        artist = scrobble.get("artist", "")
        if artist:
            venue_data[vn]["artists"][artist] += 1

    # Count checkins per venue
    for checkin in checkins:
        vn = checkin.get("venue_name", "Unknown")
        if vn in venue_data:
            venue_data[vn]["checkins"] += 1

    venue_plays = sorted(
        [
            {
                "name":           vn,
                "plays":          d["plays"],
                "checkins":       d["checkins"],
                "avg_per_checkin": round(d["plays"] / max(d["checkins"], 1), 1),
                "lat":            d["lat"],
                "lng":            d["lng"],
                "city":           d["city"],
                "country_code":   d["country_code"],
                "category":       d["category"],
                "top_artists":    [{"artist": a, "count": c}
                                   for a, c in d["artists"].most_common(5)],
            }
            for vn, d in venue_data.items() if d["plays"] > 0
        ],
        key=lambda x: -x["plays"],
    )

    # ── Category attribution ──────────────────────────────────────────────────
    category_counts = Counter()
    for _, d in venue_data.items():
        category_counts[d["category"]] += d["plays"]
    by_category = [{"cat": cat, "plays": cnt}
                   for cat, cnt in category_counts.most_common()]

    # ── City / country attribution ────────────────────────────────────────────
    city_plays    = Counter()
    country_plays = Counter()
    city_coords   = {}  # city_str → (lat, lng)

    for scrobble, checkin in attributed:
        if not checkin:
            continue
        city = checkin.get("city", "")
        cc   = checkin.get("country_code", "")
        if city and cc:
            key = f"{city}, {cc}"
            city_plays[key] += 1
            if key not in city_coords and checkin.get("lat"):
                city_coords[key] = (checkin["lat"], checkin["lng"])
        if cc:
            country_plays[cc] += 1

    by_city = [
        {"city": city_key, "plays": cnt,
         "lat": city_coords.get(city_key, (None, None))[0],
         "lng": city_coords.get(city_key, (None, None))[1]}
        for city_key, cnt in city_plays.most_common(40)
    ]

    # Load country names from generate_dashboard for consistency
    _COUNTRY_NAMES = {
        "US": "United States", "GB": "United Kingdom", "CA": "Canada",
        "FR": "France", "AU": "Australia", "SE": "Sweden", "NO": "Norway",
        "DE": "Germany", "MX": "Mexico", "BR": "Brazil", "JP": "Japan",
        "IE": "Ireland", "NL": "Netherlands", "NZ": "New Zealand",
        "IT": "Italy", "ES": "Spain", "DK": "Denmark", "FI": "Finland",
        "BE": "Belgium", "AT": "Austria", "CH": "Switzerland", "PL": "Poland",
        "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "KR": "South Korea",
        "CN": "China", "IN": "India", "LT": "Lithuania", "BY": "Belarus",
        "IS": "Iceland", "PT": "Portugal", "GR": "Greece", "UA": "Ukraine",
        "RU": "Russia", "TR": "Turkey", "SG": "Singapore", "TH": "Thailand",
    }
    by_country = [
        {"country_code": cc, "country": _COUNTRY_NAMES.get(cc, cc), "plays": cnt}
        for cc, cnt in country_plays.most_common(20)
    ]

    # ── Trip detection ────────────────────────────────────────────────────────
    home_labels = [f"{p['city']}, {p.get('state', '')}, {p['country_code']}" if p.get('state') else f"{p['city']}, {p['country_code']}" for p in home_periods]
    print(f"  Detecting trips (home: {' → '.join(home_labels) or '?'})...")
    trips = _detect_trips(checkins, home_periods)

    # Attach top scrobbles to each trip
    scrobble_by_date = defaultdict(list)
    for s in scrobbles:
        try:
            date = _parse_ts(s["timestamp"]).date().isoformat()
            scrobble_by_date[date].append(s)
        except Exception:
            pass

    for trip in trips:
        start = datetime.fromisoformat(trip["start"]).date()
        end   = datetime.fromisoformat(trip["end"]).date()
        trip_scrobbles = []
        cur = start
        while cur <= end:
            trip_scrobbles.extend(scrobble_by_date.get(cur.isoformat(), []))
            cur += timedelta(days=1)

        trip["scrobble_count"] = len(trip_scrobbles)
        # Music intensity: scrobbles per day
        trip["music_intensity"] = round(len(trip_scrobbles) / max(trip["duration_days"], 1), 1)
        if len(trip_scrobbles) < MIN_TRIP_SCROBBLES:
            continue

        top_artists = Counter(s.get("artist", "") for s in trip_scrobbles if s.get("artist"))
        trip["top_artists"] = [{"artist": a, "plays": c}
                                for a, c in top_artists.most_common(5)]
        trip["top_tracks"] = [
            {"artist": combo[0], "track": combo[1]}
            for combo, _ in Counter(
                (sc.get("artist", ""), sc.get("track", "")) for sc in trip_scrobbles
            ).most_common(3)
        ]

    trips = [t for t in trips if t.get("scrobble_count", 0) >= MIN_TRIP_SCROBBLES]
    print(f"  Found {len(trips)} trips")

    # ── Travel artist affinity ─────────────────────────────────────────────────
    trip_dates = set()
    for trip in trips:
        start = datetime.fromisoformat(trip["start"]).date()
        end   = datetime.fromisoformat(trip["end"]).date()
        cur   = start
        while cur <= end:
            trip_dates.add(cur.isoformat())
            cur += timedelta(days=1)

    travel_plays = Counter()
    home_plays   = Counter()
    for s in scrobbles:
        artist = s.get("artist", "")
        if not artist:
            continue
        try:
            date = _parse_ts(s["timestamp"]).date().isoformat()
        except Exception:
            continue
        if date in trip_dates:
            travel_plays[artist] += 1
        else:
            home_plays[artist] += 1

    total_travel = sum(travel_plays.values()) or 1
    total_home   = sum(home_plays.values()) or 1

    travel_artists = []
    for artist, tp in travel_plays.items():
        if tp < MIN_TRAVEL_PLAYS:
            continue
        hp = home_plays.get(artist, 0)
        t_share = tp / total_travel
        h_share = hp / total_home if hp > 0 else 0.5 / total_home
        lift = t_share / h_share
        travel_artists.append({
            "artist":       artist,
            "travel_plays": tp,
            "home_plays":   hp,
            "lift":         round(lift, 2),
        })
    travel_artists.sort(key=lambda x: -x["lift"])
    travel_artists = travel_artists[:25]

    # ── All checkin cities (for visited-only map layer) ────────────────────────
    all_city_counts = Counter()
    all_city_coords = {}
    for c in checkins:
        city = c.get("city", "")
        cc   = c.get("country_code", "")
        if city and cc:
            key = f"{city}, {cc}"
            all_city_counts[key] += 1
            if key not in all_city_coords and c.get("lat"):
                all_city_coords[key] = (c["lat"], c["lng"])

    all_checkin_cities = [
        {"city": key, "checkins": cnt,
         "lat": all_city_coords.get(key, (None, None))[0],
         "lng": all_city_coords.get(key, (None, None))[1]}
        for key, cnt in all_city_counts.most_common()
        if all_city_coords.get(key)
    ]

    result = {
        "home":               home_periods,
        "attributed":         attributed_count,
        "venue_plays":        venue_plays[:50],
        "by_category":        by_category,
        "by_city":            by_city,
        "by_country":         by_country,
        "all_checkin_cities": all_checkin_cities,
        "trips":              trips,
        "travel_artists":     travel_artists,
    }

    out_path = os.path.join(data_dir, "correlated.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✓  Correlation saved → {out_path}")
    return result


if __name__ == "__main__":
    try:
        import config
    except ImportError:
        print("Error: config.py not found.")
        raise SystemExit(1)
    run(config.DATA_DIR)
