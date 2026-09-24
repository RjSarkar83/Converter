# ArtViSiON 2.0 — 100% Offline Professional Use 💻🔌

**Short answer: Haan!** ArtViSiON poori tarah **offline** chalta hai.
Install ke baad internet ki **zero zaroorat** — saara kaam aapke apne computer par hota hai.

## Proof: kuch bhi internet par nahi jaata

| Cheez | Kahan chalti hai |
|---|---|
| PDF convert (PSD·AI·CDR·EPS·SVG·TIFF·DXF) | Local engines: Ghostscript / LibreOffice / Python |
| Vectorize (JPG/PNG → SVG+PDF) | Local: VTracer (fallback: Potrace) |
| Color Lab (RGB ⇄ CMYK) | Local: ICC profiles jo `profiles/` folder me bundled hain |
| Web UI | Local server `http://127.0.0.1:5000` — ye page bhi aapke PC se aata hai |
| Aapki files | **Kahin upload nahi hoti** — `jobs/` folder me local rehti hain |

Code me koi online API, cloud call, ya CDN link nahi hai — sab kuch single `index.html`
(images/fonts sab embedded) + local Python server hai.

## Quality: professional / press-ready 🖨️

- **Vectors + text preserved** — jahan possible hai wahan rasterize nahi hota,
  lines/text PDF me asli vector bankar jaate hain (zoom par bhi sharp).
- **Ghostscript `/prepress`** settings — print-grade PDF output.
- **PSD layers → PDF layers (OCG)** — layered mode me saari layers alag-alag
  PDF layers bankar aati hain; flatten mode me 300 DPI option.
- **Real ICC press profiles** — U.S. Web Coated (SWOP) v2 + sRGB bundled,
  CMYK me ink-limit (TAC) report ke saath.
- Honest note: CDR files LibreOffice engine se render hote hain (CorelDRAW ka
  closed format hai) — output press-ready hota hai, par CorelDRAW khud jaisa
  1:1 pixel-proof koi bhi third-party tool guarantee nahi kar sakta.

## Offline install (sirf ek baar)

**1. Python 3.10+** install karo ([python.org](https://www.python.org/downloads/)
— Windows par "Add to PATH" tick karna).

**2. System engines** (PDF quality ke liye zaroori):

- **Ubuntu/Debian:**
  ```bash
  sudo apt install ghostscript libreoffice-core potrace
  ```
- **Windows:** install karo aur PATH me rakho —
  [Ghostscript](https://ghostscript.com/releases/gsdnld.html) (`gswin64c.exe`),
  [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) (`soffice.exe`),
  [Potrace](http://potrace.sourceforge.net/#downloading) (`potrace.exe`).
- **macOS:** `brew install ghostscript libreoffice potrace`

**3. Python packages:**
```bash
pip install -r requirements.txt
```

## Chalana (roz ka kaam) ▶️

```bash
python app.py
```
Browser me kholo: **http://127.0.0.1:5000**

One-click shortcut: `run_local.sh` (Mac/Linux) ya `run_local.bat` (Windows)
par double-click — pehli baar packages bhi khud install kar lega.

## Folder map 🗂️

```
pdf-converter/
├── app.py              ← server (python app.py)
├── convert.py          ← CLI batch convert (bina browser ke)
├── requirements.txt    ← python packages
├── profiles/           ← ICC press profiles (offline, bundled)
├── static/logo.png     ← ArtViSiON logo
├── samples/            ← demo files (try karne ke liye)
├── jobs/               ← aapki files + outputs (local, auto-safai)
└── templates/index.html← poori UI (single file, embedded assets)
```

## Pro tips ⭐

- **CLI batch:** `python convert.py input.psd output.pdf --psd-mode layered`
- **Bade print jobs:** flatten mode me DPI 300 rakho; EPS me A4/Letter fit use karo.
- **Client files safe:** `jobs/` me rehti hain, net par kabhi nahi jaati —
  NDA/client work ke liye safe.
