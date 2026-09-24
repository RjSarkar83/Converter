# Upload ArtViSiON 2.0 to GitHub

Use the zip **`ArtViSiON-2.0-github.zip`** (same folder as this guide) **or** this `pdf-converter` project folder.

GitHub **does not run** the Python server for you. After clone, users still run `python app.py` on their PC. Do **not** enable GitHub Pages for this repo — Pages is static HTML only, so Analyze/Convert will fail there.

---

## Option A — GitHub website (no git command)

1. Sign in at [https://github.com](https://github.com/)
2. Click **+** (top right) → **New repository**
3. Repository name: `ArtViSiON` (or `ArtViSiON-2.0`)
4. Description (SEO):  
   `Offline PDF converter, photo vectorizer and RGB-CMYK color lab by RJ Sarkar/Designer`
5. Public or Private → **Create repository**
6. On the empty repo page choose **uploading an existing file**
7. Drag **all files inside the unzipped folder** (not the zip itself if you want a clean root)  
   Include: `app.py`, `README.md`, `requirements.txt`, `templates/`, `converters/`, `profiles/`, `samples/`, `static/`, `run_local.bat`, `run_local.sh`, `OFFLINE.md`, `convert.py`, `.gitignore`
8. Commit message: `ArtViSiON 2.0 by RJ Sarkar/Designer`
9. **Commit changes**

Unzip first:

```text
ArtViSiON-2.0-github.zip  →  extract  →  upload the inner files
```

File size: GitHub file limit is 100 MB. This repo is ~15 MB without `test/`. Fine.

---

## Option B — Git command line (best)

```bash
cd ArtViSiON-2.0          # unzipped folder
git init
git add .
git commit -m "ArtViSiON 2.0 by RJ Sarkar/Designer"
git branch -M main
git remote add origin https://github.com/YOUR_USER/ArtViSiON.git
git push -u origin main
```

Replace `YOUR_USER` with your GitHub username. Create the empty repo on GitHub first (no README on GitHub if you already have one locally).

---

## Repo settings (recommended)

| Setting | Value |
| --- | --- |
| About | Offline print studio: PSD/AI/CDR → PDF, JPG → SVG, RGB ⇄ CMYK |
| Topics | `pdf-converter`, `vectorizer`, `cmyk`, `psd`, `coreldraw`, `design-tools`, `offline` |
| Website | leave empty (or your domain later) |
| GitHub Pages | **Off** |

---

## What visitors should do

```bash
git clone https://github.com/YOUR_USER/ArtViSiON.git
cd ArtViSiON
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** — that is the real app. Drop files there.

If someone opens `templates/index.html` as a file, Analyze will fail. The UI must be served by `app.py`.
