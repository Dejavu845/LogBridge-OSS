"""Fixed pipeline: IDT → Exposure (stops) → AP0 WB → optional ODT.

ODT selector: Off (ACEScct deliverable) | Rec.709 preview | Rec.2100 HLG |
Rec.2100 PQ. Rec.709 is preview only. HLG/PQ are ACES Output Transform /
BT.2100 OCIO Builtins (no homemade curve). Implemented (unverified).

Not a node editor. The serial graph lives in ``color.graph`` and is shared
with Resolve export. WB is a toggleable node in ACES2065-1 (AP0) scene-linear.
Rec.709 is a preview-only ODT, not the standard Resolve deliverable.

Every IDT goes to ACES2065-1. Exposure is rgb * (2 ** stops) in that linear
domain (default 0 = identity; not a log-code add). WB (Bradford/CAT02) runs
in AP0 linear — never as a CAT on ACEScct-encoded values.
As-shot CCT/tint from camera-private metadata fills the WB knobs (UI only);
default CAT is identity (do not CAT as-shot 5600/6504 toward D65). Missing CCT
is identity (do not guess 5600 K). Grey-card override is a real CAT. Encode ACEScct only
for grading / preview display. Do not use DaVinci Wide Gamut Intermediate as
the internal reference.
"""

from __future__ import annotations

import numpy as np

from . import curves
from .gamuts import (
    IDT_PAIRS,
    aces_to_rec709_matrix,
    camera_to_aces2065_matrix,
    rgb_to_rgb_matrix,
)
from .ocio_builtins import (
    apply_apple_log2_awg,
    apply_builtin_idt,
    apply_clog2_bt2020,
    builtin_style_for,
    ocio_available,
)
from .odt import HDR_ODTS, ODT_OFF, ODT_REC709, apply_hdr_odt
from .rec709 import rec709_oetf
from .wb import apply_white_balance
from .working_space import (
    DEFAULT_WORKING_LINEAR,
    aces2065_to_acescct,
    acescct_decode,
)


def apply_idt(log_rgb, idt_id: str) -> np.ndarray:
    """Camera log RGB -> ACES2065-1 (AP0 scene-linear).

    Nikon N-Log IDT expects 10-bit code values (0-1023), not 0-1.
    All other IDTs expect normalized 0-1 log.

    Uses the OCIO BuiltinTransform when importable and a Builtin exists.
    Otherwise the white-paper reference (curve + RP 177 + Bradford D65->ACES).
    After IDT, a documented 18% grey is scene-linear ≈ 0.18 in ACES.
    """
    if idt_id not in IDT_PAIRS:
        raise KeyError(f"Unknown IDT {idt_id!r}")
    rgb = np.asarray(log_rgb, dtype=np.float64)
    style = builtin_style_for(idt_id)
    if style and ocio_available():
        curve, _gamut = IDT_PAIRS[idt_id]
        # Builtins expect 0-1 camera log. N-Log is not a Builtin.
        buf = rgb
        if curve == "nlog":
            buf = rgb / 1023.0
        return apply_builtin_idt(buf, style)
    # C-Log2 + BT.2020: no full IDT Builtin. Curve Builtin + BT.2020→AP0, or paper.
    if idt_id == "canon_clog2_bt2020":
        return apply_clog2_bt2020(rgb)
    # Apple Log 2: no APPLE_LOG2 Builtin. Same curve as Log 1 + Apple Wide Gamut.
    if idt_id == "apple_log2_awg":
        return apply_apple_log2_awg(rgb)
    return apply_idt_reference(rgb, idt_id)


def apply_idt_reference(log_rgb, idt_id: str) -> np.ndarray:
    """White-paper reference IDT: decode curve, then camera RGB -> ACES2065-1.

    Used when OCIO Python is missing, and always for F-Log2 / N-Log.
    Venice IDs fall back to the matching non-Venice S-Log3 pair (do not
    invent a Venice matrix).
    """
    curve, gamut = IDT_PAIRS[idt_id]
    cam = curves.decode_log(curve, np.asarray(log_rgb, dtype=np.float64))
    m = camera_to_aces2065_matrix(gamut)
    return np.asarray(cam, dtype=np.float64) @ m.T


