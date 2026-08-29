"""DaVinci Resolve export: serial IDT → Exposure → WB → ODT, not a prose sidecar.

Standard deliverable: ACEScct timeline or ACES2065-1 EXR / ACES workflow.
Rec.709 is preview only (optional ODT, off by default).
Rec.2100 HLG / PQ are optional ACES Output Transform / BT.2100 nodes
(unverified). No homemade HLG/PQ LUT.

  1. IDT       — camera log → ACES2065-1 → ACEScct (LUT and/or Resolve CST)
  2. Exposure  — own 1D / gain stage. ACES2065-1 linear: rgb * (2 ** stops).
                 On an ACEScct timeline: decode → gain → encode. Not a
                 log-code add. Not baked into IDT or WB when stops=0.
  3. WB        — linear AP0 Bradford/CAT02 (CCT + tint). DCTL decodes ACEScct
                 to ACES2065-1, applies the AP0 3×3, encodes ACEScct. Same 3×3
                 works on ACES2065-1 linear. Disable WB = IDT → Exposure →
                 ACEScct, no bake.
  4. ODT       — Rec.709 preview (LUT and/or Resolve CST). Off by default.

WB is never a CAT on ACEScct-encoded values and is never baked into the
IDT or ODT cubes. Exposure is never baked into IDT or WB. Status:
implemented (unverified).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .batch import BatchClip, plan_locked_batch
from .curves import decode_log, nlog_normalized_to_linear
from .gamuts import IDT_PAIRS
from .exposure import apply_exposure, stops_to_gain
from .graph import SerialGraph, graph_from_export_args, odt_node_name
from .odt import (
    CONFIG_ACES_HLG,
    CONFIG_ACES_PQ,
    HDR_ODTS,
    ODT_HLG,
    ODT_OFF,
    ODT_PQ,
    ODT_REC709,
    declared_hdr_styles,
    odt_descriptor,
)
from .pipeline import apply_idt, apply_odt_rec709, camera_linear_to_working
from .wb import white_balance_matrix, apply_white_balance
from .working_space import (
    DEFAULT_WORKING_LINEAR,
    aces2065_to_acescct,
    aces2065_to_ap1,
    acescct_decode,
    acescct_encode,
    acescct_to_aces2065,
    davinci_intermediate_decode,
    davinci_intermediate_encode,
)

# Resolve Color Space Transform labels (implemented, unverified).
RESOLVE_CST = {
    "arri_logc4_awg4": {
        "input_color_space": "ARRI Wide Gamut 4",
        "input_gamma": "ARRI LogC4",
    },
    "sony_slog3_sgamut3": {
        "input_color_space": "Sony S-Gamut3",
        "input_gamma": "Sony S-Log3",
    },
    "sony_slog3_sgamut3cine": {
        "input_color_space": "Sony S-Gamut3.Cine",
        "input_gamma": "Sony S-Log3",
    },
    "panasonic_vlog_vgamut": {
        "input_color_space": "Panasonic V-Gamut",
        "input_gamma": "Panasonic V-Log",
    },
    "fujifilm_flog2_bt2020": {
        "input_color_space": "Rec.2020",
        "input_gamma": "Fujifilm F-Log2",
    },
    "nikon_nlog_bt2020": {
        "input_color_space": "Rec.2020",
        "input_gamma": "Nikon N-Log",
    },
    "red_log3g10_rwg": {
        "input_color_space": "REDWideGamutRGB",
        "input_gamma": "RED Log3G10",
    },
    "canon_clog2_cgamut": {
        "input_color_space": "Canon Cinema Gamut",
        "input_gamma": "Canon C-Log2",
    },
    "canon_clog2_bt2020": {
        "input_color_space": "Rec.2020",
        "input_gamma": "Canon C-Log2",
    },
    "canon_clog3_cgamut": {
        "input_color_space": "Canon Cinema Gamut",
        "input_gamma": "Canon C-Log3",
    },
    "canon_clog3_bt2020": {
        "input_color_space": "Rec.2020",
        "input_gamma": "Canon C-Log3",
    },
    "apple_log_bt2020": {
        "input_color_space": "Rec.2020",
        "input_gamma": "Apple Log",
    },
    "apple_log2_awg": {
        "input_color_space": "Apple Wide Gamut",
        "input_gamma": "Apple Log",
    },
    "dji_dlog_dgamut": {
        "input_color_space": "DJI D-Gamut",
        "input_gamma": "DJI D-Log",
    },
    "arri_logc3_ei800_awg3": {
        "input_color_space": "ARRI Wide Gamut 3",
        "input_gamma": "ARRI LogC3 EI800",
    },
}

RESOLVE_OUTPUT_CS = "ACEScct"
RESOLVE_OUTPUT_GAMMA = "ACEScct"
RESOLVE_SCENE_LINEAR = "ACES2065-1"
# Rec.709 cube / XML label. DIY BT.709 OETF preview — never ACES OT.
REC709_PREVIEW_LABEL = "709 预览"
REC709_CUBE_TITLE = (
    "LogBridge 709 预览 ACEScct → Rec.709 (BT.709 OETF preview, not ACES OT)"
)
REC709_CUBE_COMMENT = (
    "# 709 预览. 预览·非成片. DIY BT.709 OETF preview. "
    "Not an ACES Output Transform / RRT."
)
# User-facing Resolve package notes. Chinese first. Copy only — no math.
RESOLVE_README_HONESTY = """## 诚实说明

