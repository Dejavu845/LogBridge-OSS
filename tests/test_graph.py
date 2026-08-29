"""Serial node graph: IDT → Exposure → WB → ODT, bypass flags match pipeline + export."""

from pathlib import Path

import numpy as np
import pytest

from color.as_shot import WB_SOURCE_GREY
from color.curves import linear_to_logc4, linear_to_slog3
from color.graph import EXPORT_SLOTS, SerialGraph, graph_from_export_args
from color.pipeline import apply_idt, process_to_rec709
from color.wb import apply_white_balance
from color.working_space import aces2065_to_acescct
from color.resolve_export import export_resolve_bundle, format_graph_xml


def _slog3_grey():
    return np.full(3, float(linear_to_slog3(0.18)))


def _logc4_chroma():
    return np.array(
        [
            float(linear_to_logc4(0.10)),
            float(linear_to_logc4(0.18)),
            float(linear_to_logc4(0.30)),
        ]
    )


def test_serial_slots_are_idt_exposure_wb_odt():
    g = SerialGraph(idt_id="arri_logc4_awg4")
    nodes = g.nodes()
    assert [n.index for n in nodes] == [1, 2, 3, 4]
    assert [n.name for n in nodes] == ["IDT", "Exposure", "WB", "ODT_Rec709"]
    assert [n.export_basename for n in nodes] == ["01_IDT", "02_Exposure", "03_WB", "04_ODT"]
    assert [s[2] for s in EXPORT_SLOTS] == ["01_IDT", "02_Exposure", "03_WB", "04_ODT"]
    assert len(nodes) == 4


def test_idt_is_not_bypassable():
    g = SerialGraph(idt_id="arri_logc4_awg4")
    assert g.node(1).bypassable is False
    assert g.node(1).enabled is True
    with pytest.raises(ValueError, match="not bypassable"):
        g.set_enabled(1, False)


def test_exposure_wb_and_odt_are_bypassable():
    g = SerialGraph(idt_id="arri_logc4_awg4", wb_enabled=True, odt_enabled=True)
    assert g.node(2).name == "Exposure"
    assert g.node(2).bypassable is True
    assert g.node(3).name == "WB"
    assert g.node(3).bypassable is True
    assert g.node(4).bypassable is True
    g.set_enabled(2, False)
    g.set_enabled(3, False)
    g.set_enabled(4, False)
    assert g.exposure_enabled is False
    assert g.wb_enabled is False
    assert g.odt_enabled is False
    assert g.node(2).enabled is False
    assert g.node(3).enabled is False
    assert g.node(4).enabled is False


def test_wb_bypass_matches_pipeline_no_bake():
    log = _logc4_chroma()
    g_off = SerialGraph(
        idt_id="arri_logc4_awg4", wb_enabled=False, wb_cct=3200.0, odt_enabled=True
    )
    g_on = SerialGraph(
        idt_id="arri_logc4_awg4", wb_enabled=True, wb_cct=3200.0, odt_enabled=True
    )
    off = g_off.apply(log)
    on = g_on.apply(log)
    direct_off = process_to_rec709(log, "arri_logc4_awg4", apply_wb=False)
    direct_on = process_to_rec709(
        log, "arri_logc4_awg4", apply_wb=True, cct=3200.0
    )
    np.testing.assert_allclose(off, direct_off, atol=1e-12)
    np.testing.assert_allclose(on, direct_on, atol=1e-12)
    assert not np.allclose(on, off, atol=1e-3)


def test_odt_off_leaves_aces2065_linear():
    log = _slog3_grey()
    g = SerialGraph(
        idt_id="sony_slog3_sgamut3", wb_enabled=False, odt_enabled=False
    )
    out = g.apply(log)
    aces = apply_idt(log, "sony_slog3_sgamut3")
    np.testing.assert_allclose(out, aces, atol=1e-12)
    # Scene-linear 18% grey in ACES2065-1, not Rec.709 OETF (~0.409).
    np.testing.assert_allclose(out, 0.18, atol=5e-4)
    rec = SerialGraph(
        idt_id="sony_slog3_sgamut3", wb_enabled=False, odt_enabled=True
    ).apply(log)
    assert not np.allclose(out, rec, atol=1e-2)


