"""Internal working encodings: ACEScct (timeline) and ACES2065-1 (scene-linear).

Default M1 timeline / grading encoding is ACEScct (AP1 log). Scene-linear
interchange is ACES2065-1 (AP0). White balance (Bradford/CAT02) runs in
ACES2065-1 scene-linear only — never as a CAT on ACEScct-encoded values.
Encode back to ACEScct only for grading / preview display.

DaVinci Wide Gamut Intermediate is an optional named export space only.
It is not roles.scene_linear and is not the default deliverable.
"""

from __future__ import annotations

import numpy as np

DEFAULT_WORKING_LINEAR = "AP0"
DEFAULT_WORKING_LOG = "ACEScct"
SCENE_LINEAR = "ACES2065-1"

# DaVinci Intermediate (Resolve 17 Wide Gamut Intermediate white paper).
# Optional named export space — not the internal reference.
DI_A = 0.0075
DI_B = 7.0
DI_C = 0.07329248
DI_M = 10.44426855
DI_LIN_CUT = 0.00262409
DI_LOG_CUT = 0.02740668
DI_18_PERCENT = 0.336043


def davinci_intermediate_encode(lin):
    lin = np.asarray(lin, dtype=np.float64)
    log = (np.log2(lin + DI_A) + DI_B) * DI_C
    linear = lin * DI_M
    return np.where(lin > DI_LIN_CUT, log, linear)


def davinci_intermediate_decode(enc):
    enc = np.asarray(enc, dtype=np.float64)
    lin = np.power(2.0, enc / DI_C - DI_B) - DI_A
    lo = enc / DI_M
    return np.where(enc > DI_LOG_CUT, lin, lo)


# ACEScct (AP1 log). linAP1 <-> ACEScct.
_ACESCCT_LO_S = 10.5402377416545
_ACESCCT_LO_O = 0.0729055341958355
_ACESCCT_BREAK_LIN = 0.0078125
_ACESCCT_BREAK_LOG = _ACESCCT_LO_S * _ACESCCT_BREAK_LIN + _ACESCCT_LO_O  # Y_break


def acescct_encode(lin_ap1):
    lin = np.asarray(lin_ap1, dtype=np.float64)
    return np.where(
        lin <= _ACESCCT_BREAK_LIN,
        _ACESCCT_LO_S * lin + _ACESCCT_LO_O,
        (np.log2(np.maximum(lin, 1e-10)) + 9.72) / 17.52,
    )


def acescct_decode(enc):
    enc = np.asarray(enc, dtype=np.float64)
    return np.where(
        enc <= _ACESCCT_BREAK_LOG,
        (enc - _ACESCCT_LO_O) / _ACESCCT_LO_S,
        np.power(2.0, enc * 17.52 - 9.72),
    )


# 18% grey in ACEScct (AP1). (log2(0.18) + 9.72) / 17.52
ACESCCT_18_PERCENT = float(acescct_encode(0.18))


def aces2065_to_ap1(aces_ap0):
    """ACES2065-1 (AP0) -> ACEScg (AP1). Same ACES white; no CAT."""
    from .gamuts import rgb_to_rgb_matrix

    return np.asarray(aces_ap0, dtype=np.float64) @ rgb_to_rgb_matrix("AP0", "AP1").T


def ap1_to_aces2065(ap1):
    """ACEScg (AP1) -> ACES2065-1 (AP0)."""
    from .gamuts import rgb_to_rgb_matrix

    return np.asarray(ap1, dtype=np.float64) @ rgb_to_rgb_matrix("AP1", "AP0").T


def aces2065_to_acescct(aces_ap0):
    """ACES2065-1 scene-linear -> ACEScct (AP1 log)."""
    return acescct_encode(aces2065_to_ap1(aces_ap0))


def acescct_to_aces2065(enc):
    """ACEScct -> ACES2065-1 scene-linear."""
    return ap1_to_aces2065(acescct_decode(enc))


# Aliases used by graph / pipeline.
aces2065_to_acescg = aces2065_to_ap1
acescg_to_aces2065 = ap1_to_aces2065