- Rec.709 cube 是 **709 预览**，DIY BT.709 OETF，**不是** ACES OT / RRT，不是成片。preview only. Not an ACES Output Transform.
- 关闭白平衡时写出 identity / `enabled=false`，不烘焙 CAT。
- 主按钮时间线/EXR 是 **整段代理，不是全精度成片**（ACES2065-1 `_proxy` 序列），不是 ACEScct。
- 机内色温只填旋钮，默认 CAT 是单位阵。用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。
"""


def _cct_label(cct) -> str:
    """Export label. None = as-shot unknown (identity), not a 5600 K guess."""
    if cct is None:
        return "as-shot unknown"
    return f"{float(cct):.0f} K"


def _cct_xml_value(cct) -> str:
    if cct is None:
        return 'pending="true" source="unknown"'
    return f">{float(cct):.4f}<"



def decode_camera_log_01(log_01, idt_id: str) -> np.ndarray:
    """Decode 0-1 camera log buffers to scene-linear camera RGB.

    Nikon N-Log white-paper ``x`` is a 10-bit code (0-1023). LUT / image
    buffers are 0-1 = code/1023; expand before the curve.
    """
    curve, _gamut = IDT_PAIRS[idt_id]
    log_01 = np.asarray(log_01, dtype=np.float64)
    if curve == "nlog":
        return nlog_normalized_to_linear(log_01)
    return decode_log(curve, log_01)


def _acescct_encode_lut(lin_ap1):
    """ACEScct encode for export LUTs. Keep log2 defined for tiny/negative."""
    lin = np.asarray(lin_ap1, dtype=np.float64)
    return acescct_encode(np.maximum(lin, 1e-10))


def idt_to_acescct(log_01, idt_id: str) -> np.ndarray:
    """IDT node: camera log (0-1) → ACEScct. No WB.

    N-Log LUT domain is 0-1 = code/1023; ``apply_idt`` takes 10-bit codes.
    """
    curve, _gamut = IDT_PAIRS[idt_id]
    log = np.asarray(log_01, dtype=np.float64)
    if curve == "nlog":
        log = log * 1023.0
    aces = apply_idt(log, idt_id)
    return aces2065_to_acescct(aces)


def wb_in_aces2065(
    aces_ap0,
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    src_cct: float | None = None,
) -> np.ndarray:
    """WB on ACES2065-1 scene-linear (AP0). Linear AP0 3x3 CAT."""
    return apply_white_balance(
        np.asarray(aces_ap0, dtype=np.float64),
        cct,
        tint=tint,
        rgb_space="AP0",
        method=method,
        src_cct=src_cct,
        dst_cct=cct if src_cct is not None else None,
    )


def wb_in_acescct(
    acescct_rgb,
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    src_cct: float | None = None,
) -> np.ndarray:
    """WB node on an ACEScct timeline: decode -> AP0 CAT -> encode.

    Never applies the CAT to ACEScct-encoded values.
    """
    ap0 = acescct_to_aces2065(np.asarray(acescct_rgb, dtype=np.float64))
    ap0 = wb_in_aces2065(ap0, cct, tint=tint, method=method, src_cct=src_cct)
    return _acescct_encode_lut(aces2065_to_ap1(ap0))


def odt_from_acescct(acescct_rgb) -> np.ndarray:
    """ODT node: ACEScct → Rec.709 encoded. No WB."""
    return apply_odt_rec709(acescct_rgb, working="ACEScct")


def exposure_in_aces2065(aces_ap0, stops: float) -> np.ndarray:
    """Exposure on ACES2065-1 scene-linear: rgb * (2 ** stops)."""
    return apply_exposure(np.asarray(aces_ap0, dtype=np.float64), stops)


def exposure_in_acescct(acescct_rgb, stops: float) -> np.ndarray:
    """Exposure on an ACEScct timeline: decode → linear gain → encode.

    Not an add/subtract on ACEScct or camera-log codes.
    """
    ap0 = acescct_to_aces2065(np.asarray(acescct_rgb, dtype=np.float64))
    ap0 = apply_exposure(ap0, stops)
    return _acescct_encode_lut(aces2065_to_ap1(ap0))


# --- Optional named-space helpers (DWG Intermediate). Not the default. ---

def _di_encode_lut(lin):
    """DI encode for optional DWG export LUTs."""
    lin = np.asarray(lin, dtype=np.float64)
    return davinci_intermediate_encode(np.maximum(lin, -0.0075 + 1e-12))


def idt_to_di(log_01, idt_id: str) -> np.ndarray:
    """Optional named-space IDT: camera log → DWG Intermediate. Not default."""
    cam_lin = decode_camera_log_01(log_01, idt_id)
    work_lin = camera_linear_to_working(cam_lin, idt_id, working="DWG")
    return _di_encode_lut(work_lin)


def wb_in_di(
    di_rgb,
    cct: float,
    tint: float = 0.0,
    method: str = "bradford",
) -> np.ndarray:
    """Optional named-space WB on a DI timeline. Not the default export."""
    lin = davinci_intermediate_decode(np.asarray(di_rgb, dtype=np.float64))
    lin = apply_white_balance(lin, cct, tint=tint, rgb_space="DWG", method=method)
    return _di_encode_lut(lin)


def odt_from_di(di_rgb) -> np.ndarray:
    """Optional named-space ODT: DaVinci Intermediate → Rec.709. Not default."""
    lin = davinci_intermediate_decode(np.asarray(di_rgb, dtype=np.float64))
    return apply_odt_rec709(lin, working="DWG")


def _cube_sample_grid(size: int) -> np.ndarray:
    """Adobe/IRIDAS .cube lattice: R fastest, then G, then B. Shape (N, 3)."""
    xs = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(xs, xs, xs, indexing="ij")
    return np.stack([r, g, b], axis=-1).reshape(-1, 3)


def format_cube(title: str, rgb: np.ndarray, size: int, extra_comments: tuple[str, ...] = ()) -> str:
    lines = [
        f'TITLE "{title}"',
        "# LogBridge M1 — implemented (unverified). Not a camera-support claim.",
        *extra_comments,
        f"LUT_3D_SIZE {size}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    rgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    for row in rgb:
        lines.append(f"{row[0]:.8f} {row[1]:.8f} {row[2]:.8f}")
    return "\n".join(lines) + "\n"


def idt_cube_bytes(idt_id: str, size: int = 17) -> str:
    grid = _cube_sample_grid(size)
    out = idt_to_acescct(grid, idt_id)
    return format_cube(
        f"LogBridge IDT {idt_id} → ACEScct (no WB)", out, size
    )


def wb_cube_bytes(
    cct: float | None,
    tint: float = 0.0,
    size: int = 17,
    method: str = "bradford",
    src_cct: float | None = None,
) -> str:
    grid = _cube_sample_grid(size)
    out = wb_in_acescct(grid, cct, tint=tint, method=method, src_cct=src_cct)
    return format_cube(
        f"LogBridge WB AP0 CAT {_cct_label(cct)} tint {tint} (ACEScct decode→ACES2065-1→encode)",
        out,
        size,
    )


def odt_cube_bytes(size: int = 17) -> str:
    grid = _cube_sample_grid(size)
    out = odt_from_acescct(grid)
    return format_cube(
        REC709_CUBE_TITLE,
        out,
        size,
        extra_comments=(REC709_CUBE_COMMENT,),
    )


def format_1d_cube(title: str, rgb: np.ndarray) -> str:
    """IRIDAS 1D cube (uniform gain / ACEScct-wrapped exposure)."""
    rgb = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    lines = [
        f'TITLE "{title}"',
        "# LogBridge Exposure — ACES2065-1 linear gain rgb*(2**stops).",
        "# ACEScct wrap: decode → gain → encode. Not a log-code add.",
        "# Implemented (unverified). Own node; not baked into IDT or WB.",
        f"LUT_1D_SIZE {len(rgb)}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
    ]
    for row in rgb:
        lines.append(f"{row[0]:.8f} {row[1]:.8f} {row[2]:.8f}")
    return "\n".join(lines) + "\n"


def exposure_cube_bytes(stops: float = 0.0, size: int = 65) -> str:
    """1D LUT: ACEScct-wrapped linear exposure. Identity at 0 stops."""
    xs = np.linspace(0.0, 1.0, int(size))
    grid = np.stack([xs, xs, xs], axis=-1)
    out = exposure_in_acescct(grid, stops)
    gain = stops_to_gain(stops)
    return format_1d_cube(
        f"LogBridge Exposure {stops:+.3f} stops (gain {gain:.8f}, ACEScct wrap)",
        out,
    )


def format_exposure_dctl(stops: float = 0.0) -> str:
    gain = stops_to_gain(stops)
    return f"""// LogBridge Exposure node — ACES2065-1 linear gain.
