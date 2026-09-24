@echo off
REM PDFLayer Studio launcher (Windows)
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
echo.
echo ==============================================
echo   PDFLayer Studio running at:
echo   http://localhost:5000
echo   (band karne ke liye Ctrl+C dabao)
echo ==============================================
python app.py
pause
