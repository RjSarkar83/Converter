"""DXF (AutoCAD) -> vector PDF converter via ezdxf.

Default backend (PyMuPdfBackend) exports DXF layers as real toggleable
PDF layers (OCG) — exactly like the original drawing structure.
"""
from __future__ import annotations

import io
import os

from .base import (ConvertResult, DXF_VERSIONS, empty_counts, mismatch_note, pdf_stats,
                   set_metadata, sniff, soffice_available, soffice_convert)

PAGE_SIZES_MM = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}


def _open_dxf(path: str, warnings: list):
    """Open DXF with recovery fallbacks. Returns (doc, how)."""
    import ezdxf
    sn = sniff(path)
    if sn.get("kind") == "dwg":
        raise RuntimeError("This is a DWG file (AutoCAD native binary), not DXF. "
                           "Fix: open in AutoCAD/BricsCAD/Draftsight and Save As → DXF, "
                           "then convert. (Direct DWG support is not included.)")
    if sn.get("kind") == "dxf_binary":
        warnings.append("Binary DXF detected — ezdxf needs text DXF, so LibreOffice "
                        "fallback will be used for conversion.")
        return None, "binary-lo"
    try:
        return ezdxf.readfile(path), "direct"
    except ezdxf.DXFError:
        pass
    except Exception as e:
        if "binary" in str(e).lower():
            return None, "binary-lo"
    # Recovery mode for damaged files (any version R12–R2018)
    try:
        from ezdxf import recover as _rec
        doc, auditor = _rec.readfile(path)
        errs = len(getattr(auditor, "errors", []) or [])
        warnings.append(f"File had structural damage — recovered with ezdxf "
                        f"({errs} error(s) fixed/skipped). Please verify output.")
        return doc, "recovered"
    except Exception as e:
        raise RuntimeError(f"Could not read DXF (tried direct + recovery): {e}")


def _acadver_code(path: str) -> str:
    try:
        with open(path, "rb") as f:
            head = f.read(200000)
        import re as _re
        m = _re.search(rb"AC10\d\d", head)
        return m.group(0).decode() if m else ""
    except Exception:
        return ""


def analyze(path: str) -> dict:
    warnings: list[str] = []
    sn = sniff(path)
    doc, how = _open_dxf(path, warnings)
    if doc is None:  # binary DXF — metadata only, LO will convert
        code = _acadver_code(path)
        return {
            "format": "DXF",
            "format_label": "AutoCAD DXF (binary)",
            "version_label": f"Binary DXF {DXF_VERSIONS.get(code, code)}".strip(),
            "sniff": sn,
            "file_size": os.path.getsize(path),
            "binary": True,
            "layouts": ["Model"],
            "entity_types": {},
            "entities_total": 0,
            "layers_total": 0,
            "counts": empty_counts(),
            "layers": [],
            "warnings": warnings,
            "notes": ["Binary DXF converts via LibreOffice (vectors preserved). "
                      "For full layer control, re-save as text DXF in CAD."],
        }

    counts = empty_counts()
    layers: list[dict] = []
    entity_types: dict[str, int] = {}
    total_entities = 0
    for layout in doc.layouts:
        try:
            for e in layout:
                t = e.dxftype()
                entity_types[t] = entity_types.get(t, 0) + 1
                total_entities += 1
                if t in ("TEXT", "MTEXT"):
                    counts["text"] += 1
                elif t == "DIMENSION":
                    counts["dimension"] += 1
                elif t == "HATCH":
                    counts["hatch"] += 1
                elif t == "INSERT":
                    counts["block"] += 1
                elif t in ("LINE", "CIRCLE", "ARC", "ELLIPSE", "LWPOLYLINE",
                           "POLYLINE", "SPLINE", "SOLID", "TRACE", "POINT",
                           "RAY", "XLINE", "LEADER", "MLINE"):
                    counts["vector"] += 1
                elif t in ("IMAGE", "WIPEOUT"):
                    counts["bitmap"] += 1
                else:
                    counts["other"] += 1
        except Exception:
            continue
    try:
        for layer in doc.layers:
            layers.append({
                "name": layer.dxf.name,
                "kind": "vector",
                "type": "DXF-Layer",
                "detail": f"color={layer.color} "
                          f"{'OFF' if layer.is_off() else 'ON'}"
                          f"{' FROZEN' if layer.is_frozen() else ''}",
                "visible": not layer.is_off() and not layer.is_frozen(),
                "depth": 0,
            })
    except Exception as e:
        warnings.append(f"Layer table partially read: {e}")

    layouts = []
    try:
        layouts = [l.name for l in doc.layouts]
    except Exception:
        pass
    code = _acadver_code(path)
    mm = mismatch_note(".dxf", sn)
    if mm:
        warnings.append(mm)
    if how == "recovered":
        notes_extra = " (recovered)"
    else:
        notes_extra = ""
    return {
        "format": "DXF",
        "format_label": f"AutoCAD DXF ({doc.dxfversion})",
        "version_label": (f"{DXF_VERSIONS.get(doc.dxfversion, doc.dxfversion)} "
                          f"({doc.dxfversion}){notes_extra}"),
        "sniff": sn,
        "file_size": os.path.getsize(path),
        "dxf_version": doc.dxfversion,
        "layouts": layouts,
        "entity_types": dict(sorted(entity_types.items(), key=lambda kv: -kv[1])[:30]),
        "entities_total": total_entities,
        "layers_total": len(layers),
        "counts": counts,
        "layers": layers,
        "warnings": warnings,
        "notes": [
            "Each DXF layer becomes a toggleable PDF layer (OCG) — same structure as CAD.",
            "All geometry exports as true vector (lines, arcs, hatches stay sharp at any zoom).",
            "TEXT/MTEXT are exported as vector outlines (curves) for font-independent accuracy.",
        ],
    }