// User-facing: stops. Internally: rgb * (2 ** stops) = rgb * {gain:.10f}f
// Timeline: ACEScct (decode → gain → encode). Tick input_aces2065 for linear EXR.
// Not a log-code add. Own node — not baked into IDT or WB when stops=0.
// Stops {stops:.6f}  gain {gain:.10f}
// Implemented (unverified). Not a camera-support claim.

DEFINE_UI_PARAMS(bypass_exposure, Bypass Exposure, DCTLUI_CHECK_BOX, 0, 0, 1)
DEFINE_UI_PARAMS(input_aces2065, Input is ACES2065-1 linear, DCTLUI_CHECK_BOX, 0, 0, 1)

__DEVICE__ float acescct_decode(float x)
{{
    const float lo_s = 10.5402377416545f;
    const float lo_o = 0.0729055341958355f;
    const float y_break = 0.1552511415525113f;
    if (x <= y_break)
        return (x - lo_o) / lo_s;
    return _exp2f(x * 17.52f - 9.72f);
}}

__DEVICE__ float acescct_encode(float lin)
{{
    const float lo_s = 10.5402377416545f;
    const float lo_o = 0.0729055341958355f;
    const float lin_break = 0.0078125f;
    if (lin <= lin_break)
        return lo_s * lin + lo_o;
    float v = lin > 1e-10f ? lin : 1e-10f;
    return (_log2f(v) + 9.72f) / 17.52f;
}}

