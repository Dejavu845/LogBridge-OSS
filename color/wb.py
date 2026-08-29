"""White balance in ACES2065-1 scene-linear (AP0): Bradford (default) or CAT02.

Absolute (grey-card): CAT(sampled white → D65).
Relative (user moved CCT/tint away from as-shot):
    CAT(user→D65)·inv(CAT(as→D65)) == CAT(user→as).
    3200 as-shot → 5600 user warms (in-camera Kelvin).
    Not CAT(as→user), not CAT(user→D65) alone.

Apply only to ACES2065-1 (AP0) scene-linear RGB — never as a CAT on
ACEScct-encoded values.

6504 K on the CIE daylight locus is D65, so the absolute CAT is ~identity.
3200 K (Planckian / tungsten) is not identity. Unmoved as-shot is identity.
"""

from __future__ import annotations

import numpy as np

from .gamuts import D65_XY, rgb_to_xyz_matrix, xy_to_xyz, xyz_to_rgb_matrix

BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ],
    dtype=np.float64,
)

CAT02 = np.array(
    [
        [0.7328, 0.4296, -0.1624],
        [-0.7036, 1.6975, 0.0061],
        [0.0030, 0.0136, 0.9834],
    ],
    dtype=np.float64,
)

D65_CCT = 6504.0


def _daylight_xy(cct: float) -> np.ndarray:
    """CIE D-series chromaticity (4000-25000 K)."""
    t = float(cct)
    if t <= 7000.0:
        xd = (
            0.244063
            + 0.09911e3 / t
            + 2.9678e6 / t**2
            - 4.6070e9 / t**3
        )
    else:
        xd = (
            0.237040
            + 0.24748e3 / t
            + 1.9018e6 / t**2
            - 2.0064e9 / t**3
        )
    yd = -3.0 * xd**2 + 2.870 * xd - 0.275
    return np.array([xd, yd], dtype=np.float64)


def _planckian_xy(cct: float) -> np.ndarray:
    """Kang 2002 approximation of the Planckian locus (xy)."""
    t = float(cct)
    inv = 1.0e3 / t
    inv2 = 1.0e6 / t**2
    inv3 = 1.0e9 / t**3
    if t < 4000.0:
        x = -0.2661239 * inv3 - 0.2343580 * inv2 + 0.8776956 * inv + 0.179910
    else:
        x = -3.0258469 * inv3 + 2.1070379 * inv2 + 0.2226347 * inv + 0.240390
    if t < 2222.0:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t < 4000.0:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return np.array([x, y], dtype=np.float64)


def cct_to_xy(cct: float, tint: float = 0.0) -> np.ndarray:
    """Illuminant xy from CCT (kelvin) and optional green-magenta tint.

    Daylight locus is used at T >= 4000 K so that 6504 K is D65.
    Planckian locus is used below 4000 K (tungsten).

    ``tint`` is a CIE 1960 uv shift along the isotherm: positive is greener
    (higher v'). Units are 1e-3 in uv (similar to a mild CC gel).
    """
    if cct >= 4000.0:
        xy = _daylight_xy(cct)
    else:
        xy = _planckian_xy(cct)
    if tint == 0.0:
        return xy
    x, y = xy
    # CIE 1960 UCS.
    denom = -2.0 * x + 12.0 * y + 3.0
    u = 4.0 * x / denom
    v = 6.0 * y / denom
    # Isotherm is perpendicular to the locus; a +tint increases v (green).
    v = v + tint * 1.0e-3
    d = 2.0 * u - 8.0 * v + 4.0
    x = 1.5 * u / d * 2.0  # inverse UCS
    # Standard inverse: x = 3u / (2u - 8v + 4), y = 2v / (2u - 8v + 4)
    x = 3.0 * u / d
    y = 2.0 * v / d
    return np.array([x, y], dtype=np.float64)


def chromatic_adaptation_matrix(
    src_xy, dst_xy=D65_XY, method: str = "bradford"
) -> np.ndarray:
    """3x3 XYZ CAT taking src white to dst white."""
    m = BRADFORD if method == "bradford" else CAT02
    src_cone = m @ xy_to_xyz(src_xy)
    dst_cone = m @ xy_to_xyz(dst_xy)
    scale = np.diag(dst_cone / src_cone)
    return np.linalg.inv(m) @ scale @ m


def bradford_cat_matrix(src_xy, dst_xy=D65_XY) -> np.ndarray:
    return chromatic_adaptation_matrix(src_xy, dst_xy, method="bradford")


def _rgb_cat(src_xy, dst_xy, rgb_space: str = "AP0", method: str = "bradford") -> np.ndarray:
    """Scene-linear RGB CAT: adapt ``src_xy`` white to ``dst_xy`` white."""
    cat = chromatic_adaptation_matrix(src_xy, dst_xy, method=method)
    to_xyz = rgb_to_xyz_matrix(rgb_space)
    to_rgb = xyz_to_rgb_matrix(rgb_space)
    return to_rgb @ cat @ to_xyz


def _rgb_cat_to_white(
    cct: float,
    tint: float = 0.0,
    rgb_space: str = "AP0",
    method: str = "bradford",
    dst_xy=D65_XY,
) -> np.ndarray:
    """Absolute scene-linear RGB CAT: adapt ``cct`` (+tint) to ``dst_xy``."""
    return _rgb_cat(cct_to_xy(cct, tint), dst_xy, rgb_space, method)


