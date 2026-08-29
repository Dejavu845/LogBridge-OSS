"""Fixed-pipeline and gamut-matrix tests."""

import numpy as np
import pytest

from color.curves import (
    linear_to_apple_log,
    linear_to_logc3_ei800,
    linear_to_clog2,
    linear_to_clog3,
    linear_to_dlog,
    linear_to_logc4,
    linear_to_nlog,
    linear_to_slog3,
)
from color.gamuts import (
    ARRI_AWG4_TO_XYZ,
    IDT_PAIRS,
    PANASONIC_VGAMUT_TO_XYZ,
    rgb_to_xyz_matrix,
)
from color.graph import GRAPH_NODES, SCENE_LINEAR, WORKING_SPACE, SerialGraph
from color.pipeline import apply_idt, process_to_rec709
from color.working_space import (
    ACESCCT_18_PERCENT,
    aces2065_to_acescct,
    acescct_decode,
    acescct_encode,
)


def test_awg4_matrix_matches_arri_published():
    computed = rgb_to_xyz_matrix("AWG4")
    np.testing.assert_allclose(computed, ARRI_AWG4_TO_XYZ, atol=2e-4)


def test_vgamut_matrix_near_panasonic_published():
    computed = rgb_to_xyz_matrix("VGamut")
    np.testing.assert_allclose(computed, PANASONIC_VGAMUT_TO_XYZ, atol=5e-3)


def test_idt_pairs_are_locked():
    assert IDT_PAIRS["sony_slog3_sgamut3"] == ("slog3", "SGamut3")
    assert IDT_PAIRS["sony_slog3_sgamut3cine"] == ("slog3", "SGamut3Cine")
    # No implicit Cine default in the pair table.
    assert "SGamut3Cine" not in IDT_PAIRS["sony_slog3_sgamut3"]
    assert IDT_PAIRS["canon_clog2_cgamut"] == ("clog2", "CinemaGamut")
    assert IDT_PAIRS["canon_clog2_bt2020"] == ("clog2", "BT2020")
    assert IDT_PAIRS["canon_clog2_bt2020"][1] != "CinemaGamut"
    assert IDT_PAIRS["canon_clog3_cgamut"] == ("clog3", "CinemaGamut")
    assert IDT_PAIRS["canon_clog3_bt2020"] == ("clog3", "BT2020")
    assert IDT_PAIRS["canon_clog3_bt2020"][1] != "CinemaGamut"
    assert IDT_PAIRS["apple_log_bt2020"] == ("apple_log", "BT2020")
    assert IDT_PAIRS["apple_log2_awg"] == ("apple_log", "AppleWideGamut")
    assert IDT_PAIRS["apple_log2_awg"][1] != "BT2020"
    assert IDT_PAIRS["arri_logc3_ei800_awg3"] == ("logc3_ei800", "AWG3")
    assert "dji_dlog_m" not in IDT_PAIRS
    assert IDT_PAIRS["dji_dlog_dgamut"] == ("dlog", "DGamut")


def test_nlog_idt_uses_10bit_codes():
    cv = np.full(3, float(linear_to_nlog(0.18)))
    lin = apply_idt(cv, "nikon_nlog_bt2020")
    np.testing.assert_allclose(lin, 0.18, rtol=1e-8)


def test_logc4_idt_18_percent():
    log = np.full(3, float(linear_to_logc4(0.18)))
    lin = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(lin, 0.18, rtol=1e-6)


def test_process_to_rec709_neutral_grey_positive():
    log = np.full(3, float(linear_to_slog3(0.18)))
    out = process_to_rec709(log, "sony_slog3_sgamut3", apply_wb=False)
    assert np.all(out > 0.0)
    # Neutral stays neutral through ACES D60 -> Rec.709 D65 CAT.
    assert out[0] == pytest.approx(out[1], rel=1e-5)
    assert out[1] == pytest.approx(out[2], rel=1e-5)


def test_wb_toggle_changes_tungsten_not_d65():
    log = np.array(
        [
            float(linear_to_logc4(0.10)),
            float(linear_to_logc4(0.18)),
            float(linear_to_logc4(0.30)),
        ]
    )
    a = process_to_rec709(log, "arri_logc4_awg4", apply_wb=True, cct=6504.0)
    b = process_to_rec709(log, "arri_logc4_awg4", apply_wb=False)
    np.testing.assert_allclose(a, b, atol=2e-3)
    c = process_to_rec709(log, "arri_logc4_awg4", apply_wb=True, cct=3200.0)
    assert not np.allclose(c, b, atol=1e-3)


