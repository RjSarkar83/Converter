"""ArtViSiON 2.0 by RJ Sarkar — PSD/AI/CDR/EPS/SVG/TIFF/DXF -> PDF
+ JPG/PNG Vectorize Art + RGB<->CMYK Color Lab."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
import zipfile

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from converters import SUPPORTED_EXTS, get
from converters import colorlab, vectorize
from converters.base import (gs_available, human_size, pdf_preview_b64,
                             soffice_available)

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
SAMPLES = os.path.join(BASE, "samples")
os.makedirs(JOBS, exist_ok=True)
os.makedirs(SAMPLES, exist_ok=True)

TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
FILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB
app.config["JSON_SORT_KEYS"] = False


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def _cors_preflight(_any):
    return ("", 204)


# ------------------------------------------------------------ housekeeping
def cleanup_old_jobs(max_age_h: float = 3.0):
    now = time.time()
    try:
        for token in os.listdir(JOBS):
            p = os.path.join(JOBS, token)
            if not os.path.isdir(p):
                continue
            try:
                if now - os.path.getmtime(p) > max_age_h * 3600:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def _janitor():
    while True:
        time.sleep(1800)
        cleanup_old_jobs()


threading.Thread(target=_janitor, daemon=True).start()


def job_dir(token: str) -> str | None:
    if not TOKEN_RE.match(token or ""):
        return None
    p = os.path.join(JOBS, token)
    return p if os.path.isdir(p) else None


def _token_tool(jd: str) -> str | None:
    """Which tool owns this job ('pdf' if unset = legacy pdf job)."""
    try:
        with open(os.path.join(jd, "analysis.json")) as fh:
            return json.load(fh).get("tool") or "pdf"
    except Exception:
        return None


def _save_upload(f, allowed: tuple | list, allowed_msg: str):
    if not f or not f.filename:
        return None, "Empty filename."
    filename = secure_filename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        return None, f"Unsupported format '{ext}'. Allowed: {allowed_msg}"
    token = uuid.uuid4().hex
    jd = os.path.join(JOBS, token)
    os.makedirs(jd, exist_ok=True)
    src = os.path.join(jd, "source" + ext)
    try:
        f.save(src)
    except Exception as e:
        shutil.rmtree(jd, ignore_errors=True)
        return None, f"Upload failed: {e}"
    if os.path.getsize(src) == 0:
        shutil.rmtree(jd, ignore_errors=True)
        return None, "Uploaded file is empty (0 bytes)."
    return {"token": token, "jobdir": jd, "src": src, "ext": ext,
            "filename": filename, "size": os.path.getsize(src)}, ""


def _job_source(jd: str):
    for f in os.listdir(jd):
        if f.startswith("source."):
            return os.path.join(jd, f)
    return None


def _orig_stem(jd: str) -> str:
    try:
        with open(os.path.join(jd, "analysis.json")) as fh:
            original = json.load(fh).get("filename", "file")
        return os.path.splitext(secure_filename(original))[0] or "converted"
    except Exception:
        return "converted"


def _parse_options():
    try:
        return json.loads(request.form.get("options", "{}") or "{}")
    except Exception:
        return {}


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/samples/<path:name>")
def samples(name: str):
    return send_from_directory(SAMPLES, name, as_attachment=False)


# -------------------------------------------------------------------- api
@app.route("/api/engines")
def engines():
    try:
        import vtracer  # noqa: F401
        has_vtracer = True
    except Exception:
        has_vtracer = False
    return jsonify({
        "ok": True,
        "app": "ArtViSiON 2.0 by RJ Sarkar",
        "ghostscript": gs_available(),
        "libreoffice": soffice_available(),
        "vtracer": has_vtracer,
        "icc": colorlab.icc_available(),
        "supported": SUPPORTED_EXTS,
        "raster": sorted(set(vectorize.RASTER_EXTS)),
        "max_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    })


@app.route("/api/samples")
def sample_list():
    out = []
    try:
        for f in sorted(os.listdir(SAMPLES)):
            fp = os.path.join(SAMPLES, f)
            if os.path.isfile(fp):
                out.append({"name": f, "size": os.path.getsize(fp),
                            "url": f"/samples/{f}"})
    except Exception:
        pass
    return jsonify({"ok": True, "samples": out})


# ------------------------------------------------------- pdf converter api
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    cleanup_old_jobs()
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    info, err = _save_upload(request.files["file"], SUPPORTED_EXTS,
                             ", ".join(SUPPORTED_EXTS))
    if info is None:
        return jsonify({"ok": False, "error": err}), 400
    analyze, _, label = get(info["ext"])
    try:
        result = analyze(info["src"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:800]}), 400
    result.update({"ok": True, "token": info["token"], "filename": info["filename"],
                   "size": info["size"], "size_h": human_size(info["size"]),
                   "ext": info["ext"], "label": label, "tool": "pdf"})
    try:
        with open(os.path.join(info["jobdir"], "analysis.json"), "w") as fh:
            json.dump(result, fh, default=str)
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/convert", methods=["POST"])
def api_convert():
    jd = job_dir(request.form.get("token", ""))
    if jd is None:
        return jsonify({"ok": False, "error": "Invalid or expired file token. Re-upload."}), 400
    if _token_tool(jd) != "pdf":
        return jsonify({"ok": False, "error": "This file belongs to another tool. Re-upload in PDF Converter."}), 400
    options = _parse_options()
    src = _job_source(jd)
    if src is None:
        return jsonify({"ok": False, "error": "Source file missing. Re-upload."}), 400
    ext = os.path.splitext(src)[1].lower()
    entry = get(ext)
    if entry is None:
        return jsonify({"ok": False, "error": f"Unsupported format '{ext}'."}), 400
    _, convert, _label = entry
    out_pdf = os.path.join(jd, "output.pdf")
    t0 = time.time()
    try:
        res = convert(src, out_pdf, options)
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return jsonify({"ok": False, "error": str(e)[:1000], "trace": tb[-1200:]}), 400
    elapsed = round(time.time() - t0, 1)
    try:
        res.report["elapsed_s"] = elapsed
        with open(os.path.join(jd, "report.json"), "w") as fh:
            json.dump(res.report, fh, default=str)
    except Exception:
        pass
    stem = _orig_stem(jd)
    return jsonify({
        "ok": True,
        "report": res.report,
        "download_url": f"/api/download/{jd.split('/')[-1]}",
        "pdf_name": f"{stem}.pdf",
        "pdf_size": os.path.getsize(out_pdf),
        "pdf_size_h": human_size(os.path.getsize(out_pdf)),
        "preview_out": pdf_preview_b64(out_pdf),
        "elapsed_s": elapsed,
    })


@app.route("/api/download/<token>")
def api_download(token: str):
    jd = job_dir(token)
    if jd is None:
        return jsonify({"ok": False, "error": "Invalid token."}), 404
    pdf = os.path.join(jd, "output.pdf")
    if not os.path.exists(pdf):
        return jsonify({"ok": False, "error": "Not converted yet."}), 404
    return send_file(pdf, as_attachment=True, download_name=f"{_orig_stem(jd)}.pdf",
                     mimetype="application/pdf")


# ------------------------------------------------------- vectorize + color
def _tool_analyze(mod, tool: str):
    cleanup_old_jobs()
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    allowed = vectorize.RASTER_EXTS if tool == "vec" else colorlab.COLOR_EXTS
    info, err = _save_upload(request.files["file"], allowed, "JPG, PNG, TIFF, WebP, BMP")
    if info is None:
        return jsonify({"ok": False, "error": err}), 400
    try:
        result = mod.analyze(info["src"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:800]}), 400
    result.update({"ok": True, "token": info["token"], "filename": info["filename"],
                   "size": info["size"], "size_h": human_size(info["size"]),
                   "ext": info["ext"], "tool": tool})
    try:
        with open(os.path.join(info["jobdir"], "analysis.json"), "w") as fh:
            json.dump(result, fh, default=str)
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/vec/analyze", methods=["POST"])
def api_vec_analyze():
    return _tool_analyze(vectorize, "vec")


@app.route("/api/color/analyze", methods=["POST"])
def api_color_analyze():
    return _tool_analyze(colorlab, "color")


@app.route("/api/vec/convert", methods=["POST"])
def api_vec_convert():
    jd = job_dir(request.form.get("token", ""))
    if jd is None:
        return jsonify({"ok": False, "error": "Invalid or expired token. Re-upload."}), 400
    if _token_tool(jd) != "vec":
        return jsonify({"ok": False, "error": "This file belongs to another tool. Re-upload in Vectorize Art."}), 400
    options = _parse_options()
    src = _job_source(jd)
    if src is None:
        return jsonify({"ok": False, "error": "Source file missing. Re-upload."}), 400
    t0 = time.time()
    try:
        out = vectorize.convert(src, jd, options)
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return jsonify({"ok": False, "error": str(e)[:1000], "trace": tb[-1200:]}), 400
    elapsed = round(time.time() - t0, 1)
    token = jd.split("/")[-1]
    stem = _orig_stem(jd)
    out["report"]["elapsed_s"] = elapsed
    try:
        with open(os.path.join(jd, "report.json"), "w") as fh:
            json.dump(out["report"], fh, default=str)
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "report": out["report"],
        "svg_url": f"/api/file/{token}/art.svg",
        "pdf_url": f"/api/file/{token}/art.pdf",
        "svg_name": f"{stem}_vector.svg",
        "pdf_name": f"{stem}_vector.pdf",
        "elapsed_s": elapsed,
    })


@app.route("/api/color/convert", methods=["POST"])
def api_color_convert():
    jd = job_dir(request.form.get("token", ""))
    if jd is None:
        return jsonify({"ok": False, "error": "Invalid or expired token. Re-upload."}), 400
    if _token_tool(jd) != "color":
        return jsonify({"ok": False, "error": "This file belongs to another tool. Re-upload in Color Lab."}), 400
    options = _parse_options()
    src = _job_source(jd)
    if src is None:
        return jsonify({"ok": False, "error": "Source file missing. Re-upload."}), 400
    t0 = time.time()
    try:
        out = colorlab.convert(src, jd, options)
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        return jsonify({"ok": False, "error": str(e)[:1000], "trace": tb[-1200:]}), 400
    elapsed = round(time.time() - t0, 1)
    token = jd.split("/")[-1]
    stem = _orig_stem(jd)
    fname = os.path.basename(out["out_path"])
    tag = "cmyk" if out["report"].get("dst_mode") == "CMYK" else "rgb"
    out["report"]["elapsed_s"] = elapsed
    try:
        with open(os.path.join(jd, "report.json"), "w") as fh:
            json.dump(out["report"], fh, default=str)
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "report": out["report"],
        "file_url": f"/api/file/{token}/{fname}",
        "file_name": f"{stem}_{tag}{os.path.splitext(fname)[1]}",
        "elapsed_s": elapsed,
    })


@app.route("/api/file/<token>/<fname>")
def api_file(token: str, fname: str):
    jd = job_dir(token)
    if jd is None or not FILE_RE.match(fname or ""):
        return jsonify({"ok": False, "error": "Invalid token/file."}), 404
    allowed_names = {"art.svg", "art.pdf", "out.tif", "out.tiff", "out.jpg",
                     "out.jpeg", "out.png", "bw.png"}
    if fname not in allowed_names:
        return jsonify({"ok": False, "error": "Not downloadable."}), 404
    fp = os.path.join(jd, fname)
    if not os.path.exists(fp):
        return jsonify({"ok": False, "error": "File not ready."}), 404
    mime = {"art.svg": "image/svg+xml", "art.pdf": "application/pdf",
            "out.tif": "image/tiff", "out.tiff": "image/tiff",
            "out.jpg": "image/jpeg", "out.jpeg": "image/jpeg",
            "out.png": "image/png", "bw.png": "image/png"}.get(fname)
    stem = _orig_stem(jd)
    if fname == "art.svg":
        dl = f"{stem}_vector.svg"
    elif fname == "art.pdf":
        dl = f"{stem}_vector.pdf"
    elif fname.startswith("out."):
        tag = "file"
        try:
            with open(os.path.join(jd, "report.json")) as fh:
                tag = "cmyk" if json.load(fh).get("dst_mode") == "CMYK" else "rgb"
        except Exception:
            pass
        dl = f"{stem}_{tag}{os.path.splitext(fname)[1]}"
    else:
        dl = f"{stem}_{fname}"
    return send_file(fp, as_attachment=True, download_name=dl, mimetype=mime)


@app.route("/api/zip", methods=["POST"])
def api_zip():
    data = request.get_json(force=True, silent=True) or {}
    tokens = data.get("tokens", [])
    if not tokens:
        return jsonify({"ok": False, "error": "No files selected."}), 400
    tmp = os.path.join(JOBS, f"bundle_{uuid.uuid4().hex}.zip")
    used_names: set[str] = set()
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for token in tokens:
            jd = job_dir(token)
            if jd is None:
                continue
            if _token_tool(jd) != "pdf":
                continue
            pdf = os.path.join(jd, "output.pdf")
            if not os.path.exists(pdf):
                continue
            name = _orig_stem(jd)
            cname = f"{name}.pdf"
            i = 2
            while cname in used_names:
                cname = f"{name}_{i}.pdf"
                i += 1
            used_names.add(cname)
            zf.write(pdf, cname)
            n += 1
    if n == 0:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return jsonify({"ok": False, "error": "No converted PDFs found."}), 400
    return send_file(tmp, as_attachment=True, download_name="artvision_pdfs.zip",
                     mimetype="application/zip")


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"ok": False, "error": "File too large (max 300 MB)."}), 413


if __name__ == "__main__":
    cleanup_old_jobs()
    app.run(host="0.0.0.0", port=5000, threaded=True)
