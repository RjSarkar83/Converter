"""AI (Adobe Illustrator) -> PDF converter.

Handles every AI flavour: modern PDF-compatible AI (lossless 1:1 copy)
and legacy PostScript AI v3-v10 (Ghostscript prepress render).
"""
from __future__ import annotations

import os
import re

import pymupdf

from .base import (ConvertResult, gs_available, gs_convert, mismatch_note, pdf_stats,
                   set_metadata, sniff)


def _try_pdf_open(path: str):
    try:
        doc = pymupdf.open(path)
        if len(doc) > 0:
            return doc
        doc.close()
    except Exception:
        pass
    return None


def _ai_version(head: bytes) -> str:
    try:
        txt = head.decode("latin-1", "replace")
        m = re.search(r"Adobe Illustrator[^0-9]{0,12}([\d.]+)", txt)
        if m:
            return m.group(1)
        m = re.search(r"%AI(\d+)_", txt)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def analyze(path: str) -> dict:
    size = os.path.getsize(path)
    sn = sniff(path)
    with open(path, "rb") as f:
        head = f.read(65536)
    is_pdf_compatible = head[:5] == b"%PDF-"
    ai_ver = _ai_version(head)
    if is_pdf_compatible:
        ver_label = "PDF-compatible" + (f" AI {ai_ver}" if ai_ver else "")
    else:
        ver_label = "legacy PostScript" + (f" AI {ai_ver}" if ai_ver else "")
    layers: list[dict] = []
    counts = {"text": 0, "bitmap": 0, "vector": 0, "shape": 0, "group": 0,
              "adjustment": 0, "smartobject": 0, "fill": 0, "dimension": 0,
              "hatch": 0, "block": 0, "other": 0}
    warnings: list[str] = []
    pages = 0
    page_sizes: list = []
    if is_pdf_compatible:
        doc = _try_pdf_open(path)
        if doc is not None:
            pages = len(doc)
            for i, page in enumerate(doc):
                try:
                    counts["vector"] += len(page.get_drawings())
                except Exception:
                    pass
                try:
                    t = page.get_text()
                    if t.strip():
                        counts["text"] += t.count("\n")
                except Exception:
                    pass
                try:
                    counts["bitmap"] += len(page.get_images(full=True))
                except Exception:
                    pass
                r = page.rect
                page_sizes.append([round(r.width, 1), round(r.height, 1)])
            try:
                for _x, oc in (doc.get_ocgs() or {}).items():
                    layers.append({"name": oc.get("name", "layer"), "kind": "group",
                                   "type": "OCG", "visible": bool(oc.get("on", True)),
                                   "depth": 0})
            except Exception:
                pass
            doc.close()
    else:
        warnings.append(
            "This .ai file is NOT PDF-compatible (legacy PostScript AI). "
            "It will be converted via Ghostscript — vectors/text preserved, "
            "AI layers cannot be recovered from legacy AI without Illustrator."
        )
        if not gs_available():
            warnings.append("Ghostscript is required for legacy AI and is not available!")
    mm = mismatch_note(".ai", sn)
    if mm:
        warnings.append(mm)
    return {
        "format": "AI",
        "format_label": "Adobe Illustrator (AI)",
        "version_label": ver_label,
        "sniff": sn,
        "pdf_compatible": is_pdf_compatible,
        "file_size": size,
        "pages": pages,
        "page_sizes": page_sizes,
        "layers_total": len(layers),
        "counts": counts,
        "layers": layers,
        "warnings": warnings,
        "notes": [
            "PDF-compatible AI keeps vectors, real text and PDF layers (OCG) 1:1.",
            "Legacy AI is rendered through Ghostscript at prepress quality.",
        ],
    }


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    options = options or {}
    dpi = int(options.get("dpi", 300) or 300)
    papersize = options.get("papersize", "") or ""
    warnings: list[str] = []

    doc = _try_pdf_open(path)
    if doc is not None:
        # Direct 1:1 — preserves vectors, text AND existing PDF layers
        n_ocg = len(doc.get_ocgs() or {})
        doc.save(out_pdf, garbage=3, deflate=True)
        doc.close()
        engine = "direct PDF-compatible copy (lossless, layers preserved)"
        if n_ocg:
            warnings.append(f"Preserved {n_ocg} embedded PDF layer(s) (OCG).")
    else:
        ok, log = gs_convert(path, out_pdf, dpi=dpi,
                             crop_bbox=(papersize == ""),
                             papersize=papersize, timeout=240)
        if not ok:
            raise RuntimeError(f"Ghostscript conversion failed: {log[-800:]}")
        engine = f"Ghostscript pdfwrite (prepress, {dpi} dpi)"
        if "warn" in log.lower():
            warnings.append("Ghostscript reported warnings (often font substitution) — "
                            "install original fonts for exact match.")

    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "AI")
    stats = pdf_stats(out_pdf)
    report = {"engine": engine, "warnings": warnings, "notes": [], **stats}
    return ConvertResult(out_pdf, report)
