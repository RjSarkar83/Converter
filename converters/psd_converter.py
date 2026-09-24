"""PSD -> PDF converter with true layered (OCG) PDF output.

Layered mode renders every layer (or clip-group) as a separate toggleable
PDF layer at its exact position. Clipping-mask groups are rendered as units
so clipped art appears exactly like in Photoshop.
"""
from __future__ import annotations

import io
import os

import numpy as np
import pymupdf
from PIL import Image

from .base import (ConvertResult, PRODUCER, empty_counts, mismatch_note, pdf_stats,
                   sanitize_name, set_metadata, sniff)

MAX_PT = 14400  # PDF max page dimension


def _classify(layer) -> str:
    t = type(layer).__name__
    if layer.is_group():
        return "group"
    if t == "TypeLayer":
        return "text"
    if t == "PixelLayer":
        return "bitmap"
    if t in ("ShapeLayer",):
        return "vector"
    if t in ("SolidColorFill", "GradientFill", "PatternFill", "FillLayer"):
        return "fill"
    if t == "SmartObjectLayer":
        return "smartobject"
    mod = type(layer).__module__
    if "Adjustment" in t or "adjustment" in mod:
        return "adjustment"
    return "other"


def _layer_text(layer) -> str:
    try:
        if type(layer).__name__ == "TypeLayer":
            data = layer.text_data or {}
            return str(data.get("text", "") or "")[:500]
    except Exception:
        pass
    return ""


def _layer_fonts(layer) -> list[str]:
    try:
        if type(layer).__name__ == "TypeLayer":
            fonts = layer.font or set()
            return sorted(str(f) for f in fonts)[:8]
    except Exception:
        pass
    return []


def _is_clipped(layer) -> bool:
    try:
        return bool(getattr(layer, "clipping", False))
    except Exception:
        return False


def _effective_visible(layer) -> bool:
    """Own flag AND all ancestor groups visible."""
    try:
        node = layer
        while node is not None:
            if hasattr(node, "visible") and not node.visible:
                return False
            node = getattr(node, "parent", None)
        return True
    except Exception:
        return bool(getattr(layer, "visible", True))


def _group_path(layer) -> str:
    parts: list[str] = []
    try:
        node = getattr(layer, "parent", None)
        while node is not None and hasattr(node, "name") and node.name:
            # stop at document root (PSDImage has no .parent chain of groups)
            if node.__class__.__name__ == "PSDImage":
                break
            parts.append(str(node.name))
            node = getattr(node, "parent", None)
    except Exception:
        pass
    parts.reverse()
    return "/".join(parts)


def _pillow_fallback_info(path: str):
    """Last-resort info via Pillow (any PSD/PSB Pillow can open)."""
    im = Image.open(path)
    im.load()
    return im


def analyze(path: str) -> dict:
    from psd_tools import PSDImage

    sn = sniff(path)
    try:
        psd = PSDImage.open(path)
    except Exception as e:
        # Fallback: Pillow composite (very old / unusual PSD)
        try:
            im = _pillow_fallback_info(path)
            w, h = im.size
            return {
                "format": "PSD",
                "format_label": "Adobe Photoshop (PSD)",
                "version_label": f"{sn.get('detail', '')} · legacy (flattened only)".strip(),
                "sniff": sn,
                "width": w, "height": h,
                "layers_total": 1,
                "counts": {**empty_counts(), "bitmap": 1},
                "layers": [{"name": "Composite (legacy file — layers unavailable)",
                            "kind": "bitmap", "type": "Pillow", "visible": True, "depth": 0}],
                "fonts": [],
                "legacy_mode": True,
                "warnings": [f"Layered parse failed ({e}); this legacy/unusual PSD will "
                             f"convert as a high-quality flattened image."],
                "notes": ["Flattened mode: pixel-exact composite."],
            }
        except Exception:
            raise RuntimeError(f"Could not read PSD (psd-tools: {e})")
    try:
        from psd_tools.constants import ColorMode as _CM
        cm_name = _CM(psd.color_mode).name
    except Exception:
        cm_name = str(getattr(psd, "color_mode", ""))
    depth = getattr(psd, "depth", "") or ""
    return _analyze_open(psd, sn, depth, cm_name)


