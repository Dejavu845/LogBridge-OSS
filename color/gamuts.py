"""RGB primaries, white points, and RGB<->XYZ matrices (SMPTE RP 177).

Internal scene-linear interchange is ACES2065-1 (AP0, ACES white ~D60).
WB (Bradford/CAT02) runs in AP0 linear. ACEScct (AP1 log) is the timeline /
grading encode only. Camera encodings use
illuminant D65; camera RGB -> AP0 uses Bradford D65->ACES CAT.

DaVinci Wide Gamut is not the internal reference. DWG primaries are not
used by the M1 pipeline.
"""

from __future__ import annotations

import numpy as np

# CIE D65 (IEC 61966-2-1 / Rec.709 / Rec.2020).
D65_XY = np.array([0.3127, 0.3290], dtype=np.float64)
# ACES white (~D60), used by AP0/AP1.
ACES_WHITE_XY = np.array([0.32168, 0.33767], dtype=np.float64)

# Camera / working primaries: (R, G, B) as xy.
PRIMARIES = {
    "AWG4": np.array(
        [[0.7347, 0.2653], [0.1424, 0.8576], [0.0991, -0.0308]], dtype=np.float64
    ),
    # ALEXA Wide Gamut 3 — ACES Lib.Arri.LogC3 / CSC.Arri.LogCv3-EI800_to_ACES.ctl
    # / OCIO ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1. EI800 pair only.
    "AWG3": np.array(
        [[0.68400, 0.31300], [0.22100, 0.84800], [0.08610, -0.10200]], dtype=np.float64
    ),
    # Sony: S-Gamut3 primaries are the same as conventional S-Gamut
    # (Technical Summary). Do not default S-Log3 to S-Gamut3.Cine.
    "SGamut3": np.array(
        [[0.730, 0.280], [0.140, 0.855], [0.100, -0.050]], dtype=np.float64
    ),
    "SGamut3Cine": np.array(
        [[0.766, 0.275], [0.225, 0.800], [0.089, -0.087]], dtype=np.float64
    ),
    "VGamut": np.array(
        [[0.730, 0.280], [0.165, 0.840], [0.100, -0.030]], dtype=np.float64
    ),
    "BT2020": np.array(
        [[0.708, 0.292], [0.170, 0.797], [0.131, 0.046]], dtype=np.float64
    ),
    "REDWideGamutRGB": np.array(
        [[0.780308, 0.304253], [0.121595, 1.493994], [0.095612, -0.084589]],
        dtype=np.float64,
    ),
    # Canon Cinema Gamut (published xy). White is D65 per the IDT pair.
    "CinemaGamut": np.array(
        [[0.74, 0.27], [0.17, 1.14], [0.08, -0.10]], dtype=np.float64
    ),
    # DJI D-Gamut (2017-10-10 white paper).
    "DGamut": np.array(
        [[0.71, 0.31], [0.21, 0.88], [0.09, -0.08]], dtype=np.float64
    ),
    # Apple Wide Gamut — ACES CSC.Apple.AppleLog2_to_ACES.ctl (not BT.2020).
    "AppleWideGamut": np.array(
        [[0.725, 0.301], [0.221, 0.814], [0.068, -0.076]], dtype=np.float64
    ),
    "Rec709": np.array(
        [[0.640, 0.330], [0.300, 0.600], [0.150, 0.060]], dtype=np.float64
    ),
    "DWG": np.array(
        [[0.8000, 0.3130], [0.1682, 0.9877], [0.0790, -0.1155]], dtype=np.float64
    ),
    "AP1": np.array(
        [[0.713, 0.293], [0.165, 0.830], [0.128, 0.044]], dtype=np.float64
    ),
    "AP0": np.array(
        [[0.7347, 0.2653], [0.0000, 1.0000], [0.0001, -0.0770]], dtype=np.float64
    ),
}

WHITE_POINTS = {
    "AWG4": D65_XY,
    "AWG3": D65_XY,
    "SGamut3": D65_XY,
    "SGamut3Cine": D65_XY,
    "VGamut": D65_XY,
    "BT2020": D65_XY,
    "REDWideGamutRGB": D65_XY,
    "CinemaGamut": D65_XY,
    "DGamut": D65_XY,
    "AppleWideGamut": D65_XY,
    "Rec709": D65_XY,
    "DWG": D65_XY,
    "AP1": ACES_WHITE_XY,
    "AP0": ACES_WHITE_XY,
}

