#!/bin/bash
# Sync source Python files + template into docs/ for GitHub Pages deployment.
# Run this after making changes to correlate.py, generate_dashboard.py,
# or foursquare_template.html.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
DOCS="$DIR/docs"

mkdir -p "$DOCS"
cp "$DIR/correlate.py"            "$DOCS/correlate.py"
cp "$DIR/generate_dashboard.py"   "$DOCS/generate_dashboard.py"
cp "$DIR/foursquare_template.html" "$DOCS/template.html"

echo "Synced to docs/:"
ls -lh "$DOCS"