__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B)
{{
    if (bypass_exposure)
        return make_float3(p_R, p_G, p_B);

    const float gain = {gain:.10f}f;
    float r = p_R;
    float g = p_G;
    float b = p_B;
    if (!input_aces2065)
    {{
        r = acescct_decode(p_R);
        g = acescct_decode(p_G);
        b = acescct_decode(p_B);
    }}
    r *= gain;
    g *= gain;
    b *= gain;
    if (input_aces2065)
        return make_float3(r, g, b);
    return make_float3(acescct_encode(r), acescct_encode(g), acescct_encode(b));
}}
"""


def cdl_slope_offset_power(
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    src_cct: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ASC CDL SOP for a bypassable Color Corrector.

    Slope is the Bradford RGB CAT applied to (1,1,1) so a Color Corrector
    node maps equal-energy the same way the CAT maps white. Offset 0, power 1.
    The full 3x3 CAT (off-diagonals) is the .cube / .dctl — use those as the
    WB node; the CDL is the same serial slot in CDL form so Resolve can
    bypass a native corrector.
    """
    m = white_balance_matrix(
        cct,
        tint=tint,
        rgb_space=DEFAULT_WORKING_LINEAR,
        method=method,
        src_cct=src_cct,
        dst_cct=cct if src_cct is not None else None,
    )
    slope = m @ np.array([1.0, 1.0, 1.0], dtype=np.float64)
    offset = np.zeros(3, dtype=np.float64)
    power = np.ones(3, dtype=np.float64)
    return slope, offset, power


def format_cdl(
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    ident: str = "LogBridge_WB",
    src_cct: float | None = None,
) -> str:
    slope, offset, power = cdl_slope_offset_power(cct, tint, method, src_cct=src_cct)
    def _v(a):
        return f"{a[0]:.10f} {a[1]:.10f} {a[2]:.10f}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ColorDecisionList xmlns="urn:ASC:CDL:v1.01">\n'
        "  <ColorDecision>\n"
        f'    <ColorCorrection id="{ident}">\n'
        "      <SOPNode>\n"
        f"        <Slope>{_v(slope)}</Slope>\n"
        f"        <Offset>{_v(offset)}</Offset>\n"
        f"        <Power>{_v(power)}</Power>\n"
        "      </SOPNode>\n"
        "      <SatNode>\n"
        "        <Saturation>1.0</Saturation>\n"
        "      </SatNode>\n"
        "    </ColorCorrection>\n"
        "  </ColorDecision>\n"
        "</ColorDecisionList>\n"
    )


def format_ccc(
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    ident: str = "LogBridge_WB",
    src_cct: float | None = None,
) -> str:
    slope, offset, power = cdl_slope_offset_power(cct, tint, method, src_cct=src_cct)
    def _v(a):
        return f"{a[0]:.10f} {a[1]:.10f} {a[2]:.10f}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ColorCorrectionCollection xmlns="urn:ASC:CDL:v1.01">\n'
        f'  <ColorCorrection id="{ident}">\n'
        "    <SOPNode>\n"
        f"      <Slope>{_v(slope)}</Slope>\n"
        f"      <Offset>{_v(offset)}</Offset>\n"
        f"      <Power>{_v(power)}</Power>\n"
        "    </SOPNode>\n"
        "    <SatNode>\n"
        "      <Saturation>1.0</Saturation>\n"
        "    </SatNode>\n"
        "  </ColorCorrection>\n"
        "</ColorCorrectionCollection>\n"
    )


def format_dctl(
    cct: float | None,
    tint: float = 0.0,
    method: str = "bradford",
    src_cct: float | None = None,
) -> str:
    m = white_balance_matrix(
        cct,
        tint=tint,
        rgb_space=DEFAULT_WORKING_LINEAR,
        method=method,
        src_cct=src_cct,
        dst_cct=cct if src_cct is not None else None,
    )
    els = ", ".join(f"{m[i, j]:.10f}f" for i in range(3) for j in range(3))
    return f"""// LogBridge M1 WB node — scene-linear Bradford/CAT02 in ACES2065-1 (AP0).
// Timeline: ACEScct (ACES workflow). Scene-linear interchange: ACES2065-1.
// Decode ACEScct → AP1 → AP0, apply cat_ap0, AP0 → AP1 → ACEScct.
// Tick input_aces2065 if the clip is already ACES2065-1 linear (skip ACEScct wrap).
// Bypass this DCTL in Resolve to restore IDT → Exposure → ACEScct, no bake. Rec.709 is preview only.
// CCT {_cct_label(cct)}  tint {tint}  method {method}
// Implemented (unverified). Not a camera-support claim.

DEFINE_UI_PARAMS(bypass_wb, Bypass WB, DCTLUI_CHECK_BOX, 0, 0, 1)
DEFINE_UI_PARAMS(input_aces2065, Input is ACES2065-1 linear, DCTLUI_CHECK_BOX, 0, 0, 1)

__DEVICE__ float acescct_decode(float x)
{{
    const float lo_s = 10.5402377416545f;
    const float lo_o = 0.0729055341958355f;
    const float y_break = 0.1552511415525113f;
    if (x <= y_break)
        return (x - lo_o) / lo_s;
    return _exp2f(x * 17.52f - 9.72f);
}}

__DEVICE__ float acescct_encode(float lin)
{{
    const float lo_s = 10.5402377416545f;
    const float lo_o = 0.0729055341958355f;
    const float lin_break = 0.0078125f;
    if (lin <= lin_break)
        return lo_s * lin + lo_o;
    float v = lin > 1e-10f ? lin : 1e-10f;
    return (_log2f(v) + 9.72f) / 17.52f;
}}

__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B)
{{
    if (bypass_wb)
        return make_float3(p_R, p_G, p_B);

    float r = p_R;
    float g = p_G;
    float b = p_B;
    if (!input_aces2065)
    {{
        // ACEScct → AP1 linear
        r = acescct_decode(p_R);
        g = acescct_decode(p_G);
        b = acescct_decode(p_B);
        // AP1 → ACES2065-1 (AP0)
        const float ap1_to_ap0[9] = {{
            0.6954522414f, 0.1406786965f, 0.1638690622f,
            0.0447945634f, 0.8596711185f, 0.0955343182f,
            -0.0055258826f, 0.0040252103f, 1.0015006723f
        }};
        float ar = ap1_to_ap0[0] * r + ap1_to_ap0[1] * g + ap1_to_ap0[2] * b;
        float ag = ap1_to_ap0[3] * r + ap1_to_ap0[4] * g + ap1_to_ap0[5] * b;
        float ab = ap1_to_ap0[6] * r + ap1_to_ap0[7] * g + ap1_to_ap0[8] * b;
        r = ar; g = ag; b = ab;
    }}

    const float cat_ap0[9] = {{ {els} }};
    float or_ = cat_ap0[0] * r + cat_ap0[1] * g + cat_ap0[2] * b;
    float og  = cat_ap0[3] * r + cat_ap0[4] * g + cat_ap0[5] * b;
    float ob  = cat_ap0[6] * r + cat_ap0[7] * g + cat_ap0[8] * b;

    if (input_aces2065)
        return make_float3(or_, og, ob);

    const float ap0_to_ap1[9] = {{
        1.4514393161f, -0.2365107469f, -0.2149285693f,
        -0.0765537734f, 1.1762296998f, -0.0996759264f,
        0.0083161484f, -0.0060324498f, 0.9977163014f
    }};
    float pr = ap0_to_ap1[0] * or_ + ap0_to_ap1[1] * og + ap0_to_ap1[2] * ob;
    float pg = ap0_to_ap1[3] * or_ + ap0_to_ap1[4] * og + ap0_to_ap1[5] * ob;
    float pb = ap0_to_ap1[6] * or_ + ap0_to_ap1[7] * og + ap0_to_ap1[8] * ob;
    return make_float3(acescct_encode(pr), acescct_encode(pg), acescct_encode(pb));
}}
"""


