"""As-shot WB review locks: AP0 CAT only, pending identity, grey-card after IDT."""

import numpy as np
import pytest

from color.as_shot import (
    UNKNOWN_AS_SHOT,
    WB_SOURCE_AS_SHOT,
    WB_SOURCE_GREY,
    WB_SOURCE_UNKNOWN,
    WB_SOURCE_USER,
    AsShotWB,
    effective_cat_cct,
    grey_card_from_ap0,
    pick_neutral_from_linear_rgb,
    read_as_shot_wb,
    wb_defaults_from_as_shot,
)
from color.curves import linear_to_logc4
from color.detect import detect_clip, detect_from_metadata
from color.gamuts import xy_to_xyz, xyz_to_rgb_matrix
from color.graph import SerialGraph
from color.pipeline import apply_idt
from color.resolve_export import (
    export_resolve_bundle,
    format_dctl,
    format_graph_xml,
    wb_in_aces2065,
    wb_in_acescct,
)
from color.wb import apply_white_balance, cct_to_xy, linear_rgb_to_cct_tint, white_balance_matrix
from color.working_space import aces2065_to_acescct


def _logc4_chroma():
    return np.array(
        [
            float(linear_to_logc4(0.10)),
            float(linear_to_logc4(0.18)),
            float(linear_to_logc4(0.30)),
        ]
    )


def _ap0_of_cct(cct: float, tint: float = 0.0) -> np.ndarray:
    return xyz_to_rgb_matrix("AP0") @ xy_to_xyz(cct_to_xy(cct, tint))


def test_missing_cct_is_pending_not_5600_or_6504():
    shot = read_as_shot_wb({})
    assert shot.pending
    assert shot.known is False
    assert shot.cct is None
    assert shot.cct not in (5600, 5600.0, 6504, 6504.0)
    assert "5600" in shot.note and "6504" in shot.note
    assert "guess" in shot.note
    assert "supported" not in shot.note.lower()
    assert "implemented (unverified)" in shot.note.lower()
    defaults = wb_defaults_from_as_shot(shot)
    assert defaults["wb_cct"] is None
    assert defaults["wb_source"] == WB_SOURCE_UNKNOWN


def test_nclc_never_supplies_as_shot_cct():
    shot = read_as_shot_wb({"nclc": "1-1-1", "quicktime_nclc": "5600", "colr": "6504"})
    assert shot.pending
    assert shot.cct is None


def test_metadata_cct_is_honored_including_5600():
    shot = read_as_shot_wb({"cct": 5600, "tint": 1.5})
    assert shot.known
    assert shot.source == WB_SOURCE_AS_SHOT
    assert shot.cct == pytest.approx(5600.0)
    assert shot.tint == pytest.approx(1.5)
    shot2 = read_as_shot_wb({"white_balance_kelvin": "3200K", "wb_tint": "-0.5"})
    assert shot2.cct == pytest.approx(3200.0)
    assert shot2.tint == pytest.approx(-0.5)


def test_detect_attaches_as_shot_from_camera_private_keys():
    d = detect_from_metadata(
        {
            "arri_mxf_color_space": "ARRI LogC4 / AWG4",
            "nclc": "1-1-1",
            "cct": 3200,
            "tint": 0.25,
        }
    )
    assert d.idt_id == "arri_logc4_awg4"
    assert d.as_shot_cct == pytest.approx(3200.0)
    assert d.as_shot_tint == pytest.approx(0.25)
    pending = detect_clip("A001_LogC4.mov", metadata={"nclc": "1-1-1"})
    assert pending.idt_id == "arri_logc4_awg4"
    assert pending.as_shot_cct is None


