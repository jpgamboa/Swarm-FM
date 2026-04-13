#!/usr/bin/env python3
"""
checkinsfm — Last.fm + Swarm/Foursquare data comparison
======================================================

Imports your Last.fm scrobble export and Foursquare/Swarm checkin export,
correlates them, and generates a self-contained HTML dashboard showing
where and how you listen to music.

Usage:
    python run.py              # run full pipeline
    python run.py lastfm       # step 1: import Last.fm CSV export
    python run.py foursquare   # step 2: import Foursquare export + geocode
    python run.py correlate    # step 3: correlate scrobbles with checkins
    python run.py dashboard    # step 4: generate HTML dashboard

Setup:
    1. Copy config.py.example to config.py
    2. Export your Last.fm history at https://benjaminbenben.com/lastfm-to-csv/
       and set LASTFM_EXPORT_FILE in config.py
    3. Download your Foursquare/Swarm data at https://foursquare.com/download-my-data
       and set FOURSQUARE_EXPORT_DIR in config.py
    4. Run: python run.py

Requirements:
    - Python 3.8+
    - No external packages needed (stdlib only)
"""

import sys
import os

STEPS = ["lastfm", "spotify", "foursquare", "correlate", "dashboard"]


def load_config():
    try:
        import config
        return config
    except ImportError:
        print("Error: config.py not found.")
        print("  → Copy config.py.example to config.py and fill in your paths.")
        sys.exit(1)


def step_lastfm(cfg):
    export_file = getattr(cfg, "LASTFM_EXPORT_FILE", "")
    if not export_file:
        print("LASTFM_EXPORT_FILE not set — skipping Last.fm import.")
        print("  → Export your history at https://benjaminbenben.com/lastfm-to-csv/")
        return
    from import_lastfm import parse
    parse(export_file, cfg.DATA_DIR)


def step_spotify(cfg):
    export_dir = getattr(cfg, "SPOTIFY_EXPORT_DIR", "")
    if not export_dir:
        print("SPOTIFY_EXPORT_DIR not set — skipping Spotify import.")
        return
    from import_spotify import parse
    scrobbles_path = os.path.join(cfg.DATA_DIR, "scrobbles.json")
    had_lastfm = os.path.exists(scrobbles_path)
    if had_lastfm:
        import json
        with open(scrobbles_path, encoding="utf-8") as f:
            lastfm_scrobbles = json.load(f)
    parse(export_dir, cfg.DATA_DIR)
    # Merge with Last.fm if both exist
    if had_lastfm and os.path.exists(scrobbles_path):
        with open(scrobbles_path, encoding="utf-8") as f:
            spotify_scrobbles = json.load(f)
        # Use Spotify for overlapping periods (richer data), Last.fm for the rest
        if spotify_scrobbles and lastfm_scrobbles:
            sp_start = spotify_scrobbles[0]["timestamp"]
            # Keep Last.fm scrobbles from before Spotify data begins
            pre_spotify = [s for s in lastfm_scrobbles if s["timestamp"] < sp_start]
            if pre_spotify:
                merged = pre_spotify + spotify_scrobbles
                merged.sort(key=lambda s: s["timestamp"])
                with open(scrobbles_path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                print(f"  Merged {len(pre_spotify):,} Last.fm scrobbles (pre-Spotify) "
                      f"+ {len(spotify_scrobbles):,} Spotify = {len(merged):,} total")


def step_foursquare(cfg):
    export_dir = getattr(cfg, "FOURSQUARE_EXPORT_DIR", "")
    if not export_dir:
        print("FOURSQUARE_EXPORT_DIR not set — skipping Foursquare import.")
        return
    from import_foursquare import parse
    parse(export_dir, cfg.DATA_DIR)


def step_correlate(cfg):
    from correlate import run as corr_run
    corr_run(cfg.DATA_DIR)


def step_dashboard(cfg):
    from generate_dashboard import run as dash_run
    dash_run(cfg.DATA_DIR)


STEP_FNS = {
    "lastfm":     step_lastfm,
    "spotify":    step_spotify,
    "foursquare": step_foursquare,
    "correlate":  step_correlate,
    "dashboard":  step_dashboard,
}

STEP_DESCRIPTIONS = {
    "lastfm":     "Import Last.fm CSV export",
    "spotify":    "Import Spotify extended streaming history",
    "foursquare": "Import Foursquare checkin export + geocode",
    "correlate":  "Correlate scrobbles with checkins",
    "dashboard":  "Generate HTML dashboard",
}


def main():
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cfg = load_config()
    os.makedirs(cfg.DATA_DIR, exist_ok=True)

    if args:
        for step in args:
            if step not in STEP_FNS:
                print(f"Unknown step: {step!r}")
                print(f"Valid steps: {', '.join(STEPS)}")
                sys.exit(1)
        for step in args:
            print(f"\n{'='*60}")
            print(f"  {STEP_DESCRIPTIONS[step]}")
            print(f"{'='*60}")
            STEP_FNS[step](cfg)
        return

    # Full pipeline
    print("checkinsfm — running full pipeline")
    print(f"  Data dir: {cfg.DATA_DIR}")
    print()

    for step in STEPS:
        print(f"\n{'='*60}")
        print(f"  Step: {STEP_DESCRIPTIONS[step]}")
        print(f"{'='*60}")
        STEP_FNS[step](cfg)

    print("\n✓  Pipeline complete.")


if __name__ == "__main__":
    main()
