# Check-Ins-FM

Compare your Last.fm or Spotify listening history against your Foursquare/Swarm checkins — generates a self-contained HTML dashboard with no database, no server, just Python and a browser.

**What you get:** an interactive dashboard showing where and how you listen to music — attributed scrobbles by venue, venue type, city, and country; a world map of listening hotspots; trip detection with per-trip listening stats; day-of-week and monthly patterns for both plays and checkins; and a travel artist affinity chart showing which artists you reach for on the road. Spotify users also get listening time graphs, platform breakdowns, and skip rate analysis.

**[Try it in your browser](https://jpgamboa.github.io/Check-Ins-FM/)**: no install required, runs entirely client-side.

## Web App

A browser-based version is available at the project's GitHub Pages site — no Python install needed. Everything runs client-side via [Pyodide](https://pyodide.org/) (Python compiled to WebAssembly).

1. Visit the [hosted page](https://jpgamboa.github.io/Check-Ins-FM/) (or serve `docs/` locally: `cd docs && python3 -m http.server 8765`)
2. Drop your Last.fm CSV or Spotify JSON files + Foursquare JSON exports
3. Enter your home cities (recommended) or use auto-detect
4. Files are parsed and correlated in your browser — preview charts show while geocoding runs
5. Download the generated dashboard HTML

After generating the dashboard, you can click **Edit Home Cities** to adjust your home periods and regenerate without re-uploading or re-geocoding. Charts and maps in the dashboard are click-to-expand for a larger view.

**To deploy your own instance:** push this repo to GitHub, then go to Settings > Pages > Source: deploy from branch `main`, folder `/docs`.

After editing the source Python files, run `./build_web.sh` to sync them into `docs/`.

## Supported music sources

### Last.fm
Export your scrobble history as CSV from [lastfmstats.com](https://lastfmstats.com/) (recommended), [benjaminbenben.com/lastfm-to-csv](https://benjaminbenben.com/lastfm-to-csv/), or the official Last.fm GDPR export.

### Spotify
Request your **Extended streaming history** from [Spotify's privacy page](https://www.spotify.com/account/privacy/) (takes up to 30 days). You'll get a zip containing `Streaming_History_Audio_*.json` files.

Spotify data includes richer metadata than Last.fm: actual play duration, skip/shuffle state, platform/device, and offline mode. When Spotify data is detected, the dashboard shows additional charts:
- **Listening time** — total hours and hours per month (not just play counts)
- **Platforms** — breakdown by device (iPhone, Mac, Web, etc.)
- **Skip rate** — overall and by hour of day
- **Shuffle rate** — how often you use shuffle mode

These sections only appear when Spotify data is present — Last.fm users see the standard dashboard without empty boxes.

### Using both sources together
If you have Last.fm history from earlier years and Spotify from later years, you can provide both. Check-Ins-FM will use Last.fm for the period before your Spotify data begins and Spotify for everything after, giving you the longest possible history with the richest available metadata.

## Foursquare/Swarm export

There are two ways to get your Foursquare/Swarm checkin history:

**Option 1: Privacy data request** — no coding required, but can take several days. Go to [Foursquare's data request page](https://foursquare.com/city-guide-sunset/#accordion_v2-0825c858-5e57-4566-8cc9-86dd86731d88) and follow the instructions. You'll receive an email with a download link when ready (up to 7 days). Extract the zip — you'll get `checkins1.json`, `checkins2.json`, etc.

**Option 2: API export via Pinback** — faster and immediate, but requires a Foursquare developer account. Visit [github.com/lokesh/pinback](https://github.com/lokesh/pinback) and follow the setup instructions.

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

**Weekday lunch suppression:** restaurant checkins on weekdays between 10am–4pm local time are not attributed when in your home city, to avoid false positives from work-adjacent dining. This suppression is disabled when traveling.

The most recent matching checkin wins if windows overlap.

**Home city** can be entered manually (recommended) or inferred automatically from checkin patterns. Auto-detect uses a rolling 120-day window to find the dominant city at each point in time, filtering out county-level geocode results and validating that each period has actual checkins. Short stays under 4 months are filtered as trips. Auto-detect works best when you check in regularly (several times per month); if your checkin frequency dropped significantly over the years, manual entry is more accurate. The web app includes an info modal explaining the algorithm's strengths and limitations. Lunch suppression, trip detection, and travel artist analysis all respect the home city active at each point in time.

**Geocode resolution:** the web version uses a three-layer geocoding strategy. First, coordinates are checked against a pre-built cache (`geo_seed.json` + browser localStorage). Uncached coordinates are resolved by an [offline geocoder](https://github.com/kyr0/offline-geocode-city) that runs entirely in the browser with no network requests. A suburb-to-metro correction table (built from [GeoNames](https://www.geonames.org/) population data) maps neighborhoods to their parent cities (e.g. "Lakeway" → "Austin", "Zaventem" → "Brussels"). Airports are detected by venue name and resolved via Nominatim search to get the served city (e.g. "Brussels Airport" → "Brussels"). Nominatim is also used as a fallback for any coordinates the offline geocoder can't resolve. The CLI version uses Nominatim directly with a broader-zoom fallback for suburb resolution. County-level results (e.g. "Travis County") are filtered out of home city inference.

**Trips** are detected by finding consecutive days where all checkins are outside your home city. Gaps of up to 7 days are tolerated. Trips must be at least 2 days and have at least 5 scrobbles to appear in the dashboard.

**Map:** the dashboard map shows two layers — green dots for cities with attributed music plays, and gray dots for all other visited cities.

## Run App Locally

## Requirements

- Python 3.8+
- No external packages needed — stdlib only
- No API keys needed — everything runs from local export files

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/Check-Ins-FM.git
cd Check-Ins-FM
```

**2. Export your music history**

Choose one or both:
- **Last.fm:** Go to https://lastfmstats.com/, enter your username, and export as CSV
- **Spotify:** Request your Extended streaming history at https://www.spotify.com/account/privacy/ (takes up to 30 days)

**3. Export your Foursquare/Swarm history**

See the [Foursquare export section](#foursquaresswarm-export) above for options.

**4. Configure**
```bash
cp config.py.example config.py
```
Edit `config.py` and set:
- `LASTFM_EXPORT_FILE` — path to your Last.fm CSV file
- `SPOTIFY_EXPORT_DIR` — path to your Spotify export folder (containing `Streaming_History_Audio_*.json`)
- `FOURSQUARE_EXPORT_DIR` — path to your Foursquare export folder

## Usage

**Run the full pipeline:**
```bash
python3 run.py
```

**Or run individual steps:**
```bash
python3 run.py lastfm       # Step 1: import Last.fm CSV
python3 run.py spotify       # Step 1b: import Spotify history (merges with Last.fm if both present)
python3 run.py foursquare    # Step 2: import Foursquare checkins + geocode
python3 run.py correlate     # Step 3: correlate scrobbles with checkins
python3 run.py dashboard     # Step 4: generate dashboard
```

Then open `data/dashboard.html` in any browser.

## Pipeline overview

| Step | Script | Input | Output |
|------|--------|-------|--------|
| 1. Last.fm | `import_lastfm.py` | Last.fm CSV export | `data/scrobbles.json` |
| 1b. Spotify | `import_spotify.py` | Spotify export folder | `data/scrobbles.json` + `data/podcasts.json` |
| 2. Foursquare | `import_foursquare.py` + `geocode.py` | Export folder | `data/checkins.json` |
| 3. Correlate | `correlate.py` | Scrobbles + checkins | `data/correlated.json` |
| 4. Dashboard | `generate_dashboard.py` | Correlated + scrobbles | `data/dashboard.html` |

If both Last.fm and Spotify are configured, the Spotify step automatically merges the two sources: Last.fm scrobbles from before the Spotify data begins are preserved, and Spotify is used for the overlap period onward. Podcasts detected in Spotify data are automatically separated into `data/podcasts.json`.

## About geocoding

Step 2 reverse-geocodes every checkin's lat/lng coordinates to city + country. The **CLI** uses the [Nominatim API](https://nominatim.org/) (OpenStreetMap, free, no key required) with results cached in `data/geo_cache.json`. The first run over a large checkin history (~1,400 unique locations) takes about 25 minutes at Nominatim's 1 req/sec rate limit; all subsequent runs are instant.

The **web version** resolves most coordinates instantly using an [offline geocoder](https://github.com/kyr0/offline-geocode-city) (loaded from [esm.sh](https://esm.sh)) with a suburb-to-metro correction table built from [GeoNames](https://www.geonames.org/) data. Only airports and edge cases fall back to Nominatim. A pre-built `geo_seed.json` cache and browser localStorage provide additional caching. The upload page shows dependency status indicators for all external services.

## Data privacy

All data stays on your machine. No tracking, cookies, or analytics.

- **Client-side processing** — both the CLI and web versions process your data locally. The web app runs entirely in your browser via Pyodide (Python in WebAssembly). Your Last.fm, Spotify, and Foursquare files are never uploaded to any server.
- **Offline geocoding** — the web version resolves most coordinates using [offline-geocode-city](https://github.com/kyr0/offline-geocode-city), loaded from [esm.sh](https://esm.sh). This library runs entirely in the browser with embedded city data — no coordinates are sent externally. The library code is fetched once from the CDN on page load.
- **Nominatim geocoding (fallback)** — for airports and edge cases, coordinates rounded to ~1 km (CLI) or ~10 km (web) are sent to [OpenStreetMap's Nominatim](https://nominatim.openstreetmap.org). See the [OSM Foundation privacy policy](https://osmfoundation.org/wiki/Privacy_Policy).
- **Pre-built caches** — the web version ships `geo_seed.json` (coordinate-to-city mappings at ~10 km grid) and `suburb_corrections.json` (neighborhood-to-metro-city mappings from GeoNames). Neither contains venue names, timestamps, or personally identifying information.
- **Browser localStorage** — geocoding results are cached in your browser's `localStorage` for faster subsequent runs. You can download, import, or clear the cache from the upload page.
- **Config and data files** — `config.py` and the `data/` directory are gitignored by default.
