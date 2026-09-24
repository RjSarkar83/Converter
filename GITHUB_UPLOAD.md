# ArtViSiON — GitHub Pages (online only)

Repo: https://github.com/rjsarkar83/Converter  
Live: https://rjsarkar83.github.io/Converter/

The converter now runs **in the browser**. No `python app.py`. Files never leave the device.

## Required GitHub settings

1. Upload the **`docs/`** folder (must include `index.html`, `logo.png`, `fonts/`, `vendor/`).
2. **Delete** any **root** `index.html` (old double-studio landing).
3. **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main**
   - Folder: **`/docs`**  ← this is required
4. Wait ~1–2 minutes, then hard-refresh the site.

Relative paths (`vendor/`, `fonts/`, `logo.png`) match project URL `/Converter/`.

## What works online

| Input | Result |
|---|---|
| JPG, PNG, WEBP, GIF, BMP | PDF page (pdf-lib) |
| SVG | Rasterized PDF |
| PDF | Pass-through download |
| Photos (Vectorize tab) | B&W SVG (ImageTracer) |
| Images (Color Lab) | CMYK-proof JPEG |

**Not in the browser:** CDR, PSD, AI, EPS, DXF (need Corel / Adobe / LibreOffice). Export PDF or SVG from those apps, then convert here.

## Zip

Use `ArtViSiON-2.0-github.zip`. Unzip, then push `docs/` as above.
