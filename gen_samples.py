"""Generate professional demo files for one-click trials."""
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(BASE, "samples")
os.makedirs(S, exist_ok=True)

# ---------------- SVG ----------------
open(os.path.join(S, "demo.svg"), "w").write("""<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#818cf8"/></linearGradient></defs>
<rect x="8" y="8" width="544" height="384" rx="14" fill="#0d1117" stroke="url(#g)" stroke-width="4"/>
<g id="shapes">
<rect x="40" y="50" width="150" height="100" rx="10" fill="#2563eb"/>
<circle cx="330" cy="100" r="55" fill="#dc2626"/>
<polygon points="460,50 520,150 400,150" fill="#16a34a"/>
<path d="M40,300 C140,220 220,380 320,300 S460,260 520,320" fill="none" stroke="#fbbf24" stroke-width="6"/>
</g>
<g id="labels">
<text x="40" y="200" font-family="Arial" font-size="30" fill="#ffffff">PDFLayer Studio</text>
<text x="40" y="235" font-family="Arial" font-size="16" fill="#9aa7bd">Vector shapes + live text demo</text>
<text x="330" y="230" font-family="Arial" font-size="20" fill="#22d3ee">100% vector</text>
</g>
</svg>""")

# ---------------- EPS ----------------
open(os.path.join(S, "demo.eps"), "w").write("""%!PS-Adobe-3.0 EPSF-3.0
%%Creator: PDFLayer Studio demo
%%Title: EPS vector demo
%%Pages: 1
%%BoundingBox: 0 0 500 350
%%DocumentFonts: Helvetica-Bold Helvetica
%%EndComments
0.05 0.07 0.10 setrgbcolor
0 0 500 350 rectfill
0.13 0.39 0.92 setrgbcolor
30 180 140 120 rectfill
0.86 0.15 0.15 setrgbcolor
330 240 55 0 360 arc fill
0.08 0.64 0.29 setrgbcolor
newpath 420 180 moveto 480 300 lineto 360 300 lineto closepath fill
1 1 1 setrgbcolor
/Helvetica-Bold findfont 30 scalefont setfont
30 140 moveto (PDFLayer Studio) show
/Helvetica findfont 15 scalefont setfont
0.6 0.65 0.74 setrgbcolor
30 112 moveto (EPS vectors + real text demo) show
0.13 0.83 0.93 setrgbcolor
6 setlinewidth
30 60 moveto 470 60 lineto stroke
showpage
%%EOF
""")

# ---------------- AI (PDF-compatible) ----------------
import warnings
warnings.filterwarnings("ignore")
import pymupdf
d = pymupdf.open()
p = d.new_page(width=560, height=400)
p.draw_rect(pymupdf.Rect(8, 8, 552, 392), fill=(0.05, 0.07, 0.10), color=(0.13, 0.83, 0.93), width=4)
p.draw_rect(pymupdf.Rect(40, 50, 190, 150), fill=(0.15, 0.39, 0.92), color=None)
p.draw_circle(pymupdf.Point(330, 100), 55, fill=(0.86, 0.15, 0.15), color=None)
tri = [pymupdf.Point(460, 50), pymupdf.Point(520, 150), pymupdf.Point(400, 150),
       pymupdf.Point(460, 50)]
p.draw_polyline(tri, color=(0.08, 0.64, 0.29), fill=(0.08, 0.64, 0.29), width=2)
p.insert_text((40, 205), "PDFLayer Studio", fontsize=30, color=(1, 1, 1))
p.insert_text((40, 232), "Illustrator vectors + live text demo", fontsize=15, color=(0.6, 0.65, 0.74))
oc = d.add_ocg("Demo Artwork", on=True)
p.draw_line(pymupdf.Point(40, 300), pymupdf.Point(520, 300), color=(0.13, 0.83, 0.93), width=4)
d.save(os.path.join(S, "demo.ai"), garbage=3, deflate=True)
d.close()

# ---------------- TIFF (2 pages) ----------------
from PIL import Image, ImageDraw
frames = []
for i, (bg, label) in enumerate([((37, 99, 235), "TIFF Page 1 — 300 DPI print scan"),
                                 ((22, 163, 74), "TIFF Page 2 — multi-page demo")]):
    im = Image.new("RGB", (1240, 900), (13, 17, 23))
    dr = ImageDraw.Draw(im)
    dr.rectangle([60, 60, 1180, 840], outline=bg, width=10)
    dr.rectangle([110, 140, 750, 320], fill=bg)
    dr.text((140, 190), "PDFLayer Studio", fill="white")
    dr.text((140, 260), label, fill="white")
    dr.text((140, 420), f"Resolution 1240x900 @ 300dpi = {1240/300:.1f} x {900/300:.1f} inch print size",
            fill=(200, 210, 225))
    frames.append(im)
frames[0].save(os.path.join(S, "demo.tiff"), save_all=True, append_images=frames[1:], dpi=(300, 300))

# ---------------- DXF ----------------
import ezdxf
doc = ezdxf.new("R2018")
doc.layers.add("WALLS", color=1)
doc.layers.add("DOORS", color=3)
doc.layers.add("TEXT_NOTES", color=150)
doc.layers.add("DIMENSIONS", color=5)
doc.layers.add("HATCH", color=8)
msp = doc.modelspace()
msp.add_lwpolyline([(0, 0), (120, 0), (120, 80), (0, 80), (0, 0)], dxfattribs={"layer": "WALLS"})
msp.add_line((40, 0), (40, 80), dxfattribs={"layer": "WALLS"})
msp.add_line((80, 0), (80, 80), dxfattribs={"layer": "WALLS"})
msp.add_circle((20, 40), 8, dxfattribs={"layer": "DOORS"})
msp.add_arc((100, 40), 12, 0, 180, dxfattribs={"layer": "DOORS"})
msp.add_text("PDFLayer Studio — CAD Demo", height=6, dxfattribs={"layer": "TEXT_NOTES"}).set_placement((10, 90))
msp.add_text("Walls / Doors / Hatches on separate layers", height=3.5,
             dxfattribs={"layer": "TEXT_NOTES"}).set_placement((10, -10))
h = msp.add_hatch(color=8, dxfattribs={"layer": "HATCH"})
h.paths.add_polyline_path([(85, 5), (115, 5), (115, 25), (85, 25)], is_closed=True)
h.set_pattern_fill("ANSI31", scale=2)
dim = msp.add_linear_dim(base=(0, -16), p1=(0, 0), p2=(120, 0), dxfattribs={"layer": "DIMENSIONS"})
dim.render()
doc.saveas(os.path.join(S, "demo.dxf"))

# ---------------- PSD (reuse MIT-licensed psd-tools test fixture) ----------------
src_psd = os.path.join(BASE, "test", "sample.psd")
if os.path.exists(src_psd):
    shutil.copyfile(src_psd, os.path.join(S, "demo.psd"))
    print("demo.psd copied from psd-tools test fixture (MIT)")

print("samples:", sorted(os.listdir(S)))
