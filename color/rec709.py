"""Rec.709 OETF / inverse (ITU-R BT.709). Simple M1 ODT, no RRT/DRT.

This is a scene-linear to Rec.709 *encoding*, not a display rendering
transform. The Rec.709 ODT preview pane tags the framebuffer as Rec.709;
the source pane does not. Never blit these values into an untagged
(default Display P3) layer.
"""

from __future__ import annotations

import numpy as np

# Continuity-corrected BT.709 constants (IEC 61966-2-1 uses the rounded pair).
_BETA = 0.018053968510807
_ALPHA = 1.09929682680944


def rec709_oetf(lin):
    """Scene-linear Rec.709 RGB -> Rec.709 encoded (0-1)."""
    lin = np.asarray(lin, dtype=np.float64)
    return np.where(
        lin < _BETA,
        4.5 * lin,
        _ALPHA * np.power(np.maximum(lin, 0.0), 0.45) - (_ALPHA - 1.0),
    )


def rec709_oetf_inverse(enc):
    """Rec.709 encoded -> scene-linear Rec.709 RGB."""
    enc = np.asarray(enc, dtype=np.float64)
    thresh = 4.5 * _BETA
    return np.where(
        enc < thresh,
        enc / 4.5,
        np.power((enc + (_ALPHA - 1.0)) / _ALPHA, 1.0 / 0.45),
    )


def bt1886_eotf(v, gamma: float = 2.4):
    """BT.1886 display EOTF (black=0, white=1): V**gamma."""
    v = np.asarray(v, dtype=np.float64)
    return np.power(np.maximum(v, 0.0), gamma)


def bt1886_eotf_inverse(lin, gamma: float = 2.4):
    lin = np.asarray(lin, dtype=np.float64)
    return np.power(np.maximum(lin, 0.0), 1.0 / gamma)