def test_as_shot_writes_existing_ap0_node_only():
    g = SerialGraph.from_metadata({"cct": 3200, "tint": 0.0}, idt_id="arri_logc4_awg4")
    assert [n.name for n in g.nodes()] == ["IDT", "Exposure", "WB", "ODT_Rec709"]
    assert g.wb_cct == pytest.approx(3200.0)
    assert g.wb_source == WB_SOURCE_AS_SHOT
    assert g.effective_wb_cct is None
    assert g.node(3).name == "WB"
    assert g.node(3).bypassable is True
    log = _logc4_chroma()
    out = g.apply(log)
    aces = apply_idt(log, "arri_logc4_awg4")
    # As-shot knobs are UI only — CAT is identity (no double WB).
    np.testing.assert_allclose(out, aces, atol=1e-12)
    enc = aces2065_to_acescct(aces)
    wrong_log = apply_white_balance(log, 3200.0, rgb_space="AP0")
    wrong_cct = apply_white_balance(enc, 3200.0, rgb_space="AP0")
    doubled = apply_white_balance(aces, 3200.0, rgb_space="AP0")
    assert not np.allclose(out, wrong_log, atol=1e-3)
    assert not np.allclose(out, wrong_cct, atol=1e-3)
    assert not np.allclose(out, doubled, atol=1e-3)


def test_pending_as_shot_is_identity():
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    g = SerialGraph.from_as_shot(UNKNOWN_AS_SHOT, idt_id="arri_logc4_awg4", wb_enabled=True)
    assert g.wb_cct is None
    assert g.as_shot_unknown
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)
    np.testing.assert_allclose(apply_white_balance(aces, None), aces)


def test_grey_card_samples_ap0_after_idt_and_overrides_metadata():
    g = SerialGraph.from_metadata({"cct": 5600}, idt_id="arri_logc4_awg4")
    assert g.wb_cct == pytest.approx(5600.0)
    ap0 = _ap0_of_cct(3200.0)
    shot = g.apply_grey_card(ap0)
    assert shot.source == WB_SOURCE_GREY
    assert g.wb_source == WB_SOURCE_GREY
    assert g.wb_cct == pytest.approx(3200.0, rel=0.05)
    assert abs(g.wb_tint) < 1.5
    # Overrides metadata 5600.
    assert g.wb_cct != pytest.approx(5600.0, abs=50)


def test_grey_card_is_not_log_or_acescct():
    log = _logc4_chroma()
    ap0 = apply_idt(log, "arri_logc4_awg4")
    enc = aces2065_to_acescct(ap0)
    from_ap0 = grey_card_from_ap0(ap0)
    from_log = pick_neutral_from_linear_rgb(log, rgb_space="AP0")
    from_enc = pick_neutral_from_linear_rgb(enc, rgb_space="AP0")
    assert from_ap0.cct != pytest.approx(from_log.cct, rel=0.02)
    assert from_ap0.cct != pytest.approx(from_enc.cct, rel=0.02)


def test_grey_card_roundtrip_locus():
    rgb = _ap0_of_cct(3200.0, 0.0)
    cct, tint = linear_rgb_to_cct_tint(rgb, rgb_space="AP0")
    assert cct == pytest.approx(3200.0, rel=0.03)
    assert abs(tint) < 0.75


def test_resolve_wb_stays_bypassable_with_as_shot(tmp_path):
    g = SerialGraph.from_metadata({"cct": 3200}, idt_id="arri_logc4_awg4")
    assert g.node(3).bypassable is True
    xml = format_graph_xml(["arri_logc4_awg4"], 3200.0, 0.0, include_wb=True, graph=g)
    assert 'name="WB"' in xml
    assert 'bypassable="true"' in xml
    assert "<CCT>3200.0000</CCT>" in xml
    assert "do not guess 5600 or 6504" in xml
    g.set_enabled(3, False)
    log = _logc4_chroma()
    np.testing.assert_allclose(g.apply(log), apply_idt(log, "arri_logc4_awg4"), atol=1e-12)
    off = format_graph_xml(["arri_logc4_awg4"], 3200.0, 0.0, include_wb=True, graph=g)
    assert 'enabled="false"' in off
    written = export_resolve_bundle(tmp_path, idt_ids=["arri_logc4_awg4"], graph=g, lut_size=5)
    names = {p.name for p in written}
    assert "03_WB.cube" in names
    assert "03_WB.dctl" in names
    dctl = (tmp_path / "03_WB.dctl").read_text(encoding="utf-8")
    assert "bypass_wb" in dctl