def format_dot(
    idt_ids: list[str],
    cct: float,
    tint: float,
    include_wb: bool,
    exposure_stops: float = 0.0,
    exposure_enabled: bool = True,
) -> str:
    idt_label = ", ".join(idt_ids) if idt_ids else "(per clip CST/LUT)"
    wb_style = "solid" if include_wb else "dashed"
    wb_fill = "lightgrey" if include_wb else "white"
    exp_style = "solid" if exposure_enabled else "dashed"
    exp_fill = "lightgrey" if exposure_enabled else "white"
    gain = stops_to_gain(exposure_stops)
    return f"""digraph LogBridgeResolve {{
  rankdir=LR;
  labelloc="t";
  label="LogBridge M1 Resolve graph — implemented (unverified)";
  node [shape=box, fontname="Helvetica"];

  clip [label="Clip\\ncamera log"];
  idt  [label="IDT\\n{idt_label}\\n01_IDT_<idt>.cube\\nor Resolve CST → ACEScct (ACES workflow)"];
  exp  [label="Exposure (bypassable/zeroable)\\nACES2065-1 linear gain\\n{exposure_stops:+.2f} stops  gain {gain:.4f}\\n02_Exposure.cube / .dctl", style="filled,{exp_style}", fillcolor="{exp_fill}"];
  wb   [label="WB (bypassable)\\nscene-linear Bradford/CAT02\\n{_cct_label(cct)}  tint {tint}\\n03_WB.cube / .cdl / .ccc / .dctl", style="filled,{wb_style}", fillcolor="{wb_fill}"];
  odt  [label="709 预览 (later node)\\n04_ODT_Rec709.cube\\nor CST ACEScct → Rec.709\\nBT.709 OETF, not ACES OT"];
  timeline [shape=oval, label="Timeline\\nACEScct"];

  clip -> idt -> exp -> wb -> odt;
  idt -> timeline [style=dashed, label="working space"];
}}
"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_graph_xml(
    idt_ids: list[str],
    cct: float,
    tint: float,
    include_wb: bool,
    method: str = "bradford",
    odt_enabled: bool = False,
    odt: str | None = None,
    graph: SerialGraph | None = None,
) -> str:
    if graph is None:
        graph = graph_from_export_args(
            idt_id=idt_ids[0] if idt_ids else None,
            cct=cct,
            tint=tint,
            include_wb=include_wb,
            odt_enabled=odt_enabled,
            method=method,
            odt=odt,
        )
    wb_enabled = "true" if graph.wb_enabled else "false"
    odt_on = "true" if graph.odt_enabled else "false"
    exp_on = "true" if graph.exposure_enabled else "false"
    exp_stops = graph.exposure_stops
    exp_gain = stops_to_gain(exp_stops) if graph.exposure_enabled else 1.0
    odt_mode = graph.odt
    odt_name = odt_node_name(odt_mode)
    cct = graph.wb_cct
    tint = graph.wb_tint
    method = graph.wb_method
    wb_source = getattr(graph, "wb_source", "user")
    if cct is None:
        cct_xml = '<CCT pending="true" source="unknown"/>'
        cct_for_files = None
    else:
        cct_xml = f"<CCT>{float(cct):.4f}</CCT>"
        cct_for_files = float(cct)
    idt_nodes = []
    for i, idt_id in enumerate(idt_ids):
        cst = RESOLVE_CST.get(idt_id, {})
        ics = _xml_escape(cst.get("input_color_space", idt_id))
        ig = _xml_escape(cst.get("input_gamma", idt_id))
        idt_nodes.append(
            "    "
            f'<IDT idt="{_xml_escape(idt_id)}" file="01_IDT_{idt_id}.cube" '
            f'resolveInputColorSpace="{ics}" resolveInputGamma="{ig}" '
            'resolveOutputColorSpace="ACEScct" '
            'resolveOutputGamma="ACEScct"/>'
        )
    if not idt_nodes:
        idt_nodes.append(
            '    <IDT idt="(user picker)" file="" '
            'resolveOutputColorSpace="ACEScct" '
            'resolveOutputGamma="ACEScct"/>'
        )
    idt_block = "\n".join(idt_nodes)
    if odt_mode == ODT_HLG:
        styles = declared_hdr_styles(ODT_HLG)
        odt_type = "ACES_OT"
        odt_desc = (
            "Rec.2100 HLG via ACES Output Transform / BT.2100. "
            "Implemented (unverified). Not supported. No homemade HLG curve."
        )
        style_xml = "\n".join(
            f'    <OCIOBuiltin style="{s}"/>' for s in styles
        )
        odt_payload = (
            f"{style_xml}\n"
            f'    <ConfigACES name="{CONFIG_ACES_HLG}"/>\n'
            '    <ResolveCST inputColorSpace="ACEScct" inputGamma="ACEScct" '
            'outputColorSpace="Rec.2100-HLG" outputGamma="Rec.2100 HLG"/>\n'
        )
    elif odt_mode == ODT_PQ:
        styles = declared_hdr_styles(ODT_PQ)
        odt_type = "ACES_OT"
        odt_desc = (
            "Rec.2100 PQ via ACES Output Transform / BT.2100. "
            "Implemented (unverified). Not supported. No homemade PQ curve."
        )
        style_xml = "\n".join(
            f'    <OCIOBuiltin style="{s}"/>' for s in styles
        )
        odt_payload = (
            f"{style_xml}\n"
            f'    <ConfigACES name="{CONFIG_ACES_PQ}"/>\n'
            '    <ResolveCST inputColorSpace="ACEScct" inputGamma="ACEScct" '
            'outputColorSpace="Rec.2100-PQ" outputGamma="Rec.2100 PQ"/>\n'
        )
    else:
        odt_type = "LUT_or_CST"
        odt_desc = (
            "Rec.709 预览 preview ODT only (BT.709 OETF, no RRT). "
            "Not an ACES Output Transform. 预览·非成片. "
            "Off = ACEScct deliverable (or ACES2065-1 EXR)."
        )
        odt_payload = (
            '    <File role="lut">04_ODT_Rec709.cube</File>\n'
            '    <ResolveCST inputColorSpace="ACEScct" inputGamma="ACEScct" '
            'outputColorSpace="Rec.709" outputGamma="Rec.709"/>\n'
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<LogBridgeResolveGraph version="1" status="implemented (unverified)">
  <WorkingSpace gamut="AP0" encoding="ACEScct" white="ACES" scene_linear="ACES2065-1"/>
  <Node index="1" name="IDT" type="LUT_or_CST" bypassable="false">
    <Description>Camera log to ACEScct via ACES2065-1. No white balance, no exposure. ACES workflow. Exposure is its own node (not baked into IDT).</Description>
{idt_block}
  </Node>
  <Node index="2" name="Exposure" type="Gain_1D" bypassable="true" enabled="{exp_on}" stops="{exp_stops:.6f}">
    <Description>ACES2065-1 linear gain: rgb * (2 ** stops). Not a log-code add. Own bypassable/zeroable node — not baked into IDT or WB when stops=0. On ACEScct timeline: decode → gain → encode.</Description>
    <Stops>{exp_stops:.6f}</Stops>
    <Gain>{exp_gain:.10f}</Gain>
    <File role="lut1d">02_Exposure.cube</File>
    <File role="dctl">02_Exposure.dctl</File>
  </Node>
  <Node index="3" name="WB" type="Corrector" bypassable="true" enabled="{wb_enabled}" method="{_xml_escape(method)}">
    <Description>Linear AP0 Bradford/CAT02 (CCT + tint) in ACES2065-1. Never a CAT on ACEScct-encoded values. As-shot CCT/tint fills knobs (UI only); default CAT is identity — do not treat as-shot 5600/6504 as an illuminant (double WB). CAT applies when the user moves knobs or on a grey-card override. Missing CCT/tint is pending / identity (do not guess 5600 or 6504). Bypass this node in Resolve (Color page: disable WB, or DCTL Bypass WB, or skip 03_WB.cube). Remaining graph is IDT → Exposure → ACEScct, no bake.</Description>
    {cct_xml}
    <Tint>{tint:.6f}</Tint>
    <WBSource>{_xml_escape(wb_source)}</WBSource>
    <File role="lut">03_WB.cube</File>
    <File role="cdl">03_WB.cdl</File>
    <File role="ccc">03_WB.ccc</File>
    <File role="dctl">03_WB.dctl</File>
  </Node>
  <Node index="4" name="{odt_name}" type="{odt_type}" bypassable="true" enabled="{odt_on}" odt="{odt_mode}">
    <Description>{odt_desc}</Description>
{odt_payload}  </Node>
</LogBridgeResolveGraph>
"""


