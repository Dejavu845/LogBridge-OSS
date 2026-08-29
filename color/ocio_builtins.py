"""OCIO BuiltinTransform helpers.

config.ocio names Academy/vendor BuiltinTransform styles so Mac OpenColorIO
uses them. Python calls the same builtins when PyOpenColorIO is importable.

On Linux, system Python is often missing OCIO (externally-managed env; the
pytest command does not install it). Then color/ uses white-paper reference
implementations that match the documented 18% codes. Those references match
the builtins on 18% grey to well under 0.5%; they are not a second, more
accurate IDT.

F-Log2, N-Log, C-Log2+BT.2020, C-Log3+BT.2020, D-Log, and Apple Log 2
have no full IDT Builtin — keep the papers / ACES CSC matrix.
C-Log2+Cinema Gamut / C-Log3+Cinema Gamut / Apple Log 1 / LogC3 EI800+AWG3
use Builtins when present. There is no APPLE_LOG2 Builtin.
C-Log2+BT.2020 is handwritten C-Log2 curve + BT.2020→AP0 if no Builtin.
Venice Builtins are used only when a Venice camera is detected, never as a
silent S-Log3 default.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

# Locked IDT -> OCIO BuiltinTransform style (camera log RGB -> ACES2065-1).
IDT_BUILTINS: dict[str, str] = {
    "arri_logc4_awg4": "ARRI_LOGC4_to_ACES2065-1",
    "sony_slog3_sgamut3": "SONY_SLOG3-SGAMUT3_to_ACES2065-1",
    "sony_slog3_sgamut3cine": "SONY_SLOG3-SGAMUT3.CINE_to_ACES2065-1",
    "sony_slog3_sgamut3_venice": "SONY_SLOG3-SGAMUT3-VENICE_to_ACES2065-1",
    "sony_slog3_sgamut3cine_venice": "SONY_SLOG3-SGAMUT3.CINE-VENICE_to_ACES2065-1",
    "panasonic_vlog_vgamut": "PANASONIC_VLOG-VGAMUT_to_ACES2065-1",
    "red_log3g10_rwg": "RED_LOG3G10-RWG_to_ACES2065-1",
    "canon_clog2_cgamut": "CANON_CLOG2-CGAMUT_to_ACES2065-1",
    "canon_clog3_cgamut": "CANON_CLOG3-CGAMUT_to_ACES2065-1",
    "apple_log_bt2020": "APPLE_LOG_to_ACES2065-1",
    # ACES CSC / ARRI 2017-03. EI800 + AWG3 only. Not a generic LogC3.
    "arri_logc3_ei800_awg3": "ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1",
}

# No standard Builtin (checked against BuiltinTransformRegistry).
HANDWRITTEN_IDTS = frozenset(
    {
        "fujifilm_flog2_bt2020",
        "nikon_nlog_bt2020",
        # No full IDT Builtin (handwritten C-Log2 curve + BT.2020→AP0).
        "canon_clog2_bt2020",
        # No full IDT Builtin (curve Builtin + BT.2020 matrix, or paper).
        "canon_clog3_bt2020",
        # 2017 white paper. D-Log M is unsupported.
        "dji_dlog_dgamut",
        # Same Apple Log 1 curve + Apple Wide Gamut. No APPLE_LOG2 Builtin.
        "apple_log2_awg",
    }
)

WORKING_BUILTIN_ACESCCT = "ACEScct_to_ACES2065-1"
WORKING_BUILTIN_ACESCG = "ACEScg_to_ACES2065-1"
ACES_AP0_TO_XYZ_D65 = "UTILITY - ACES-AP0_to_CIE-XYZ-D65_BFD"
ACES_AP1_TO_REC709 = "UTILITY - ACES-AP1_to_LINEAR-REC709_BFD"
CANON_CLOG2_CURVE = "CURVE - CANON_CLOG2_to_LINEAR"
CANON_CLOG2_IDT = "CANON_CLOG2-CGAMUT_to_ACES2065-1"
CANON_CLOG3_CURVE = "CURVE - CANON_CLOG3_to_LINEAR"
CANON_CLOG3_IDT = "CANON_CLOG3-CGAMUT_to_ACES2065-1"
APPLE_LOG_CURVE = "CURVE - APPLE_LOG_to_LINEAR"
APPLE_LOG_IDT = "APPLE_LOG_to_ACES2065-1"
# No APPLE_LOG2 Builtin. Apple Log 2 is the Log 1 curve + Apple Wide Gamut.
ARRI_LOGC3_EI800_IDT = "ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1"

# ACES Output Transform / BT.2100 (Rec.2100 HLG + PQ). Prefer these
# BuiltinTransform styles over any handwritten HLG/PQ curve.
# ACES 1.3 OT → CIE-XYZ-D65; DISPLAY encodes Rec.2100.
ACES_OT_HLG_1_3 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1"
)
ACES_OT_PQ_1_3 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-ST2084_1.1"
)
DISPLAY_REC2100_HLG = "DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG"
DISPLAY_REC2100_PQ = "DISPLAY - CIE-XYZ-D65_to_REC.2100-REC2020-ST2084"
# ACES 2.0 Rec.2100-named OT (OCIO 2.4+), used when the registry has them.
ACES_OT_HLG_2_0 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-HLG-1000nit_2.0"
)
ACES_OT_PQ_2_0 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-Rec.2020-ST2084-1000nit_2.0"
)
# Academy config-aces colorspace names.
CONFIG_ACES_HLG = "Output - Rec.2100-HLG - 1000 nit"
CONFIG_ACES_PQ = "Output - Rec.2100-Rec.2020-ST2084 - 1000 nit"

ODT_BUILTINS: dict[str, tuple[str, ...]] = {
    "hlg": (ACES_OT_HLG_1_3, DISPLAY_REC2100_HLG),
    "pq": (ACES_OT_PQ_1_3, DISPLAY_REC2100_PQ),
}

_OCIO = None
_OCIO_TRIED = False


def _import_ocio():
    global _OCIO, _OCIO_TRIED
    if _OCIO_TRIED:
        return _OCIO
    _OCIO_TRIED = True
    try:
        import PyOpenColorIO as ocio  # type: ignore
    except ImportError:
        try:
            import OpenColorIO as ocio  # type: ignore
        except ImportError:
            _OCIO = None
            return None
    _OCIO = ocio
    return _OCIO


def ocio_available() -> bool:
    """True when PyOpenColorIO/OpenColorIO imports and has BuiltinTransform."""
    ocio = _import_ocio()
    return ocio is not None and hasattr(ocio, "BuiltinTransform")


def builtin_style_for(idt_id: str) -> str | None:
    return IDT_BUILTINS.get(idt_id)


def list_registry() -> list[tuple[str, str]]:
    """Return (style, description) pairs from BuiltinTransformRegistry, or []."""
    ocio = _import_ocio()
    if ocio is None or not hasattr(ocio, "BuiltinTransformRegistry"):
        return []
    reg = ocio.BuiltinTransformRegistry()
    out: list[tuple[str, str]] = []
    for item in reg.getBuiltins():
        if isinstance(item, (tuple, list)) and len(item) >= 1:
            style = str(item[0])
            desc = str(item[1]) if len(item) > 1 else ""
            out.append((style, desc))
        else:
            out.append((str(item), ""))
    return out


def registry_styles() -> set[str]:
    return {style for style, _desc in list_registry()}


def apply_builtin(style: str, rgb, *, inverse: bool = False) -> np.ndarray:
    """Apply an OCIO BuiltinTransform to RGB (..., 3). Requires OCIO."""
    ocio = _import_ocio()
    if ocio is None:
        raise RuntimeError("OpenColorIO Python is not importable")
    arr = np.asarray(rgb, dtype=np.float32)
    shape = arr.shape
    flat = np.ascontiguousarray(arr.reshape(-1, 3))
    cfg = ocio.Config()
    cfg.setMajorVersion(2)
    bt = ocio.BuiltinTransform()
    bt.setStyle(style)
    if inverse:
        direction = getattr(ocio, "TRANSFORM_DIR_INVERSE", None)
        if direction is None:
            td = ocio.TransformDirection
            direction = getattr(td, "INVERSE", None) or getattr(td, "inverse", None)
        if direction is not None:
            bt.setDirection(direction)
    proc = cfg.getProcessor(bt).getDefaultCPUProcessor()
    proc.applyRGB(flat)
    return flat.reshape(shape).astype(np.float64)


def apply_builtin_idt(log_rgb, style: str) -> np.ndarray:
    """Camera log RGB (0-1, or already in the Builtin's domain) -> ACES2065-1."""
    return apply_builtin(style, log_rgb, inverse=False)


def apply_apple_log2_awg(log_rgb) -> np.ndarray:
    """Apple Log 2 + Apple Wide Gamut → ACES2065-1.

    No ``APPLE_LOG2`` Builtin. Reuse ``CURVE - APPLE_LOG_to_LINEAR`` (same
    curve as Apple Log 1) plus AWG→AP0 from ACES
    ``CSC.Apple.AppleLog2_to_ACES.ctl`` (Bradford default).
    """
    from .curves import apple_log_to_linear
    from .gamuts import camera_to_aces2065_matrix

    rgb = np.asarray(log_rgb, dtype=np.float64)
    if ocio_available() and APPLE_LOG_CURVE in registry_styles():
        lin = apply_builtin(APPLE_LOG_CURVE, rgb)
    else:
        lin = apple_log_to_linear(rgb)
    m = camera_to_aces2065_matrix("AppleWideGamut")
    return np.asarray(lin, dtype=np.float64) @ m.T


def apply_clog2_bt2020(log_rgb) -> np.ndarray:
    """C-Log2 + BT.2020 → ACES2065-1.

    No full IDT Builtin (``CANON_CLOG2-CGAMUT_to_ACES2065-1`` is Cinema Gamut
    only). Prefer ``CURVE - CANON_CLOG2_to_LINEAR`` + BT.2020→AP0 when that
    curve Builtin is in the registry; otherwise the handwritten C-Log2 curve
    and RP 177 Bradford D65→ACES matrix.
    """
    from .curves import clog2_to_linear
    from .gamuts import camera_to_aces2065_matrix

    rgb = np.asarray(log_rgb, dtype=np.float64)
    if ocio_available() and CANON_CLOG2_CURVE in registry_styles():
        lin = apply_builtin(CANON_CLOG2_CURVE, rgb)
    else:
        lin = clog2_to_linear(rgb)
    m = camera_to_aces2065_matrix("BT2020")
    return np.asarray(lin, dtype=np.float64) @ m.T


def print_registry(stream=None) -> None:
    """Print BuiltinTransformRegistry contents (or a missing-OCIO note)."""
    import sys

    out = stream or sys.stdout
    styles = list_registry()
    if not styles:
        print("OpenColorIO BuiltinTransformRegistry: none (OCIO Python not importable)", file=out)
        return
    ocio = _import_ocio()
    print(f"OpenColorIO {getattr(ocio, '__version__', '?')} BuiltinTransformRegistry ({len(styles)}):", file=out)
    for style, desc in styles:
        print(f"  {style}" + (f"  # {desc}" if desc else ""), file=out)


if __name__ == "__main__":
    print_registry()
