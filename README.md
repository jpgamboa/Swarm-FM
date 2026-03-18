# swarmfm

Compare your Last.fm scrobble history against your Foursquare/Swarm checkins — generates a self-contained HTML dashboard with no database, no server, just Python and a browser.

**What you get:** an interactive dashboard showing where and how you listen to music — attributed scrobbles by venue, venue type, city, and country; a world map of listening hotspots; trip detection with per-trip listening stats; day-of-week and monthly patterns for both plays and checkins; and a travel artist affinity chart showing which artists you reach for on the road.

## Requirements

- Python 3.8+
- No external packages needed — stdlib only
- No API keys needed — everything runs from local export files

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/swarmfm.git
cd swarmfm
```

**2. Export your Last.fm history**

Go to https://benjaminbenben.com/lastfm-to-csv/, enter your username, and download the CSV. Save it somewhere on your machine.

**3. Export your Foursquare history**

Download your data at https://foursquare.com/download-my-data. Extract the zip — you'll get a folder containing `checkins1.json`, `checkins2.json`, etc.

**4. Configure**
```bash
cp config.py.example config.py
```
Edit `config.py` and set:
- `LASTFM_EXPORT_FILE` — path to your Last.fm CSV file
- `FOURSQUARE_EXPORT_DIR` — path to your Foursquare export folder

## Usage

**Run the full pipeline:**
```bash
python3 run.py
```

**Or run individual steps:**
```bash
python3 run.py lastfm       # Step 1: import Last.fm CSV
python3 run.py foursquare   # Step 2: import Foursquare checkins + geocode
python3 run.py correlate    # Step 3: correlate scrobbles with checkins
python3 run.py dashboard    # Step 4: generate dashboard
```

Then open `data/dashboard.html` in any browser.

## Pipeline overview

| Step | Script | Input | Output |
|------|--------|-------|--------|
| 1. Last.fm | `import_lastfm.py` | Last.fm CSV export | `data/scrobbles.json` |
| 2. Foursquare | `import_foursquare.py` + `geocode.py` | Export folder | `data/checkins.json` |
| 3. Correlate | `correlate.py` | Scrobbles + checkins | `data/correlated.json` |
| 4. Dashboard | `generate_dashboard.py` | Correlated + scrobbles | `data/dashboard.html` |

## About geocoding

Step 2 reverse-geocodes every checkin's lat/lng coordinates to city + country using the [Nominatim API](https://nominatim.org/) (OpenStreetMap, free, no key required). Results are cached in `data/geo_cache.json`. The first run over a large checkin history (~1,400 unique locations) takes about 25 minutes at Nominatim's 1 req/sec rate limit; all subsequent runs are instant.

## How correlation works

A scrobble is attributed to a venue if it occurred within **2 hours after** a checkin at that venue. The most recent matching checkin wins if windows overlap.

**Home city** is inferred automatically as the most frequently checked-in `(city, country)` pair — no manual configuration needed.

**Trips** are detected by finding consecutive days where all checkins are outside your home city. Gaps of up to 7 days are tolerated. Trips must be at least 2 days and have at least 5 scrobbles to appear in the dashboard.

## Data privacy

All data stays on your machine. The only network calls are to Nominatim (for reverse geocoding checkin coordinates, ~25 min on first run). Your config and data files are gitignored by default.
