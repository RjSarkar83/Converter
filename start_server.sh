#!/bin/bash
# PDFLayer Studio launcher (Linux/Mac)
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
echo ""
echo "=============================================="
echo "  PDFLayer Studio running at:"
echo "  http://localhost:5000"
echo "  (band karne ke liye Ctrl+C dabao)"
echo "=============================================="
python3 app.py
