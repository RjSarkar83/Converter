"""RGB <-> CMYK image converter (JPG/PNG/TIFF).

Professional ICC-profile path: sRGB <-> U.S. Web Coated (SWOP) v2,
with source-embedded-profile support. Naive fallback when ICC off.
"""
from __future__ import annotations

import io
import os

import numpy as np
from PIL import Image, ImageCms

from .base import human_size, pil_thumb_b64

PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "profiles")
SRGB_PATH = os.path.join(PROFILES_DIR, "sRGB.icc")
SWOP_PATH = os.path.join(PROFILES_DIR, "USWebCoatedSWOP.icc")

INTENTS = {"perceptual": ImageCms.Intent.PERCEPTUAL,
           "relative": ImageCms.Intent.RELATIVE_COLORIMETRIC,
           "saturation": ImageCms.Intent.SATURATION,
           "absolute": ImageCms.Intent.ABSOLUTE_COLORIMETRIC}

COLOR_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp")


def icc_available() -> bool:
    return os.path.exists(SRGB_PATH) and os.path.exists(SWOP_PATH)


def _profile_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def _embedded_profile(im: Image.Image):
    """Source embedded ICC (e.g. AdobeRGB JPG from camera) or None."""
    try:
        raw = im.info.get("icc_profile")
        if raw:
            return ImageCms.getOpenProfile(io.BytesIO(raw))
    except Exception:
        pass
    return None


def _profile_name(p) -> str:
    try:
        return ImageCms.getProfileName(p).strip().strip("\x00")
    except Exception:
        return "embedded"


def _flatten(im: Image.Image, notes: list) -> Image.Image:
    if im.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        try:
            bg.paste(im, mask=im.split()[-1])
        except Exception:
            bg.paste(im)
        notes.append("Transparency flattened onto white (standard for print CMYK).")
        return bg
    if im.mode == "P":
        return im.convert("RGB")
    if im.mode in ("I;16", "I;16B", "I;16L"):
        notes.append("16-bit → 8-bit for output.")
        return Image.fromarray((np.array(im) >> 8).astype("uint8"), "L").convert("RGB")
    if im.mode in ("I", "F"):
        return im.convert("L").convert("RGB")
    if im.mode == "L":
        return im.convert("RGB")
    return im


def _tac_stats(cmyk: Image.Image) -> tuple[float, float]:
    try:
        a = np.asarray(cmyk).astype(np.float32)
        tac = a.sum(axis=2) / 2.55  # -> percent
        return round(float(tac.max()), 1), round(float(tac.mean()), 1)
    except Exception:
        return 0.0, 0.0


# ------------------------------------------------------------------ public
def analyze(path: str) -> dict:
    notes: list[str] = []
    im = Image.open(path)
    im.load()
    if getattr(im, "n_frames", 1) > 1:
        notes.append("Multi-page TIFF — first page will be converted.")
        try:
            im.seek(0)
        except Exception:
            pass
    emb = _embedded_profile(im)
    if emb is not None:
        notes.append(f"Embedded source profile detected: {_profile_name(emb)} — "
                     f"it will be honoured.")
    direction = "cmyk2rgb" if im.mode == "CMYK" else "rgb2cmyk"
    return {
        "format": "COLOR",
        "format_label": "Image for color conversion",
        "version_label": f"{im.mode} · {im.width}×{im.height}",
        "file_size": os.path.getsize(path),
        "width": im.width, "height": im.height, "mode": im.mode,
        "embedded_profile": _profile_name(emb) if emb else "",
        "suggest_direction": direction,
        "icc_available": icc_available(),
        "thumb": pil_thumb_b64(im.convert("RGB") if im.mode == "CMYK" else im),
        "layers_total": 1,
        "counts": {"text": 0, "bitmap": 1, "vector": 0, "shape": 0, "group": 0,
                   "adjustment": 0, "smartobject": 0, "fill": 0, "dimension": 0,
                   "hatch": 0, "block": 0, "other": 0},
        "layers": [{"name": f"Image {im.width}×{im.height} {im.mode}",
                    "kind": "bitmap", "type": "raster", "visible": True, "depth": 0}],
        "warnings": [],
        "notes": notes + [
            "RGB → CMYK: press-ready separation (U.S. Web Coated SWOP v2).",
            "CMYK → RGB: screen-ready sRGB.",
        ],
    }


