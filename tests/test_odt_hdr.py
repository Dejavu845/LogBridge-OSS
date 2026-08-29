"""M2-start: Rec.2100 HLG/PQ ODT paths are declared; Rec.709 stays preview-only.

HLG/PQ use ACES Output Transform / BT.2100 OCIO BuiltinTransform names
(or config-aces aliases). No homemade HLG/PQ curve. Unverified. Not supported.
"""

from pathlib import Path

import numpy as np
import pytest

from color.curves import linear_to_slog3
from color.graph import (
    GRAPH_NODES,
    ODT_CHOICES,
    ODT_DEFAULT,
    ODT_HLG,
    ODT_OFF,
    ODT_PQ,
    ODT_REC709,
    SerialGraph,
)
from color.odt import (
    ACES_OT_HLG_1_3,
    ACES_OT_HLG_2_0,
    ACES_OT_PQ_1_3,
    ACES_OT_PQ_2_0,
    CONFIG_ACES_HLG,
    CONFIG_ACES_PQ,
    CS_REC2100_HLG,
    CS_REC2100_PQ,
    DISPLAY_REC2100_HLG,
    DISPLAY_REC2100_PQ,
    HDR_ODTS,
    HDRODTRequiresOCIO,
    apply_hdr_odt,
    apply_odt,
    declared_hdr_styles,
    odt_descriptor,
)
from color.ocio_builtins import ODT_BUILTINS, ocio_available
from color.pipeline import apply_idt, process_to_rec709
from color.resolve_export import format_graph_xml

ROOT = Path(__file__).resolve().parents[1]


def _slog3_grey():
    return np.full(3, float(linear_to_slog3(0.18)))


def test_odt_choices_declare_off_709_hlg_pq():
    assert ODT_CHOICES == (ODT_OFF, ODT_REC709, ODT_HLG, ODT_PQ)
    assert ODT_DEFAULT == ODT_OFF
    assert HDR_ODTS == (ODT_HLG, ODT_PQ)
    g = SerialGraph(idt_id="sony_slog3_sgamut3")
    assert g.odt == ODT_OFF
    assert g.odt_enabled is False
    assert g.node(4).enabled is False
    assert g.node(4).name == "ODT_Rec709"


def test_rec709_remains_preview_only():
    desc = odt_descriptor(ODT_REC709)
    assert desc["preview_only"] is True
    assert desc["role"] == "preview"
    assert desc["supported"] is False
    assert desc["status"] == "implemented (unverified)"
    assert "preview" in desc["via"].lower() or desc["preview_only"]
    # Slot identity is the four-node graph (IDT → Exposure → WB → ODT).
    assert GRAPH_NODES == ("IDT", "Exposure", "WB", "ODT_Rec709")
    g = SerialGraph(idt_id="sony_slog3_sgamut3", odt_enabled=True)
    assert g.odt == ODT_REC709
    log = _slog3_grey()
    rec = g.apply(log)
    direct = process_to_rec709(log, "sony_slog3_sgamut3", apply_wb=False)
    np.testing.assert_allclose(rec, direct, atol=1e-10)
    # Off still leaves ACES2065-1 (deliverable), not Rec.709.
    off = SerialGraph(idt_id="sony_slog3_sgamut3", odt=ODT_OFF).apply(log)
    aces = apply_idt(log, "sony_slog3_sgamut3")
    np.testing.assert_allclose(off, aces, atol=1e-12)
    assert not np.allclose(off, rec, atol=1e-2)


