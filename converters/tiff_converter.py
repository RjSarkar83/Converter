"""TIFF -> PDF converter (multi-page, resolution-aware)."""
from __future__ import annotations

import io
import os

import pymupdf
from PIL import Image

from .base import (ConvertResult, TIFF_COMPRESSION, mismatch_note, pdf_stats, px_to_pt,
                   run, set_metadata, sniff, which)


def _frame_compression(im) -> str:
    try:
        tag = im.tag_v2.get(259) if hasattr(im, "tag_v2") else None
        if tag is not None:
            return TIFF_COMPRESSION.get(int(tag), f"code {tag}")
    except Exception:
        pass
    return str(im.info.get("compression", "") or "unknown")


def analyze(path: str) -> dict:
    warnings: list[str] = []
    frames: list[dict] = []
    layers: list[dict] = []
    sn = sniff(path)
    try:
        im = Image.open(path)
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            try:
                im.seek(i)
                im.load()
            except Exception as e:
                warnings.append(f"Page {i+1} unreadable by Pillow ({e}) — will try fallback.")
                frames.append({"index": i, "size": [0, 0], "mode": "?",
                               "dpi": [None, None], "compression": "unreadable"})
                continue
            dpi = im.info.get("dpi", (None, None))
            comp = _frame_compression(im)
            if "OJPEG" in comp:
                warnings.append(f"Page {i+1} uses OJPEG (obsolete JPEG-in-TIFF) — "
                                f"will attempt ImageMagick fallback; quality may vary.")
            frames.append({
                "index": i, "size": [im.width, im.height], "mode": im.mode,
                "dpi": [round(float(dpi[0]), 1) if dpi[0] else None,
                        round(float(dpi[1]), 1) if dpi and len(dpi) > 1 and dpi[1] else None],
                "compression": comp,
            })
            layers.append({"name": f"Page {i+1} — {im.width}×{im.height} {im.mode} · {comp}",
                           "kind": "bitmap", "type": "TIFF-IFD",
                           "visible": True, "depth": 0})
        try:
            im.seek(0)
        except Exception:
            pass
    except Exception as e:
        warnings.append(f"Could not fully read TIFF: {e}")
    mm = mismatch_note(".tiff", sn)
    if mm:
        warnings.append(mm)
    comps = sorted({f.get("compression", "") for f in frames if f.get("compression")})
    modes = sorted({f.get("mode", "") for f in frames if f.get("mode")})
    ver_bits = []
    if sn.get("kind") == "bigtiff":
        ver_bits.append("BigTIFF")
    if comps:
        ver_bits.append(", ".join(comps[:3]))
    if modes:
        ver_bits.append("/".join(modes[:3]))
    return {
        "format": "TIFF",
        "format_label": "Tagged Image File Format (TIFF)",
        "version_label": " · ".join(ver_bits) if ver_bits else "TIFF (auto)",
        "sniff": sn,
        "file_size": os.path.getsize(path),
        "frames": frames,
        "pages": len(frames),
        "layers_total": len(layers),
        "counts": {"text": 0, "bitmap": len(frames), "vector": 0, "shape": 0,
                   "group": 0, "adjustment": 0, "smartobject": 0, "fill": 0,
                   "dimension": 0, "hatch": 0, "block": 0, "other": 0},
        "layers": layers,
        "warnings": warnings,
        "notes": [
            "Every TIFF page/IFD becomes one PDF page at its true print size (embedded DPI respected).",
            "ZIP = lossless, JPEG = smaller file. 1-bit faxes stay razor sharp (Group4 → ZIP).",
        ],
    }


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    options = options or {}
    compression = options.get("compression", "auto")  # auto|zip|jpeg
    quality = int(options.get("quality", 92) or 92)
    dpi_opt = options.get("dpi", "auto")
    only_page = options.get("page", "all")  # all | int (1-based)

    def _normalize(fr: Image.Image, pageno: int) -> Image.Image:
        if fr.mode in ("I;16", "I;16B", "I;16L"):
            import numpy as _np
            fr = Image.fromarray((_np.array(fr) >> 8).astype("uint8"), "L")
            warnings.append(f"Page {pageno}: 16-bit → 8-bit for PDF.")
        elif fr.mode in ("I", "F"):
            fr = fr.convert("L")
        elif fr.mode in ("CMYK", "YCbCr", "LAB", "HSV"):
            src_mode = fr.mode
            fr = fr.convert("RGB")
            notes.append(f"Page {pageno}: {src_mode} → RGB for screen PDF.")
        elif fr.mode == "P":
            fr = fr.convert("RGB")
        return fr

    def _load_frame(idx: int):
        try:
            im.seek(idx)
            im.load()
            return im.copy(), False
        except Exception as e:
            pass
        # ImageMagick fallback (helps some OJPEG / exotic TIFFs)
        if which("convert"):
            import tempfile as _tf
            tmp = _tf.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            try:
                p = run(["convert", f"{path}[{idx}]", tmp.name], timeout=120)
                if os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
                    fr = Image.open(tmp.name)
                    fr.load()
                    return fr, True
            except Exception:
                pass
            finally:
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass
        return None, False

    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    pages_idx = list(range(n))
    if only_page != "all":
        try:
            p = int(only_page) - 1
            if 0 <= p < n:
                pages_idx = [p]
        except Exception:
            pass

    doc = pymupdf.open()
    warnings: list[str] = []
    notes: list[str] = []
    done = 0
    for i in pages_idx:
        frame, via_magick = _load_frame(i)
        if frame is None:
            warnings.append(f"Page {i+1} could not be decoded (unsupported variant) — skipped.")
            continue
        if via_magick:
            warnings.append(f"Page {i+1} decoded via ImageMagick fallback.")
        frame = _normalize(frame, i + 1)
        # embedded dpi
        emb = frame.info.get("dpi", (None, None))
        try:
            dpi = float(dpi_opt) if str(dpi_opt).lower() not in ("auto", "") else None
        except Exception:
            dpi = None
        if dpi is None:
            dpi = float(emb[0]) if emb and emb[0] else 150.0
        w_pt, h_pt = px_to_pt(frame.width, dpi), px_to_pt(frame.height, dpi)
        page = doc.new_page(width=w_pt, height=h_pt)

        comp = compression
        if comp == "auto":
            comp = "jpeg" if frame.mode in ("RGB", "L") and max(frame.size) > 2500 else "zip"
        try:
            if comp == "jpeg":
                if frame.mode in ("RGBA", "LA", "PA"):
                    bg = Image.new("RGB", frame.size, (255, 255, 255))
                    bg.paste(frame, mask=frame.split()[-1])
                    frame = bg
                elif frame.mode not in ("RGB", "L", "CMYK"):
                    frame = frame.convert("RGB")
                buf = io.BytesIO()
                frame.save(buf, "JPEG", quality=quality)
                page.insert_image(page.rect, stream=buf.getvalue())
            else:
                if frame.mode == "P":
                    frame = frame.convert("RGB")
                buf = io.BytesIO()
                frame.save(buf, "PNG")
                page.insert_image(page.rect, stream=buf.getvalue())
        except Exception as e:
            try:
                if frame.mode != "RGB":
                    frame = frame.convert("RGB")
                buf = io.BytesIO()
                frame.save(buf, "PNG")
                page.insert_image(page.rect, stream=buf.getvalue())
                warnings.append(f"Page {i+1} encode hiccup ({e}) — inserted as PNG.")
            except Exception as e2:
                warnings.append(f"Page {i+1} failed ({e2}) — skipped.")
                continue
        done += 1

    if done == 0:
        raise RuntimeError("No TIFF pages could be decoded. " +
                           (" ".join(warnings)[:400] if warnings else
                            "The file may use an unsupported variant (e.g. OJPEG)."))
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "TIFF")
    stats = pdf_stats(out_pdf)
    report = {"engine": f"Pillow + PyMuPDF (multi-page, {compression})",
              "warnings": warnings, "notes": notes, **stats}
    return ConvertResult(out_pdf, report)
