"""Serial node graph: IDT → Exposure → WB (bypassable) → selectable ODT.

Not a node editor. Used by ``pipeline`` and Resolve export.

  1. IDT       — camera log → ACES2065-1 (AP0 scene-linear). No WB, no exposure.
  2. Exposure  — stops (default 0). In ACES2065-1 linear: rgb * (2 ** stops).
                 Not a log-code add. Bypassable / zeroable. Own export node
                 (1D / gain); not baked into IDT or WB when stops=0.
  3. WB        — Bradford/CAT02 in ACES2065-1 scene-linear (AP0). Never a CAT
                 on ACEScct-encoded values. As-shot CCT/tint from camera-private
                 metadata (not nclc) fills the knobs (UI only). Default CAT is
                 identity — Log IDTs assume already white-balanced. Do not CAT
                 as-shot 5600/6504 toward D65 (double WB). User move away from
                 as-shot is relative CAT(user->D65)·inv(CAT(as->D65))
                 == CAT(user->as) in AP0; 3200->5600 warms. Not
                 CAT(as->user), not CAT(user->D65) alone. First typed CCT
                 with no as-shot is a label (identity).
                 Grey-card is absolute CAT. Confirmed auto WB (白平衡（估计）)
                 is also absolute; propose does not write CAT. Missing CCT: knobs empty / pending,
                 identity, no 5600 guess. Bypassable.
  4. ODT       — Off (ACEScct deliverable, default) | Rec.709 preview |
                 Rec.2100 HLG | Rec.2100 PQ. Rec.709 is preview only (DIY
                 BT.709 OETF, no RRT). HLG/PQ are ACES Output Transform /
                 BT.2100 OCIO Builtins — no homemade HLG/PQ curve.

Locked order: IDT → Exposure → WB → ACEScct → preview ODT.
Uniform gain and CAT commute; the order is still locked.
Working / deliverable: ACEScct timeline or ACES2065-1 EXR / ACES workflow.
Rec.709 is preview only. HLG/PQ are implemented (unverified). Not supported.
Do not bake DaVinci Wide Gamut Intermediate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gamuts import IDT_PAIRS, aces_to_rec709_matrix
from .odt import (
    HDR_ODTS,
    ODT_CHOICES,
    ODT_DEFAULT,
    ODT_HLG,
    ODT_OFF,
    ODT_PQ,
    ODT_REC709,
    apply_hdr_odt,
)
from .exposure import apply_exposure, stops_to_gain
from .rec709 import rec709_oetf
from .wb import white_balance_matrix
from .as_shot import (
    WB_SOURCE_AS_SHOT,
    WB_SOURCE_ESTIMATE,
    WB_SOURCE_GREY,
    WB_SOURCE_UNKNOWN,
    WB_SOURCE_USER,
    AsShotWB,
    UNKNOWN_AS_SHOT,
    effective_cat_cct,
    effective_cat_src_cct,
    pick_neutral_from_linear_rgb,
    read_as_shot_wb,
    wb_defaults_from_as_shot,
)
from .working_space import (
    aces2065_to_acescct,
    acescct_to_aces2065,
)

NODE_IDT = "IDT"
NODE_EXPOSURE = "Exposure"
NODE_WB = "WB"
NODE_ODT = "ODT_Rec709"
NODE_ODT_HLG = "ODT_Rec2100_HLG"
NODE_ODT_PQ = "ODT_Rec2100_PQ"
GRAPH_NODES = (NODE_IDT, NODE_EXPOSURE, NODE_WB, NODE_ODT)
# ODT slot selector. Default Off = ACEScct deliverable.
ODT_OFF = ODT_OFF
ODT_REC709 = ODT_REC709
ODT_HLG = ODT_HLG
ODT_PQ = ODT_PQ
ODT_CHOICES = ODT_CHOICES
ODT_DEFAULT = ODT_DEFAULT
EXPORT_SLOTS = (
    (1, NODE_IDT, "01_IDT"),
    (2, NODE_EXPOSURE, "02_Exposure"),
    (3, NODE_WB, "03_WB"),
    (4, NODE_ODT, "04_ODT"),
)

WORKING_SPACE = "ACEScct"
SCENE_LINEAR = "ACES2065-1"
WB_LINEAR_SPACE = "AP0"


@dataclass
class GraphNode:
    index: int
    name: str
    export_basename: str
    enabled: bool = True
    bypassable: bool = False


def odt_node_name(odt: str) -> str:
    """Export / graph name for the ODT slot. Default slot stays ODT_Rec709."""
    if odt == ODT_HLG:
        return NODE_ODT_HLG
    if odt == ODT_PQ:
        return NODE_ODT_PQ
    return NODE_ODT


@dataclass
class SerialGraph:
    """Fixed four-node graph: IDT → Exposure → WB → ODT.

    Exposure is stop-based linear gain in ACES2065-1 (default 0 = identity).
    WB is bypassable. As-shot camera-private CCT/tint (not nclc) fills the
    knobs (UI only). Default CAT is identity — do not treat as-shot
    5600/6504 as an illuminant (double WB). ``wb_cct is None`` /
    ``wb_source==as_shot`` is identity — do not guess 5600 K. User move
    away from as-shot is relative CAT (src=as-shot, dst=user). First
    typed CCT with no as-shot is a label (identity). Grey-card is
    absolute CAT. ``odt`` selects Off | Rec.709 preview | Rec.2100 HLG |
    Rec.2100 PQ.
    """

    idt_id: str | None = None
    exposure_stops: float = 0.0
    exposure_enabled: bool = True
    wb_enabled: bool = False
    wb_cct: float | None = None
    wb_tint: float = 0.0
    wb_method: str = "bradford"
    wb_source: str = WB_SOURCE_UNKNOWN
    as_shot_cct: float | None = None
    as_shot_tint: float = 0.0
    auto_wb_cct: float | None = None
    auto_wb_tint: float = 0.0
    auto_wb_note: str = ""
    odt_enabled: bool = False
    odt: str = ODT_OFF

    def __post_init__(self) -> None:
        if self.odt not in ODT_CHOICES:
            raise ValueError(f"Unknown ODT {self.odt!r} (use {ODT_CHOICES})")
        if self.odt != ODT_OFF:
            self.odt_enabled = True
        elif self.odt_enabled:
            self.odt = ODT_REC709

    @property
    def apply_wb(self) -> bool:
        return self.wb_enabled

    @property
    def apply_odt(self) -> bool:
        return self.odt != ODT_OFF

    @property
    def cct(self) -> float | None:
        return self.wb_cct

    @property
    def tint(self) -> float:
        return self.wb_tint

    def odt_slot_name(self) -> str:
        return odt_node_name(self.odt)

    def nodes(self) -> list[GraphNode]:
        return [
            GraphNode(1, NODE_IDT, "01_IDT", enabled=True, bypassable=False),
            GraphNode(
                2,
                NODE_EXPOSURE,
                "02_Exposure",
                enabled=self.exposure_enabled,
                bypassable=True,
            ),
            GraphNode(3, NODE_WB, "03_WB", enabled=self.wb_enabled, bypassable=True),
            GraphNode(
                4,
                self.odt_slot_name(),
                "04_ODT",
                enabled=self.odt_enabled,
                bypassable=True,
            ),
        ]

    def node(self, index: int) -> GraphNode:
        for n in self.nodes():
            if n.index == index:
                return n
        raise KeyError(index)

    def set_enabled(self, index: int, enabled: bool) -> None:
        if index == 1:
            raise ValueError("IDT is not bypassable")
        if index == 2:
            self.exposure_enabled = bool(enabled)
        elif index == 3:
            self.wb_enabled = bool(enabled)
        elif index == 4:
            if enabled:
                if self.odt == ODT_OFF:
                    self.odt = ODT_REC709
                self.odt_enabled = True
            else:
                self.odt = ODT_OFF
                self.odt_enabled = False
        else:
            raise KeyError(index)

    def set_exposure_stops(self, stops: float) -> None:
        self.exposure_stops = float(stops)

    @classmethod
    def from_as_shot(cls, as_shot: AsShotWB | None = None, **kwargs) -> "SerialGraph":
        """Build a graph whose WB knobs default to as-shot (CAT stays identity)."""
        shot = as_shot if as_shot is not None else UNKNOWN_AS_SHOT
        defaults = wb_defaults_from_as_shot(shot)
        defaults.update(kwargs)
        return cls(**defaults)

    @classmethod
    def from_metadata(cls, meta: dict | None, **kwargs) -> "SerialGraph":
        """Read camera-private CCT/tint (never nclc) into the WB node default."""
        return cls.from_as_shot(read_as_shot_wb(meta), **kwargs)

    def apply_as_shot(self, as_shot: AsShotWB) -> None:
        """Write as-shot CCT/tint into the WB knobs (UI only). CAT stays identity."""
        self.as_shot_cct = as_shot.cct
        self.as_shot_tint = float(as_shot.tint)
        if as_shot.known:
            self.wb_cct = float(as_shot.cct)
            self.wb_tint = float(as_shot.tint)
            self.wb_source = WB_SOURCE_AS_SHOT
            self.wb_enabled = True
        else:
            self.wb_cct = None
            self.wb_tint = 0.0
            self.wb_source = WB_SOURCE_UNKNOWN

    def pick_neutral(self, linear_rgb, rgb_space: str = "AP0") -> AsShotWB:
        """Grey-card / pick-neutral override: sample preview linear RGB.

        Review lock: sample after IDT in ACES2065-1 (AP0) linear. Default
        space is AP0. Overrides as-shot metadata. Writes this WB node only.
        """
        shot = pick_neutral_from_linear_rgb(linear_rgb, rgb_space=rgb_space)
        self.wb_cct = float(shot.cct)
        self.wb_tint = float(shot.tint)
        self.wb_source = WB_SOURCE_GREY
        self.wb_enabled = True
        return shot

    def apply_grey_card(self, ap0_rgb) -> AsShotWB:
        """Grey-card pick after IDT in ACES2065-1 (AP0) linear. Overrides metadata."""
        return self.pick_neutral(ap0_rgb, rgb_space="AP0")

    def propose_auto_wb(self, ap0_rgb):
        """Estimate residual WB. Does not write CAT. Empty on low confidence."""
        from .auto_wb import estimate_auto_wb

        est = estimate_auto_wb(ap0_rgb)
        if est.ok:
            self.auto_wb_cct = float(est.cct)
            self.auto_wb_tint = float(est.tint)
            self.auto_wb_note = est.note
        else:
            self.auto_wb_cct = None
            self.auto_wb_tint = 0.0
            self.auto_wb_note = est.note
        return est

    def confirm_auto_wb(self) -> bool:
        """User confirm: write absolute AP0 CAT. Grey-card wins. Empty stays empty."""
        if self.wb_source == WB_SOURCE_GREY:
            return False
        if self.auto_wb_cct is None:
            return False
        self.wb_cct = float(self.auto_wb_cct)
        self.wb_tint = float(self.auto_wb_tint)
        self.wb_source = WB_SOURCE_ESTIMATE
        self.wb_enabled = True
        return True

    def set_user_wb(self, cct: float, tint: float | None = None) -> None:
        """User CCT/tint. Relative CAT if knobs leave as-shot; else a label."""
        self.wb_cct = float(cct)
        if tint is not None:
            self.wb_tint = float(tint)
        self.wb_source = WB_SOURCE_USER
        self.wb_enabled = True

    @property
    def as_shot_unknown(self) -> bool:
        """Pending when no CCT is written. An explicit CCT is never dropped."""
        return self.wb_cct is None

    @property
    def effective_wb_cct(self) -> float | None:
        """Destination CCT applied by the CAT, or None when identity.

        As-shot knobs are UI only — identity even at 3200 or 5600 (no
        double WB). Missing CCT is identity — do not guess 5600.
        First typed CCT with no as-shot is a label (identity).
        User move away from as-shot is relative (see ``effective_src_cct``).
        Grey-card override is an absolute CAT.
        """
        return effective_cat_cct(
            wb_cct=self.wb_cct,
            wb_tint=self.wb_tint,
            wb_source=self.wb_source,
            as_shot_cct=self.as_shot_cct,
            as_shot_tint=self.as_shot_tint,
        )

    @property
    def effective_src_cct(self) -> float | None:
        """As-shot CCT for relative CAT, or None for absolute / identity."""
        return effective_cat_src_cct(
            wb_cct=self.wb_cct,
            wb_tint=self.wb_tint,
            wb_source=self.wb_source,
            as_shot_cct=self.as_shot_cct,
            as_shot_tint=self.as_shot_tint,
        )

    def wb_matrix(self) -> np.ndarray:
        """3x3 AP0 CAT applied by ``wb_node`` (identity when no CAT).

        Relative: ``src_cct`` = as-shot, ``dst_cct`` = user.
        Grey-card / CLI-unknown: absolute CAT(cct->D65).
        """
        cct = self.effective_wb_cct
        src = self.effective_src_cct
        return white_balance_matrix(
            cct if src is None else None,
            tint=self.wb_tint,
            rgb_space=WB_LINEAR_SPACE,
            method=self.wb_method,
            src_cct=src,
            dst_cct=cct if src is not None else None,
            src_tint=self.as_shot_tint,
        )

    @property
    def exposure_gain(self) -> float:
        if not self.exposure_enabled:
            return 1.0
        return stops_to_gain(self.exposure_stops)

    def set_odt(self, odt: str) -> None:
        if odt not in ODT_CHOICES:
            raise ValueError(f"Unknown ODT {odt!r} (use {ODT_CHOICES})")
        self.odt = odt
        self.odt_enabled = odt != ODT_OFF

    def idt_node(self, log_rgb, idt_id: str | None = None) -> np.ndarray:
        """IDT: camera log → ACES2065-1 linear (AP0). No WB, no exposure.

        Preview cache stores this buffer. Exposure + WB apply in linear
        on top of it. ACEScct encode is only for grading / preview
        display / the Resolve timeline.
        """
        from .pipeline import apply_idt

        chosen = idt_id or self.idt_id
        if not chosen:
            raise ValueError("IDT is required")
        return apply_idt(log_rgb, chosen)

    def idt_to_acescct(self, log_rgb, idt_id: str | None = None) -> np.ndarray:
        """IDT then ACEScct encode (timeline / grading). No WB."""
        return aces2065_to_acescct(self.idt_node(log_rgb, idt_id))

    def exposure_node(self, aces_ap0) -> np.ndarray:
        """Exposure: uniform gain in ACES2065-1 linear. Identity at 0 / bypass.

        ``rgb * (2 ** stops)``. Not an add/subtract on log code values.
        """
        rgb = np.asarray(aces_ap0, dtype=np.float64)
        if not self.exposure_enabled or self.exposure_stops == 0.0:
            return rgb
        return apply_exposure(rgb, self.exposure_stops)

    def wb_node(self, aces_ap0) -> np.ndarray:
        """WB CAT in ACES2065-1 (AP0) scene-linear. Identity when disabled.

        Input must be ACES2065-1 linear, not ACEScct-encoded.
        As-shot knobs (unmoved) and missing CCT are identity — not 5600 K.
        User move: relative CAT via ``src_cct`` (as-shot) and ``dst_cct``
        (user) — CAT(user->D65)·inv(CAT(as->D65)) == CAT(user->as);
        3200->5600 warms. Not CAT(as->user), not CAT(user->D65) alone.
        First typed CCT with no as-shot is a label (identity).
        Grey-card is absolute.
        Do not CAT as-shot 5600/6504 toward D65 (double WB).
        """
        rgb = np.asarray(aces_ap0, dtype=np.float64)
        if not self.wb_enabled:
            return rgb
        m = self.wb_matrix()
        return rgb @ m.T

    def wb_on_acescct(self, acescct_rgb) -> np.ndarray:
        """ACEScct in/out wrapper: decode → AP0 CAT → encode. Not a CAT on log."""
        enc = np.asarray(acescct_rgb, dtype=np.float64)
        if not self.wb_enabled:
            return enc
        ap0 = acescct_to_aces2065(enc)
        ap0 = self.wb_node(ap0)
        return aces2065_to_acescct(ap0)

    def odt_node(self, aces_ap0) -> np.ndarray:
        """Preview ODT: ACES2065-1 → Rec.709 encoded. Not the deliverable."""
        m = aces_to_rec709_matrix("AP0")
        rec_lin = np.asarray(aces_ap0, dtype=np.float64) @ m.T
        return rec709_oetf(np.clip(rec_lin, 0.0, None))

    def ap0_write_setup(self) -> tuple[float, np.ndarray | None]:
        """Clip-constant exposure gain + CAT for a locked write.

        Long sequences reuse this. Do not rebuild the CAT per write frame.
        WB off → ``None`` (skip the matrix). Numbers match ``exposure_node``
        / ``wb_node``.
        """
        gain = float(self.exposure_gain)
        cat = self.wb_matrix() if self.wb_enabled else None
        return gain, cat

    def apply_ap0(
        self,
        log_rgb,
        idt_id: str | None = None,
        *,
        setup: tuple[float, np.ndarray | None] | None = None,
    ) -> np.ndarray:
        """Write / linear-cache path: IDT → exposure → WB. Never ODT.

        EXR stays ACES2065-1 AP0 linear proxy. Preview ODT (709 / HLG / PQ)
        is not applied here — ``apply`` still runs ODT for preview/scrub.
        ``setup`` is ``ap0_write_setup()`` so a long clip does not rebuild
        the CAT per frame. Pixel math matches ``exposure_node`` / ``wb_node``.
        """
        chosen = idt_id or self.idt_id
        if not chosen:
            raise ValueError("IDT is required")
        if chosen not in IDT_PAIRS:
            raise KeyError(f"Unknown IDT {chosen!r}")
        work = self.idt_node(log_rgb, chosen)
        if setup is None:
            work = self.exposure_node(work)
            return self.wb_node(work)
        gain, cat = setup
        work = np.asarray(work, dtype=np.float64)
        if gain != 1.0:
            work = work * float(gain)
        if cat is not None:
            work = work @ np.asarray(cat, dtype=np.float64).T
        return work

    def apply(self, log_rgb, idt_id: str | None = None) -> np.ndarray:
        """Run IDT → Exposure (AP0 linear) → optional WB (AP0) → optional ODT.

        ODT off: ACES2065-1 scene-linear (ACEScct deliverable when encoded
        for the Resolve timeline). Rec.709 is preview only. HLG/PQ use
        ACES Output Transform / BT.2100 (OCIO Builtin; no homemade curve).
        Locked proxy EXR writes use ``apply_ap0`` — not this method —
        so a 709 preview ODT is not baked into the sequence.
        """
        work = self.apply_ap0(log_rgb, idt_id)
        if self.odt == ODT_REC709:
            return self.odt_node(work)
        if self.odt in HDR_ODTS:
            return apply_hdr_odt(work, self.odt)
        return work

    def process(self, log_rgb, idt_id: str) -> np.ndarray:
        """Alias for ``apply`` used by the pipeline."""
        return self.apply(log_rgb, idt_id)


def graph_from_export_args(
    idt_id: str | None = None,
    cct: float | None = 6504.0,
    tint: float = 0.0,
    include_wb: bool = True,
    odt_enabled: bool = False,
    method: str = "bradford",
    odt: str | None = None,
    exposure_stops: float = 0.0,
    exposure_enabled: bool = True,
) -> SerialGraph:
    """Build a SerialGraph from Resolve-export CLI / Swift flags.

    ODT defaults Off (ACEScct deliverable). Rec.709 is preview only.
    HLG/PQ are ACES Output Transform / BT.2100 (unverified).
    Exposure is its own node (default 0 stops = identity gain).
    """
    chosen = odt if odt is not None else (ODT_REC709 if odt_enabled else ODT_OFF)
    # CLI / export CCT without as-shot is an explicit absolute CAT
    # (unknown-but-set), not a first-typed UI label.
    source = WB_SOURCE_UNKNOWN
    return SerialGraph(
        idt_id=idt_id,
        exposure_stops=exposure_stops,
        exposure_enabled=exposure_enabled,
        wb_enabled=include_wb,
        wb_cct=cct,
        wb_tint=tint,
        wb_method=method,
        wb_source=source,
        odt_enabled=odt_enabled,
        odt=chosen,
    )