def test_hlg_pq_paths_are_aces_ot_bt2100():
    hlg = odt_descriptor(ODT_HLG)
    pq = odt_descriptor(ODT_PQ)
    for desc, name, cs, cfg, ot, disp in (
        (hlg, "Rec.2100 HLG", CS_REC2100_HLG, CONFIG_ACES_HLG, ACES_OT_HLG_1_3, DISPLAY_REC2100_HLG),
        (pq, "Rec.2100 PQ", CS_REC2100_PQ, CONFIG_ACES_PQ, ACES_OT_PQ_1_3, DISPLAY_REC2100_PQ),
    ):
        assert desc["name"] == name
        assert desc["colorspace"] == cs
        assert desc["config_aces"] == cfg
        assert desc["via"] == "ACES Output Transform / BT.2100"
        assert desc["status"] == "implemented (unverified)"
        assert desc["supported"] is False
        assert desc["preview_only"] is False
        assert desc["role"] == "hdr_output"
        assert ot in desc["ocio_styles"]
        assert disp in desc["ocio_styles"]
        assert "ACES-OUTPUT" in ot
        assert "BT.2100" in name or "Rec.2100" in name
    assert ACES_OT_HLG_2_0 in hlg["ocio_styles_aces2"]
    assert ACES_OT_PQ_2_0 in pq["ocio_styles_aces2"]
    assert ODT_BUILTINS["hlg"] == declared_hdr_styles(ODT_HLG)
    assert ODT_BUILTINS["pq"] == declared_hdr_styles(ODT_PQ)


def test_no_homemade_hlg_pq_curve_in_color_package():
    """Do not invent a DIY Rec.2100 transfer like the Rec.709 OETF."""
    forbidden = (
        "def hlg_oetf",
        "def hlg_eotf",
        "def pq_oetf",
        "def pq_eotf",
        "def st2084",
        "def bt2100_hlg",
        "def bt2100_pq",
        "def homemade_hlg",
        "def homemade_pq",
    )
    blob = ""
    for path in (ROOT / "color").glob("*.py"):
        blob += path.read_text(encoding="utf-8")
    for token in forbidden:
        assert token not in blob, token
    # Rec.709 DIY OETF is allowed and stays preview-only.
    assert "def rec709_oetf" in (ROOT / "color" / "rec709.py").read_text(encoding="utf-8")


def test_hdr_apply_requires_ocio_no_diy_fallback():
    log = _slog3_grey()
    aces = apply_idt(log, "sony_slog3_sgamut3")
    if ocio_available():
        out_hlg = apply_hdr_odt(aces, ODT_HLG)
        out_pq = apply_hdr_odt(aces, ODT_PQ)
        assert out_hlg.shape == aces.shape
        assert out_pq.shape == aces.shape
        assert not np.allclose(out_hlg, aces, atol=1e-3)
        assert not np.allclose(out_pq, aces, atol=1e-3)
    else:
        with pytest.raises(HDRODTRequiresOCIO, match="ACES Output Transform"):
            apply_hdr_odt(aces, ODT_HLG)
        with pytest.raises(HDRODTRequiresOCIO, match="ACES Output Transform"):
            apply_odt(aces, ODT_PQ)
        with pytest.raises(HDRODTRequiresOCIO, match="BT.2100"):
            SerialGraph(idt_id="sony_slog3_sgamut3", odt=ODT_HLG).apply(log)
        with pytest.raises(HDRODTRequiresOCIO, match="No homemade"):
            SerialGraph(idt_id="sony_slog3_sgamut3", odt=ODT_PQ).apply(log)


def test_graph_selects_hlg_pq_without_extra_grade_nodes():
    g = SerialGraph(idt_id="arri_logc4_awg4", odt=ODT_HLG)
    assert g.odt_enabled is True
    assert g.node(4).name == "ODT_Rec2100_HLG"
    assert g.node(4).bypassable is True
    names = {n.name for n in g.nodes()}
    assert names == {"IDT", "Exposure", "WB", "ODT_Rec2100_HLG"}
    g.set_odt(ODT_PQ)
    assert g.node(4).name == "ODT_Rec2100_PQ"
    g.set_odt(ODT_OFF)
    assert g.odt_enabled is False
    assert g.node(4).name == "ODT_Rec709"
    assert len(g.nodes()) == 4


