"""Manufacturer log curve encode/decode (reference implementations).

When OpenColorIO Python is importable, IDTs with a BuiltinTransform
(LogC4, S-Log3, V-Log, Log3G10, Venice) call that Builtin to ACES2065-1.
These functions stay as the Linux/no-OCIO reference and as the 18% grey
unit-test source. They match the Builtins on documented 18% codes to well
under 0.5%. Do not replace them with invented “more accurate” constants.

F-Log2 and N-Log have no standard Builtin — these papers are the IDT.

Inputs are normalized 0-1 except Nikon N-Log, whose white-paper ``x`` is a
10-bit code value in 0-1023. Do not divide N-Log by 1023 before the curve.

References (public white papers):
- ARRI LogC4 Specification (2025-01-23)
- Sony Technical Summary S-Gamut3.Cine/S-Log3 and S-Gamut3/S-Log3
- Panasonic VARICAM V-Log/V-Gamut (2014-11-28)
- Fujifilm F-Log2 Data Sheet Ver.1.0 / GFX ETERNA white paper
- Nikon N-Log Specification Document 1.0.0 (2018-09-01)
- RED OPS White Paper on REDWideGamutRGB and Log3G10 (915-0187 Rev-C)
- Canon Log Gamma Curves white paper (revised C-Log2 / C-Log3) / ACES CTL
- Apple Log Profile White Paper (September 2023) — Log 1 curve (Log 2 reuses this)
- ACES ``Lib.Arri.LogC3`` / ``CSC.Arri.LogCv3-EI800_to_ACES.ctl`` (EI800 only)
- ACES ``CSC.Apple.AppleLog2_to_ACES.ctl`` (same Apple Log curve + Apple Wide Gamut)
- DJI White Paper on D-Log and D-Gamut (2017-10-10)
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# ARRI LogC4 (EI-independent). Spec 2025-01-23 CTL reference.
# ---------------------------------------------------------------------------
_LOGC4_A = (2.0**18 - 16.0) / 117.45
_LOGC4_B = (1023.0 - 95.0) / 1023.0
_LOGC4_C = 95.0 / 1023.0
# Inverse slope at threshold t, and relative-scene-linear threshold.
# Linear extension for negative LogC4 (post-production may introduce them).
_LOGC4_S = (7.0 * np.log(2.0) * (2.0 ** (7.0 - 14.0 * _LOGC4_C / _LOGC4_B))) / (
    _LOGC4_A * _LOGC4_B
)
_LOGC4_T = (2.0 ** (14.0 * (-_LOGC4_C / _LOGC4_B) + 6.0) - 64.0) / _LOGC4_A

# 18% grey from ARRI conversion table (normalized LogC4).
LOGC4_18_PERCENT = 0.2784


def logc4_to_linear(x):
    """Decode ARRI LogC4 (normalized 0-1, negatives allowed) to scene linear."""
    x = np.asarray(x, dtype=np.float64)
    p = 14.0 * (x - _LOGC4_C) / _LOGC4_B + 6.0
    lin_pos = (np.power(2.0, p) - 64.0) / _LOGC4_A
    lin_neg = x * _LOGC4_S + _LOGC4_T
    return np.where(x >= 0.0, lin_pos, lin_neg)


def linear_to_logc4(lin):
    """Encode relative scene linear to ARRI LogC4."""
    lin = np.asarray(lin, dtype=np.float64)
    log_pos = (np.log2(_LOGC4_A * lin + 64.0) - 6.0) / 14.0 * _LOGC4_B + _LOGC4_C
    log_neg = (lin - _LOGC4_T) / _LOGC4_S
    return np.where(lin >= _LOGC4_T, log_pos, log_neg)


# ---------------------------------------------------------------------------
# Sony S-Log3 (normalized 0-1, 10-bit equivalent). Reflection encoding.
# ---------------------------------------------------------------------------
_SLOG3_CUT = 171.2102946929 / 1023.0
_SLOG3_A = 0.01125000
SLOG3_18_PERCENT = 420.0 / 1023.0  # documented 10-bit 18% grey
SLOG3_0_PERCENT = 95.0 / 1023.0
SLOG3_90_PERCENT = 598.0 / 1023.0  # 10-bit 598 for 90% reflectance


def slog3_to_linear(x):
    """Decode Sony S-Log3 (normalized 0-1) to scene-linear reflectance."""
    x = np.asarray(x, dtype=np.float64)
    cv = x * 1023.0
    lin_hi = (10.0 ** ((cv - 420.0) / 261.5)) * (0.18 + 0.01) - 0.01
    lin_lo = (cv - 95.0) * _SLOG3_A / (171.2102946929 - 95.0)
    return np.where(x >= _SLOG3_CUT, lin_hi, lin_lo)


def linear_to_slog3(lin):
    """Encode scene-linear reflectance to Sony S-Log3 (normalized 0-1)."""
    lin = np.asarray(lin, dtype=np.float64)
    log_hi = (420.0 + np.log10((lin + 0.01) / (0.18 + 0.01)) * 261.5) / 1023.0
    log_lo = (lin * (171.2102946929 - 95.0) / _SLOG3_A + 95.0) / 1023.0
    return np.where(lin >= _SLOG3_A, log_hi, log_lo)


# ---------------------------------------------------------------------------
# Panasonic V-Log (normalized 0-1).
# ---------------------------------------------------------------------------
_VLOG_CUT1 = 0.01
_VLOG_CUT2 = 0.181
_VLOG_B = 0.00873
_VLOG_C = 0.241514
_VLOG_D = 0.598206
VLOG_18_PERCENT = 433.0 / 1023.0  # white paper 10-bit 18% grey
VLOG_0_PERCENT = 128.0 / 1023.0
VLOG_90_PERCENT = 602.0 / 1023.0


def vlog_to_linear(x):
    """Decode Panasonic V-Log (normalized 0-1) to scene-linear reflectance."""
    x = np.asarray(x, dtype=np.float64)
    lin_hi = np.power(10.0, (x - _VLOG_D) / _VLOG_C) - _VLOG_B
    lin_lo = (x - 0.125) / 5.6
    return np.where(x >= _VLOG_CUT2, lin_hi, lin_lo)


def linear_to_vlog(lin):
    """Encode scene-linear reflectance to Panasonic V-Log."""
    lin = np.asarray(lin, dtype=np.float64)
    log_hi = _VLOG_C * np.log10(lin + _VLOG_B) + _VLOG_D
    log_lo = 5.6 * lin + 0.125
    return np.where(lin >= _VLOG_CUT1, log_hi, log_lo)


# ---------------------------------------------------------------------------
# Fujifilm F-Log2 (normalized 0-1). a=5.555556 (NOT F-Log's 0.555556).
# ---------------------------------------------------------------------------
_FLOG2_A = 5.555556
_FLOG2_B = 0.064829
_FLOG2_C = 0.245281
_FLOG2_D = 0.384316
_FLOG2_E = 8.799461
_FLOG2_F = 0.092864
_FLOG2_CUT1 = 0.000889
_FLOG2_CUT2 = 0.100686685370811
FLOG2_18_PERCENT = 400.0 / 1023.0  # white paper 10-bit 18% grey
FLOG2_0_PERCENT = 95.0 / 1023.0


def flog2_to_linear(x):
    """Decode Fujifilm F-Log2 (normalized 0-1) to scene-linear reflectance."""
    x = np.asarray(x, dtype=np.float64)
    lin_hi = np.power(10.0, (x - _FLOG2_D) / _FLOG2_C) / _FLOG2_A - _FLOG2_B / _FLOG2_A
    lin_lo = (x - _FLOG2_F) / _FLOG2_E
    return np.where(x >= _FLOG2_CUT2, lin_hi, lin_lo)


def linear_to_flog2(lin):
    """Encode scene-linear reflectance to Fujifilm F-Log2."""
    lin = np.asarray(lin, dtype=np.float64)
    log_hi = _FLOG2_C * np.log10(_FLOG2_A * lin + _FLOG2_B) + _FLOG2_D
    log_lo = _FLOG2_E * lin + _FLOG2_F
    return np.where(lin >= _FLOG2_CUT1, log_hi, log_lo)


# ---------------------------------------------------------------------------
# Nikon N-Log. White-paper x is a 10-bit code value 0-1023, NOT 0-1.
# Inverse uses natural log (pairs with exp in the decode).
# ---------------------------------------------------------------------------
NLOG_18_PERCENT_10BIT = 650.0 * (0.18 + 0.0075) ** (1.0 / 3.0)  # ~372
NLOG_CUT_X = 452.0
NLOG_CUT_Y = 0.328


def nlog_to_linear(x):
    """Decode Nikon N-Log 10-bit code value (0-1023) to reflectance.

    ``x`` is the 10-bit code, not a 0-1 normalized value. Dividing by 1023
    before this function is incorrect per the Nikon N-Log Specification.
    """
    x = np.asarray(x, dtype=np.float64)
    lin_lo = (x / 650.0) ** 3.0 - 0.0075
    lin_hi = np.exp((x - 619.0) / 150.0)
    return np.where(x < NLOG_CUT_X, lin_lo, lin_hi)


def linear_to_nlog(lin):
    """Encode reflectance to Nikon N-Log 10-bit code value (0-1023)."""
    lin = np.asarray(lin, dtype=np.float64)
    # Spec: log is natural log because decode uses exp.
    # np.where evaluates both branches; keep the log argument positive.
    cv_lo = 650.0 * np.power(np.maximum(lin + 0.0075, 0.0), 1.0 / 3.0)
    cv_hi = 150.0 * np.log(np.maximum(lin, 1e-30)) + 619.0
    return np.where(lin < NLOG_CUT_Y, cv_lo, cv_hi)


def nlog_normalized_to_linear(x01):
    """Convenience: decode N-Log stored as 0-1 (code/1023) by expanding to 10-bit.

    OCIO image buffers are 0-1; this wrapper multiplies by 1023 then calls
    :func:`nlog_to_linear`. The curve itself still sees 10-bit codes.
    """
    x01 = np.asarray(x01, dtype=np.float64)
    return nlog_to_linear(x01 * 1023.0)


def linear_to_nlog_normalized(lin):
    """Encode reflectance to N-Log stored as 0-1 (code/1023)."""
    return linear_to_nlog(lin) / 1023.0


# ---------------------------------------------------------------------------
# RED Log3G10 (normalized 0-1). 18% grey maps to 1/3.
# ---------------------------------------------------------------------------
_L3G10_A = 0.224282
_L3G10_B = 155.975327
_L3G10_C = 0.01
_L3G10_G = 15.1927
LOG3G10_18_PERCENT = 1.0 / 3.0
LOG3G10_ZERO = 0.091551  # white-paper mapping of linear 0
LOG3G10_MAX_LIN = 0.18 * (2.0**10)  # 184.32, encodes to 1.0


def log3g10_to_linear(x):
    """Decode RED Log3G10 (normalized, 0 is the break) to scene linear."""
    x = np.asarray(x, dtype=np.float64)
    lin_pos = (np.power(10.0, x / _L3G10_A) - 1.0) / _L3G10_B - _L3G10_C
    lin_neg = x / _L3G10_G - _L3G10_C
    return np.where(x >= 0.0, lin_pos, lin_neg)


def linear_to_log3g10(lin):
    """Encode scene linear to RED Log3G10.

    Matches the white-paper C: offset by c, then linear slope if the offset
    signal is negative, else a*log10(x*b+1).
    """
    lin = np.asarray(lin, dtype=np.float64)
    x = lin + _L3G10_C
    log_neg = x * _L3G10_G
    log_pos = _L3G10_A * np.log10(x * _L3G10_B + 1.0)
    return np.where(x < 0.0, log_neg, log_pos)


# ---------------------------------------------------------------------------
# Canon C-Log2 (normalized 0-1). Official ACES CTL / Canon v1.2.
# Negative toe is the ACES CTL inverse — NOT an invented mirrored toe.
# Prefer OCIO CURVE - CANON_CLOG2_to_LINEAR / CANON_CLOG2-CGAMUT_to_ACES2065-1.
# ---------------------------------------------------------------------------
_CLOG2_CUT = 0.092864125
_CLOG2_C1 = 0.24136077
_CLOG2_C2 = 87.099375
CLOG2_18_PERCENT = 0.39825469203794917  # encode(0.18) reflection


def clog2_to_linear(x):
    """Decode Canon C-Log2 (normalized 0-1) to scene-linear reflectance.

    Positive: ``0.9*(10**((in-0.092864125)/0.24136077)-1)/87.099375``.
    Negative: ACES CTL / Canon v1.2 inverse (same constants, sign-flipped
    log). Do not replace this with an invented mirrored toe.
    """
    x = np.asarray(x, dtype=np.float64)
    lin_pos = 0.9 * (np.power(10.0, (x - _CLOG2_CUT) / _CLOG2_C1) - 1.0) / _CLOG2_C2
    # ACES CTL: -(10**((cut-in)/c1)-1)/c2 * 0.9
    lin_neg = -0.9 * (np.power(10.0, (_CLOG2_CUT - x) / _CLOG2_C1) - 1.0) / _CLOG2_C2
    return np.where(x >= _CLOG2_CUT, lin_pos, lin_neg)


def linear_to_clog2(lin):
    """Encode scene-linear reflectance to Canon C-Log2 (ACES CTL inverse)."""
    lin = np.asarray(lin, dtype=np.float64)
    ire = lin / 0.9
    log_pos = _CLOG2_C1 * np.log10(1.0 + _CLOG2_C2 * ire) + _CLOG2_CUT
    # np.where evaluates both; keep the log argument positive.
    log_neg = -_CLOG2_C1 * np.log10(np.maximum(1.0 - _CLOG2_C2 * ire, 1e-30)) + _CLOG2_CUT
    return np.where(lin >= 0.0, log_pos, log_neg)


# ---------------------------------------------------------------------------
# Canon C-Log3 (normalized 0-1). Three segments. ACES / Canon v1.2.
# Prefer OCIO CURVE - CANON_CLOG3_to_LINEAR / CANON_CLOG3-CGAMUT_to_ACES2065-1.
# ---------------------------------------------------------------------------
_CLOG3_CUT_LO = 0.097465473
_CLOG3_CUT_HI = 0.15277891
_CLOG3_A = 0.36726845
_CLOG3_B = 14.98325
_CLOG3_NEG_OFF = 0.12783901
_CLOG3_LIN_SLOPE = 1.9754798
_CLOG3_LIN_OFF = 0.12512219
_CLOG3_POS_OFF = 0.12240537
CLOG3_18_PERCENT = 0.3433893703739356  # encode(0.18) reflection


def clog3_to_linear(x):
    """Decode Canon C-Log3 (normalized 0-1) to scene-linear reflectance.

    ``<0.097465473`` negative log, ``0.097465473–0.15277891`` linear,
    ``>`` positive log. Coeffs 0.36726845 / 14.98325 (ACES / Canon v1.2).
    Output is reflectance (×0.9 on the IRE result).
    """
    x = np.asarray(x, dtype=np.float64)
    ire_neg = -(np.power(10.0, (_CLOG3_NEG_OFF - x) / _CLOG3_A) - 1.0) / _CLOG3_B
    ire_mid = (x - _CLOG3_LIN_OFF) / _CLOG3_LIN_SLOPE
    ire_pos = (np.power(10.0, (x - _CLOG3_POS_OFF) / _CLOG3_A) - 1.0) / _CLOG3_B
    ire = np.where(x < _CLOG3_CUT_LO, ire_neg, np.where(x <= _CLOG3_CUT_HI, ire_mid, ire_pos))
    return ire * 0.9


def linear_to_clog3(lin):
    """Encode scene-linear reflectance to Canon C-Log3 (ACES / Canon v1.2)."""
    lin = np.asarray(lin, dtype=np.float64)
    ire = lin / 0.9
    log_neg = -_CLOG3_A * np.log10(np.maximum(-ire * _CLOG3_B + 1.0, 1e-30)) + _CLOG3_NEG_OFF
    log_mid = _CLOG3_LIN_SLOPE * ire + _CLOG3_LIN_OFF
    log_pos = _CLOG3_A * np.log10(ire * _CLOG3_B + 1.0) + _CLOG3_POS_OFF
    # Segment joins in IRE (not reflectance): decode cuts at 0.097465473 / 0.15277891.
    ire_lo = (_CLOG3_CUT_LO - _CLOG3_LIN_OFF) / _CLOG3_LIN_SLOPE
    ire_hi = (_CLOG3_CUT_HI - _CLOG3_LIN_OFF) / _CLOG3_LIN_SLOPE
    return np.where(ire < ire_lo, log_neg, np.where(ire <= ire_hi, log_mid, log_pos))


# ---------------------------------------------------------------------------
# ARRI LogC3 EI800 only. ACES Lib.Arri.LogC3 / CSC.Arri.LogCv3-EI800_to_ACES.ctl
# OCIO Builtin: ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1 (ACES CSC / ARRI 2017-03).
# Not a generic LogC3. EI>1600 has no closed-form inverse (Hermite). Do not add.
# 18% grey encodes to 0.391.
# ---------------------------------------------------------------------------
_LOGC3_NOMINAL_EI = 400.0
_LOGC3_EI800 = 800.0
_LOGC3_BLACK = 16.0 / 4095.0
_LOGC3_MID_GRAY = 0.01
_LOGC3_ENC_GAIN = 500.0 / 1023.0 * 0.525
_LOGC3_ENC_OFFSET = 400.0 / 1023.0
_LOGC3_CUT = 1.0 / 9.0
_LOGC3_SLOPE = 1.0 / (_LOGC3_CUT * np.log(10.0))
_LOGC3_OFFSET = np.log10(_LOGC3_CUT) - _LOGC3_SLOPE * _LOGC3_CUT


def _logc3_ei800_params():
    """ACES Lib.Arri.LogC3 constants at EI=800 only (xm < 1, no Hermite)."""
    gain = _LOGC3_EI800 / _LOGC3_NOMINAL_EI
    gray = _LOGC3_MID_GRAY / gain
    enc_gain = (np.log2(gain) * (0.89 - 1.0) / 3.0 + 1.0) * _LOGC3_ENC_GAIN
    enc_offset = _LOGC3_ENC_OFFSET
    nz = 0.0
    for _ in range(3):
        nz = ((95.0 / 1023.0 - enc_offset) / enc_gain - _LOGC3_OFFSET) / _LOGC3_SLOPE
        enc_offset = _LOGC3_ENC_OFFSET - np.log10(1.0 + nz) * enc_gain
    return enc_gain, enc_offset, nz, gray


_LOGC3_EI800_ENC_GAIN, _LOGC3_EI800_ENC_OFFSET, _LOGC3_EI800_NZ, _LOGC3_EI800_GRAY = (
    _logc3_ei800_params()
)
# Documented lock: 18% grey encodes to 0.391 (ACES EI800).
LOGC3_EI800_18_PERCENT = 0.391


def logc3_ei800_to_linear(x):
    """Decode ARRI LogC3 EI800 (normalized 0-1) to relative scene exposure.

    ACES ``normalizedLogC3ToRelativeExposure(t, 800)``. EI800 only.
    """
    x = np.asarray(x, dtype=np.float64)
    out = (x - _LOGC3_EI800_ENC_OFFSET) / _LOGC3_EI800_ENC_GAIN
    ns_lin = (out - _LOGC3_OFFSET) / _LOGC3_SLOPE
    ns = np.where(ns_lin > _LOGC3_CUT, np.power(10.0, out), ns_lin)
    ns = (ns - _LOGC3_EI800_NZ) * _LOGC3_EI800_GRAY + _LOGC3_BLACK
    return (ns - _LOGC3_BLACK) * (
        0.18 / (_LOGC3_MID_GRAY * _LOGC3_NOMINAL_EI / _LOGC3_EI800)
    )


def linear_to_logc3_ei800(lin):
    """Encode relative scene exposure to ARRI LogC3 EI800 (ACES, EI<1600)."""
    lin = np.asarray(lin, dtype=np.float64)
    ns = lin * (_LOGC3_MID_GRAY * _LOGC3_NOMINAL_EI / _LOGC3_EI800) / 0.18 + _LOGC3_BLACK
    ns = (ns - _LOGC3_BLACK) / _LOGC3_EI800_GRAY + _LOGC3_EI800_NZ
    log_hi = np.log10(np.maximum(ns, 1e-30))
    log_lo = _LOGC3_SLOPE * ns + _LOGC3_OFFSET
    out = np.where(ns > _LOGC3_CUT, log_hi, log_lo)
    return out * _LOGC3_EI800_ENC_GAIN + _LOGC3_EI800_ENC_OFFSET


# ---------------------------------------------------------------------------
# Apple Log (Log 1 curve). Apple Log Profile White Paper, Sept 2023.
# Apple Log 1 + BT.2020. Apple Log 2 reuses this curve + Apple Wide Gamut
# (ACES CSC.Apple.AppleLog2_to_ACES.ctl). No APPLE_LOG2 Builtin.
# Prefer OCIO APPLE_LOG_to_ACES2065-1 / CURVE - APPLE_LOG_to_LINEAR.
# ---------------------------------------------------------------------------
_APPLE_R0 = -0.05641088
_APPLE_RT = 0.01
_APPLE_C = 47.28711236
_APPLE_BETA = 0.00964052
_APPLE_GAMMA = 0.08550479
_APPLE_DELTA = 0.69336945
_APPLE_PT = _APPLE_C * (_APPLE_RT - _APPLE_R0) ** 2
APPLE_LOG_18_PERCENT = 0.4882724585268676  # encode(0.18)


def apple_log_to_linear(p):
    """Decode Apple Log 1 (normalized 0-1) to scene-linear reflectance."""
    p = np.asarray(p, dtype=np.float64)
    lin_hi = np.power(2.0, (p - _APPLE_DELTA) / _APPLE_GAMMA) - _APPLE_BETA
    lin_mid = np.sqrt(np.maximum(p / _APPLE_C, 0.0)) + _APPLE_R0
    return np.where(p >= _APPLE_PT, lin_hi, np.where(p >= 0.0, lin_mid, _APPLE_R0))


def linear_to_apple_log(lin):
    """Encode scene-linear reflectance to Apple Log 1."""
    lin = np.asarray(lin, dtype=np.float64)
    log_hi = _APPLE_GAMMA * np.log2(np.maximum(lin + _APPLE_BETA, 1e-30)) + _APPLE_DELTA
    log_mid = _APPLE_C * (lin - _APPLE_R0) ** 2
    return np.where(lin >= _APPLE_RT, log_hi, np.where(lin >= _APPLE_R0, log_mid, 0.0))


# ---------------------------------------------------------------------------
# DJI D-Log (normalized 0-1). 2017-10-10 white paper. D-Log M unsupported.
# No standard OCIO Builtin.
# ---------------------------------------------------------------------------
_DLOG_CUT_LOG = 0.14
_DLOG_CUT_LIN = 0.0078
DLOG_18_PERCENT = 0.3987645561893306  # encode(0.18)


def dlog_to_linear(x):
    """Decode DJI D-Log (2017 white paper) to scene-linear."""
    x = np.asarray(x, dtype=np.float64)
    lin_hi = (np.power(10.0, 3.89616 * x - 2.27752) - 0.0108) / 0.9892
    lin_lo = (x - 0.0929) / 6.025
    return np.where(x > _DLOG_CUT_LOG, lin_hi, lin_lo)


def linear_to_dlog(lin):
    """Encode scene-linear to DJI D-Log (2017 white paper)."""
    lin = np.asarray(lin, dtype=np.float64)
    log_hi = np.log10(lin * 0.9892 + 0.0108) * 0.256663 + 0.584555
    log_lo = 6.025 * lin + 0.0929
    return np.where(lin > _DLOG_CUT_LIN, log_hi, log_lo)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
# Curve names used by locked clip pairs. Sony has one curve, two gamuts.
CURVE_LOGC4 = "logc4"
CURVE_SLOG3 = "slog3"
CURVE_VLOG = "vlog"
CURVE_FLOG2 = "flog2"
CURVE_NLOG = "nlog"
CURVE_LOG3G10 = "log3g10"

CURVE_CLOG2 = "clog2"
CURVE_CLOG3 = "clog3"
CURVE_APPLE_LOG = "apple_log"
CURVE_DLOG = "dlog"
CURVE_LOGC3_EI800 = "logc3_ei800"

IDT_NAMES = (
    "ARRI LogC4 / AWG4",
    "ARRI LogC3 EI800 / AWG3",
    "Sony S-Log3 / S-Gamut3",
    "Sony S-Log3 / S-Gamut3.Cine",
    "Panasonic V-Log / V-Gamut",
    "Fujifilm F-Log2 / BT.2020",
    "Nikon N-Log / BT.2020",
    "RED Log3G10 / REDWideGamutRGB",
    "Sony S-Log3 / S-Gamut3 (Venice)",
    "Sony S-Log3 / S-Gamut3.Cine (Venice)",
    "Canon C-Log2 / Cinema Gamut",
    "Canon C-Log2 / BT.2020",
    "Canon C-Log3 / Cinema Gamut",
    "Canon C-Log3 / BT.2020",
    "Apple Log / BT.2020",
    "Apple Log 2 / Apple Wide Gamut",
    "DJI D-Log / D-Gamut",
)

_DECODE = {
    CURVE_LOGC4: logc4_to_linear,
    CURVE_SLOG3: slog3_to_linear,
    CURVE_VLOG: vlog_to_linear,
    CURVE_FLOG2: flog2_to_linear,
    CURVE_NLOG: nlog_to_linear,
    CURVE_LOG3G10: log3g10_to_linear,
    CURVE_CLOG2: clog2_to_linear,
    CURVE_CLOG3: clog3_to_linear,
    CURVE_APPLE_LOG: apple_log_to_linear,
    CURVE_DLOG: dlog_to_linear,
    CURVE_LOGC3_EI800: logc3_ei800_to_linear,
}

_ENCODE = {
    CURVE_LOGC4: linear_to_logc4,
    CURVE_SLOG3: linear_to_slog3,
    CURVE_VLOG: linear_to_vlog,
    CURVE_FLOG2: linear_to_flog2,
    CURVE_NLOG: linear_to_nlog,
    CURVE_LOG3G10: linear_to_log3g10,
    CURVE_CLOG2: linear_to_clog2,
    CURVE_CLOG3: linear_to_clog3,
    CURVE_APPLE_LOG: linear_to_apple_log,
    CURVE_DLOG: linear_to_dlog,
    CURVE_LOGC3_EI800: linear_to_logc3_ei800,
}


def decode_log(curve: str, x):
    """Decode a named camera log curve to scene linear."""
    try:
        fn = _DECODE[curve]
    except KeyError as exc:
        raise KeyError(f"Unknown curve {curve!r}") from exc
    return fn(x)


def encode_log(curve: str, lin):
    """Encode scene linear to a named camera log curve."""
    try:
        fn = _ENCODE[curve]
    except KeyError as exc:
        raise KeyError(f"Unknown curve {curve!r}") from exc
    return fn(lin)
