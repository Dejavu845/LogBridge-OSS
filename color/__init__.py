"""LogBridge color science (M1 + M2-start HDR ODT).

Internal: every IDT lands in ACES2065-1; Exposure is linear gain (stops); WB CAT is AP0 linear; ACEScct is the timeline encode.
OCIO BuiltinTransform is used when PyOpenColorIO is importable and a
Builtin exists. Otherwise white-paper reference implementations (18% codes).
config.ocio always names the Builtins so Mac OCIO uses them.

Status of every IDT: implemented (unverified) until golden grey-card samples
are measured. Do not describe cameras as "supported".
"""

from .curves import (
    IDT_NAMES,
    decode_log,
    encode_log,
    logc4_to_linear,
    linear_to_logc4,
    slog3_to_linear,
    linear_to_slog3,
    vlog_to_linear,
    linear_to_vlog,
    flog2_to_linear,
    linear_to_flog2,
    nlog_to_linear,
    linear_to_nlog,
    log3g10_to_linear,
    linear_to_log3g10,
    clog2_to_linear,
    linear_to_clog2,
    clog3_to_linear,
    linear_to_clog3,
    apple_log_to_linear,
    linear_to_apple_log,
    dlog_to_linear,
    linear_to_dlog,
    logc3_ei800_to_linear,
    linear_to_logc3_ei800,
)
from .gamuts import GAMUTS, primaries_xy, rgb_to_xyz_matrix
from .odt import (
    ACES_OT_HLG_1_3,
    ACES_OT_PQ_1_3,
    CONFIG_ACES_HLG,
    CONFIG_ACES_PQ,
    DISPLAY_REC2100_HLG,
    DISPLAY_REC2100_PQ,
    HDR_ODTS,
    ODT_CHOICES,
    ODT_DEFAULT,
    ODT_HLG,
    ODT_OFF,
    ODT_PQ,
    ODT_REC709,
    apply_hdr_odt,
    apply_odt,
    odt_descriptor,
)
from .exposure import apply_exposure, stops_to_gain
from .pipeline import apply_idt, apply_odt_rec709, apply_selected_odt, process_to_rec709
from .wb import bradford_cat_matrix, linear_rgb_to_cct_tint, white_balance_matrix
from .as_shot import AsShotWB, effective_cat_cct, pick_neutral_from_linear_rgb, read_as_shot_wb

__all__ = [
    "IDT_NAMES",
    "decode_log",
    "encode_log",
    "logc4_to_linear",
    "linear_to_logc4",
    "slog3_to_linear",
    "linear_to_slog3",
    "vlog_to_linear",
    "linear_to_vlog",
    "flog2_to_linear",
    "linear_to_flog2",
    "nlog_to_linear",
    "linear_to_nlog",
    "log3g10_to_linear",
    "linear_to_log3g10",
    "clog2_to_linear",
    "linear_to_clog2",
    "clog3_to_linear",
    "linear_to_clog3",
    "apple_log_to_linear",
    "linear_to_apple_log",
    "dlog_to_linear",
    "linear_to_dlog",
    "logc3_ei800_to_linear",
    "linear_to_logc3_ei800",
    "GAMUTS",
    "primaries_xy",
    "rgb_to_xyz_matrix",
    "apply_idt",
    "apply_odt_rec709",
    "apply_selected_odt",
    "apply_odt",
    "apply_hdr_odt",
    "odt_descriptor",
    "ODT_CHOICES",
    "ODT_DEFAULT",
    "ODT_OFF",
    "ODT_REC709",
    "ODT_HLG",
    "ODT_PQ",
    "HDR_ODTS",
    "ACES_OT_HLG_1_3",
    "ACES_OT_PQ_1_3",
    "DISPLAY_REC2100_HLG",
    "DISPLAY_REC2100_PQ",
    "CONFIG_ACES_HLG",
    "CONFIG_ACES_PQ",
    "process_to_rec709",
    "apply_exposure",
    "stops_to_gain",
    "bradford_cat_matrix",
    "white_balance_matrix",
    "linear_rgb_to_cct_tint",
    "AsShotWB",
    "read_as_shot_wb",
    "effective_cat_cct",
    "pick_neutral_from_linear_rgb",
]

__version__ = "0.1.0"
