"""Extension-point stubs for IDTs that stay unimplemented.

LogC3 EI800 + AWG3 and Apple Log 2 + Apple Wide Gamut are implemented
(unverified) in ``color.curves`` / ``color.gamuts``. This remains a stub:

- DJI D-Log M (unsupported; 2017 D-Log + D-Gamut only)

Status: not implemented. Do not mark this camera as supported.
"""

from __future__ import annotations

STUB_IDTS = (
    {
        "id": "dji_dlog_m",
        "curve": "dlog_m",
        "gamut": "DJI (unspecified)",
        "status": "stub",
        "note": "D-Log M is unsupported. DJI D-Log + D-Gamut (2017 white paper) is implemented (unverified).",
    },
)


def dlog_m_to_linear(_x):
    raise NotImplementedError(
        "DJI D-Log M is unsupported. Use D-Log + D-Gamut (2017 white paper)."
    )
