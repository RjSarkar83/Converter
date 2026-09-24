"""JPEG/JPG/PNG -> Minimal Black & White Vector Artwork.

Pipeline: denoise -> grayscale -> Otsu/manual threshold -> vtracer
(binary vector tracing) -> SVG + vector PDF. Potrace fallback included.
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageFilter

from .base import (human_size, pdf_stats, pil_thumb_b64, run, svg_preview_b64,
                   which)

MAX_DIM_DEFAULT = 1600

DETAIL_PRESETS = {
    "minimal": dict(filter_speckle=24, length_threshold=10.0, corner_threshold=60,
                    splice_threshold=45, mode="spline", path_precision=3,
                    color_precision=6, layer_difference=16),
    "balanced": dict(filter_speckle=8, length_threshold=5.0, corner_threshold=60,
                     splice_threshold=45, mode="spline", path_precision=3,
                     color_precision=6, layer_difference=16),
    "detailed": dict(filter_speckle=2, length_threshold=3.0, corner_threshold=30,
                     splice_threshold=45, mode="spline", path_precision=5,
                     color_precision=6, layer_difference=16),
}

POTRACE_PRESETS = {
    "minimal": ["--turdsize=12", "--opttolerance=1.2", "--alphamax=1.2"],
    "balanced": ["--turdsize=4", "--opttolerance=0.4", "--alphamax=1.0"],
    "detailed": ["--turdsize=1", "--opttolerance=0.15", "--alphamax=0.8"],
}


# ------------------------------------------------------------- preprocessing
def otsu_threshold(gray: np.ndarray) -> int:
    hist, _ = np.histogram(gray, bins=256, range=(0, 255))
    total = float(gray.size)
    sum_tot = float(np.dot(np.arange(256), hist))
    sum_b, w_b, best, th = 0.0, 0.0, -1.0, 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_tot - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, th = var, t
    return int(th)


def _load_printable(path: str, max_dim: int, notes: list) -> Image.Image:
    im = Image.open(path)
    im.load()
    if getattr(im, "n_frames", 1) > 1:
        try:
            im.seek(0)
        except Exception:
            pass
        notes.append("Multi-frame image — first frame used.")
    if im.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        try:
            bg.paste(im, mask=im.split()[-1])
        except Exception:
            bg.paste(im)
        im = bg
        notes.append("Transparency flattened onto white.")
    elif im.mode == "P":
        im = im.convert("RGB")
    elif im.mode in ("I;16", "I;16B", "I;16L"):
        im = Image.fromarray((np.array(im) >> 8).astype("uint8"), "L").convert("RGB")
    elif im.mode == "CMYK":
        im = im.convert("RGB")
        notes.append("CMYK image converted to RGB for tracing.")
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > max_dim:
        im.thumbnail((max_dim, max_dim), Image.LANCZOS)
        notes.append(f"Downscaled to {im.width}×{im.height} for clean minimal tracing.")
    return im


def _to_binary(im: Image.Image, threshold, invert: bool, denoise: int):
    g = im.convert("L")
    if denoise >= 2:
        g = g.filter(ImageFilter.MedianFilter(3 if denoise <= 2 else 5))
    elif denoise == 1:
        g = g.filter(ImageFilter.MedianFilter(3))
    arr = np.array(g)
    th = otsu_threshold(arr) if str(threshold).lower() == "auto" else int(threshold)
    bw = (arr > th).astype(np.uint8) * 255
    if invert:
        bw = 255 - bw
    ink_pct = round(float((bw < 128).mean()) * 100, 1)
    return Image.fromarray(bw.astype(np.uint8), "L"), th, ink_pct


# ------------------------------------------------------------------ tracing
def _trace_vtracer(bw_png: str, svg_path: str, detail: str, hierarchical: str = "stacked"):
    import vtracer
    p = DETAIL_PRESETS.get(detail, DETAIL_PRESETS["balanced"])
    vtracer.convert_image_to_svg_py(
        bw_png, svg_path, colormode="binary", hierarchical=hierarchical,
        mode=p["mode"], filter_speckle=p["filter_speckle"],
        color_precision=p["color_precision"], layer_difference=p["layer_difference"],
        corner_threshold=p["corner_threshold"], length_threshold=p["length_threshold"],
        splice_threshold=p["splice_threshold"], path_precision=p["path_precision"])


def _trace_potrace(bw_png: str, svg_path: str, detail: str):
    if not which("potrace"):
        raise RuntimeError("potrace not installed")
    # potrace needs PBM/PGM
    im = Image.open(bw_png).convert("1")
    with tempfile.NamedTemporaryFile(suffix=".pbm", delete=False) as tf:
        pbm = tf.name
    im.save(pbm)
    try:
        cmd = ["potrace", pbm, "-s", "-o", svg_path,
               *POTRACE_PRESETS.get(detail, POTRACE_PRESETS["balanced"])]
        p = run(cmd, timeout=180)
        if not os.path.exists(svg_path) or os.path.getsize(svg_path) == 0:
            raise RuntimeError(f"potrace failed: {(p.stderr or '')[-300:]}")
    finally:
        try:
            os.remove(pbm)
        except Exception:
            pass


def _is_light(fill: str) -> bool:
    f = (fill or "").strip().lower()
    if f in ("#fff", "#ffffff", "white", "#fefefe", "none", ""):
        return True
    m = re.fullmatch(r"#([0-9a-f]{6})", f)
    if m:
        v = int(m.group(1), 16)
        r, g, b = (v >> 16) & 255, (v >> 8) & 255, v & 255
        return (r + g + b) / 3 > 200
    return False


def _strip_background(svg_path: str, W: int, H: int) -> bool:
    """Remove full-canvas light background rect/path for transparent BG."""
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        ns = "{http://www.w3.org/2000/svg}"
        removed = False
        for tag in (f"{ns}rect", "rect"):
            for el in list(root.findall(tag)):
                try:
                    x = float(el.get("x", 0)); y = float(el.get("y", 0))
                    w = float(el.get("width", 0)); h = float(el.get("height", 0))
                except Exception:
                    continue
                if x <= 1 and y <= 1 and w >= W - 1 and h >= H - 1 \
                        and _is_light(el.get("fill", "")):
                    root.remove(el)
                    removed = True
        # vtracer stacked-mode bg path: first path covering ~full canvas, light fill
        for el in list(root):
            if not el.tag.endswith("path"):
                continue
            if not _is_light(el.get("fill", "")):
                continue
            nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", el.get("d", ""))]
            if len(nums) < 8:
                continue
            xs = nums[0::2]; ys = nums[1::2]
            if (min(xs) <= 1 and min(ys) <= 1 and max(xs) >= W - 1
                    and max(ys) >= H - 1):
                root.remove(el)
                removed = True
                break
        if removed:
            tree.write(svg_path, encoding="utf-8", xml_declaration=True)
        return removed
    except Exception:
        return False


def _count_paths(svg_path: str) -> int:
    try:
        with open(svg_path, "rb") as f:
            return f.read().count(b"<path")
    except Exception:
        return 0


# ------------------------------------------------------------------ public
RASTER_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")


def analyze(path: str) -> dict:
    notes: list[str] = []
    im = _load_printable(path, MAX_DIM_DEFAULT, notes)
    g = np.array(im.convert("L"))
    th = otsu_threshold(g)
    ink = round(float((g <= th).mean()) * 100, 1)
    return {
        "format": "RASTER",
        "format_label": "Raster image (JPG/PNG/…)",
        "version_label": f"{im.mode} · {im.width}×{im.height}",
        "file_size": os.path.getsize(path),
        "width": im.width, "height": im.height, "mode": im.mode,
        "suggest_threshold": th,
        "est_ink_pct": ink,
        "thumb": pil_thumb_b64(im),
        "layers_total": 1,
        "counts": {"text": 0, "bitmap": 1, "vector": 0, "shape": 0, "group": 0,
                   "adjustment": 0, "smartobject": 0, "fill": 0, "dimension": 0,
                   "hatch": 0, "block": 0, "other": 0},
        "layers": [{"name": f"Photo {im.width}×{im.height} {im.mode}",
                    "kind": "bitmap", "type": "raster", "visible": True, "depth": 0}],
        "warnings": [],
        "notes": notes + [
            f"Suggested threshold: {th} (auto Otsu), est. ink {ink}%.",
            "Output: minimal black & white vector SVG + print-ready vector PDF.",
        ],
    }


def convert(path: str, workdir: str, options: dict | None = None) -> dict:
    options = options or {}
    detail = options.get("detail", "balanced") or "balanced"
    threshold = options.get("threshold", "auto")
    invert = bool(options.get("invert", False))
    try:
        denoise = int(options.get("denoise", 1) or 0)
    except Exception:
        denoise = 1
    bg = options.get("background", "white") or "white"
    engine_pref = options.get("engine", "auto") or "auto"
    try:
        max_dim = int(options.get("max_dim", MAX_DIM_DEFAULT) or MAX_DIM_DEFAULT)
    except Exception:
        max_dim = MAX_DIM_DEFAULT

    os.makedirs(workdir, exist_ok=True)
    notes: list[str] = []
    warnings: list[str] = []

    im = _load_printable(path, max_dim, notes)
    bw, th_used, ink_pct = _to_binary(im, threshold, invert, denoise)
    bw_png = os.path.join(workdir, "bw.png")
    bw.save(bw_png)
    if ink_pct < 1.0 or ink_pct > 99.0:
        warnings.append(f"Ink coverage is {ink_pct}% — artwork may be blank. "
                        f"Try threshold {'lower' if ink_pct < 1 else 'higher'} or invert.")

    svg_path = os.path.join(workdir, "art.svg")
    pdf_path = os.path.join(workdir, "art.pdf")
    engine = ""
    errs: list[str] = []
    hier = "cutout" if bg == "transparent" else "stacked"
    if engine_pref in ("auto", "vtracer"):
        try:
            _trace_vtracer(bw_png, svg_path, detail, hier)
            engine = f"VTracer 0.6 (binary, {detail})"
        except Exception as e:
            errs.append(f"vtracer: {e}")
    if not engine and engine_pref in ("auto", "potrace"):
        try:
            _trace_potrace(bw_png, svg_path, detail)
            engine = f"Potrace (binary, {detail})"
            if engine_pref == "auto":
                warnings.append("VTracer unavailable — used Potrace fallback.")
        except Exception as e:
            errs.append(f"potrace: {e}")
    if not engine:
        raise RuntimeError("Vector tracing failed: " + " | ".join(errs)[:500])

    bg_stripped = False
    if bg == "transparent":
        if engine.startswith("VTracer"):
            bg_stripped = True  # cutout mode emits foreground paths only
            notes.append("Transparent SVG — foreground paths only (ideal for screen print).")
        elif engine.startswith("Potrace"):
            bg_stripped = True  # potrace SVG is natively transparent
            notes.append("Transparent SVG from Potrace (ideal for screen print).")
        else:
            bg_stripped = _strip_background(svg_path, im.width, im.height)
            if bg_stripped:
                notes.append("Background removed — transparent SVG (ideal for screen print).")
            else:
                notes.append("No flat background found to remove — SVG kept as traced.")

    # SVG -> vector PDF (always on white page)
    from . import svg_converter
    res = svg_converter.convert(svg_path, pdf_path,
                                {"scale": 1.0, "background": "white"})
    stats = pdf_stats(pdf_path)

    report = {
        "engine": engine + " → vector PDF",
        "trace_engine": engine,
        "threshold_used": th_used,
        "threshold_mode": "auto (Otsu)" if str(threshold).lower() == "auto" else "manual",
        "invert": invert,
        "detail": detail,
        "ink_pct": ink_pct,
        "art_size": [im.width, im.height],
        "svg_bytes": os.path.getsize(svg_path),
        "svg_size_h": human_size(os.path.getsize(svg_path)),
        "svg_paths": _count_paths(svg_path),
        "bg_transparent": bg_stripped,
        "preview_in": pil_thumb_b64(im),
        "preview_out": svg_preview_b64(svg_path),
        "warnings": warnings,
        "notes": notes,
        **stats,
    }
    return {"svg_path": svg_path, "pdf_path": pdf_path, "report": report}
