#!/usr/bin/env python3
"""Batch CLI: convert PSD/AI/CDR/EPS/SVG/TIFF/DXF -> PDF.

Examples:
  python3 convert.py design.psd
  python3 convert.py *.dxf --out pdfs/ --dxf-page-size A1
  python3 convert.py scan.tiff --tiff-dpi 300 --tiff-compression zip
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from converters import get  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="ArtViSiON batch converter (RJ Sarkar)")
    ap.add_argument("files", nargs="+", help="input files (globs allowed)")
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--psd-mode", default="layered", choices=["layered", "flattened"])
    ap.add_argument("--no-hidden", action="store_true", help="skip hidden PSD layers")
    ap.add_argument("--flat-dpi", type=int, default=150)
    ap.add_argument("--dpi", type=int, default=300, help="EPS/AI render DPI")
    ap.add_argument("--papersize", default="", help="EPS/AI fit page (a4/a3/letter or ''=artwork)")
    ap.add_argument("--svg-scale", type=float, default=1.0)
    ap.add_argument("--tiff-compression", default="auto", choices=["auto", "zip", "jpeg"])
    ap.add_argument("--tiff-dpi", default="auto")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--dxf-layout", default="Model")
    ap.add_argument("--dxf-page-size", default="A3")
    ap.add_argument("--dxf-bg", default="white", choices=["white", "black"])
    ap.add_argument("--dxf-backend", default="layered", choices=["layered", "classic"])
    ap.add_argument("--report", action="store_true", help="write JSON report next to PDF")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    inputs: list[str] = []
    for pat in args.files:
        hits = sorted(glob.glob(pat))
        inputs.extend(hits if hits else ([pat] if os.path.isfile(pat) else []))
    if not inputs:
        print("No input files found.")
        return 1

    fails = 0
    for src in inputs:
        ext = os.path.splitext(src)[1].lower()
        entry = get(ext)
        if entry is None:
            print(f"[SKIP] {src}: unsupported format")
            fails += 1
            continue
        _analyze, convert, label = entry
        stem = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(args.out, stem + ".pdf")
        options = {
            "psd_mode": args.psd_mode, "include_hidden": not args.no_hidden,
            "flat_dpi": args.flat_dpi, "flat_quality": args.quality,
            "dpi": args.dpi, "papersize": args.papersize,
            "scale": args.svg_scale, "background": "white" if label != "DXF" else args.dxf_bg,
            "compression": args.tiff_compression, "quality": args.quality,
            "layout": args.dxf_layout, "page_size": args.dxf_page_size,
            "backend": args.dxf_backend,
        }
        if label == "TIFF":
            options["dpi"] = args.tiff_dpi
        print(f"[..] {src} ({label}) -> {dst} ...", flush=True)
        try:
            res = convert(src, dst, options)
            r = res.report
            print(f"[OK] pages={r.get('pages')} vectors={r.get('vectors')} "
                  f"text={r.get('text_chars')} ocg={len(r.get('ocg_layers', []))} "
                  f"size={os.path.getsize(dst)} | {r.get('engine')}")
            for w in (r.get("warnings") or [])[:3]:
                print(f"     warn: {w[:160]}")
            if args.report:
                with open(os.path.join(args.out, stem + ".report.json"), "w") as fh:
                    json.dump(r, fh, indent=1, default=str)
        except Exception as e:
            print(f"[FAIL] {src}: {e}")
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