def format_readme(
    idt_ids: list[str],
    cct: float,
    tint: float,
    include_wb: bool,
    exposure_stops: float = 0.0,
    exposure_enabled: bool = True,
) -> str:
    idt_list = ", ".join(idt_ids) if idt_ids else "(none — assign IDT in Resolve CST)"
    wb_state = (
        "默认开启"
        if include_wb
        else "已写出但默认旁路（identity / enabled=false，不烘焙 CAT）"
    )
    exp_state = "开启" if exposure_enabled else "旁路 / bypassed"
    gain = stops_to_gain(exposure_stops) if exposure_enabled else 1.0
    return f"""# LogBridge Resolve 导出

状态：**已实现（未验证）** / implemented (unverified)。不是相机支持声明。

{RESOLVE_README_HONESTY}
## Graph (serial nodes)

Timeline color management: **ACEScct**, ACES workflow. Scene-linear interchange: **ACES2065-1**.
Do not set DaVinci Wide Gamut Intermediate as the default deliverable.

Locked order: **IDT → Exposure → WB → ACEScct → preview ODT**. Rec.709 / HLG / PQ are preview only.

1. **IDT** — `01_IDT_<idt>.cube` or Color Space Transform
   - Input: camera log / camera gamut (`{idt_list}`)
   - Output: ACEScct (via ACES2065-1)
   - Contains **no** white balance and **no** exposure.

2. **Exposure** — own 1D / gain stage, **{exp_state}**, {exposure_stops:+.3f} stops (gain {gain:.6f})
   - `02_Exposure.cube` — 1D LUT: ACEScct decode → rgb * (2 ** stops) → encode.
   - `02_Exposure.dctl` — same gain as a DCTL (checkbox **Bypass Exposure**, or tick input_aces2065 for linear EXR).
   - User-facing unit is **stops**. Internally after IDT, in ACES2065-1 linear: `rgb * (2 ** stops)`.
   - Not a log-code add. Not baked into IDT or WB when stops=0 (zeroable identity node).

3. **WB** — own corrector, **{wb_state}**
   - `03_WB.cube` — 3D LUT of the Bradford/CAT02 3×3 in ACES2065-1 (AP0), wrapped in ACEScct so it sits on the ACEScct timeline.
   - `03_WB.dctl` — same 3×3 as a DCTL (Decode ACEScct → matrix → Encode ACEScct). Checkbox **Bypass WB** inside the DCTL, or disable the node.
   - `03_WB.cdl` / `03_WB.ccc` — ASC CDL Color Corrector for the same serial slot (slope = CAT × (1,1,1); offset 0; power 1). Prefer the cube/DCTL for the full 3×3; the CDL is the bypassable corrector form.
   - CCT {_cct_label(cct)}, tint {tint}, method Bradford (CAT02 selectable in code). As-shot fills knobs (UI only); default CAT is identity (do not CAT as-shot 5600/6504 toward D65). Missing CCT is identity (not 5600 K). Scene-linear only.

4. **ODT** — Off (ACEScct deliverable, default) | Rec.709 预览 | Rec.2100 HLG | Rec.2100 PQ
   - Rec.709: `04_ODT_Rec709.cube` or CST. **709 预览**, preview only, off by default. DIY BT.709 OETF, no RRT. Not an ACES Output Transform. 预览·非成片.
   - Rec.2100 HLG / PQ: ACES Output Transform / BT.2100 OCIO Builtin (no homemade curve). Implemented (unverified). Not a support claim.
   - Contains **no** white balance and **no** exposure. Optional later node.

## How to bypass Exposure / WB in Resolve

Color page, serial node graph:

- Apply **IDT** (node 1: LUT `01_IDT_*.cube`, or CST camera → ACEScct, ACES workflow).
- Apply **Exposure** (node 2: LUT `02_Exposure.cube` or DCTL `02_Exposure.dctl`). Zero stops or bypass = identity.
- Apply **WB** (node 3: LUT `03_WB.cube`, **or** DCTL `03_WB.dctl`, **or** import `03_WB.cdl` onto a Color Corrector).
- Apply **ODT** (node 4: LUT `04_ODT_Rec709.cube`, or CST ACEScct → Rec.709) if you need a **709 预览** viewing node (not ACES OT). 预览·非成片.

To bypass Exposure: disable node 2 (or tick DCTL **Bypass Exposure**, or leave stops at 0). To bypass WB: disable node 3 (or tick DCTL **Bypass WB**, or skip the CDL/LUT). The remaining graph is **IDT → (optional Exposure) → ACEScct → optional Rec.709 ODT**.

Do not use a single Rec.709 file as the only deliverable. Rec.709 is preview only.

## Files

| File | Role |
| --- | --- |
| `graph.xml` | Machine-readable node graph (bypassable Exposure + WB) |
| `graph.dot` | Graphviz of the same graph |
| `01_IDT_<idt>.cube` | IDT LUT (no WB, no exposure) |
| `02_Exposure.cube` | Exposure 1D LUT (ACEScct-wrapped linear gain) |
| `02_Exposure.dctl` | Exposure as DCTL (linear gain) |
| `03_WB.cube` | WB LUT (Bradford CAT, ACEScct-wrapped) |
| `03_WB.cdl` / `03_WB.ccc` | WB as ASC CDL Color Corrector |
| `03_WB.dctl` | WB as DCTL (exact 3×3) |
| `04_ODT_Rec709.cube` | 709 预览 (BT.709 OETF, not ACES OT) |
| `README_RESOLVE.md` | This file |

M1 is a serial node graph (IDT → Exposure → WB → ODT), not a general node editor. Golden grey-card samples are required before any accuracy claim. Implemented (unverified).
"""


