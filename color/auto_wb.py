"""Automatic white-balance *estimate* (not calibration).

After IDT, estimate a residual cast in linear ACEScg with Shades-of-Gray
(p=6). Correction, if the user confirms, is an absolute AP0 CAT — the
same class as a grey-card, not relative to as-shot.

Engineering locks (not a white paper):
  * Drop Y < 0.02 and any channel > 8.
  * Residual angle vs ACEScg (1,1,1) < 2° → treat as 0 (empty).
  * 3×3 tiles, max inter-tile angle > 5° → mixed light (empty).
  * Valid pixels < 15% → empty.
  * Never guess 5600 / 6504. Never read Rec.709 pixels.
  * Label: 白平衡（估计）. Confirm writes CAT; low confidence stays empty.
  * Grey-card overrides the estimate. As-shot default stays identity.

Implemented (unverified). Not 精准. Not 一键校准.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .as_shot import WB_SOURCE_ESTIMATE, AsShotWB
from .gamuts import rgb_to_xyz_matrix
from .wb import linear_rgb_to_cct_tint
from .working_space import aces2065_to_ap1, ap1_to_aces2065

SOG_P = 6.0
Y_MIN = 0.02
CHAN_MAX = 8.0
MIN_VALID_FRAC = 0.15
RESIDUAL_ZERO_DEG = 2.0
MIXED_MAX_DEG = 5.0

AUTO_WB_LABEL = "白平衡（估计）"
EMPTY_NOTE = (
    "白平衡（估计） empty — low confidence or no residual. "
    "Do not guess 5600 or 6504. Implemented (unverified)."
)
ESTIMATE_NOTE = (
    "白平衡（估计）: Shades-of-Gray p=6 in linear ACEScg after IDT. "
    "Engineering lock, not a white paper. Confirm writes an absolute AP0 CAT. "
    "Implemented (unverified)."
)

_AP1_Y = rgb_to_xyz_matrix("AP1")[1]


def _as_hw3(rgb) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float64)
    if arr.ndim == 1:
        return arr.reshape(1, 1, 3)
    if arr.ndim == 2 and arr.shape[-1] == 3:
        return arr.reshape(arr.shape[0], 1, 3)
    if arr.ndim == 3 and arr.shape[-1] == 3:
        return arr
    raise ValueError("auto WB expects RGB with last dim 3 (IDT-after AP0 linear)")


def _valid_mask(ap1: np.ndarray) -> np.ndarray:
    pix = ap1.reshape(-1, 3)
    y = pix @ _AP1_Y
    finite = np.all(np.isfinite(pix), axis=1)
    return finite & (y >= Y_MIN) & (np.max(pix, axis=1) <= CHAN_MAX) & np.all(pix >= 0.0, axis=1)


def _angle_deg(a, b) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    c = float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def _sog_illum(ap1: np.ndarray) -> tuple[np.ndarray | None, float]:
    mask = _valid_mask(ap1)
    frac = float(np.mean(mask)) if mask.size else 0.0
    if frac < MIN_VALID_FRAC or not np.any(mask):
        return None, frac
    valid = np.maximum(ap1.reshape(-1, 3)[mask], 0.0)
    mean_p = np.mean(np.power(valid, SOG_P), axis=0)
    illum = np.power(np.maximum(mean_p, 0.0), 1.0 / SOG_P)
    if not np.all(np.isfinite(illum)) or float(np.max(illum)) <= 1e-12:
        return None, frac
    return illum, frac


def _tile_max_angle(ap1: np.ndarray) -> float:
    h, w = ap1.shape[:2]
    if h < 3 or w < 3:
        return 0.0
    hs = np.array_split(np.arange(h), 3)
    ws = np.array_split(np.arange(w), 3)
    illums: list[np.ndarray] = []
    for rr in hs:
        for cc in ws:
            tile = ap1[int(rr[0]) : int(rr[-1]) + 1, int(cc[0]) : int(cc[-1]) + 1]
            illum, _ = _sog_illum(tile)
            if illum is not None:
                illums.append(illum)
    if len(illums) < 2:
        return 0.0
    mx = 0.0
    for i, a in enumerate(illums):
        for b in illums[i + 1 :]:
            mx = max(mx, _angle_deg(a, b))
    return mx


@dataclass(frozen=True)
class AutoWBEstimate:
    """Proposal only. Confirm writes CAT. Empty = do not apply."""

    cct: float | None
    tint: float = 0.0
    residual_deg: float = 0.0
    valid_frac: float = 0.0
    mixed_deg: float = 0.0
    reason: str = "empty"
    note: str = EMPTY_NOTE

    @property
    def ok(self) -> bool:
        return self.cct is not None

    @property
    def label(self) -> str:
        return AUTO_WB_LABEL


EMPTY_AUTO_WB = AutoWBEstimate(cct=None)


def _empty(reason: str, *, residual=0.0, frac=0.0, mixed=0.0) -> AutoWBEstimate:
    return AutoWBEstimate(
        cct=None,
        residual_deg=residual,
        valid_frac=frac,
        mixed_deg=mixed,
        reason=reason,
        note=EMPTY_NOTE,
    )


def estimate_auto_wb(ap0_rgb) -> AutoWBEstimate:
    """Estimate residual CCT from post-IDT ACES2065-1 (AP0) linear RGB.

    Does not apply a CAT. Does not guess 5600. Rec.709 / ACEScct / log
    buffers are the wrong domain — pass AP0 linear only.
    """
    ap0 = _as_hw3(ap0_rgb)
    ap1 = aces2065_to_ap1(ap0)
    illum, frac = _sog_illum(ap1)
    if illum is None:
        return _empty("valid<15%", frac=frac)
    residual = _angle_deg(illum, np.ones(3))
    if residual < RESIDUAL_ZERO_DEG:
        return _empty("residual<2", residual=residual, frac=frac)
    mixed = _tile_max_angle(ap1)
    if mixed > MIXED_MAX_DEG:
        return _empty("mixed>5", residual=residual, frac=frac, mixed=mixed)
    ap0_illum = ap1_to_aces2065(illum)
    cct, tint = linear_rgb_to_cct_tint(ap0_illum, rgb_space="AP0")
    return AutoWBEstimate(
        cct=float(cct),
        tint=float(tint),
        residual_deg=residual,
        valid_frac=frac,
        mixed_deg=mixed,
        reason="ok",
        note=ESTIMATE_NOTE,
    )


def estimate_to_shot(est: AutoWBEstimate) -> AsShotWB | None:
    """Confirmed estimate → AsShotWB (absolute CAT). None if empty."""
    if not est.ok:
        return None
    return AsShotWB(
        cct=float(est.cct),
        tint=float(est.tint),
        source=WB_SOURCE_ESTIMATE,
        note=est.note,
    )
