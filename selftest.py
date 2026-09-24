"""End-to-end self test of all 7 converters."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from converters import get  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
OUT = os.path.join(TEST, "out")
os.makedirs(OUT, exist_ok=True)

CASES = [
    ("sample.psd", {"psd_mode": "layered", "include_hidden": True}),
    ("t.ai", {}),
    ("real.cdr", {}),
    ("t.eps", {}),
    ("t.svg", {}),
    ("t.tiff", {"compression": "auto", "dpi": "auto"}),
    ("t.dxf", {"layout": "Model", "page_size": "A3", "orientation": "auto",
               "background": "white", "backend": "layered"}),
]

fails = 0
for fname, opts in CASES:
    src = os.path.join(TEST, fname)
    ext = os.path.splitext(fname)[1]
    entry = get(ext)
    print(f"\n===== {fname} =====")
    if not os.path.exists(src):
        print("  MISSING SAMPLE — skip"); fails += 1; continue
    analyze, convert, label = entry
    try:
        a = analyze(src)
        print(f"  analyze: layers={a.get('layers_total')} counts={a.get('counts')}")
        if a.get("warnings"):
            print(f"  analyze warnings: {a['warnings'][:2]}")
    except Exception as e:
        print(f"  ANALYZE FAIL: {e}"); fails += 1; continue
    dst = os.path.join(OUT, os.path.splitext(fname)[0] + ".pdf")
    try:
        res = convert(src, dst, opts)
        r = res.report
        print(f"  convert: engine={r.get('engine')}")
        print(f"  output: pages={r.get('pages')} vectors={r.get('vectors')} "
              f"text_chars={r.get('text_chars')} images={r.get('images')} "
              f"ocg={len(r.get('ocg_layers', []))} size={os.path.getsize(dst)}")
        if r.get("warnings"):
            for w in r["warnings"][:3]:
                print(f"  warn: {w[:160]}")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  CONVERT FAIL: {e}"); fails += 1

print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURES'}")
