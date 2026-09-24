"""Converter registry: ext -> (analyze, convert)."""
from . import (ai_converter, cdr_converter, dxf_converter, eps_converter,
               psd_converter, svg_converter, tiff_converter)

REGISTRY = {
    ".psd": (psd_converter.analyze, psd_converter.convert, "PSD"),
    ".psb": (psd_converter.analyze, psd_converter.convert, "PSB"),
    ".ai": (ai_converter.analyze, ai_converter.convert, "AI"),
    ".cdr": (cdr_converter.analyze, cdr_converter.convert, "CDR"),
    ".eps": (eps_converter.analyze, eps_converter.convert, "EPS"),
    ".svg": (svg_converter.analyze, svg_converter.convert, "SVG"),
    ".svgz": (svg_converter.analyze, svg_converter.convert, "SVG"),
    ".tif": (tiff_converter.analyze, tiff_converter.convert, "TIFF"),
    ".tiff": (tiff_converter.analyze, tiff_converter.convert, "TIFF"),
    ".dxf": (dxf_converter.analyze, dxf_converter.convert, "DXF"),
}

SUPPORTED_EXTS = sorted(REGISTRY.keys())


def get(ext: str):
    return REGISTRY.get(ext.lower())