def export_resolve_bundle(
    dest,
    *,
    idt_ids: list[str] | None = None,
    cct: float = 6504.0,
    tint: float = 0.0,
    include_wb: bool = True,
    lut_size: int = 17,
    method: str = "bradford",
    odt_enabled: bool = False,
    odt: str | None = None,
    graph: SerialGraph | None = None,
    exposure_stops: float = 0.0,
    exposure_enabled: bool = True,
) -> list[Path]:
    """Write a Resolve-importable graph (XML, DOT, CDL, DCTL, cubes, README).

    Bypass flags come from ``graph`` when given. Exposure is its own
    1D/gain node (not baked into IDT or WB when stops=0).
    Default timeline is ACEScct / ACES2065-1. Rec.709 ODT is preview, off by default.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    idt_ids = list(idt_ids or [])
    if graph is not None:
        include_wb = graph.wb_enabled
        cct = graph.wb_cct
        tint = graph.wb_tint
        method = graph.wb_method
        odt_enabled = graph.odt_enabled
        odt = graph.odt
        exposure_stops = graph.exposure_stops
        exposure_enabled = graph.exposure_enabled
        cat_cct = graph.effective_wb_cct
        cat_src = graph.effective_src_cct
    else:
        graph = graph_from_export_args(
            idt_id=idt_ids[0] if idt_ids else None,
            cct=cct,
            tint=tint,
            include_wb=include_wb,
            odt_enabled=odt_enabled,
            method=method,
            odt=odt,
            exposure_stops=exposure_stops,
            exposure_enabled=exposure_enabled,
        )
        cat_cct = graph.effective_wb_cct
        cat_src = graph.effective_src_cct
    seen: list[str] = []
    for i in idt_ids:
        if i in IDT_PAIRS and i not in seen:
            seen.append(i)
    idt_ids = seen

    written: list[Path] = []

    def _w(name: str, text: str) -> Path:
        p = dest / name
        p.write_text(text, encoding="utf-8")
        written.append(p)
        return p

    _w("README_RESOLVE.md", format_readme(
        idt_ids, cct, tint, include_wb,
        exposure_stops=exposure_stops, exposure_enabled=exposure_enabled,
    ))
    _w("graph.xml", format_graph_xml(idt_ids, cct, tint, include_wb, method, odt_enabled=odt_enabled, graph=graph))
    _w("graph.dot", format_dot(
        idt_ids, cct, tint, include_wb,
        exposure_stops=exposure_stops, exposure_enabled=exposure_enabled,
    ))
    _w("02_Exposure.cube", exposure_cube_bytes(exposure_stops if exposure_enabled else 0.0))
    _w("02_Exposure.dctl", format_exposure_dctl(exposure_stops if exposure_enabled else 0.0))
    # Knobs (cct) stay in XML/README. CAT files use effective_wb_cct
    # so as-shot-unmoved exports identity (no double WB).
    # WB off: identity CAT — do not bake the knob CCT into cube/DCTL/CDL.
    if not include_wb:
        cat_cct = None
        cat_src = None
    _w("03_WB.cdl", format_cdl(cat_cct, tint, method, src_cct=cat_src))
    _w("03_WB.ccc", format_ccc(cat_cct, tint, method, src_cct=cat_src))
    _w("03_WB.dctl", format_dctl(cat_cct, tint, method, src_cct=cat_src))
    _w("03_WB.cube", wb_cube_bytes(cat_cct, tint, size=lut_size, method=method, src_cct=cat_src))
    _w("04_ODT_Rec709.cube", odt_cube_bytes(size=lut_size))
    for idt_id in idt_ids:
        _w(f"01_IDT_{idt_id}.cube", idt_cube_bytes(idt_id, size=lut_size))
    return written


@dataclass(frozen=True)
class LockedResolveReport:
    """Session-level Resolve package: locked IDTs only. Pending stay listed."""

    written: tuple[Path, ...]
    skipped: tuple[tuple[BatchClip, str], ...]

    @property
    def written_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.written)

    @property
    def skipped_reasons(self) -> dict[str, str]:
        return {c.name: reason for c, reason in self.skipped}


def export_locked_resolve_bundle(
    dest,
    clips: Sequence[BatchClip],
    *,
    graph: SerialGraph | None = None,
    lut_size: int = 17,
    method: str = "bradford",
) -> LockedResolveReport:
    """Write one session Resolve package for locked paired-IDT clips only.

    Pending / unlocked stay listed with the existing Chinese reasons
    (先选择成对 IDT / 先选择 Log 与色域) and never produce a file.
    Same serial graph as ``export_resolve_bundle``. WB off = identity CAT.
    """
    plan = plan_locked_batch(clips)
    if not plan.locked:
        return LockedResolveReport(written=(), skipped=plan.skipped)
    idt_ids: list[str] = []
    seen: set[str] = set()
    for clip in plan.locked:
        if clip.idt and clip.idt not in seen:
            seen.add(clip.idt)
            idt_ids.append(clip.idt)
    written = export_resolve_bundle(
        dest,
        idt_ids=idt_ids,
        graph=graph,
        lut_size=lut_size,
        method=method,
    )
    return LockedResolveReport(written=tuple(written), skipped=plan.skipped)