def _analyze_open(psd, sn: dict, depth, cm_name: str = "") -> dict:
    layers: list[dict] = []
    counts = empty_counts()
    fonts: set[str] = set()
    clipped_n = 0

    def walk(ls, depth=0, parent=""):
        nonlocal clipped_n
        for l in ls:
            kind = _classify(l)
            counts[kind] = counts.get(kind, 0) + 1
            clipped = (not l.is_group()) and _is_clipped(l)
            if clipped:
                clipped_n += 1
            entry = {
                "name": l.name or "(unnamed)",
                "path": f"{parent}/{l.name}" if parent else (l.name or ""),
                "kind": kind,
                "type": type(l).__name__,
                "visible": bool(l.visible),
                "eff_visible": _effective_visible(l),
                "clipped": clipped,
                "opacity": int(getattr(l, "opacity", 255) or 255),
                "depth": depth,
            }
            try:
                if not l.is_group():
                    x1, y1, x2, y2 = l.bbox
                    entry["bbox"] = [int(x1), int(y1), int(x2), int(y2)]
            except Exception:
                pass
            if kind == "text":
                entry["text"] = _layer_text(l)
                fl = _layer_fonts(l)
                entry["fonts"] = fl
                fonts.update(fl)
            layers.append(entry)
            if l.is_group():
                walk(l, depth + 1, entry["path"])

    walk(psd)
    total = len(layers)
    warnings: list[str] = []
    if counts.get("adjustment", 0):
        warnings.append(
            f"{counts['adjustment']} adjustment layer(s): their effect is baked into "
            f"flattened mode; in layered mode clipped adjustments render inside their group."
        )
    if counts.get("text", 0):
        warnings.append(
            "Text layers are rasterized with available system fonts — install the original "
            "fonts for closest match; extracted text is included above."
        )
    notes = [
        "Layered PDF: every layer becomes a toggleable PDF layer (OCG) at exact position/size.",
        "Flattened mode: single pixel-exact composite (adjustments + blend modes baked).",
    ]
    if clipped_n:
        notes.append(f"{clipped_n} clipped layer(s) detected — rendered inside their "
                     f"clip-group so art matches Photoshop exactly.")
    return {
        "format": "PSD",
        "format_label": "Adobe Photoshop (PSD)",
        "version_label": f"{'PSB' if sn.get('kind') == 'psb' else 'PSD'} "
                         f"{sn.get('detail', '')} · "
                         f"{cm_name or getattr(psd, 'color_mode', '')}{' %s-bit' % depth if depth else ''}".strip(),
        "sniff": sn,
        "width": psd.width,
        "height": psd.height,
        "color_mode": cm_name or str(getattr(psd, "color_mode", "")),
        "color_depth": depth,
        "layers_total": total,
        "counts": counts,
        "layers": layers,
        "fonts": sorted(fonts),
        "warnings": warnings,
        "notes": notes,
    }


# ------------------------------------------------------------------ render
def _convert_pillow_flattened(path, out_pdf, flat_dpi, flat_quality, warnings, notes):
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode == "CMYK":
        im = im.convert("RGB")
        notes.append("CMYK PSD converted to RGB for screen PDF.")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=flat_quality)
    doc = pymupdf.open()
    page = doc.new_page(width=im.width * 72.0 / flat_dpi,
                        height=im.height * 72.0 / flat_dpi)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.set_metadata({"title": os.path.basename(path), "producer": PRODUCER,
                      "creator": f"{PRODUCER} (PSD/legacy-flattened)"})
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "PSD/legacy")
    stats = pdf_stats(out_pdf)
    return ConvertResult(out_pdf, {
        "engine": "Pillow legacy PSD (flattened)", "mode": "legacy-flattened",
        "source_size": [im.width, im.height], "layers_total": 1,
        "layers_written": 0, "warnings": warnings, "notes": notes, **stats})


