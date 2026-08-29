"""Auto WB estimate: SoG p=6 in ACEScg, absolute AP0 CAT only after confirm."""

import numpy as np
import pytest

from color.as_shot import (
    WB_SOURCE_AS_SHOT,
    WB_SOURCE_ESTIMATE,
    WB_SOURCE_GREY,
    UNKNOWN_AS_SHOT,
)
from color.auto_wb import (
    AUTO_WB_LABEL,
    EMPTY_AUTO_WB,
    estimate_auto_wb,
)
from color.gamuts import xy_to_xyz, xyz_to_rgb_matrix
from color.graph import SerialGraph
from color.pipeline import apply_idt
from color.wb import apply_white_balance, cct_to_xy, white_balance_matrix
from color.working_space import aces2065_to_ap1


def _ap0_of_cct(cct: float, tint: float = 0.0) -> np.ndarray:
    return xyz_to_rgb_matrix("AP0") @ xy_to_xyz(cct_to_xy(cct, tint))


def _image(rgb, h=12, w=12) -> np.ndarray:
    pix = np.asarray(rgb, dtype=np.float64).reshape(3)
    return np.tile(pix, (h, w, 1))


def test_label_is_estimate_not_calibrate():
    assert AUTO_WB_LABEL == "白平衡（估计）"
    assert "精准" not in EMPTY_AUTO_WB.note
    assert "一键" not in EMPTY_AUTO_WB.note
    est = estimate_auto_wb(_image(_ap0_of_cct(3200.0)))
    assert "估计" in est.label
    assert "精准" not in est.note
    assert "一键校准" not in est.note


def test_neutral_aces_white_is_empty():
    white = np.ones(3) * 0.18
    # AP0 18% equal RGB is near ACES white → residual < 2°.
    est = estimate_auto_wb(_image(white))
    assert est.ok is False
    assert est.cct is None
    assert est.cct not in (5600, 5600.0, 6504, 6504.0)
    assert est.reason == "residual<2"


def test_no_5600_guess_on_empty():
    dark = np.full((8, 8, 3), 1e-4)
    est = estimate_auto_wb(dark)
    assert est.ok is False
    assert est.cct is None
    assert "5600" in est.note
    assert est.reason == "valid<15%"


def test_uniform_3200_cast_estimates_and_needs_confirm():
    ap0 = _image(_ap0_of_cct(3200.0) * 0.18)
    g = SerialGraph.from_as_shot(UNKNOWN_AS_SHOT, idt_id="arri_logc4_awg4")
    assert g.effective_wb_cct is None
    est = g.propose_auto_wb(ap0)
    assert est.ok
    assert est.cct == pytest.approx(3200.0, rel=0.08)
    assert g.effective_wb_cct is None
    assert g.wb_source != WB_SOURCE_ESTIMATE
    assert g.confirm_auto_wb() is True
    assert g.wb_source == WB_SOURCE_ESTIMATE
    assert g.effective_wb_cct == pytest.approx(est.cct)
    assert g.effective_src_cct is None
    got = g.wb_matrix()
    absolute = white_balance_matrix(g.wb_cct, tint=g.wb_tint, rgb_space="AP0")
    np.testing.assert_allclose(got, absolute, atol=1e-12)
    rel = white_balance_matrix(src_cct=5600.0, dst_cct=g.wb_cct, rgb_space="AP0")
    assert not np.allclose(got, rel, atol=1e-3)


def test_mixed_light_3x3_is_empty():
    left = _ap0_of_cct(3200.0) * 0.18
    right = _ap0_of_cct(6504.0) * 0.18
    img = np.zeros((12, 12, 3))
    img[:, :6] = left
    img[:, 6:] = right
    est = estimate_auto_wb(img)
    assert est.ok is False
    assert est.cct is None
    assert est.reason == "mixed>5"
    assert est.mixed_deg > 5.0


def test_grey_card_overrides_estimate():
    g = SerialGraph.from_metadata({"cct": 5600.0}, idt_id="arri_logc4_awg4")
    assert g.wb_source == WB_SOURCE_AS_SHOT
    assert g.effective_wb_cct is None
    g.propose_auto_wb(_image(_ap0_of_cct(3200.0) * 0.18))
    g.confirm_auto_wb()
    assert g.wb_source == WB_SOURCE_ESTIMATE
    g.apply_grey_card(_ap0_of_cct(6504.0))
    assert g.wb_source == WB_SOURCE_GREY
    # D65-ish sample → near-identity absolute CAT.
    m = g.wb_matrix()
    np.testing.assert_allclose(m, np.eye(3), atol=5e-3)


def test_confirm_does_not_override_grey():
    g = SerialGraph(idt_id="arri_logc4_awg4")
    g.apply_grey_card(_ap0_of_cct(3200.0))
    assert g.wb_source == WB_SOURCE_GREY
    g.propose_auto_wb(_image(_ap0_of_cct(5600.0) * 0.18))
    assert g.confirm_auto_wb() is False
    assert g.wb_source == WB_SOURCE_GREY


def test_as_shot_stays_identity_until_confirm():
    g = SerialGraph.from_metadata({"cct": 3200.0}, idt_id="arri_logc4_awg4")
    assert g.effective_wb_cct is None
    g.propose_auto_wb(_image(_ap0_of_cct(4000.0) * 0.18))
    assert g.wb_source == WB_SOURCE_AS_SHOT
    assert g.effective_wb_cct is None


def test_domain_is_ap0_not_acescg_identity_on_ap0_white():
    """Estimator converts AP0 → ACEScg internally; equal AP0 is empty."""
    est = estimate_auto_wb(_image(np.array([0.18, 0.18, 0.18])))
    assert est.ok is False


def test_sog_runs_in_acescg():
    ap0 = _image(_ap0_of_cct(3200.0) * 0.18)
    ap1 = aces2065_to_ap1(ap0)
    assert not np.allclose(ap0, ap1, atol=1e-4)
    est = estimate_auto_wb(ap0)
    assert est.ok
