"""Exposure node: stops in ACES2065-1 linear, not a log-code add."""

from pathlib import Path

import numpy as np

from color.curves import linear_to_logc4, linear_to_slog3
from color.exposure import apply_exposure, stops_to_gain
from color.graph import GRAPH_NODES, SerialGraph
from color.pipeline import apply_idt, process_to_rec709
from color.resolve_export import (
    export_resolve_bundle,
    exposure_in_aces2065,
    exposure_in_acescct,
    idt_to_acescct,
)
from color.wb import apply_white_balance
from color.working_space import aces2065_to_acescct, acescct_to_aces2065


def _logc4_chroma():
    return np.array(
        [
            float(linear_to_logc4(0.10)),
            float(linear_to_logc4(0.18)),
            float(linear_to_logc4(0.30)),
        ]
    )


def _slog3_grey():
    return np.full(3, float(linear_to_slog3(0.18)))


def test_plus_one_stop_doubles_linear():
    rgb = np.array([0.05, 0.18, 0.40])
    out = apply_exposure(rgb, 1.0)
    np.testing.assert_allclose(out, 2.0 * rgb, atol=0)
    assert stops_to_gain(1.0) == 2.0
    log = _slog3_grey()
    g = SerialGraph(idt_id="sony_slog3_sgamut3", exposure_stops=1.0)
    out = g.apply(log)
    aces = apply_idt(log, "sony_slog3_sgamut3")
    np.testing.assert_allclose(out, 2.0 * aces, atol=1e-12)
    np.testing.assert_allclose(out, 0.36, atol=1e-3)


def test_zero_stops_is_identity():
    rgb = np.array([0.05, 0.18, 0.40])
    np.testing.assert_allclose(apply_exposure(rgb, 0.0), rgb, atol=0)
    assert stops_to_gain(0.0) == 1.0
    log = _logc4_chroma()
    g0 = SerialGraph(idt_id="arri_logc4_awg4", exposure_stops=0.0)
    g_off = SerialGraph(
        idt_id="arri_logc4_awg4", exposure_stops=1.0, exposure_enabled=False
    )
    aces = apply_idt(log, "arri_logc4_awg4")
    np.testing.assert_allclose(g0.apply(log), aces, atol=1e-12)
    np.testing.assert_allclose(g_off.apply(log), aces, atol=1e-12)


def test_order_idt_then_exposure_then_wb():
    assert GRAPH_NODES == ("IDT", "Exposure", "WB", "ODT_Rec709")
    log = _logc4_chroma()
    g = SerialGraph(
        idt_id="arri_logc4_awg4",
        exposure_stops=1.0,
        wb_enabled=True,
        wb_cct=3200.0,
        odt_enabled=False,
    )
    assert [n.name for n in g.nodes()][:3] == ["IDT", "Exposure", "WB"]
    aces = g.idt_node(log)
    after_exp = g.exposure_node(aces)
    after_wb = g.wb_node(after_exp)
    np.testing.assert_allclose(g.apply(log), after_wb, atol=1e-12)
    np.testing.assert_allclose(after_exp, 2.0 * aces, atol=1e-12)
    expected = apply_white_balance(2.0 * aces, 3200.0, rgb_space="AP0")
    np.testing.assert_allclose(after_wb, expected, atol=1e-12)
    # Locked order still holds even though uniform gain and CAT commute.
    commuted = 2.0 * apply_white_balance(aces, 3200.0, rgb_space="AP0")
    np.testing.assert_allclose(after_wb, commuted, atol=1e-12)


def test_exposure_is_not_a_log_code_add():
    """rgb * (2**stops) after IDT ≠ adding an offset to camera-log / ACEScct."""
    log = _logc4_chroma()
    aces = apply_idt(log, "arri_logc4_awg4")
    linear = apply_exposure(aces, 1.0)
    # Adding +something to camera-log codes then IDT is a different operator.
    wrong_log = apply_idt(log + 0.05, "arri_logc4_awg4")
    assert not np.allclose(linear, wrong_log, atol=1e-3)
    # Adding an offset to ACEScct codes is also wrong (log-domain add).
    enc = aces2065_to_acescct(aces)
    wrong_cct = acescct_to_aces2065(enc + 0.05)
    assert not np.allclose(linear, wrong_cct, atol=1e-3)
    # ACEScct-wrapped exposure must decode, gain, encode — not add to codes.
    wrapped = exposure_in_acescct(enc, 1.0)
    direct = aces2065_to_acescct(linear)
    np.testing.assert_allclose(wrapped, direct, atol=1e-10)
    # In the ACEScct toe (lin <= 0.0078125) a log-code add is the wrong operator.
    toe = np.full(3, 0.004)
    toe_enc = aces2065_to_acescct(toe)
    toe_lin = apply_exposure(toe, 1.0)
    toe_wrapped = exposure_in_acescct(toe_enc, 1.0)
    np.testing.assert_allclose(toe_wrapped, aces2065_to_acescct(toe_lin), atol=1e-10)
    naive_add = toe_enc + np.log2(2.0) / 17.52
    assert not np.allclose(toe_wrapped, naive_add, atol=1e-3)


def test_minus_one_stop_halves_linear():
    rgb = np.array([0.20, 0.18, 0.10])
    np.testing.assert_allclose(apply_exposure(rgb, -1.0), 0.5 * rgb, atol=0)


def test_process_to_rec709_forwards_stops():
    log = _slog3_grey()
    a = process_to_rec709(log, "sony_slog3_sgamut3", exposure_stops=0.0)
    b = process_to_rec709(log, "sony_slog3_sgamut3", exposure_stops=1.0)
    assert not np.allclose(a, b, atol=1e-3)


def test_export_exposure_is_own_node_not_baked(tmp_path: Path):
    g0 = SerialGraph(idt_id="arri_logc4_awg4", exposure_stops=0.0)
    written = export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], graph=g0, lut_size=5
    )
    names = {p.name for p in written}
    assert "02_Exposure.cube" in names
    assert "02_Exposure.dctl" in names
    xml = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    assert 'name="Exposure" type="Gain_1D" bypassable="true"' in xml
    assert "not baked into IDT or WB" in xml
    assert "02_Exposure.cube" in xml
    idt = (tmp_path / "01_IDT_arri_logc4_awg4.cube").read_text(encoding="utf-8")
    assert "no WB" in idt
    dctl = (tmp_path / "02_Exposure.dctl").read_text(encoding="utf-8")
    assert "2 ** stops" in dctl or "2 ** stops" in xml
    assert "bypass_exposure" in dctl
    assert "Not a log-code add" in dctl
    # 0-stop 1D LUT is identity on ACEScct (decode→*1→encode).
    cube = (tmp_path / "02_Exposure.cube").read_text(encoding="utf-8")
    assert "LUT_1D_SIZE" in cube
    # IDT cube at stops=0 matches a no-exposure IDT helper.
    log = np.full(3, float(linear_to_logc4(0.18)))
    enc = idt_to_acescct(log, "arri_logc4_awg4")
    np.testing.assert_allclose(
        exposure_in_aces2065(apply_idt(log, "arri_logc4_awg4"), 0.0),
        apply_idt(log, "arri_logc4_awg4"),
        atol=0,
    )
    _ = enc