def test_acescct_18_percent():
    enc = acescct_encode(0.18)
    assert enc == pytest.approx(ACESCCT_18_PERCENT, abs=5e-6)
    assert acescct_decode(enc) == pytest.approx(0.18, rel=1e-6)


def test_acescct_roundtrip():
    lin = np.array([0.001, 0.0078125, 0.18, 1.0, 16.0])
    np.testing.assert_allclose(
        acescct_decode(acescct_encode(lin)), lin, rtol=1e-10, atol=1e-12
    )


def test_idt_grey_is_aces_018():
    log = np.full(3, float(linear_to_slog3(0.18)))
    aces = apply_idt(log, "sony_slog3_sgamut3")
    np.testing.assert_allclose(aces, 0.18, rtol=1e-6)
    enc = aces2065_to_acescct(aces)
    np.testing.assert_allclose(enc, ACESCCT_18_PERCENT, atol=5e-5)


def test_serial_graph_nodes():
    assert GRAPH_NODES == ("IDT", "Exposure", "WB", "ODT_Rec709")
    assert WORKING_SPACE == "ACEScct"
    assert SCENE_LINEAR == "ACES2065-1"
    g = SerialGraph(idt_id="arri_logc4_awg4", wb_enabled=False, odt_enabled=True)
    assert g.node(2).name == "Exposure"
    assert g.node(2).bypassable is True
    assert g.node(3).name == "WB"
    assert g.node(3).bypassable is True
    assert g.node(3).enabled is False
    log = np.full(3, float(linear_to_logc4(0.18)))
    rec = g.apply(log)
    direct = process_to_rec709(log, "arri_logc4_awg4", apply_wb=False)
    np.testing.assert_allclose(rec, direct, atol=1e-10)


def test_clog2_idt_18_percent_both_pairs():
    log = np.full(3, float(linear_to_clog2(0.18)))
    for idt_id in ("canon_clog2_cgamut", "canon_clog2_bt2020"):
        lin = apply_idt(log, idt_id)
        np.testing.assert_allclose(lin, 0.18, rtol=1e-6)


def test_clog3_idt_18_percent_both_pairs():
    log = np.full(3, float(linear_to_clog3(0.18)))
    for idt_id in ("canon_clog3_cgamut", "canon_clog3_bt2020"):
        lin = apply_idt(log, idt_id)
        np.testing.assert_allclose(lin, 0.18, rtol=1e-6)


def test_apple_log_idt_18_percent():
    log = np.full(3, float(linear_to_apple_log(0.18)))
    lin = apply_idt(log, "apple_log_bt2020")
    np.testing.assert_allclose(lin, 0.18, rtol=1e-6)


def test_apple_log2_awg_not_bt2020():
    from color.gamuts import IDT_PAIRS, camera_to_aces2065_matrix

    log = np.full(3, float(linear_to_apple_log(0.18)))
    awg = apply_idt(log, "apple_log2_awg")
    np.testing.assert_allclose(awg, 0.18, rtol=1e-6)
    assert IDT_PAIRS["apple_log2_awg"][1] == "AppleWideGamut"
    assert IDT_PAIRS["apple_log2_awg"][1] != "BT2020"
    m_awg = camera_to_aces2065_matrix("AppleWideGamut")
    m_2020 = camera_to_aces2065_matrix("BT2020")
    assert not np.allclose(m_awg, m_2020, rtol=1e-4, atol=1e-4)
    chroma = np.array([0.30, 0.50, 0.70])
    assert not np.allclose(
        apply_idt(chroma, "apple_log2_awg"),
        apply_idt(chroma, "apple_log_bt2020"),
        rtol=1e-4,
        atol=1e-4,
    )


def test_logc3_ei800_idt_18_percent():
    log = np.full(3, float(linear_to_logc3_ei800(0.18)))
    lin = apply_idt(log, "arri_logc3_ei800_awg3")
    np.testing.assert_allclose(lin, 0.18, rtol=1e-5)
    assert float(linear_to_logc3_ei800(0.18)) == pytest.approx(0.391, abs=5e-4)


def test_dlog_idt_18_percent():
    log = np.full(3, float(linear_to_dlog(0.18)))
    lin = apply_idt(log, "dji_dlog_dgamut")
    np.testing.assert_allclose(lin, 0.18, rtol=1e-6)
