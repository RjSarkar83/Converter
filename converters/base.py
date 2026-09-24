"""Shared helpers for all converters."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import warnings

warnings.filterwarnings("ignore")

import pymupdf  # PyMuPDF

PRODUCER = "ArtViSiON 2.0 by RJ Sarkar"


# ---------------------------------------------------------------- models
class AnalyzeResult(dict):
    """Dict subclass for clarity."""


class ConvertResult:
    def __init__(self, pdf_path: str, report: dict):
        self.pdf_path = pdf_path
        self.report = report


# ---------------------------------------------------------------- process
def run(cmd: list[str], timeout: int = 120, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )


def which(binary: str) -> str | None:
    return shutil.which(binary)


# ---------------------------------------------------------------- pdf utils
def pdf_stats(pdf_path: str) -> dict:
    """Collect vector/text/layer stats from a PDF."""
    info: dict = {"pages": 0, "vectors": 0, "text_chars": 0, "images": 0,
                  "ocg_layers": [], "page_sizes": [], "pdf_version": ""}
    try:
        doc = pymupdf.open(pdf_path)
        info["pages"] = len(doc)
        info["pdf_version"] = f"{doc.pdf_version():.1f}" if hasattr(doc, "pdf_version") else ""
        for page in doc:
            try:
                info["vectors"] += len(page.get_drawings())
            except Exception:
                pass
            try:
                info["text_chars"] += len(page.get_text())
            except Exception:
                pass
            try:
                info["images"] += len(page.get_images(full=True))
            except Exception:
                pass
            r = page.rect
            info["page_sizes"].append([round(r.width, 1), round(r.height, 1)])
        try:
            ocgs = doc.get_ocgs() or {}
            for _xref, oc in ocgs.items():
                info["ocg_layers"].append({"name": oc.get("name", "layer"), "on": bool(oc.get("on", True))})
        except Exception:
            pass
        doc.close()
    except Exception as e:
        info["error"] = str(e)
    return info


def set_metadata(pdf_path: str, title: str, source: str = ""):
    try:
        doc = pymupdf.open(pdf_path)
        doc.set_metadata({
            "title": title,
            "producer": PRODUCER,
            "creator": f"{PRODUCER} ({source})" if source else PRODUCER,
        })
        doc.save(pdf_path + ".meta.pdf", garbage=3, deflate=True)
        doc.close()
        os.replace(pdf_path + ".meta.pdf", pdf_path)
    except Exception:
        pass


def sanitize_name(name: str, default: str = "layer") -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()
    return name[:80] if name else default


def px_to_pt(px: float, dpi: float) -> float:
    return px * 72.0 / dpi


# ---------------------------------------------------------------- ghostscript
def gs_available() -> bool:
    return which("gs") is not None


def gs_convert(src: str, dst: str, dpi: int = 300, crop_bbox: bool = True,
               papersize: str = "", timeout: int = 180) -> tuple[bool, str]:
    """Convert PostScript/EPS/AI -> PDF via Ghostscript. Returns (ok, log)."""
    if not gs_available():
        return False, "Ghostscript (gs) not installed."
    cmd = ["gs", "-dQUIET", "-dSAFER", "-dBATCH", "-dNOPAUSE",
           "-sDEVICE=pdfwrite",
           "-dCompatibilityLevel=1.7",
           "-dPDFSETTINGS=/prepress",
           f"-r{dpi}",
           "-dHaveTrueTypes=true", "-dEmbedAllFonts=true",
           "-dSubsetFonts=false",
           "-dAutoRotatePages=/None",
           "-dCannotEmbedFontPolicy=/Warning",
           ]
    if crop_bbox and not papersize:
        cmd.append("-dEPSCrop")
    elif papersize:
        cmd += ["-dFIXEDMEDIA", "-dPDFFitPage", f"-sPAPERSIZE={papersize}"]
    cmd += [f"-sOutputFile={dst}", src]
    try:
        p = run(cmd, timeout=timeout)
        log = (p.stdout or "") + (p.stderr or "")
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            return True, log[-1500:]
        return False, (log or "Ghostscript produced no output.")[-1500:]
    except subprocess.TimeoutExpired:
        return False, f"Ghostscript timed out after {timeout}s."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- libreoffice
def soffice_available() -> bool:
    return which("soffice") is not None


_LO_NOISE = ("javaldx", "Warning: failed", "Failed to load", "no suitable windowing",
             "libpng warning", "Session D-BUS", "dbus", "XDG_RUNTIME", "Gdk-")


def _clean_lo_log(log: str) -> str:
    """Strip LibreOffice environment-noise lines so user-facing errors read clean."""
    lines = [ln for ln in (log or "").splitlines()
             if ln.strip() and not any(n.lower() in ln.lower() for n in _LO_NOISE)]
    return "\n".join(lines)[-1200:]


def soffice_pdf_filter(kind: str = "draw", dpi: int = 600, lossless: bool = True) -> str:
    """LibreOffice PDF export filter (Draw/Impress). High-quality, no downsample."""
    dpi = max(72, min(int(dpi or 600), 1200))
    q = 100 if lossless else 92
    # JSON FilterData — LibreOffice 7+
    data = (
        '{"UseLosslessCompression":{"type":"boolean","value":"%s"},'
        '"Quality":{"type":"long","value":"%d"},'
        '"ReduceImageResolution":{"type":"boolean","value":"false"},'
        '"MaxImageResolution":{"type":"long","value":"%d"},'
        '"SelectPdfVersion":{"type":"long","value":"0"},'
        '"UseTaggedPDF":{"type":"boolean","value":"false"},'
        '"ExportFormFields":{"type":"boolean","value":"false"}}'
        % ("true" if lossless else "false", q, dpi)
    )
    engine = "draw_pdf_Export" if kind == "draw" else "writer_pdf_Export"
    return f"pdf:{engine}:{data}"


def gs_prepress_polish(src_pdf: str, dst_pdf: str, dpi: int = 300,
                       timeout: int = 180) -> tuple[bool, str]:
    """Re-write PDF with Ghostscript /prepress — embed fonts, keep vectors, no downsample."""
    if not gs_available():
        return False, "Ghostscript not installed."
    dpi = max(150, min(int(dpi or 300), 1200))
    cmd = [
        "gs", "-dQUIET", "-dSAFER", "-dBATCH", "-dNOPAUSE",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dPDFSETTINGS=/prepress",
        "-dEmbedAllFonts=true", "-dSubsetFonts=true",
        "-dCompressFonts=true",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dDownsampleColorImages=false",
        "-dDownsampleGrayImages=false",
        "-dDownsampleMonoImages=false",
        "-dAutoFilterColorImages=false",
        "-dAutoFilterGrayImages=false",
        "-dColorImageFilter=/FlateEncode",
        "-dGrayImageFilter=/FlateEncode",
        "-dCannotEmbedFontPolicy=/Warning",
        f"-dColorImageResolution={dpi}",
        f"-dGrayImageResolution={dpi}",
        f"-dMonoImageResolution={dpi}",
        f"-sOutputFile={dst_pdf}",
        src_pdf,
    ]
    try:
        p = run(cmd, timeout=timeout)
        log = (p.stdout or "") + (p.stderr or "")
        if os.path.isfile(dst_pdf) and os.path.getsize(dst_pdf) > 100:
            return True, log[-800:]
        return False, log[-800:] or "Ghostscript produced no PDF."
    except subprocess.TimeoutExpired:
        return False, f"Ghostscript timed out after {timeout}s."
    except Exception as e:
        return False, str(e)


def soffice_convert(src: str, outdir: str, timeout: int = 240,
                    filter_spec: str = "pdf") -> tuple[str | None, str]:
    """Convert via LibreOffice headless. Returns (pdf_path or None, log)."""
    if not soffice_available():
        return None, "LibreOffice (soffice) not installed."
    os.makedirs(outdir, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    base = os.path.splitext(os.path.basename(src))[0]
    # LibreOffice writes <base>.pdf into outdir
    cmd = ["soffice", "--headless", "--nologo", "--nolockcheck",
           f"-env:UserInstallation=file://{profile}",
           "--convert-to", filter_spec, "--outdir", outdir, src]
    log = ""
    try:
        p = run(cmd, timeout=timeout)
        log = _clean_lo_log((p.stdout or "") + (p.stderr or ""))
    except subprocess.TimeoutExpired:
        shutil.rmtree(profile, ignore_errors=True)
        return None, f"LibreOffice timed out after {timeout}s."
    except Exception as e:
        shutil.rmtree(profile, ignore_errors=True)
        return None, str(e)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    # find output (name may vary in case)
    for f in os.listdir(outdir):
        if f.lower().endswith(".pdf") and os.path.splitext(f)[0].lower() == base.lower():
            return os.path.join(outdir, f), log
    # fallback: newest pdf
    pdfs = sorted(
        (os.path.join(outdir, f) for f in os.listdir(outdir) if f.lower().endswith(".pdf")),
        key=os.path.getmtime,
    )
    if pdfs:
        return pdfs[-1], log
    return None, log or "LibreOffice produced no PDF."


# ---------------------------------------------------------------- misc
def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


LAYER_KINDS = ("text", "bitmap", "vector", "shape", "group", "adjustment",
               "smartobject", "fill", "dimension", "hatch", "block", "other")


def empty_counts() -> dict:
    return {k: 0 for k in LAYER_KINDS}


# ============================================================ version sniff
TIFF_COMPRESSION = {1: "Uncompressed", 2: "CCITT G3", 3: "CCITT G3", 4: "CCITT G4",
                    5: "LZW", 6: "OJPEG (old-JPEG)", 7: "JPEG", 8: "ZIP/Deflate",
                    32766: "NeXT", 32771: "CCIRLEW", 32773: "PackBits",
                    32809: "ThunderScan", 32895: "IT8CTPAD", 32896: "IT8LW",
                    32897: "IT8MP", 32898: "IT8BL", 32908: "PixarFilm",
                    32909: "PixarLog", 32946: "DeflatePK", 32947: "DCS",
                    34661: "JBIG", 34676: "SGILog", 34677: "SGILog24",
                    34712: "JPEG2000", 34713: "Nikon NEF", 34715: "JBIG2"}

DXF_VERSIONS = {"AC1006": "R10", "AC1009": "R11/R12", "AC1012": "R13",
                "AC1014": "R14", "AC1015": "R2000", "AC1018": "R2004",
                "AC1021": "R2007", "AC1024": "R2010", "AC1027": "R2013",
                "AC1032": "R2018"}


def sniff(path: str) -> dict:
    """Detect ACTUAL file type from magic bytes (extension may lie).

    Returns {kind, detail}. kind in: pdf, ps, eps, ai_pdf, cdr_riff, cdr_zip,
    zip, tiff, bigtiff, psd, psb, png, jpeg, gif, bmp, webp, svg, svgz,
    dxf, dxf_binary, dwg, unknown.
    """
    out = {"kind": "unknown", "detail": ""}
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except Exception as e:
        out["detail"] = str(e)
        return out
    if len(head) < 4:
        out["detail"] = "file too small"
        return out

    def has(s: bytes) -> bool:
        return s in head

    # --- PDF ---
    if head[:5] == b"%PDF-":
        out["kind"] = "pdf"
        m = re.search(rb"%PDF-(\d\.\d)", head[:32])
        out["detail"] = f"v{m.group(1).decode()}" if m else ""
        if b"Adobe Illustrator" in head[:20000]:
            out["kind"] = "ai_pdf"
            m2 = re.search(rb"Adobe Illustrator[^0-9]*(\d+)", head[:20000])
            out["detail"] = f"AI {m2.group(1).decode()}" if m2 else "Illustrator"
        return out
    # --- PostScript / EPS / legacy AI ---
    if head[:4] == b"%!PS" or head[:11] == b"%!PS-Adobe-":
        if b"EPSF" in head[:64]:
            out["kind"] = "eps"
            ll = re.search(rb"%%LanguageLevel:\s*(\d+)", head)
            out["detail"] = f"Level {ll.group(1).decode()}" if ll else "EPSF"
        else:
            out["kind"] = "ps"
            if b"Illustrator" in head[:8000]:
                out["kind"] = "ai_ps"
                m = re.search(rb"Adobe Illustrator[^0-9]*([\d.]+)", head[:8000])
                out["detail"] = f"AI {m.group(1).decode()}" if m else "legacy AI"
        return out
    if head[:4] == b"\xc5\xd0\xd3\xc6":  # DOS EPS binary
        out["kind"] = "eps"
        out["detail"] = "DOS binary EPS (with preview)"
        return out
    # --- RIFF (CDR / WebP / AVI...) ---
    if head[:4] == b"RIFF" and len(head) >= 12:
        fcc = head[8:12]
        if fcc in (b"CDR9", b"CDRA", b"CDR8", b"CDR7", b"cdr7",
                   b"CDR6", b"CDR5", b"CDR4", b"CDR3") or fcc.startswith(b"CDR") \
           or fcc.startswith(b"cdr"):
            out["kind"] = "cdr_riff"
            out["detail"] = fcc.decode("ascii", "replace").strip()
            return out
        if fcc == b"WEBP":
            out["kind"] = "webp"
            return out
        out["kind"] = "riff"
        out["detail"] = fcc.decode("ascii", "replace")
        return out
    # --- ZIP (new CDR / Office / generic) ---
    if head[:4] == b"PK\x03\x04":
        out["kind"] = "zip"
        low = head.lower()
        if b"cdr" in low[:4000] or b"corel" in low[:4000]:
            out["kind"] = "cdr_zip"
            out["detail"] = "ZIP-based CDR (new Corel)"
        return out
    # --- TIFF ---
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        out["kind"] = "tiff"
        out["detail"] = "little-endian" if head[:2] == b"II" else "big-endian"
        return out
    if head[:4] in (b"II+\x00", b"MM\x00+"):
        out["kind"] = "bigtiff"
        out["detail"] = "BigTIFF (>4GB capable)"
        return out
    # --- PSD / PSB ---
    if head[:4] == b"8BPS" and len(head) >= 6:
        ver = int.from_bytes(head[4:6], "big")
        out["kind"] = "psb" if ver == 2 else "psd"
        out["detail"] = f"v{ver}" + (" (Large Document)" if ver == 2 else "")
        return out
    # --- rasters ---
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        out["kind"] = "png"
        return out
    if head[:3] == b"\xff\xd8\xff":
        out["kind"] = "jpeg"
        return out
    if head[:6] in (b"GIF87a", b"GIF89a"):
        out["kind"] = "gif"
        return out
    if head[:2] == b"BM":
        out["kind"] = "bmp"
        return out
    # --- gzip (SVGZ?) ---
    if head[:2] == b"\x1f\x8b":
        out["kind"] = "gzip"
        try:
            import gzip as _gz
            with _gz.open(path, "rb") as f:
                inner = f.read(2000)
            if b"<svg" in inner[:2000]:
                out["kind"] = "svgz"
                out["detail"] = "gzipped SVG"
        except Exception:
            pass
        return out
    # --- SVG (xml) ---
    low = head[:4000].lower()
    if b"<svg" in low:
        out["kind"] = "svg"
        m = re.search(rb"<svg[^>]*version=[\"']([\d.]+)[\"']", head[:4000])
        out["detail"] = f"v{m.group(1).decode()}" if m else ""
        if b"inkscape" in low:
            out["detail"] = (out["detail"] + " Inkscape").strip()
        return out
    # --- DXF / DWG ---
    if head[:20].startswith(b"AutoCAD Binary DXF"):
        out["kind"] = "dxf_binary"
        out["detail"] = "binary DXF"
        return out
    if b"AutoCAD Binary DWG" in head[:64] or head[:6] in (
            b"MC0.0", b"AC1.2", b"AC1.4", b"AC1.5"):
        out["kind"] = "dwg"
        out["detail"] = head[:12].decode("ascii", "replace")
        return out
    if b"$ACADVER" in head or (b"SECTION" in head[:2000] and b"ENTITIES" in head):
        out["kind"] = "dxf"
        m = re.search(rb"AC10\d\d", head)
        if m:
            code = m.group(0).decode()
            out["detail"] = f"{DXF_VERSIONS.get(code, code)} ({code})"
        return out
    return out


def mismatch_note(ext: str, sniffed: dict) -> str:
    """Human note when extension and content disagree (but handled)."""
    k = sniffed.get("kind", "")
    table = {".ai": ("pdf", "ai_pdf", "ai_ps", "ps"),
             ".eps": ("eps", "pdf", "ps"),
             ".cdr": ("cdr_riff", "cdr_zip", "zip", "riff"),
             ".psd": ("psd",), ".psb": ("psb", "psd"),
             ".svg": ("svg",), ".svgz": ("svgz", "gzip"),
             ".tif": ("tiff", "bigtiff"), ".tiff": ("tiff", "bigtiff"),
             ".dxf": ("dxf", "dxf_binary")}
    ok = table.get(ext.lower(), ())
    if k in ok or k == "unknown":
        return ""
    friendly = {"pdf": "a PDF file", "ai_pdf": "PDF-based Illustrator art",
                "ps": "a PostScript file", "ai_ps": "legacy Illustrator art",
                "eps": "an EPS file", "zip": "a ZIP-based file",
                "cdr_zip": "new-format CorelDRAW (ZIP)",
                "dxf_binary": "binary DXF", "dwg": "DWG (AutoCAD native)",
                "gzip": "a gzipped file"}.get(k, f"{k} content")
    return (f"Note: extension is {ext} but content looks like {friendly} — "
            f"handled automatically.")


# ============================================================ previews
def pil_thumb_b64(img, max_w: int = 440) -> str:
    """Pillow image -> base64 PNG data URI thumbnail."""
    import base64
    import io as _io
    try:
        im = img.copy()
        if max(im.size) > max_w:
            im.thumbnail((max_w, max_w))
        if im.mode in ("RGBA", "LA", "PA"):
            bg = __import__("PIL.Image", fromlist=["new"]).new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        buf = _io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def pdf_preview_b64(pdf_path: str, page_no: int = 0, max_w: int = 440) -> str:
    try:
        doc = pymupdf.open(pdf_path)
        if len(doc) == 0:
            return ""
        page = doc[min(page_no, len(doc) - 1)]
        zoom = max_w / max(1.0, page.rect.width)
        zoom = min(zoom, 3.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        import base64
        uri = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
        doc.close()
        return uri
    except Exception:
        return ""


def svg_preview_b64(svg_path: str, max_w: int = 440) -> str:
    try:
        doc = pymupdf.open(svg_path)
        if len(doc) == 0:
            return ""
        page = doc[0]
        zoom = max_w / max(1.0, page.rect.width or 1)
        zoom = min(max(zoom, 0.2), 3.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        import base64
        uri = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
        doc.close()
        return uri
    except Exception:
        return ""