def camera_linear_to_working(lin_rgb, idt_id: str, working: str = "AP1") -> np.ndarray:
    """Scene-linear camera RGB -> scene-linear working RGB (default ACEScg / AP1).

    Prefer ``apply_idt`` (camera log -> ACES2065-1) then AP0->AP1. This helper
    remains for callers that already hold camera-linear RGB.

    ``working="DWG"`` is an optional named export space only — not the
    internal reference.
    """
    _curve, gamut = IDT_PAIRS[idt_id]
    rgb = np.asarray(lin_rgb, dtype=np.float64)
    if working == "DWG":
        # Optional D65 named space: same-white camera RGB -> DWG, no ACES CAT.
        return rgb @ rgb_to_rgb_matrix(gamut, "DWG").T
    aces = rgb @ camera_to_aces2065_matrix(gamut).T
    if working in ("AP0", "ACES2065-1"):
        return aces
    if working in ("AP1", "ACEScg"):
        return aces @ rgb_to_rgb_matrix("AP0", "AP1").T
    if working == "ACEScct":
        return aces2065_to_acescct(aces)
    raise KeyError(f"Unsupported working space {working!r} (use AP1 / ACEScct / ACES2065-1)")


def apply_odt_rec709(working_lin, working: str = "AP1"):
    """Scene-linear working RGB -> Rec.709 encoded RGB.

    Tags conceptually as Rec.709. No tone-mapping RRT; 18% grey will encode
    near the Rec.709 OETF of 0.18 (~0.409). Implemented (unverified).
    ``working`` is ACEScg/AP1 (or AP0 / ACEScct). Bradford CAT when whites differ.
    ``working="DWG"`` is an optional named export space only.
    """
    if working in ("ACEScct",):
        working_lin = acescct_decode(np.asarray(working_lin, dtype=np.float64))
        working = "AP1"
    if working == "DWG":
        m = rgb_to_rgb_matrix("DWG", "Rec709")
        rec_lin = np.asarray(working_lin, dtype=np.float64) @ m.T
        return rec709_oetf(np.clip(rec_lin, 0.0, None))
    space = "AP0" if working in ("AP0", "ACES2065-1") else "AP1"
    m = aces_to_rec709_matrix(space)
    rgb = np.asarray(working_lin, dtype=np.float64)
    rec_lin = rgb @ m.T
    return rec709_oetf(np.clip(rec_lin, 0.0, None))


def apply_selected_odt(aces_ap0, odt: str):
    """Apply the selected ODT to ACES2065-1. Off returns the AP0 buffer."""
    if odt in (ODT_OFF, None, ""):
        return np.asarray(aces_ap0, dtype=np.float64)
    if odt == ODT_REC709:
        return apply_odt_rec709(aces_ap0, working="AP0")
    if odt in HDR_ODTS:
        return apply_hdr_odt(aces_ap0, odt)
    raise KeyError(f"Unknown ODT {odt!r}")


def process_to_rec709(
    log_rgb,
    idt_id: str,
    *,
    apply_wb: bool = False,
    cct: float | None = 6504.0,
    tint: float = 0.0,
    working: str = "AP1",
    wb_method: str = "bradford",
    exposure_stops: float = 0.0,
) -> np.ndarray:
    """Full fixed pipeline to Rec.709 encoded RGB via the serial graph."""
    from .graph import SerialGraph

    graph = SerialGraph(
        idt_id=idt_id,
        exposure_stops=exposure_stops,
        wb_enabled=apply_wb,
        wb_cct=cct,
        wb_tint=tint,
        wb_method=wb_method,
        odt_enabled=True,
    )
    return graph.apply(log_rgb)
