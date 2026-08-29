"""Optional ODT nodes: Rec.709 preview, Rec.2100 HLG, Rec.2100 PQ.

Rec.709 stays the DIY BT.709 OETF preview (unverified). HLG / PQ are
ACES Output Transform / BT.2100 paths named for OCIO BuiltinTransform
(and config-aces aliases). Prefer those Builtins over any handwritten
HLG or PQ curve — this module does not implement ITU-R BT.2100 math.

When PyOpenColorIO is importable, apply() uses the ACES OT + DISPLAY
BuiltinTransform chain. When it is not, HDR apply raises: no homemade
fallback. Status of every ODT: implemented (unverified). Not supported.
Not 一键精准.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from .ocio_builtins import apply_builtin, ocio_available, registry_styles

# Serial-graph ODT selector. Default Off = ACEScct / ACES2065-1 deliverable.
ODT_OFF = "off"
ODT_REC709 = "rec709"
ODT_HLG = "hlg"
ODT_PQ = "pq"
ODT_CHOICES = (ODT_OFF, ODT_REC709, ODT_HLG, ODT_PQ)
ODT_DEFAULT = ODT_OFF
HDR_ODTS = (ODT_HLG, ODT_PQ)

# --- OCIO BuiltinTransform styles (ACES Output Transform / BT.2100) ---
# ACES 1.3 (OCIO 2.1+). OT lands in CIE-XYZ-D65; DISPLAY encodes Rec.2100.
ACES_OT_HLG_1_3 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1"
)
ACES_OT_PQ_1_3 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-ST2084_1.1"
)
DISPLAY_REC2100_HLG = "DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG"
DISPLAY_REC2100_PQ = "DISPLAY - CIE-XYZ-D65_to_REC.2100-REC2020-ST2084"

# ACES 2.0 Rec.2100-named OT (OCIO 2.4+). Preferred when the registry has them.
ACES_OT_HLG_2_0 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-HLG-1000nit_2.0"
)
ACES_OT_PQ_2_0 = (
    "ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-Rec.2020-ST2084-1000nit_2.0"
)

# Academy config-aces color-space names (cg-config / studio-config).
CONFIG_ACES_HLG = "Output - Rec.2100-HLG - 1000 nit"
CONFIG_ACES_PQ = "Output - Rec.2100-Rec.2020-ST2084 - 1000 nit"

# Public colorspace / view names used in ocio/config.ocio.
CS_REC2100_HLG = "Rec.2100-HLG"
CS_REC2100_PQ = "Rec.2100-PQ"

# Rec.709 remains preview-only. Not an ACES RRT/ODT.
REC709_ROLE = "preview"
REC709_STATUS = "implemented (unverified)"
HDR_STATUS = "implemented (unverified)"


class HDRODTRequiresOCIO(RuntimeError):
    """Rec.2100 HLG/PQ is ACES Output Transform only — no homemade curve."""


def _chain_for(odt: str, styles: set[str] | None) -> tuple[str, ...]:
    """Return the BuiltinTransform style chain for HLG or PQ.

    Prefer ACES 2.0 Rec.2100-named OT when the registry lists it; otherwise
    ACES 1.3 OT + DISPLAY. ``styles is None`` means "declare the 1.3 chain"
    (Linux / no-OCIO). Never invent a transfer.
    """
    if odt == ODT_HLG:
        if styles is not None and ACES_OT_HLG_2_0 in styles:
            return (ACES_OT_HLG_2_0,)
        return (ACES_OT_HLG_1_3, DISPLAY_REC2100_HLG)
    if odt == ODT_PQ:
        if styles is not None and ACES_OT_PQ_2_0 in styles:
            return (ACES_OT_PQ_2_0,)
        return (ACES_OT_PQ_1_3, DISPLAY_REC2100_PQ)
    raise KeyError(f"Not an HDR ODT: {odt!r}")


def declared_hdr_styles(odt: str) -> tuple[str, ...]:
    """Styles named in config / docs (ACES 1.3 OT + DISPLAY). Always declared."""
    return _chain_for(odt, styles=None)


def resolve_hdr_styles(odt: str) -> tuple[str, ...]:
    """Styles to apply: ACES 2.0 if present, else the declared 1.3 chain."""
    live = registry_styles() if ocio_available() else None
    return _chain_for(odt, live)


def odt_descriptor(odt: str) -> dict:
    """Machine-readable ODT declaration. Used by tests and export."""
    if odt == ODT_OFF:
        return {
            "id": ODT_OFF,
            "name": "Off",
            "display_name": "Off (ACEScct deliverable)",
            "role": "deliverable",
            "status": HDR_STATUS,
            "preview_only": False,
            "supported": False,
            "via": "ACEScct timeline / ACES2065-1 EXR",
            "ocio_styles": (),
            "config_aces": None,
            "colorspace": "ACEScct",
        }
    if odt == ODT_REC709:
        return {
            "id": ODT_REC709,
            "name": "Rec.709",
            "display_name": "Rec.709 preview",
            "role": REC709_ROLE,
            "status": REC709_STATUS,
            "preview_only": True,
            "supported": False,
            "via": "DIY BT.709 OETF (preview only, no ACES RRT)",
            "ocio_styles": (),
            "config_aces": None,
            "colorspace": "Rec.709",
        }
    if odt == ODT_HLG:
        return {
            "id": ODT_HLG,
            "name": "Rec.2100 HLG",
            "display_name": "Rec.2100 HLG",
            "role": "hdr_output",
            "status": HDR_STATUS,
            "preview_only": False,
            "supported": False,
            "via": "ACES Output Transform / BT.2100",
            "ocio_styles": declared_hdr_styles(ODT_HLG),
            "ocio_styles_aces2": (ACES_OT_HLG_2_0,),
            "config_aces": CONFIG_ACES_HLG,
            "colorspace": CS_REC2100_HLG,
        }
    if odt == ODT_PQ:
        return {
            "id": ODT_PQ,
            "name": "Rec.2100 PQ",
            "display_name": "Rec.2100 PQ",
            "role": "hdr_output",
            "status": HDR_STATUS,
            "preview_only": False,
            "supported": False,
            "via": "ACES Output Transform / BT.2100",
            "ocio_styles": declared_hdr_styles(ODT_PQ),
            "ocio_styles_aces2": (ACES_OT_PQ_2_0,),
            "config_aces": CONFIG_ACES_PQ,
            "colorspace": CS_REC2100_PQ,
        }
    raise KeyError(f"Unknown ODT {odt!r}")


def all_odt_descriptors() -> list[dict]:
    return [odt_descriptor(x) for x in ODT_CHOICES]


def apply_builtin_group(styles: Iterable[str], rgb) -> np.ndarray:
    """Apply a sequence of OCIO BuiltinTransform styles. Requires OCIO."""
    work = np.asarray(rgb, dtype=np.float64)
    for style in styles:
        work = apply_builtin(style, work, inverse=False)
    return np.asarray(work, dtype=np.float64)


def apply_hdr_odt(aces_ap0, odt: str) -> np.ndarray:
    """ACES2065-1 → Rec.2100 HLG or PQ via ACES Output Transform.

    No homemade HLG/PQ curve. Raises HDRODTRequiresOCIO when OCIO Python
    is missing. Status: implemented (unverified).
    """
    if odt not in HDR_ODTS:
        raise KeyError(f"HDR ODT expected, got {odt!r}")
    desc = odt_descriptor(odt)
    if not ocio_available():
        chain = " then ".join(desc["ocio_styles"])
        raise HDRODTRequiresOCIO(
            f"{desc['name']} requires OCIO ACES Output Transform / BT.2100 "
            f"({chain}; config-aces {desc['config_aces']!r}). "
            "No homemade HLG/PQ curve. Implemented (unverified)."
        )
    return apply_builtin_group(resolve_hdr_styles(odt), aces_ap0)


def apply_odt(aces_ap0, odt: str):
    """Dispatch ODT. Off returns ACES2065-1. Rec.709 is preview-only."""
    if odt in (ODT_OFF, None, ""):
        return np.asarray(aces_ap0, dtype=np.float64)
    if odt == ODT_REC709:
        from .pipeline import apply_odt_rec709

        return apply_odt_rec709(aces_ap0, working="AP0")
    if odt in HDR_ODTS:
        return apply_hdr_odt(aces_ap0, odt)
    raise KeyError(f"Unknown ODT {odt!r}")
