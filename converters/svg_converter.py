"""SVG -> PDF converter (true vector + real text via PyMuPDF).

Triple-engine fallback (PyMuPDF -> CairoSVG -> svglib) plus SVGZ support,
so virtually any SVG flavour converts.
"""
from __future__ import annotations

import gzip
import os
import re
import tempfile
import xml.etree.ElementTree as ET

import pymupdf

from .base import ConvertResult, mismatch_note, pdf_stats, set_metadata, sniff

SHAPE_TAGS = ("rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
              "use", "symbol", "marker", "pattern")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_size(root) -> tuple[float | None, float | None]:
    def num(v: str | None):
        if not v:
            return None
        m = re.match(r"\s*([\d.]+)", v)
        return float(m.group(1)) if m else None
    w, h = num(root.get("width")), num(root.get("height"))
    if (w is None or h is None) and root.get("viewBox"):
        try:
            vb = [float(x) for x in root.get("viewBox").split()]
            if len(vb) == 4:
                w = w or vb[2]
                h = h or vb[3]
        except Exception:
            pass
    return w, h


def _ungzip(path: str) -> tuple[str, str | None]:
    """Return (usable_svg_path, temp_to_cleanup or None)."""
    sn = sniff(path)
    if sn.get("kind") in ("svgz", "gzip"):
        tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        tmp.close()
        try:
            with gzip.open(path, "rb") as f:
                data = f.read(200 * 1024 * 1024)
            if b"<svg" not in data[:8000].lower():
                raise RuntimeError("not an SVG inside gzip")
            with open(tmp.name, "wb") as f:
                f.write(data)
            return tmp.name, tmp.name
        except Exception as e:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
            raise RuntimeError(f"Could not decompress SVGZ: {e}")
    return path, None


def analyze(path: str) -> dict:
    warnings: list[str] = []
    sn = sniff(path)
    counts = {"text": 0, "bitmap": 0, "vector": 0, "shape": 0, "group": 0,
              "adjustment": 0, "smartobject": 0, "fill": 0, "dimension": 0,
              "hatch": 0, "block": 0, "other": 0}
    layers: list[dict] = []
    fonts: set[str] = set()
    w = h = None
    svg_ver = ""
    use_path, tmp = path, None
    try:
        use_path, tmp = _ungzip(path)
    except Exception as e:
        warnings.append(str(e))
    try:
        tree = ET.parse(use_path)
        root = tree.getroot()
        svg_ver = str(root.get("version", "") or "")
        w, h = _parse_size(root)
        for el in root.iter():
            t = _local(el.tag)
            if t == "text":
                counts["text"] += 1
                ff = el.get("font-family", "")
                if ff:
                    fonts.add(ff.split(",")[0].strip(" '\"")[:40])
            elif t == "image":
                counts["bitmap"] += 1
            elif t in SHAPE_TAGS:
                counts["vector"] += 1
            elif t == "g":
                counts["group"] += 1
            elif t in ("lineargradient", "radialgradient", "filter", "clippath", "mask"):
                counts["other"] += 1
        # top-level structure as "layers"
        for i, child in enumerate(list(root)[:60]):
            t = _local(child.tag)
            kind = {"text": "text", "image": "bitmap", "g": "group"}.get(
                t, "vector" if t in SHAPE_TAGS else "other")
            label = child.get("id") or child.get("{http://www.inkscape.org/namespaces/inkscape}label") \
                or f"{t} #{i+1}"
            layers.append({"name": label[:60], "kind": kind, "type": t,
                           "visible": True, "depth": 0})
    except ET.ParseError as e:
        warnings.append(f"SVG XML parse warning: {e} — will still try to convert.")
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
    mm = mismatch_note(os.path.splitext(path)[1] or ".svg", sn)
    if mm:
        warnings.append(mm)
    ver_bits = []
    if sn.get("kind") == "svgz":
        ver_bits.append("SVGZ (compressed)")
    if svg_ver:
        ver_bits.append(f"v{svg_ver}")
    if sn.get("detail"):
        ver_bits.append(sn["detail"])
    return {
        "format": "SVG",
        "format_label": "Scalable Vector Graphics (SVG)",
        "version_label": " · ".join(ver_bits) if ver_bits else "SVG (auto)",
        "sniff": sn,
        "file_size": os.path.getsize(path),
        "width": w,
        "height": h,
        "layers_total": len(layers),
        "counts": counts,
        "layers": layers,
        "fonts": sorted(fonts),
        "warnings": warnings,
        "notes": [
            "Vectors stay 100% vector and text stays real selectable text in the PDF.",
            "Embedded raster images are carried over at original resolution.",
        ],
    }


