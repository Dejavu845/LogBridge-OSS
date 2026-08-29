"""As-shot WB: fill CCT/tint knobs; default CAT is identity.

Log IDTs assume the image is already white-balanced (neutrals are
neutral after IDT). Camera CCT/tint metadata is UI only — fill the
knobs as “as-shot”. Default CAT is identity.

Apply the existing linear AP0 CAT **only** when the user moves CCT/tint
away from the as-shot values (relative CAT(user→D65)·inv(CAT(as→D65))
== CAT(user→as) in AP0; 3200→5600 warms),
or applies a grey-card override (absolute CAT). First typed CCT with
no as-shot is a label (identity).

Review locks:
  * As-shot writes ONLY the existing linear AP0 CAT node. Never CAT on
    camera-log or ACEScct-encoded values.
  * Do NOT treat as-shot 5600/6504 as an illuminant and CAT toward D65
    again (double WB).
  * Missing CCT/tint → knobs empty / pending, identity CAT, no 5600 guess.
  * Grey-card pick samples after IDT in ACES2065-1 (AP0) linear, sets
    CCT/tint, and THAT is a real CAT (override). Identity only if the
    sample is D65.
  * Resolve WB node remains bypassable.
  * Status: implemented (unverified). Not a support claim.

6504 K remains the D65 identity of the CAT math when a caller *explicitly*
sets that CCT (user move or grey-card). It is never filled in when
as-shot metadata is missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .wb import linear_rgb_to_cct_tint

WB_SOURCE_UNKNOWN = "unknown"
WB_SOURCE_PENDING = WB_SOURCE_UNKNOWN  # review-lock alias
WB_SOURCE_AS_SHOT = "as_shot"
WB_SOURCE_GREY = "grey"
WB_SOURCE_GREY_CARD = WB_SOURCE_GREY
WB_SOURCE_USER = "user"
WB_SOURCE_MANUAL = WB_SOURCE_USER
WB_SOURCE_ESTIMATE = "estimate"

PENDING_NOTE = (
    "Missing as-shot CCT/tint; knobs empty / pending, identity CAT "
    "(do not guess 5600 or 6504). Implemented (unverified)."
)


@dataclass(frozen=True)
class AsShotWB:
    """Resolved as-shot / grey-card CCT+tint for the existing AP0 CAT node."""

    cct: float | None
    tint: float = 0.0
    source: str = WB_SOURCE_UNKNOWN
    note: str = PENDING_NOTE

    @property
    def known(self) -> bool:
        return self.cct is not None and self.source != WB_SOURCE_UNKNOWN

    @property
    def pending(self) -> bool:
        return not self.known

    @property
    def is_identity(self) -> bool:
        """Pending and unmodified as-shot are identity CAT (UI only)."""
        return self.source in (WB_SOURCE_UNKNOWN, WB_SOURCE_AS_SHOT)


UNKNOWN_AS_SHOT = AsShotWB(
    cct=None,
    tint=0.0,
    source=WB_SOURCE_UNKNOWN,
    note=PENDING_NOTE,
)


def pending_as_shot(note: str | None = None) -> AsShotWB:
    if note is None:
        return UNKNOWN_AS_SHOT
    return AsShotWB(cct=None, tint=0.0, source=WB_SOURCE_UNKNOWN, note=note)


def _as_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number:  # NaN
            return None
        return number
    if isinstance(value, str):
        text = value.strip().lower().replace("kelvin", "").replace(",", "")
        if text.endswith("k") and text[:-1].replace(".", "", 1).lstrip("-").isdigit():
            text = text[:-1]
        text = text.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


_CCT_KEYS = (
    "as_shot_cct",
    "as_shot_kelvin",
    "white_balance_kelvin",
    "wb_kelvin",
    "color_temperature",
    "colour_temperature",
    "cct",
    "kelvin",
    "arri_white_balance",
    "arri_wb_kelvin",
    "sony_white_balance",
    "sony_wb_kelvin",
    "red_kelvin",
    "red_color_temperature",
    "canon_color_temperature",
    "canon_wb_kelvin",
)

_TINT_KEYS = (
    "as_shot_tint",
    "white_balance_tint",
    "wb_tint",
    "tint",
    "arri_tint",
    "arri_wb_tint",
    "sony_tint",
    "sony_wb_tint",
    "red_tint",
    "canon_tint",
    "canon_wb_tint",
)

_NCLC_KEYS = {"nclc", "nclx", "colr", "quicktime_nclc", "qt_nclc"}


def _first_number(meta: dict, keys: tuple[str, ...]) -> float | None:
    lowered = {str(k).lower(): v for k, v in meta.items()}
    for key in keys:
        if key in lowered:
            number = _as_number(lowered[key])
            if number is not None:
                return number
    return None


def read_as_shot_wb(meta: dict | None) -> AsShotWB:
    """Read CCT/tint from camera-private metadata. Missing → pending / identity.

    Never invent 5600 or 6504 when the keys are absent. A metadata value of
    5600 or 6504 is honored (the camera wrote it). QuickTime nclc is ignored.
    """
    if not meta:
        return UNKNOWN_AS_SHOT
    cleaned = {k: v for k, v in meta.items() if str(k).lower() not in _NCLC_KEYS}
    cct = _first_number(cleaned, _CCT_KEYS)
    tint = _first_number(cleaned, _TINT_KEYS)
    if cct is None:
        return UNKNOWN_AS_SHOT
    return AsShotWB(
        cct=float(cct),
        tint=0.0 if tint is None else float(tint),
        source=WB_SOURCE_AS_SHOT,
        note=(
            "As-shot CCT/tint from camera-private metadata (UI only). "
            "Log IDT assumes already white-balanced; CAT stays identity. "
            "Do not CAT as-shot 5600/6504 toward D65 (double WB). "
            "Implemented (unverified)."
        ),
    )


parse_as_shot_metadata = read_as_shot_wb


def pick_neutral_from_linear_rgb(linear_rgb, rgb_space: str = "AP0") -> AsShotWB:
    """Grey-card / pick-neutral from scene-linear RGB.

    Review lock: sample **after IDT in ACES2065-1 (AP0) linear**. Default
    ``rgb_space`` is AP0. Do not pass camera-log or ACEScct-encoded values.
    Overrides as-shot metadata when written onto the existing WB node.
    """
    cct, tint = linear_rgb_to_cct_tint(linear_rgb, rgb_space=rgb_space)
    return AsShotWB(
        cct=float(cct),
        tint=float(tint),
        source=WB_SOURCE_GREY,
        note=(
            "Grey-card pick after IDT in ACES2065-1 (AP0) linear; overrides metadata. "
            "This is a real AP0 CAT (identity only if the sample is D65). "
            "Implemented (unverified)."
        ),
    )


def grey_card_from_ap0(ap0_rgb) -> AsShotWB:
    """Grey-card pick: sample after IDT in ACES2065-1 (AP0) linear only."""
    return pick_neutral_from_linear_rgb(ap0_rgb, rgb_space="AP0")


def knobs_match_as_shot(
    wb_cct: float | None,
    wb_tint: float,
    as_shot_cct: float | None,
    as_shot_tint: float,
    *,
    cct_tol: float = 0.5,
    tint_tol: float = 1e-3,
) -> bool:
    """True when the knobs still sit on the as-shot metadata values."""
    if wb_cct is None or as_shot_cct is None:
        return False
    return (
        abs(float(wb_cct) - float(as_shot_cct)) <= cct_tol
        and abs(float(wb_tint) - float(as_shot_tint)) <= tint_tol
    )


def effective_cat_cct(
    *,
    wb_cct: float | None,
    wb_tint: float = 0.0,
    wb_source: str = WB_SOURCE_UNKNOWN,
    as_shot_cct: float | None = None,
    as_shot_tint: float = 0.0,
) -> float | None:
    """Destination CCT fed to the AP0 CAT, or None for identity.

    Log IDTs assume the image is already white-balanced. Camera CCT/tint
    is UI only (as-shot knobs). Default CAT is identity — do not treat
    as-shot 5600/6504 as an illuminant and CAT toward D65 (double WB).

    Apply CAT only when the user moves CCT/tint away from as-shot
    (relative: CAT(user→D65)·inv(CAT(as→D65)) == CAT(user→as)
    in AP0; 3200→5600 warms — not CAT(as→user), not CAT(user→D65)
    alone), or on a
    grey-card override (absolute CAT of the sampled white to D65).

    First manually typed CCT with no as-shot is a label, not an
    illuminant — identity until there is a reference (as-shot or grey).
    Do not CAT(user→D65) on first fill.

    Missing CCT: identity, no 5600 guess.

    Source ``as_shot`` is never a CAT, even at 3200 or 5600.
    Source ``grey`` is an absolute CAT. Source ``estimate`` (confirmed
    auto WB) is an absolute CAT. Source ``user`` with as-shot
    is relative. Source ``unknown`` with an explicit CCT (CLI / unit
    construction) stays an absolute CAT.
    """
    if wb_cct is None:
        return None
    if wb_source == WB_SOURCE_AS_SHOT:
        return None
    if wb_source == WB_SOURCE_USER:
        if as_shot_cct is None:
            return None
        if knobs_match_as_shot(wb_cct, wb_tint, as_shot_cct, as_shot_tint):
            return None
        return float(wb_cct)
    return float(wb_cct)


def effective_cat_src_cct(
    *,
    wb_cct: float | None,
    wb_tint: float = 0.0,
    wb_source: str = WB_SOURCE_UNKNOWN,
    as_shot_cct: float | None = None,
    as_shot_tint: float = 0.0,
) -> float | None:
    """As-shot CCT for relative CAT, or None for absolute / identity.

    Relative only when the user moved knobs away from a known as-shot.
    Grey-card and CLI/unknown stay absolute (no src).
    """
    dst = effective_cat_cct(
        wb_cct=wb_cct,
        wb_tint=wb_tint,
        wb_source=wb_source,
        as_shot_cct=as_shot_cct,
        as_shot_tint=as_shot_tint,
    )
    if dst is None:
        return None
    if wb_source == WB_SOURCE_USER and as_shot_cct is not None:
        return float(as_shot_cct)
    return None


def wb_defaults_from_as_shot(shot: AsShotWB) -> dict:
    """SerialGraph field defaults. Knobs from as-shot; CAT stays identity.

    Pending → knobs empty, identity, no 5600/6504 guess.
    """
    if shot.known:
        return {
            "wb_cct": float(shot.cct),
            "wb_tint": float(shot.tint),
            "wb_source": WB_SOURCE_AS_SHOT,
            "wb_enabled": True,
            "as_shot_cct": float(shot.cct),
            "as_shot_tint": float(shot.tint),
        }
    return {
        "wb_cct": None,
        "wb_tint": 0.0,
        "wb_source": WB_SOURCE_UNKNOWN,
        "wb_enabled": False,
        "as_shot_cct": None,
        "as_shot_tint": 0.0,
    }


def write_as_shot_to_graph(graph, shot: AsShotWB):
    """Populate the existing WB knobs (UI only). CAT stays identity."""
    graph.apply_as_shot(shot)
    return graph