def test_pending_export_does_not_write_guessed_cct(tmp_path):
    g = SerialGraph.from_as_shot(UNKNOWN_AS_SHOT, idt_id="arri_logc4_awg4")
    xml = format_graph_xml(["arri_logc4_awg4"], None, 0.0, include_wb=False, graph=g)
    assert 'pending="true"' in xml
    assert "5600" not in xml or "do not guess 5600" in xml
    # Must not emit a guessed CCT element.
    assert "<CCT>5600" not in xml
    assert "<CCT>6504" not in xml
    dctl = format_dctl(None, 0.0)
    assert "as-shot unknown" in dctl
    assert "6504 K" not in dctl
    export_resolve_bundle(tmp_path, idt_ids=["arri_logc4_awg4"], graph=g, lut_size=5)
    disk = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    assert 'pending="true"' in disk
    assert "<CCT>5600" not in disk
    assert "<CCT>6504" not in disk


def test_as_shot_present_unmoved_knobs_are_identity_cat():
    """As-shot present, user has not moved knobs → CAT is identity (3200 or 5600)."""
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    for kelvin in (3200.0, 5600.0, 6504.0):
        g = SerialGraph.from_metadata({"cct": kelvin}, idt_id="arri_logc4_awg4")
        assert g.wb_cct == pytest.approx(kelvin)
        assert g.as_shot_cct == pytest.approx(kelvin)
        assert g.wb_source == WB_SOURCE_AS_SHOT
        assert g.effective_wb_cct is None
        np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)
        if kelvin != 6504.0:
            doubled = apply_white_balance(aces, kelvin, rgb_space="AP0")
            assert not np.allclose(g.apply(log), doubled, atol=1e-3)


def test_user_changes_cct_from_as_shot_applies_cat():
    """User changes CCT from as-shot -> relative CAT, not CAT(user->D65)."""
    g = SerialGraph.from_metadata({"cct": 5600.0}, idt_id="arri_logc4_awg4")
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)
    g.set_user_wb(3200.0, 0.0)
    assert g.wb_source == WB_SOURCE_USER
    assert g.effective_wb_cct == pytest.approx(3200.0)
    assert g.effective_src_cct == pytest.approx(5600.0)
    out = g.apply(log)
    expected = apply_white_balance(
        aces, src_cct=5600.0, dst_cct=3200.0, rgb_space="AP0"
    )
    np.testing.assert_allclose(out, expected, atol=1e-12)
    assert not np.allclose(out, aces, atol=1e-3)


def test_grey_card_override_is_real_cat_unless_d65():
    """Grey-card override → CAT not identity (unless sampled D65)."""
    g = SerialGraph.from_metadata({"cct": 5600.0}, idt_id="arri_logc4_awg4")
    assert g.effective_wb_cct is None
    ap0_3200 = _ap0_of_cct(3200.0)
    shot = g.apply_grey_card(ap0_3200)
    assert shot.source == WB_SOURCE_GREY
    assert g.wb_source == WB_SOURCE_GREY
    assert g.effective_wb_cct is not None
    m = white_balance_matrix(g.effective_wb_cct, tint=g.wb_tint, rgb_space="AP0")
    assert np.linalg.norm(m - np.eye(3)) > 0.05

    g65 = SerialGraph.from_metadata({"cct": 3200.0}, idt_id="arri_logc4_awg4")
    g65.apply_grey_card(_ap0_of_cct(6504.0))
    assert g65.wb_source == WB_SOURCE_GREY
    m65 = white_balance_matrix(g65.effective_wb_cct, tint=g65.wb_tint, rgb_space="AP0")
    np.testing.assert_allclose(m65, np.eye(3), atol=5e-3)


def test_missing_cct_identity_no_5600_guess():
    """Missing CCT → identity, no 5600."""
    assert effective_cat_cct(wb_cct=None) is None
    g = SerialGraph.from_as_shot(UNKNOWN_AS_SHOT, idt_id="arri_logc4_awg4")
    assert g.wb_cct is None
    assert g.effective_wb_cct is None
    assert g.wb_cct not in (5600, 5600.0)
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)


def test_no_supported_in_as_shot_copy():
    shot = read_as_shot_wb(None)
    grey = grey_card_from_ap0(_ap0_of_cct(3200.0))
    for note in (shot.note, grey.note, UNKNOWN_AS_SHOT.note):
        assert "supported" not in note.lower()
        assert "implemented (unverified)" in note.lower()


