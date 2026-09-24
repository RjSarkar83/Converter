#!/usr/bin/env bash
# ArtViSiON 2.0 — one-click local starter (Mac/Linux). 100% offline after install.
cd "$(dirname "$0")"
python3 -c "import flask" 2>/dev/null || { echo "Installing packages (one time, needs internet)..."; pip install -r requirements.txt; }
echo "ArtViSiON 2.0 by RJ Sarkar — open http://127.0.0.1:5000"
python3 app.py