def test_ocio_config_names_aces_ot_bt2100():
    text = (ROOT / "ocio" / "config.ocio").read_text(encoding="utf-8")
    assert "name: Rec.2100-HLG" in text
    assert "name: Rec.2100-PQ" in text
    assert ACES_OT_HLG_1_3 in text
    assert ACES_OT_PQ_1_3 in text
    assert DISPLAY_REC2100_HLG in text
    assert DISPLAY_REC2100_PQ in text
    assert CONFIG_ACES_HLG in text
    assert CONFIG_ACES_PQ in text
    assert "ACES Output Transform" in text
    assert "No homemade HLG curve" in text
    assert "No homemade PQ" in text
    assert "implemented (unverified)" in text.lower() or "Implemented (unverified)" in text
    assert "Not supported" in text
    # Rec.709 stays the preview DIY path.
    assert "name: Rec.709" in text
    assert "lin_to_Rec709_oetf.spi1d" in text
    # No homemade HDR LUTs.
    luts = ROOT / "ocio" / "luts"
    assert not (luts / "lin_to_HLG.spi1d").is_file()
    assert not (luts / "lin_to_PQ.spi1d").is_file()
    assert not (luts / "lin_to_ST2084.spi1d").is_file()


def test_export_xml_declares_hdr_aces_ot():
    xml_hlg = format_graph_xml(
        ["arri_logc4_awg4"], 6504.0, 0.0, include_wb=False, odt=ODT_HLG
    )
    assert 'name="ODT_Rec2100_HLG"' in xml_hlg
    assert 'type="ACES_OT"' in xml_hlg
    assert ACES_OT_HLG_1_3 in xml_hlg
    assert DISPLAY_REC2100_HLG in xml_hlg
    assert CONFIG_ACES_HLG in xml_hlg
    assert "implemented (unverified)" in xml_hlg
    assert "Not supported" in xml_hlg
    xml_pq = format_graph_xml(
        ["arri_logc4_awg4"], 6504.0, 0.0, include_wb=False, odt=ODT_PQ
    )
    assert 'name="ODT_Rec2100_PQ"' in xml_pq
    assert ACES_OT_PQ_1_3 in xml_pq
    assert DISPLAY_REC2100_PQ in xml_pq
    # Default / Rec.709 still preview-only in XML.
    xml_off = format_graph_xml(
        ["arri_logc4_awg4"], 6504.0, 0.0, include_wb=False
    )
    assert 'name="ODT_Rec709" type="LUT_or_CST" bypassable="true" enabled="false"' in xml_off
    assert "preview ODT only" in xml_off


def test_docs_hdr_ot_unverified_not_supported():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    blob = readme + "\n" + acceptance
    assert "ACES Output Transform" in blob or "ACES/BT.2100" in blob
    assert "Rec.2100 HLG" in blob
    assert "Rec.2100 PQ" in blob
    assert "BT.2100" in blob
    assert "implemented (unverified)" in blob
    assert "一键精准" in blob  # named as forbidden
    # Must not claim HDR is supported or a one-click accurate path.
    assert "HLG/PQ supported" not in blob.lower()
    assert "一键精准" in blob
    assert "ColorSync" in blob
    assert "itur_2100" in blob
    assert "HDR 预览建不出" in blob
    assert "屏幕无 EDR，预览被压到 SDR" in blob


def test_macos_hdr_preview_is_colorsync_not_aces_ot():
    """App preview is ColorSync itur_2100. Not homemade. Not 709 fallback."""
    hdr = (ROOT / "macos/LogBridge/LogBridge/Color/HDRPreview.swift").read_text(
        encoding="utf-8"
    )
    engine = (ROOT / "macos/LogBridge/LogBridge/Preview/PreviewEngine.swift").read_text(
        encoding="utf-8"
    )
    assert "itur_2100_HLG" in hdr
    assert "itur_2100_PQ" in hdr
    assert "ColorSync" in hdr
    assert "Not an ACES Output Transform" in hdr
    assert "No OCIO" in hdr
    assert "encodeFromGradedAP0" in engine
    assert "PreviewColor.applyODT" in engine
    hdr_branch = (
        engine.split("func renderODTFromGraded")[1]
        .split("func publishODTOnly")[0]
        .split("} else if graph.odt.isHDR")[1]
        .split('note = "709 预览关"')[0]
    )
    assert "applyODT" not in hdr_branch
    assert "u8(" not in hdr_branch
    assert "rec709OETF" not in hdr_branch
    assert "HDR 预览建不出" in hdr_branch
    for token in (
        "def hlg_oetf",
        "0.17883277",
        "78.84375",
        "homemade_hlg",
        "ACES-OUTPUT",
    ):
        assert token not in hdr, token