def test_wb_acescct_wrap_still_decodes_before_as_shot_cat():
    ap0 = np.array([0.10, 0.18, 0.30])
    enc = aces2065_to_acescct(ap0)
    wrapped = wb_in_acescct(enc, 3200.0)
    direct = aces2065_to_acescct(wb_in_aces2065(ap0, 3200.0))
    np.testing.assert_allclose(wrapped, direct, atol=1e-10)



def test_as_shot_3200_unmoved_knobs_identity_matrix():
    """as-shot 3200, knobs still 3200 -> identity."""
    g = SerialGraph.from_metadata({"cct": 3200.0}, idt_id="arri_logc4_awg4")
    assert g.wb_cct == pytest.approx(3200.0)
    assert g.effective_wb_cct is None
    np.testing.assert_allclose(g.wb_matrix(), np.eye(3), atol=1e-12)
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)


def test_as_shot_3200_user_5600_is_relative_not_absolute():
    """as-shot 3200, user 5600 == CAT(5600->D65) @ inv(CAT(3200->D65)).

    Not equal to CAT(5600->D65) alone.
    """
    g = SerialGraph.from_metadata({"cct": 3200.0}, idt_id="arri_logc4_awg4")
    g.set_user_wb(5600.0, 0.0)
    assert g.effective_wb_cct == pytest.approx(5600.0)
    assert g.effective_src_cct == pytest.approx(3200.0)
    got = g.wb_matrix()
    cat_user = white_balance_matrix(5600.0, rgb_space="AP0")
    cat_shot = white_balance_matrix(3200.0, rgb_space="AP0")
    expected = cat_user @ np.linalg.inv(cat_shot)
    np.testing.assert_allclose(got, expected, atol=1e-12)
    assert not np.allclose(got, cat_user, atol=1e-3)
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    out = g.wb_node(aces)
    np.testing.assert_allclose(out, aces @ expected.T, atol=1e-12)
    absolute = apply_white_balance(aces, 5600.0, rgb_space="AP0")
    assert not np.allclose(out, absolute, atol=1e-3)


def test_first_typed_cct_no_as_shot_is_identity():
    """No as-shot, user types 5600 first time -> identity (label, not illuminant)."""
    g = SerialGraph(idt_id="arri_logc4_awg4", wb_enabled=True)
    g.set_user_wb(5600.0, 0.0)
    assert g.as_shot_cct is None
    assert g.wb_source == WB_SOURCE_USER
    assert g.effective_wb_cct is None
    assert g.effective_src_cct is None
    np.testing.assert_allclose(g.wb_matrix(), np.eye(3), atol=1e-12)
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)
    g.set_user_wb(3200.0, 0.0)
    assert g.effective_wb_cct is None
    np.testing.assert_allclose(g.apply(log), aces, atol=1e-12)
    absolute_3200 = apply_white_balance(aces, 3200.0, rgb_space="AP0")
    assert not np.allclose(g.apply(log), absolute_3200, atol=1e-3)


def test_grey_card_is_absolute_cat_not_relative():
    """Grey-card -> absolute CAT of sampled white to D65, not relative to as-shot."""
    g = SerialGraph.from_metadata({"cct": 5600.0}, idt_id="arri_logc4_awg4")
    ap0_3200 = _ap0_of_cct(3200.0)
    shot = g.apply_grey_card(ap0_3200)
    assert shot.source == WB_SOURCE_GREY
    assert g.wb_source == WB_SOURCE_GREY
    assert g.effective_wb_cct is not None
    assert g.effective_src_cct is None
    got = g.wb_matrix()
    absolute = white_balance_matrix(g.wb_cct, tint=g.wb_tint, rgb_space="AP0")
    np.testing.assert_allclose(got, absolute, atol=1e-12)
    rel = white_balance_matrix(
        src_cct=5600.0, dst_cct=g.wb_cct, tint=g.wb_tint, rgb_space="AP0"
    )
    assert not np.allclose(got, rel, atol=1e-3)
    cat_3200 = white_balance_matrix(3200.0, rgb_space="AP0")
    np.testing.assert_allclose(got, cat_3200, atol=5e-2)
