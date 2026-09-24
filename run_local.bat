@echo off
REM ArtViSiON 2.0 — one-click local starter (Windows). 100%% offline after install.
cd /d %~dp0
python -c "import flask" 2>nul || (echo Installing packages - one time, needs internet... & pip install -r requirements.txt)
echo ArtViSiON 2.0 by RJ Sarkar - open http://127.0.0.1:5000
python app.py
pause
