"""ArtViSiON QA matrix: every tool x key options, with timings."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []
tests = []


def run(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        dt = time.time() - t0
        tests.append((name, True, dt, detail))
        print(f"  PASS {name} ({dt:.1f}s) {detail}")
    except Exception as e:
        dt = time.time() - t0
        tests.append((name, False, dt, str(e)[:150]))
        fails.append(name)
        print(f"  FAIL {name} ({dt:.1f}s): {e}")


from converters import (ai_converter, cdr_converter, colorlab, dxf_converter,
                        eps_converter, psd_converter, svg_converter,
                        tiff_converter, vectorize)

S = "samples"
T = "test"
V = "test/versions"
OUT = "/tmp/qa"
os.makedirs(OUT, exist_ok=True)
n = [0]


def dst(suffix=".pdf"):
    n[0] += 1
    return os.path.join(OUT, f"qa{n[0]:03d}{suffix}")


print("== PDF: 7 formats ==")
run("PSD layered", lambda: psd_converter.convert(f"{S}/demo.psd", dst(), {"psd_mode": "layered"}) and "ocg")
run("PSD flattened", lambda: psd_converter.convert(f"{S}/demo.psd", dst(), {"psd_mode": "flattened", "flat_dpi": 300}))
run("AI pdf-direct", lambda: ai_converter.convert(f"{S}/demo.ai", dst(), {}))
run("CDR real", lambda: cdr_converter.convert(f"{T}/real.cdr", dst(), {}))
run("EPS bbox", lambda: eps_converter.convert(f"{S}/demo.eps", dst(), {}))
run("EPS A4-fit", lambda: eps_converter.convert(f"{S}/demo.eps", dst(), {"papersize": "a4"}))
run("SVG", lambda: svg_converter.convert(f"{S}/demo.svg", dst(), {"scale": 2.0}))
run("TIFF multi", lambda: tiff_converter.convert(f"{S}/demo.tiff", dst(), {"compression": "zip"}))
run("TIFF jpeg", lambda: tiff_converter.convert(f"{S}/demo.tiff", dst(), {"compression": "jpeg", "quality": 80}))
run("DXF layered", lambda: dxf_converter.convert(f"{S}/demo.dxf", dst(), {"backend": "layered", "page_size": "A1"}))
run("DXF classic-black", lambda: dxf_converter.convert(f"{S}/demo.dxf", dst(), {"backend": "classic", "background": "black"}))

print("== Versions/edge ==")
run("SVGZ", lambda: svg_converter.convert(f"{V}/vtest.svgz", dst(), {}))
run("PDF-as-EPS", lambda: eps_converter.convert(f"{V}/vtest_fakeeps.eps", dst(), {}))
run("CMYK TIFF", lambda: tiff_converter.convert(f"{V}/vtest_cmyk.tif", dst(), {}))
run("16-bit TIFF", lambda: tiff_converter.convert(f"{V}/vtest_16bit.tif", dst(), {}))
run("G4 fax TIFF", lambda: tiff_converter.convert(f"{V}/vtest_g4.tif", dst(), {}))

print("== Vectorize matrix ==")
for detail in ("minimal", "balanced", "detailed"):
    for bg in ("white", "transparent"):
        run(f"VEC {detail}/{bg}",
            lambda d=detail, b=bg: vectorize.convert(
                f"{S}/demo_art.jpg", os.path.join(OUT, f"v_{d}_{b}"),
                {"detail": d, "background": b})["report"]["engine"])
run("VEC invert+manual", lambda: vectorize.convert(
    f"{S}/demo_art.jpg", os.path.join(OUT, "v_inv"),
    {"detail": "balanced", "invert": True, "threshold": 100,
     "denoise": 2, "max_dim": 800})["report"]["threshold_used"])
run("VEC potrace-fallback", lambda: vectorize.convert(
    f"{S}/demo_art.jpg", os.path.join(OUT, "v_pot"),
    {"detail": "minimal", "engine": "potrace"})["report"]["trace_engine"])

print("== Color matrix ==")
run("RGB->CMYK tiff/icc", lambda: colorlab.convert(
    f"{S}/demo_color.jpg", os.path.join(OUT, "c1"),
    {"direction": "rgb2cmyk", "format": "tiff"})["report"]["method"][:40])
run("RGB->CMYK jpg", lambda: colorlab.convert(
    f"{S}/demo_color.jpg", os.path.join(OUT, "c2"),
    {"direction": "rgb2cmyk", "format": "jpg", "quality": 90,
     "intent": "saturation"})["report"]["out_format"])
run("RGB->CMYK png-forced", lambda: colorlab.convert(
    f"{S}/demo_color.jpg", os.path.join(OUT, "c3"),
    {"direction": "rgb2cmyk", "format": "png"})["report"]["out_format"])
run("RGB->CMYK naive", lambda: colorlab.convert(
    f"{S}/demo_color.jpg", os.path.join(OUT, "c4"),
    {"direction": "rgb2cmyk", "use_icc": False})["report"]["method"][:30])
run("CMYK->RGB", lambda: colorlab.convert(
    "test/new/logo_cmyk.tif", os.path.join(OUT, "c5"),
    {"direction": "auto", "format": "auto"})["report"]["direction"])

print("== Analyze matrix (all samples) ==")
import glob
from converters import get as _get
for f in sorted(glob.glob(f"{S}/*")):
    ext = os.path.splitext(f)[1].lower()
    if ext in (".jpg",):
        continue
    entry = _get(ext)
    if entry:
        run(f"ANALYZE {os.path.basename(f)}",
            lambda f=f, e=entry: e[0](f).get("version_label", "?"))

total = sum(t for _, _, t, _ in tests)
print(f"\n==== {len(tests)-len(fails)}/{len(tests)} PASS, total {total:.1f}s ====")
if fails:
    print("FAILURES:", fails)
    sys.exit(1)
