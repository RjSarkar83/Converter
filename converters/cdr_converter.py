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
        "CDR is converted with LibreOffice Draw (libcdr) — vectors and text are preserved.",
        "Exact Corel-only effects (lenses, blends, fountain fills) are approximated.",
        "Install the original fonts for closest text match.",
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
    sn = sniff(path)
    pdf, log = soffice_convert(path, os.path.dirname(out_pdf) or ".", timeout=timeout)
    if not pdf or not os.path.exists(pdf):
        hint = ""
        if sn.get("kind") == "cdr_zip":
            hint = (" This looks like a newest-version CorelDRAW file (ZIP container). "
                    "Fix: open it in CorelDRAW and File → Save As → CDR version X7 (or older), "
                    "then convert again — or export PDF directly from CorelDRAW.")
        elif sn.get("kind") not in ("cdr_riff", "cdr_zip"):
            hint = (f" The file content looks like {sn.get('kind')} rather than CDR — "
                    f"it may be renamed or corrupt.")
        raise RuntimeError(f"LibreOffice conversion failed.{hint} {log[-700:]}")
    if os.path.abspath(pdf) != os.path.abspath(out_pdf):
        try:
            os.replace(pdf, out_pdf)
        except Exception:
            # different names — copy
            import shutil
            shutil.copyfile(pdf, out_pdf)
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "CDR")
    stats = pdf_stats(out_pdf)
    warnings: list[str] = []
    if stats.get("text_chars", 0) == 0 and stats.get("vectors", 0) > 0:
        warnings.append("No selectable text detected — text may have been converted to curves "
                        "(usually missing fonts).")
    report = {
        "engine": "LibreOffice Draw + libcdr (headless)",
        "warnings": warnings,
        "notes": ["Vectors and layout preserved from CorelDRAW document."],
        "log_tail": log[-600:],
        **stats,
    }
    return ConvertResult(out_pdf, report)