def convert(path: str, workdir: str, options: dict | None = None) -> dict:
    options = options or {}
    direction = options.get("direction", "auto") or "auto"
    out_fmt = (options.get("format", "auto") or "auto").lower()
    try:
        quality = int(options.get("quality", 95) or 95)
    except Exception:
        quality = 95
    intent = INTENTS.get(options.get("intent", "perceptual") or "perceptual",
                         ImageCms.Intent.PERCEPTUAL)
    intent_name = options.get("intent", "perceptual") or "perceptual"
    use_icc = bool(options.get("use_icc", True)) and icc_available()

    os.makedirs(workdir, exist_ok=True)
    notes: list[str] = []
    warnings: list[str] = []

    im = Image.open(path)
    im.load()
    try:
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
    except Exception:
        pass
    src_mode = im.mode

    if direction == "auto":
        direction = "cmyk2rgb" if src_mode == "CMYK" else "rgb2cmyk"
    to_cmyk = direction == "rgb2cmyk"

    # normalize inputs
    if to_cmyk and src_mode == "CMYK":
        notes.append("Source is already CMYK — re-separated through press profile "
                     "(normalizes TAC) and re-saved.")
    if not to_cmyk and src_mode != "CMYK":
        notes.append(f"Source is {src_mode} (not CMYK) — converted/normalized to sRGB.")

    work = _flatten(im, notes)
    if to_cmyk and work.mode != "RGB":
        work = work.convert("RGB")

    method = ""
    if use_icc:
        try:
            srgb = ImageCms.getOpenProfile(SRGB_PATH)
            swop = ImageCms.getOpenProfile(SWOP_PATH)
            if to_cmyk:
                src_prof = _embedded_profile(im) or srgb
                if _embedded_profile(im) is not None:
                    notes.append(f"Source profile honoured: {_profile_name(src_prof)}.")
                t = ImageCms.buildTransform(src_prof, swop, "RGB", "CMYK",
                                            renderingIntent=intent)
                out = ImageCms.applyTransform(work.convert("RGB"), t)
                method = (f"ICC: {_profile_name(src_prof)} → U.S. Web Coated (SWOP) v2 "
                          f"({intent_name})")
                out_profile_bytes = _profile_bytes(SWOP_PATH)
            else:
                src_prof = swop if src_mode == "CMYK" else ImageCms.createProfile("sRGB")
                if src_mode == "CMYK":
                    t = ImageCms.buildTransform(src_prof, srgb, "CMYK", "RGB",
                                                renderingIntent=intent)
                    out = ImageCms.applyTransform(work, t)
                    method = (f"ICC: U.S. Web Coated (SWOP) v2 → sRGB ({intent_name})")
                else:
                    out = work.convert("RGB")
                    method = "sRGB normalize (source was not CMYK)"
                out_profile_bytes = _profile_bytes(SRGB_PATH)
        except Exception as e:
            warnings.append(f"ICC transform failed ({e}) — used standard conversion.")
            use_icc = False
    if not use_icc:
        if to_cmyk:
            out = work.convert("RGB").convert("CMYK")
            method = "Standard conversion (no ICC profile)"
        else:
            out = work.convert("RGB")
            method = "Standard conversion (no ICC profile)"
        out_profile_bytes = None
        if options.get("use_icc", True):
            notes.append("ICC profiles not found — standard conversion used.")

    # output format
    if out_fmt == "auto":
        out_fmt = "tiff" if to_cmyk else "png"
    if to_cmyk and out_fmt == "png":
        warnings.append("PNG cannot store CMYK — switched to TIFF (proper print format).")
        out_fmt = "tiff"
    ext = {"tiff": ".tif", "jpg": ".jpg", "jpeg": ".jpg", "png": ".png"}.get(out_fmt, ".tif")
    out_path = os.path.join(workdir, "out" + ext)
    save_kw: dict = {}
    if out_profile_bytes:
        save_kw["icc_profile"] = out_profile_bytes
    if ext == ".jpg":
        out.save(out_path, "JPEG", quality=quality, **save_kw)
        if to_cmyk:
            warnings.append("CMYK JPEG is for PRINT workflows — web browsers will show "
                            "wrong colors. Prefer TIFF for press.")
    elif ext == ".tif":
        out.save(out_path, "TIFF", compression="tiff_lzw", **save_kw)
    else:
        out.save(out_path, "PNG", **save_kw)

    # RGB proof preview (so CMYK result is viewable)
    try:
        if out.mode == "CMYK" and icc_available():
            swop = ImageCms.getOpenProfile(SWOP_PATH)
            srgb = ImageCms.getOpenProfile(SRGB_PATH)
            t = ImageCms.buildTransform(swop, srgb, "CMYK", "RGB",
                                        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
            proof = ImageCms.applyTransform(out, t)
        else:
            proof = out.convert("RGB")
    except Exception:
        proof = out.convert("RGB")

    tac_max, tac_mean = _tac_stats(out) if out.mode == "CMYK" else (0.0, 0.0)
    if out.mode == "CMYK":
        notes.append(f"Total ink (TAC): max {tac_max}%, mean {tac_mean}% "
                     f"(SWOP-safe ≤ ~300%).")
        if tac_max > 340:
            warnings.append(f"Max TAC {tac_max}% is high for coated press — dark areas "
                            f"may smear. This is normal for rich blacks.")

    report = {
        "engine": "LittleCMS ICC" if options.get("use_icc", True) and icc_available()
                  else "Pillow standard",
        "method": method,
        "src_mode": src_mode,
        "dst_mode": out.mode,
        "direction": ("RGB → CMYK (press)" if to_cmyk else "CMYK → RGB (screen)"),
        "out_format": ext,
        "out_size_h": human_size(os.path.getsize(out_path)),
        "tac_max": tac_max, "tac_mean": tac_mean,
        "icc_embedded": bool(out_profile_bytes),
        "preview_in": pil_thumb_b64(im.convert("RGB") if im.mode == "CMYK" else im),
        "preview_out": pil_thumb_b64(proof),
        "warnings": warnings,
        "notes": notes,
    }
    return {"out_path": out_path, "report": report}