def _via_pymupdf(svg_path: str, scale: float, background: str) -> bytes:
    doc = pymupdf.open(svg_path)
    try:
        if len(doc) == 0:
            raise RuntimeError("SVG produced no pages.")
        pdf_bytes = doc.convert_to_pdf()
    finally:
        doc.close()
    pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if background == "white":
        for page in pdf:
            shape = page.new_shape()
            shape.draw_rect(page.rect)
            shape.finish(fill=(1, 1, 1), color=None, fill_opacity=1)
            shape.commit(overlay=False)
    if scale != 1.0:
        dst = pymupdf.open()
        for spage in pdf:
            r = spage.rect
            dpage = dst.new_page(width=r.width * scale, height=r.height * scale)
            dpage.show_pdf_page(
                pymupdf.Rect(0, 0, r.width * scale, r.height * scale),
                pdf, spage.number, clip=r)
        pdf.close()
        pdf = dst
    out = pdf.tobytes(garbage=3, deflate=True)
    pdf.close()
    return out


def _via_cairosvg(svg_path: str, scale: float, background: str) -> bytes:
    import cairosvg
    kw: dict = {"url": svg_path, "scale": scale}
    if background == "white":
        kw["background_color"] = "white"
    return cairosvg.svg2pdf(**kw)


def _via_svglib(svg_path: str, scale: float, background: str) -> bytes:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
    drawing = svg2rlg(svg_path)
    if drawing is None:
        raise RuntimeError("svglib could not parse SVG")
    if scale != 1.0:
        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)
    import io as _io
    buf = _io.BytesIO()
    renderPDF.drawToFile(drawing, buf)
    return buf.getvalue()


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    options = options or {}
    scale = float(options.get("scale", 1.0) or 1.0)
    scale = min(8.0, max(0.1, scale))
    background = options.get("background", "white")
    warnings: list[str] = []

    use_path, tmp = _ungzip(path)
    try:
        errors: list[str] = []
        pdf_bytes = None
        engine = ""
        try:
            pdf_bytes = _via_pymupdf(use_path, scale, background)
            engine = "PyMuPDF (vector + real text)"
        except Exception as e:
            errors.append(f"PyMuPDF: {e}")
        if pdf_bytes is None:
            try:
                pdf_bytes = _via_cairosvg(use_path, scale, background)
                engine = "CairoSVG fallback (vector; text may become curves)"
                warnings.append("Primary SVG engine failed — used CairoSVG fallback "
                                "(vectors kept; text may be curves, not selectable).")
            except Exception as e:
                errors.append(f"CairoSVG: {e}")
        if pdf_bytes is None:
            try:
                pdf_bytes = _via_svglib(use_path, scale, background)
                engine = "svglib fallback (vector)"
                warnings.append("Used svglib fallback engine — complex CSS/filters "
                                "may render slightly differently.")
            except Exception as e:
                errors.append(f"svglib: {e}")
        if pdf_bytes is None:
            raise RuntimeError("All SVG engines failed: " + " | ".join(errors)[:600])
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass

    with open(out_pdf, "wb") as f:
        f.write(pdf_bytes)
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "SVG")
    stats = pdf_stats(out_pdf)
    if stats.get("vectors", 0) == 0 and stats.get("text_chars", 0) == 0:
        warnings.append("Output has no vectors/text — the SVG may be image-only or empty.")
    report = {"engine": engine, "warnings": warnings, "notes": [], **stats}
    return ConvertResult(out_pdf, report)