def _content_aspect(doc, layout) -> float:
    """width/height of layout content, best effort."""
    try:
        from ezdxf import bbox as _bbox
        ext = _bbox.extents(layout, fast=True)
        w = float(ext.extmax.x - ext.extmin.x)
        h = float(ext.extmax.y - ext.extmin.y)
        if w > 0 and h > 0:
            return w / h
    except Exception:
        pass
    return 1.41


def _render_pymupdf(doc, layout_names, page_size, orientation, background,
                    lineweight_scaling) -> list[bytes]:
    from ezdxf.addons.drawing import Frontend, RenderContext, layout as _layout
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend

    W, H = PAGE_SIZES_MM.get(page_size, PAGE_SIZES_MM["A3"])
    if background == "white":
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                            lineweight_scaling=lineweight_scaling)
    else:
        cfg = Configuration(background_policy=BackgroundPolicy.BLACK,
                            lineweight_scaling=lineweight_scaling)
    out: list[bytes] = []
    for lname in layout_names:
        layout_obj = doc.layouts.get(lname)
        aspect = _content_aspect(doc, layout_obj)
        pw, ph = W, H
        orient = orientation
        if orient == "auto":
            orient = "landscape" if aspect >= 1.0 else "portrait"
        if orient == "portrait":
            pw, ph = H, W
        ctx = RenderContext(doc)
        backend = PyMuPdfBackend()
        backend.configure(cfg)
        Frontend(ctx, backend, cfg).draw_layout(layout_obj, finalize=True)
        page = _layout.Page(pw, ph, _layout.Units.mm,
                            margins=_layout.Margins.all(10))
        settings = _layout.Settings(fit_page=True, output_layers=True)
        out.append(backend.get_pdf_bytes(page, settings=settings))
    return out


def _render_matplotlib(doc, layout_names, background, out_pdf):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    face = "white" if background == "white" else "black"
    with PdfPages(out_pdf) as pdfpages:
        for lname in layout_names:
            layout_obj = doc.layouts.get(lname)
            ctx = RenderContext(doc)
            fig = plt.figure(figsize=(16.54, 11.69), facecolor=face)
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_axis_off()
            Frontend(ctx, MatplotlibBackend(ax)).draw_layout(layout_obj, finalize=True)
            try:
                ax.autoscale(True)
                ax.set_aspect("equal", adjustable="datalim")
            except Exception:
                pass
            pdfpages.savefig(fig, facecolor=face)
            plt.close(fig)


def convert(path: str, out_pdf: str, options: dict | None = None) -> ConvertResult:
    import ezdxf

    options = options or {}
    layout_opt = options.get("layout", "Model") or "Model"
    page_size = options.get("page_size", "A3") or "A3"
    orientation = options.get("orientation", "auto") or "auto"
    background = options.get("background", "white") or "white"
    backend_opt = options.get("backend", "layered") or "layered"
    try:
        lw_scale = float(options.get("lineweight_scaling", 1.0) or 1.0)
    except Exception:
        lw_scale = 1.0
    warnings: list[str] = []
    notes: list[str] = []

    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise RuntimeError(f"Could not read DXF: {e}")
    try:
        doc.audit()
    except Exception:
        warnings.append("DXF audit found/fixed minor errors.")

    all_layouts = [l.name for l in doc.layouts]
    if layout_opt == "__all__":
        layout_names = all_layouts
    else:
        layout_names = [layout_opt if layout_opt in all_layouts else "Model"]

    engine = ""
    if backend_opt == "layered":
        try:
            import pymupdf
            pdfs = _render_pymupdf(doc, layout_names, page_size, orientation,
                                   background, lw_scale)
            if len(pdfs) == 1:
                # direct write keeps DXF->PDF layer (OCG) toggles intact
                with open(out_pdf, "wb") as f:
                    f.write(pdfs[0])
            else:
                merged = pymupdf.open()
                for b in pdfs:
                    with pymupdf.open(stream=b, filetype="pdf") as single:
                        merged.insert_pdf(single)
                merged.save(out_pdf, garbage=3, deflate=True)
                merged.close()
                notes.append("Multi-layout merge: per-layout layer toggles are flattened "
                             "when combining pages (single layout keeps full layer toggles).")
            engine = "ezdxf PyMuPdf vector backend (DXF layers → PDF layers)"
            if len(pdfs) == 1:
                notes.append("DXF layers exported as toggleable PDF layers (OCG).")
        except Exception as e:
            warnings.append(f"Layered backend issue ({e}); used classic backend.")

    if not engine:
        _render_matplotlib(doc, layout_names, background, out_pdf)
        engine = "ezdxf matplotlib vector backend"
        notes.append("Classic vector render (no per-layer toggles in this mode).")

    set_metadata(out_pdf, os.path.splitext(os.path.basename(path))[0], "DXF")
    stats = pdf_stats(out_pdf)
    if stats.get("vectors", 0) == 0:
        warnings.append("No vector content detected — layout may be empty or paperspace-only. "
                        "Try a different layout.")
    report = {"engine": engine, "layouts_rendered": layout_names,
              "warnings": warnings, "notes": notes, **stats}
    return ConvertResult(out_pdf, report)