def _bbox_of(layer, W: int, H: int):
    try:
        x1, y1, x2, y2 = (int(v) for v in layer.bbox)
    except Exception:
        return None
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(W, x2); y2 = min(H, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _has_pixels(img: Image.Image) -> bool:
    try:
        if img.mode != "RGBA":
            return True  # opaque RGB etc.
        a = np.asarray(img)
        return bool((a[:, :, 3] > 0).any())
    except Exception:
        return True


def _partition_units(leaves: list) -> list[list]:
    """Group bottom-to-top leaves into render units.

    A base layer (clipping=False) plus all consecutive clipped layers above
    it form one clip-group unit; everything else renders solo.
    """
    units: list[list] = []
    i = 0
    n = len(leaves)
    while i < n:
        base = leaves[i]
        if not _is_clipped(base):
            run = [base]
            j = i + 1
            while j < n and _is_clipped(leaves[j]):
                run.append(leaves[j])
                j += 1
            units.append(run)
            i = j
        else:
            # orphan clipped layer (no base below, e.g. base filtered out) — solo attempt
            units.append([base])
            i += 1
    return units


def _render_unit_solo(unit: list, W: int, H: int):
    """Fast path: single non-clipped layer via its own composite."""
    layer = unit[0]
    box = _bbox_of(layer, W, H)
    if box is None:
        return None, "no bounds"
    try:
        img = layer.composite()
    except Exception as e:
        return None, f"{type(e).__name__}"
    if img is None:
        return None, "not rasterizable"
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    # solo composite is cropped to bbox — but be tolerant of size mismatch
    bw, bh = box[2] - box[0], box[3] - box[1]
    if img.size != (bw, bh):
        # center-crop or pad to bbox (effects can change size)
        canvas = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ox, oy = (bw - img.width) // 2, (bh - img.height) // 2
        if img.width <= bw and img.height <= bh:
            canvas.alpha_composite(img, (max(0, ox), max(0, oy)))
        else:
            canvas = img.crop((-ox, -oy, -ox + bw, -oy + bh))
        img = canvas
    if not _has_pixels(img):
        return None, "empty render"
    return (img, box), ""


def _render_unit_clipgroup(psd, unit: list, leaves: list, W: int, H: int):
    """Render a clip-group: show only its members, full composite, crop union box."""
    boxes = []
    for m in unit:
        b = _bbox_of(m, W, H)
        if b is not None:
            boxes.append(b)
    if not boxes:
        # members without bounds (e.g. pure adjustments) — still try full-canvas?
        return None, "no bounds"
    ux1 = min(b[0] for b in boxes); uy1 = min(b[1] for b in boxes)
    ux2 = max(b[2] for b in boxes); uy2 = max(b[3] for b in boxes)
    members = set(map(id, unit))
    for l in leaves:
        l.visible = id(l) in members
    try:
        img = psd.composite()
    except Exception as e:
        return None, f"{type(e).__name__}"
    if img is None:
        return None, "not rasterizable"
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    crop = img.crop((ux1, uy1, ux2, uy2))
    if not _has_pixels(crop):
        return None, "empty render"
    return (crop, (ux1, uy1, ux2, uy2)), ""


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    from psd_tools import PSDImage

    options = options or {}
    mode = options.get("psd_mode", "layered")  # layered | flattened
    include_hidden = options.get("include_hidden", True)
    flat_dpi = int(options.get("flat_dpi", 150) or 150)
    flat_quality = int(options.get("flat_quality", 92) or 92)

    psd = PSDImage.open(path)
    W, H = int(psd.width), int(psd.height)
    warnings: list[str] = []
    notes: list[str] = []
    used_mode = mode

    doc = pymupdf.open()

    if mode == "flattened":
        comp = psd.composite()
        if comp is None:
            raise RuntimeError("Could not composite PSD (unsupported features).")
        if comp.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", comp.size, (255, 255, 255))
            bg.paste(comp, mask=comp.split()[-1])
            comp = bg
        elif comp.mode != "RGB":
            comp = comp.convert("RGB")
        buf = io.BytesIO()
        comp.save(buf, "JPEG", quality=flat_quality)
        page_w, page_h = W * 72.0 / flat_dpi, H * 72.0 / flat_dpi
        page = doc.new_page(width=page_w, height=page_h)
        page.insert_image(page.rect, stream=buf.getvalue())
        layers_written = 0
    else:
        # ---------------- layered OCG mode ----------------
        scale = min(1.0, MAX_PT / max(W, H)) if max(W, H) > 0 else 1.0
        if scale < 1.0:
            warnings.append(f"Canvas scaled to {scale*100:.1f}% to fit PDF max page size.")
        pw, ph = W * scale, H * scale
        page = doc.new_page(width=pw, height=ph)
        page.draw_rect(pymupdf.Rect(0, 0, pw, ph), fill=(1, 1, 1), color=None)

        leaves = [l for l in psd.descendants() if not l.is_group()]
        orig_vis = {id(l): bool(l.visible) for l in leaves}
        units = _partition_units(leaves)
        # snapshot ON/OFF now — clip-group renders mutate flags mid-loop
        unit_vis = [_effective_visible(u[0]) for u in units]
        clipgroups = sum(1 for u in units if len(u) > 1)
        if clipgroups:
            notes.append(f"{clipgroups} clipping-mask group(s) rendered as units (exact Photoshop look).")

        layers_written = 0
        skipped: list[str] = []
        try:
            for idx, unit in enumerate(units):  # bottom-to-top painter's order
                base = unit[0]
                gpath = _group_path(base)
                disp = (base.name or f"layer-{layers_written+1}")
                if gpath:
                    disp = f"{gpath}/{disp}"
                eff_vis = unit_vis[idx]
                if not eff_vis and not include_hidden:
                    skipped.append(f"{disp} (hidden)")
                    continue
                if len(unit) == 1 and not _is_clipped(base):
                    rendered, why = _render_unit_solo(unit, W, H)
                else:
                    rendered, why = _render_unit_clipgroup(psd, unit, leaves, W, H)
                if rendered is None:
                    skipped.append(f"{disp} ({why})")
                    continue
                img, (x1, y1, x2, y2) = rendered
                try:
                    if scale < 1.0:
                        img = img.resize((max(1, int(img.width * scale)),
                                          max(1, int(img.height * scale))), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, "PNG")
                    rect = pymupdf.Rect(x1 * scale, y1 * scale, x2 * scale, y2 * scale)
                    rect = rect & pymupdf.Rect(0, 0, pw, ph)
                    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                        skipped.append(f"{disp} (off-canvas)")
                        continue
                    oc_name = disp if len(unit) == 1 else \
                        f"{disp} (+{len(unit)-1} clipped)"
                    oc = doc.add_ocg(sanitize_name(oc_name), on=eff_vis)
                    page.insert_image(rect, stream=buf.getvalue(), oc=oc)
                    layers_written += 1
                except Exception as e:
                    skipped.append(f"{disp} ({type(e).__name__})")
                    continue
        finally:
            for l in leaves:
                try:
                    l.visible = orig_vis.get(id(l), True)
                except Exception:
                    pass

        if layers_written == 0:
            warnings.append("No individual layers could be rasterized — used flattened composite instead.")
            comp = psd.composite()
            if comp is None:
                raise RuntimeError("Could not render PSD.")
            if comp.mode != "RGB":
                comp = comp.convert("RGB")
            buf = io.BytesIO()
            comp.save(buf, "JPEG", quality=flat_quality)
            page.insert_image(page.rect, stream=buf.getvalue())
            used_mode = "flattened-fallback"
        if skipped:
            warnings.append(f"Skipped {len(skipped)} layer(s): " + ", ".join(skipped[:8]) +
                            ("…" if len(skipped) > 8 else "") +
                            " — re-convert as Flattened for pixel-exact output.")

    doc.set_metadata({"title": os.path.basename(path), "producer": PRODUCER,
                      "creator": f"{PRODUCER} (PSD/{used_mode})"})
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()
    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], f"PSD/{used_mode}")

    stats = pdf_stats(out_pdf)
    report = {
        "engine": f"psd-tools + PyMuPDF ({used_mode})",
        "mode": used_mode,
        "source_size": [W, H],
        "layers_total": len([l for l in psd.descendants()]),
        "layers_written": layers_written,
        "warnings": warnings,
        "notes": notes + [
            "Layer positions/sizes are pixel-exact.",
            "Blend modes are approximated per-layer; use Flattened mode for pixel-exact output.",
        ],
        **stats,
    }
    return ConvertResult(out_pdf, report)