def white_balance_matrix(
    cct: float | None = None,
    tint: float = 0.0,
    rgb_space: str = "AP0",
    method: str = "bradford",
    dst_xy=D65_XY,
    src_cct: float | None = None,
    dst_cct: float | None = None,
    src_tint: float = 0.0,
) -> np.ndarray:
    """Scene-linear RGB CAT in ACES2065-1 (AP0) by default.

    Absolute (grey-card / explicit illuminant):
        ``cct`` (+tint) → ``dst_xy`` (default D65).
        ``white_balance_matrix(3200)`` is CAT(3200→D65).

    Relative (user moved CCT/tint away from as-shot):
        ``src_cct`` = as-shot, ``dst_cct`` = user (``cct`` is dst if
        ``dst_cct`` is omitted). Locked: CAT(user→D65)·inv(CAT(as→D65))
        == CAT(user→as). 3200→5600 warms. Not CAT(as→user), not CAT(user→D65) alone.

    Identity when both sides are missing, or when src equals dst.
    ``cct is None`` without src/dst is identity (pending / unmoved).
    Do not guess 5600 K. Never apply this CAT to ACEScct-encoded values.
    """
    dest = dst_cct if dst_cct is not None else cct
    if src_cct is not None and dest is not None:
        # CAT(user→D65) @ inv(CAT(as→D65)) == CAT(user→as).
        # 3200 as-shot → 5600 user warms the picture (in-camera Kelvin).
        m_user = _rgb_cat_to_white(dest, tint, rgb_space, method, dst_xy)
        m_shot = _rgb_cat_to_white(src_cct, src_tint, rgb_space, method, dst_xy)
        return m_user @ np.linalg.inv(m_shot)
    if dest is None:
        return np.eye(3, dtype=np.float64)
    return _rgb_cat_to_white(dest, tint, rgb_space, method, dst_xy)


def apply_white_balance(
    rgb,
    cct: float | None = None,
    tint: float = 0.0,
    rgb_space: str = "AP0",
    method: str = "bradford",
    src_cct: float | None = None,
    dst_cct: float | None = None,
    src_tint: float = 0.0,
) -> np.ndarray:
    """Apply CCT+tint CAT to scene-linear RGB (..., 3).

    Default domain is ACES2065-1 (AP0). Do not pass ACEScct-encoded RGB.
    Relative: pass ``src_cct`` (as-shot) and ``dst_cct`` (user).
    ``cct is None`` without src/dst is identity — do not guess 5600 K.
    """
    rgb = np.asarray(rgb, dtype=np.float64)
    m = white_balance_matrix(
        cct,
        tint,
        rgb_space=rgb_space,
        method=method,
        src_cct=src_cct,
        dst_cct=dst_cct,
        src_tint=src_tint,
    )
    return rgb @ m.T


def _xy_to_uv(x: float, y: float) -> tuple[float, float]:
    denom = -2.0 * x + 12.0 * y + 3.0
    return 4.0 * x / denom, 6.0 * y / denom


def xyz_to_xy(xyz) -> np.ndarray:
    xyz = np.asarray(xyz, dtype=np.float64)
    s = float(np.sum(xyz))
    if s <= 0.0:
        raise ValueError("XYZ sum must be positive")
    return np.array([xyz[0] / s, xyz[1] / s], dtype=np.float64)


def xy_to_cct_tint(xy) -> tuple[float, float]:
    """Invert ``cct_to_xy``: chromaticity → CCT (K) + tint (1e-3 uv).

    Searches this module's daylight/Planckian locus (not McCamy-only) so a
    grey-card sample in AP0 linear round-trips the same CAT the WB node uses.
    """
    x, y = float(xy[0]), float(xy[1])
    u, v = _xy_to_uv(x, y)

    def locus_err(cct: float) -> float:
        lx, ly = cct_to_xy(float(cct), 0.0)
        lu, lv = _xy_to_uv(float(lx), float(ly))
        return (u - lu) ** 2 + (v - lv) ** 2

    grid = np.linspace(1000.0, 20000.0, 381)
    errs = np.array([locus_err(c) for c in grid])
    i = int(np.argmin(errs))
    lo = float(grid[max(0, i - 1)])
    hi = float(grid[min(len(grid) - 1, i + 1)])
    phi = (1.0 + 5.0 ** 0.5) / 2.0
    for _ in range(48):
        a = hi - (hi - lo) / phi
        b = lo + (hi - lo) / phi
        if locus_err(a) < locus_err(b):
            hi = b
        else:
            lo = a
    cct = 0.5 * (lo + hi)
    lu, lv = _xy_to_uv(*cct_to_xy(cct, 0.0))
    tint = (v - lv) / 1.0e-3
    return float(cct), float(tint)


def linear_rgb_to_cct_tint(rgb, rgb_space: str = "AP0") -> tuple[float, float]:
    """Estimate CCT+tint from preview scene-linear RGB (default ACES2065-1 / AP0).

    Average if ``rgb`` is an image patch. Used by grey-card / pick-neutral.
    """
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.ndim == 1:
        pix = rgb[..., :3]
    else:
        pix = rgb.reshape(-1, rgb.shape[-1])[:, :3].mean(axis=0)
    if not np.all(np.isfinite(pix)) or float(np.max(pix)) <= 1e-12:
        raise ValueError("cannot estimate CCT from empty or black linear RGB")
    xyz = rgb_to_xyz_matrix(rgb_space) @ pix
    if float(np.sum(xyz)) <= 1e-12:
        raise ValueError("cannot estimate CCT from non-positive XYZ")
    return xy_to_cct_tint(xyz_to_xy(xyz))