def test_apply_ap0_skips_preview_odt():
    """Write / linear-cache grade is AP0. Preview ``apply`` still runs ODT."""
    log = _slog3_grey()
    preview = SerialGraph(
        idt_id="sony_slog3_sgamut3", wb_enabled=False, odt_enabled=True
    )
    write = preview.apply_ap0(log)
    shown = preview.apply(log)
    aces = apply_idt(log, "sony_slog3_sgamut3")
    np.testing.assert_allclose(write, aces, atol=1e-12)
    np.testing.assert_allclose(write, 0.18, atol=5e-4)
    assert not np.allclose(write, shown, atol=1e-2)
    setup = preview.ap0_write_setup()
    assert setup[0] == 1.0
    assert setup[1] is None
    np.testing.assert_allclose(preview.apply_ap0(log, setup=setup), write, atol=1e-12)
    wb = SerialGraph(
        idt_id="sony_slog3_sgamut3",
        wb_enabled=True,
        wb_cct=3200.0,
        wb_source=WB_SOURCE_GREY,
        odt_enabled=True,
    )
    prepared = wb.apply_ap0(log, setup=wb.ap0_write_setup())
    np.testing.assert_allclose(prepared, wb.apply_ap0(log), atol=1e-12)
    with pytest.raises(ValueError, match="IDT"):
        SerialGraph(idt_id=None).apply_ap0(np.zeros(3))


def test_odt_defaults_off():
    g = SerialGraph(idt_id="arri_logc4_awg4")
    assert g.odt_enabled is False
    assert g.node(4).enabled is False


def test_wb_runs_in_ap0_not_on_acescct():
    log = _logc4_chroma()
    g = SerialGraph(
        idt_id="arri_logc4_awg4", wb_enabled=True, wb_cct=3200.0, odt_enabled=False
    )
    out = g.apply(log)
    aces = apply_idt(log, "arri_logc4_awg4")
    expected = apply_white_balance(aces, 3200.0, rgb_space="AP0")
    np.testing.assert_allclose(out, expected, atol=1e-12)
    enc = aces2065_to_acescct(aces)
    wrong = apply_white_balance(enc, 3200.0, rgb_space="AP0")
    assert not np.allclose(out, wrong, atol=1e-3)


def test_apply_requires_idt():
    g = SerialGraph(idt_id=None)
    with pytest.raises(ValueError, match="IDT"):
        g.apply(np.zeros(3))


def test_export_xml_reads_graph_bypass(tmp_path: Path):
    g = graph_from_export_args(
        idt_id="arri_logc4_awg4",
        cct=3200.0,
        tint=0.25,
        include_wb=False,
        odt_enabled=False,
    )
    xml = format_graph_xml(
        ["arri_logc4_awg4"], 3200.0, 0.25, include_wb=True, graph=g
    )
    assert 'name="Exposure"' in xml
    assert 'name="WB"' in xml
    assert 'name="ODT_Rec709"' in xml
    assert 'index="2"' in xml
    assert 'index="3"' in xml
    assert 'index="4"' in xml
    # Graph wins over include_wb=True: WB off = no bake.
    assert 'name="WB" type="Corrector" bypassable="true" enabled="false"' in xml
    assert 'name="ODT_Rec709" type="LUT_or_CST" bypassable="true" enabled="false"' in xml
    assert 'name="Exposure" type="Gain_1D" bypassable="true"' in xml
    written = export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], graph=g, lut_size=5
    )
    names = {p.name for p in written}
    assert "02_Exposure.cube" in names
    assert "02_Exposure.dctl" in names
    assert "03_WB.cube" in names
    assert "04_ODT_Rec709.cube" in names
    disk = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    assert 'enabled="false"' in disk
    assert "01_IDT" in disk and "02_Exposure" in disk and "03_WB" in disk and "04_ODT" in disk


def test_no_sat_or_unlisted_grade_nodes():
    g = SerialGraph(idt_id="arri_logc4_awg4")
    names = {n.name for n in g.nodes()}
    assert names == {"IDT", "Exposure", "WB", "ODT_Rec709"}
    assert "sat" not in {n.name.lower() for n in g.nodes()}