# Locked curve+gamut pairs for M1 IDTs. Sony is two pairs, user/metadata picks.
# Canon C-Log2 and C-Log3 are each two pairs — never default either gamut.
# Venice pairs are only selected when a Venice camera is detected — never default.
IDT_PAIRS = {
    "arri_logc4_awg4": ("logc4", "AWG4"),
    "sony_slog3_sgamut3": ("slog3", "SGamut3"),
    "sony_slog3_sgamut3cine": ("slog3", "SGamut3Cine"),
    "sony_slog3_sgamut3_venice": ("slog3", "SGamut3"),
    "sony_slog3_sgamut3cine_venice": ("slog3", "SGamut3Cine"),
    "panasonic_vlog_vgamut": ("vlog", "VGamut"),
    "fujifilm_flog2_bt2020": ("flog2", "BT2020"),
    "nikon_nlog_bt2020": ("nlog", "BT2020"),
    "red_log3g10_rwg": ("log3g10", "REDWideGamutRGB"),
    "canon_clog2_cgamut": ("clog2", "CinemaGamut"),
    "canon_clog2_bt2020": ("clog2", "BT2020"),
    "canon_clog3_cgamut": ("clog3", "CinemaGamut"),
    "canon_clog3_bt2020": ("clog3", "BT2020"),
    "apple_log_bt2020": ("apple_log", "BT2020"),
    "apple_log2_awg": ("apple_log", "AppleWideGamut"),
    "dji_dlog_dgamut": ("dlog", "DGamut"),
    "arri_logc3_ei800_awg3": ("logc3_ei800", "AWG3"),
}

VENICE_IDTS = frozenset(
    {
        "sony_slog3_sgamut3_venice",
        "sony_slog3_sgamut3cine_venice",
    }
)

GAMUTS = tuple(PRIMARIES.keys())

# ARRI-published AWG4 to CIE XYZ (D65). Cross-check of RP 177 from primaries,
# not a substitute IDT matrix (IDT uses OCIO Builtin ARRI_LOGC4_to_ACES2065-1).
ARRI_AWG4_TO_XYZ = np.array(
    [
        [0.704858320407232064, 0.129760295170463003, 0.115837311473976537],
        [0.254524176404027025, 0.781477732712002049, -0.036001909116029039],
        [0.000000000000000000, 0.000000000000000000, 1.089057750759878429],
    ],
    dtype=np.float64,
)

# Panasonic-published V-Gamut to XYZ.
PANASONIC_VGAMUT_TO_XYZ = np.array(
    [
        [0.679644, 0.152211, 0.118600],
        [0.260686, 0.774894, -0.035580],
        [-0.009310, -0.004612, 1.102980],
    ],
    dtype=np.float64,
)


def xy_to_xyz(xy) -> np.ndarray:
    x, y = np.asarray(xy, dtype=np.float64)
    return np.array([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64)


def primaries_xy(name: str) -> np.ndarray:
    return PRIMARIES[name].copy()


def rgb_to_xyz_matrix(name: str) -> np.ndarray:
    """Normalized primary matrix (SMPTE RP 177) for a named RGB space."""
    P = PRIMARIES[name]
    W = WHITE_POINTS[name]
    xyz_rgb = np.column_stack([xy_to_xyz(P[0]), xy_to_xyz(P[1]), xy_to_xyz(P[2])])
    S = np.linalg.inv(xyz_rgb) @ xy_to_xyz(W)
    return xyz_rgb @ np.diag(S)


def xyz_to_rgb_matrix(name: str) -> np.ndarray:
    return np.linalg.inv(rgb_to_xyz_matrix(name))


def rgb_to_rgb_matrix(src: str, dst: str, cat: np.ndarray | None = None) -> np.ndarray:
    """Scene-linear RGB (src) -> scene-linear RGB (dst).

    Optional 3x3 ``cat`` is applied in XYZ (e.g. Bradford D65->ACES for AP0).
    Same-white conversions need no CAT.
    """
    m = rgb_to_xyz_matrix(src)
    if cat is not None:
        m = cat @ m
    return xyz_to_rgb_matrix(dst) @ m


def camera_to_aces2065_matrix(gamut: str) -> np.ndarray:
    """Scene-linear camera RGB (D65) -> ACES2065-1 (AP0).

    Bradford CAT D65 -> ACES white, then RP 177 from published primaries,
    except AWG3 which uses CAT02 (ACES ``Lib.Arri.LogC3`` /
    ``CSC.Arri.LogCv3-EI800_to_ACES.ctl`` / OCIO
    ``ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1``).
    Used only as the Linux/no-OCIO reference path. Prefer the OCIO Builtin
    when it exists; do not invent a second homemade camera matrix.
    """
    from .wb import bradford_cat_matrix, chromatic_adaptation_matrix

    if gamut == "AWG3":
        cat = chromatic_adaptation_matrix(D65_XY, ACES_WHITE_XY, method="cat02")
    else:
        cat = bradford_cat_matrix(D65_XY, ACES_WHITE_XY)
    return rgb_to_rgb_matrix(gamut, "AP0", cat=cat)


def aces_to_rec709_matrix(working: str = "AP1") -> np.ndarray:
    """Scene-linear ACES RGB (AP0 or AP1) -> scene-linear Rec.709 (D65)."""
    from .wb import bradford_cat_matrix

    cat = bradford_cat_matrix(ACES_WHITE_XY, D65_XY)
    return rgb_to_rgb_matrix(working, "Rec709", cat=cat)
