"""EPS -> PDF converter via Ghostscript (vectors + real text preserved)."""
from __future__ import annotations

import os
import re

import pymupdf

from .base import (ConvertResult, gs_available, gs_convert, mismatch_note, pdf_stats,
                   set_metadata, sniff)


def _parse_header(path: str) -> dict:
    info: dict = {"bbox": None, "creator": "", "title": "", "fonts": [],
                  "pages": 1, "language_level": "", "epsf_version": "",
                  "dos_binary": False}
    try:
        with open(path, "rb") as f:
            raw = f.read(16384)
        if raw[:4] == b"\xc5\xd0\xd3\xc6":
            info["dos_binary"] = True
            # DOS EPS: PS starts at offset in header
            import struct as _st
            try:
                ps_off = _st.unpack("<I", raw[4:8])[0]
                with open(path, "rb") as f2:
                    f2.seek(ps_off)
                    raw = f2.read(16384)
            except Exception:
                pass
        head = raw.decode("latin-1", "replace")
        m0 = re.search(r"%!PS-Adobe-([\d.]+)\s+EPSF-([\d.]+)", head)
        if m0:
            info["epsf_version"] = m0.group(2)
        m = re.search(r"%%BoundingBox:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", head)
        if m:
            info["bbox"] = [int(x) for x in m.groups()]
        for key, pat in (("creator", r"%%Creator:\s*(.+)"),
                         ("title", r"%%Title:\s*(.+)"),
                         ("language_level", r"%%LanguageLevel:\s*(\d+)"),
                         ("pages", r"%%Pages:\s*(\d+)")):
            mm = re.search(pat, head)
            if mm:
                info[key] = mm.group(1).strip()[:120]
        fm = re.search(r"%%DocumentFonts:\s*(.+)", head)
        if fm:
            info["fonts"] = fm.group(1).strip().split()[:20]
        else:
            fonts = set(re.findall(r"/([A-Za-z][A-Za-z0-9+\-]*)\s+findfont", head))
            info["fonts"] = sorted(fonts)[:20]
        # embedded preview?
        info["has_preview"] = ("%%BeginPreview" in head or "%%BeginEPSF" in head)
    except Exception:
        pass
    return info


def analyze(path: str) -> dict:
    warnings: list[str] = []
    if not gs_available():
        warnings.append("Ghostscript is required for EPS and is not available!")
    hdr = _parse_header(path)
    layers: list[dict] = []
    if hdr.get("bbox"):
        x1, y1, x2, y2 = hdr["bbox"]
        layers.append({"name": f"Artwork ({x2-x1}×{y2-y1} pt)", "kind": "vector",
                       "type": "EPS", "visible": True, "depth": 0,
                       "bbox": hdr["bbox"]})
    if hdr.get("fonts"):
        layers.append({"name": f"Fonts: {', '.join(hdr['fonts'][:6])}"
                               + ("…" if len(hdr["fonts"]) > 6 else ""),
                       "kind": "text", "type": "FontList", "visible": True, "depth": 0})
    sn = sniff(path)
    parts = []
    if hdr.get("epsf_version"):
        parts.append(f"EPSF {hdr['epsf_version']}")
    if hdr.get("language_level"):
        parts.append(f"Level {hdr['language_level']}")
    if hdr.get("dos_binary"):
        parts.append("DOS binary")
        warnings.append("DOS binary EPS (with low-res preview) — vectors are rendered "
                        "fresh; the embedded preview is ignored.")
    if sn.get("kind") == "pdf":
        parts.append("actually PDF — direct copy")
    mm = mismatch_note(".eps", sn)
    if mm:
        warnings.append(mm)
    return {
        "format": "EPS",
        "format_label": "Encapsulated PostScript (EPS)",
        "version_label": " · ".join(parts) if parts else "EPS (auto)",
        "sniff": sn,
        "file_size": os.path.getsize(path),
        "header": hdr,
        "layers_total": len(layers),
        "counts": {"text": 1 if hdr.get("fonts") else 0, "bitmap": 0, "vector": 1,
                   "shape": 0, "group": 0, "adjustment": 0, "smartobject": 0,
                   "fill": 0, "dimension": 0, "hatch": 0, "block": 0, "other": 0},
        "layers": layers,
        "fonts": hdr.get("fonts", []),
        "warnings": warnings,
        "notes": [
            "Converted at prepress quality — vectors stay vector, text stays real text.",
            "Default crops the page exactly to the EPS BoundingBox (exact artwork size).",
        ],
    }


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    options = options or {}
    dpi = int(options.get("dpi", 300) or 300)
    papersize = options.get("papersize", "") or ""  # "" = EPSCrop bbox
    warnings: list[str] = []
    # Mislabelled .eps that is really a PDF (common!) — lossless direct copy
    if sniff(path).get("kind") == "pdf":
        try:
            doc = pymupdf.open(path)
            n_ocg = len(doc.get_ocgs() or {})
            doc.save(out_pdf, garbage=3, deflate=True)
            doc.close()
            set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "EPS-as-PDF")
            stats = pdf_stats(out_pdf)
            if n_ocg:
                warnings.append(f"Preserved {n_ocg} embedded PDF layer(s).")
            return ConvertResult(out_pdf, {
                "engine": "direct PDF copy (file is PDF despite .eps name)",
                "warnings": warnings, "notes": [], **stats})
        except Exception:
            pass  # fall through to Ghostscript
    ok, log = gs_convert(path, out_pdf, dpi=dpi,
                         crop_bbox=(papersize == ""),
                         papersize=papersize, timeout=240)
    if not ok:
        raise RuntimeError(f"Ghostscript conversion failed: {log[-800:]}")
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "EPS")
    stats = pdf_stats(out_pdf)
    if "substitut" in log.lower() or "cannot embed" in log.lower():
        warnings.append("A font was substituted or could not be embedded — "
                        "install the original font for exact match.")
    report = {
        "engine": f"Ghostscript pdfwrite (prepress, {dpi} dpi"
                  + (", EPSCrop bbox)" if not papersize else f", fit {papersize})"),
        "warnings": warnings,
        "notes": [],
        "log_tail": log[-600:],
        **stats,
    }
    return ConvertResult(out_pdf, report)
