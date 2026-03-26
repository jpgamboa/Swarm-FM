# Swarm-FM

Compare your Last.fm scrobble history against your Foursquare/Swarm checkins — generates a self-contained HTML dashboard with no database, no server, just Python and a browser.

**What you get:** an interactive dashboard showing where and how you listen to music — attributed scrobbles by venue, venue type, city, and country; a world map of listening hotspots; trip detection with per-trip listening stats; day-of-week and monthly patterns for both plays and checkins; and a travel artist affinity chart showing which artists you reach for on the road.

**[Try it in your browser](https://jpgamboa.github.io/Swarm-FM/)** — no install required, runs entirely client-side.

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

**3. Export your Foursquare/Swarm history**

Request a data export through Foursquare (exports both City Guide and Swarm data together):

**On the web:** Log in at foursquare.com → click your name (top right) → Settings → Privacy Settings → Initiate Data Download Request

**In the Swarm app:** Profile (top left) → gear icon → Settings → Privacy Settings → Initiate Data Download Request

You'll get a confirmation email from `noreply@legal.foursquare.com`, then a second email with a download link when your data is ready (up to 7 days). Extract the zip — you'll get a folder containing `checkins1.json`, `checkins2.json`, etc.

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

## Web version (no install required)

A browser-based version is available at the project's GitHub Pages site — no Python install needed. Everything runs client-side via [Pyodide](https://pyodide.org/) (Python compiled to WebAssembly).

1. Visit the hosted page (or serve `docs/` locally: `cd docs && python3 -m http.server 8765`)
2. Drop your Last.fm CSV + Foursquare JSON export
3. Files are parsed and correlated in your browser
4. Download the generated dashboard HTML

**To deploy your own instance:** push this repo to GitHub, then go to Settings > Pages > Source: deploy from branch `main`, folder `/docs`.

After editing the source Python files, run `./build_web.sh` to sync them into `docs/`.

## How correlation works

A scrobble is attributed to a venue if it occurred within a **per-category time window** after a checkin. Different venue types get different windows:

| Venue type | Window |
|---|---|
| Transit, hotel, work | 4 hours |
| Coffee shop, bar/brewery | 3 hours |
| Restaurant, music venue | 1.5 hours |
| Gym, outdoor | 2 hours |
| Shopping | 1 hour |
| Cinema | 30 min |
| Other | 3 hours |

**Weekday lunch suppression:** restaurant checkins on weekdays between 10am–4pm are not attributed, to avoid false positives from work-adjacent dining.

The most recent matching checkin wins if windows overlap.

**Home city** is inferred automatically as the most frequently checked-in `(city, country)` pair — no manual configuration needed.

**Trips** are detected by finding consecutive days where all checkins are outside your home city. Gaps of up to 7 days are tolerated. Trips must be at least 2 days and have at least 5 scrobbles to appear in the dashboard. Trip type (flight, train, or road) is inferred from venue names during the trip.

**Map:** the dashboard map shows two layers — green dots for cities with attributed music plays, and gray dots for all other visited cities.

## Data privacy

All data stays on your machine. The CLI version's only network calls are to Nominatim (for reverse geocoding, ~25 min on first run). The web version also uses Nominatim for checkins missing city data, with results cached in your browser's localStorage. Your config and data files are gitignored by default.
