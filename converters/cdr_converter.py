"""CDR (CorelDRAW) -> PDF converter via LibreOffice + libcdr."""
from __future__ import annotations

import os
import struct

from .base import (ConvertResult, mismatch_note, pdf_stats, set_metadata,
                   soffice_available, soffice_convert, sniff)


def _riff_info(path: str) -> dict:
    """Best-effort parse of RIFF CDR header (CDR v7+)."""
    info: dict = {"container": "unknown"}
    try:
        with open(path, "rb") as f:
            data = f.read(64)
        if len(data) >= 12 and data[0:4] == b"RIFF":
            info["container"] = "RIFF"
            info["riff_size"] = struct.unpack("<I", data[4:8])[0]
            info["riff_type"] = data[8:12].decode("ascii", "replace")
            # CDR version stamp often follows
            tail = data[12:32].decode("ascii", "replace").strip("\x00 ")
            if tail:
                info["stamp"] = "".join(c for c in tail if 32 <= ord(c) < 127)[:24]
        elif data[:4] == b"MSCF":
            info["container"] = "MSCF (zip-like, CDR X4+?)"
    except Exception:
        pass
    return info


CDR_FCC = {"CDR3": "v3", "CDR4": "v4", "CDR5": "v5", "CDR6": "v6",
             "CDR7": "v7", "CDR8": "v8", "CDR9": "v9", "CDRA": "v10",
             "CDRB": "v11", "CDRC": "v12", "CDRD": "X3", "CDRE": "X4",
             "CDRF": "X5", "CDRG": "X6", "CDRH": "X7",
             "cdr4": "v4", "cdr5": "v5", "cdr6": "v6", "cdr7": "v7"}


def analyze(path: str) -> dict:
    warnings: list[str] = []
    if not soffice_available():
        warnings.append("LibreOffice is required for CDR and is not available!")
    sn = sniff(path)
    riff = _riff_info(path)
    fcc = (riff.get("riff_type") or "").strip()
    if sn.get("kind") == "cdr_zip":
        ver_label = "new CorelDRAW (ZIP container, 2017+)"
        warnings.append("New ZIP-based CDR detected — LibreOffice support for the newest "
                        "Corel versions is partial. If conversion fails, open in CorelDRAW "
                        "and re-save as an older CDR (X7) or export PDF directly.")
    elif fcc:
        ver_label = f"CorelDRAW {CDR_FCC.get(fcc, fcc)} (RIFF)"
    else:
        ver_label = "CDR (version auto)"
    mm = mismatch_note(".cdr", sn)
    if mm:
        warnings.append(mm)
    notes = [
        "Print-grade CDR → PDF (CloudConvert-class): LibreOffice Draw + libcdr, then Ghostscript /prepress.",
        "Vectors and live text stay vector — not flattened to pixels unless you pick Rasterize.",
        "Corel-only effects (lenses, blends, mesh fills) are approximated by libcdr.",
        "Install the original fonts on this PC for closest text match.",
    ]
    return {
        "format": "CDR",
        "format_label": "CorelDRAW (CDR)",
        "version_label": ver_label,
        "sniff": sn,
        "file_size": os.path.getsize(path),
        "container": riff,
        "layers_total": 0,
        "counts": {"text": 0, "bitmap": 0, "vector": 0, "shape": 0, "group": 0,
                   "adjustment": 0, "smartobject": 0, "fill": 0, "dimension": 0,
                   "hatch": 0, "block": 0, "other": 0},
        "layers": [],
        "warnings": warnings,
        "notes": notes + [
            "Layer inventory for CDR is extracted from the converted PDF "
            "(vectors / text / images per page)."
        ],
    }


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    options = options or {}
    timeout = int(options.get("timeout", 240) or 240)
    dpi = int(options.get("dpi", 300) or 300)
    quality = str(options.get("quality", "print") or "print")  # print | screen | raster
    lossless = quality != "screen"
    sn = sniff(path)

    from .base import gs_available, gs_prepress_polish, soffice_pdf_filter
    import shutil

    outdir = os.path.dirname(out_pdf) or "."
    filt = soffice_pdf_filter(
        "draw",
        dpi=max(dpi, 300) if quality == "print" else dpi,
        lossless=lossless,
    )
    pdf, log = soffice_convert(path, outdir, timeout=timeout, filter_spec=filt)
    if not pdf or not os.path.exists(pdf):
        pdf, log2 = soffice_convert(path, outdir, timeout=timeout, filter_spec="pdf:draw_pdf_Export")
        log = (log or "") + "\n" + (log2 or "")
    if not pdf or not os.path.exists(pdf):
        pdf, log3 = soffice_convert(path, outdir, timeout=timeout, filter_spec="pdf")
        log = (log or "") + "\n" + (log3 or "")
    if not pdf or not os.path.exists(pdf):
        hint = ""
        if sn.get("kind") == "cdr_zip":
            hint = (" This looks like a newest-version CorelDRAW file (ZIP container). "
                    "Fix: open it in CorelDRAW and File → Save As → CDR version X7 (or older), "
                    "then convert again — or export PDF directly from CorelDRAW.")
        elif sn.get("kind") not in ("cdr_riff", "cdr_zip"):
            hint = (f" The file content looks like {sn.get('kind')} rather than CDR — "
                    f"it may be renamed or corrupt.")
        raise RuntimeError(f"LibreOffice conversion failed.{hint} {(log or '')[-700:]}")
    if os.path.abspath(pdf) != os.path.abspath(out_pdf):
        try:
            os.replace(pdf, out_pdf)
        except Exception:
            shutil.copyfile(pdf, out_pdf)

    engine = "LibreOffice Draw + libcdr"
    notes = ["Vectors and layout preserved from the CorelDRAW document (libcdr)."]

    if quality == "raster" and gs_available():
        tmp = out_pdf + ".raster.pdf"
        try:
            import pymupdf
            zoom = dpi / 72.0
            mat = pymupdf.Matrix(zoom, zoom)
            src = pymupdf.open(out_pdf)
            dst = pymupdf.open()
            for page in src:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                r = page.rect
                npg = dst.new_page(width=r.width, height=r.height)
                npg.insert_image(r, pixmap=pix)
            dst.save(tmp, garbage=4, deflate=True)
            dst.close()
            src.close()
            os.replace(tmp, out_pdf)
            engine += " → rasterized pages"
            notes.append(f"Rasterized at {dpi} DPI (CloudConvert-style flatten). Vectors are pixels now.")
        except Exception as e:
            notes.append(f"Rasterize skipped: {e}")
    elif quality == "print" and gs_available():
        tmp = out_pdf + ".prepress.pdf"
        ok, glog = gs_prepress_polish(out_pdf, tmp, dpi=dpi, timeout=timeout)
        log = (log or "") + "\n" + (glog or "")
        if ok:
            os.replace(tmp, out_pdf)
            engine += " → Ghostscript /prepress"
            notes.append("Ghostscript prepress pass: fonts embedded, images lossless, vectors kept.")
        else:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            notes.append("Ghostscript polish skipped — using LibreOffice PDF.")

    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "CDR")
    stats = pdf_stats(out_pdf)
    warnings: list[str] = []
    if stats.get("text_chars", 0) == 0 and stats.get("vectors", 0) > 0:
        warnings.append("No selectable text detected — text may have been converted to curves "
                        "(usually missing fonts).")
    report = {
        "engine": engine,
        "warnings": warnings,
        "notes": notes,
        "quality": quality,
        "dpi": dpi,
        "log_tail": (log or "")[-600:],
        **stats,
    }
    return ConvertResult(out_pdf, report)
