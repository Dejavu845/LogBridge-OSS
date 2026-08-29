"""Exposure in ACES2065-1 scene-linear (AP0): uniform gain from stops.

User-facing control is **stops**. After IDT, in ACES2065-1 linear:

    rgb * (2 ** stops)

Do **not** add or subtract from camera-log or ACEScct code values.
0 stops is identity. +1 stop doubles scene-linear RGB.

Uniform gain commutes with a CAT (WB), but the locked order is still
IDT → Exposure → WB. Rec.709 / HLG / PQ remain preview only.
"""

from __future__ import annotations

import numpy as np

def stops_to_gain(stops: float) -> float:
    """Linear multiplier for ``stops`` (2**stops). 0 → 1."""
    return float(2.0 ** float(stops))


def apply_exposure(rgb, stops: float = 0.0) -> np.ndarray:
    """Apply stop-based exposure to ACES2065-1 (AP0) scene-linear RGB.

    Identity at 0 stops. Never an offset on log / ACEScct codes.
    """
    rgb = np.asarray(rgb, dtype=np.float64)
    if stops == 0.0:
        return rgb
    return rgb * stops_to_gain(stops)
