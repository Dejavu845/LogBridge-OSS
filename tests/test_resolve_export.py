"""Resolve export is a bypassable WB node graph, not a prose sidecar."""

from pathlib import Path

import numpy as np
import pytest

from color.curves import linear_to_logc4, linear_to_slog3
from color.pipeline import process_to_rec709
from color.as_shot import WB_SOURCE_GREY
from color.batch import (
    REASON_PICK_LOG_GAMUT,
    REASON_PICK_PAIRED_IDT,
    BatchClip,
)
from color.graph import SerialGraph
from color.resolve_export import (
    REC709_CUBE_TITLE,
    REC709_PREVIEW_LABEL,
    RESOLVE_README_HONESTY,
    cdl_slope_offset_power,
    export_locked_resolve_bundle,
    export_resolve_bundle,
    format_ccc,
    format_cdl,
    format_dctl,
    format_dot,
    format_graph_xml,
    format_readme,
    idt_to_acescct,
    odt_cube_bytes,
    odt_from_acescct,
    wb_cube_bytes,
    wb_in_aces2065,
    wb_in_acescct,
)
from color.wb import apply_white_balance
from color.working_space import (
    ACESCCT_18_PERCENT,
    aces2065_to_acescct,
    acescct_to_aces2065,
)


def test_idt_acescct_18_percent_logc4():
    log = np.full(3, float(linear_to_logc4(0.18)))
    enc = idt_to_acescct(log, "arri_logc4_awg4")
    np.testing.assert_allclose(enc, ACESCCT_18_PERCENT, atol=5e-5)
    assert enc[0] == pytest.approx(enc[1], rel=1e-5)


def test_bypass_wb_idt_then_odt_matches_pipeline():
    log = np.full(3, float(linear_to_slog3(0.18)))
    enc = idt_to_acescct(log, "sony_slog3_sgamut3")
    rec = odt_from_acescct(enc)
    direct = process_to_rec709(log, "sony_slog3_sgamut3", apply_wb=False)
    np.testing.assert_allclose(rec, direct, atol=1e-6)
    assert rec[0] == pytest.approx(rec[1], rel=1e-5)


def test_wb_node_identity_at_d65_not_at_tungsten():
    grey = np.full(3, ACESCCT_18_PERCENT)
    a = wb_in_acescct(grey, 6504.0)
    np.testing.assert_allclose(a, grey, atol=2e-3)
    b = wb_in_acescct(grey, 3200.0)
    assert not np.allclose(b, grey, atol=1e-3)


def test_odt_has_no_wb_baked():
    """ODT of tungsten-shifted ACEScct grey is not the ODT of D65 grey — WB is separate."""
    grey = np.full(3, ACESCCT_18_PERCENT)
    shifted = wb_in_acescct(grey, 3200.0)
    assert not np.allclose(odt_from_acescct(shifted), odt_from_acescct(grey), atol=1e-3)


def test_cdl_slope_near_identity_at_6504k():
    slope, offset, power = cdl_slope_offset_power(6504.0)
    np.testing.assert_allclose(slope, 1.0, atol=5e-3)
    np.testing.assert_allclose(offset, 0.0, atol=0)
    np.testing.assert_allclose(power, 1.0, atol=0)


def test_cdl_slope_moves_at_3200k():
    s65, _, _ = cdl_slope_offset_power(6504.0)
    s32, _, _ = cdl_slope_offset_power(3200.0)
    assert not np.allclose(s32, s65, atol=1e-3)


def test_export_bundle_writes_graph_not_sidecar_only(tmp_path: Path):
    written = export_resolve_bundle(
        tmp_path,
        idt_ids=["arri_logc4_awg4", "sony_slog3_sgamut3"],
        cct=3200.0,
        tint=0.5,
        include_wb=True,
        lut_size=5,
    )
    names = {p.name for p in written}
    assert "README_RESOLVE.md" in names
    assert "graph.xml" in names
    assert "graph.dot" in names
    assert "02_Exposure.cube" in names
    assert "02_Exposure.dctl" in names
    assert "03_WB.cdl" in names
    assert "03_WB.ccc" in names
    assert "03_WB.dctl" in names
    assert "03_WB.cube" in names
    assert "04_ODT_Rec709.cube" in names
    assert "01_IDT_arri_logc4_awg4.cube" in names
    assert "01_IDT_sony_slog3_sgamut3.cube" in names
    assert len(written) >= 8


def test_xml_wb_node_is_bypassable(tmp_path: Path):
    export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], include_wb=True, lut_size=5
    )
    xml = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    assert 'name="WB"' in xml
    assert 'bypassable="true"' in xml
    assert "Bradford" in xml
    assert "ACEScct" in xml
    assert "ACES2065-1" in xml
    assert "03_WB.cube" in xml
    assert "03_WB.cdl" in xml
    off = format_graph_xml(["arri_logc4_awg4"], 5600.0, 0.0, include_wb=False)
    assert 'enabled="false"' in off
    assert 'bypassable="true"' in off


def test_dot_and_readme_explain_bypass():
    dot = format_dot(["arri_logc4_awg4"], 3200.0, 0.0, True)
    assert "WB" in dot
    assert "bypassable" in dot
    readme = format_readme(["arri_logc4_awg4"], 3200.0, 0.0, True)
    assert "bypass" in readme.lower()
    assert "ACEScct" in readme
    assert "ACES2065-1" in readme
    assert "implemented (unverified)" in readme
    assert "supported" not in readme.lower()
    assert "一键精准" not in readme
    assert "preview only" in readme.lower() or "preview" in readme.lower()
    assert "ACEScct deliverable" in readme or "ACEScct" in readme
    assert "most standard" not in readme.lower()
    assert "ACES2065-1" in readme
    # Default copy is ACES deliverable, not DWG.
    assert "default deliverable" not in readme.lower() or "ACES" in readme


def test_cdl_ccc_dctl_are_real_payloads():
    cdl = format_cdl(3200.0, 0.0)
    assert "<Slope>" in cdl
    assert "ColorDecisionList" in cdl
    ccc = format_ccc(3200.0, 0.0)
    assert "ColorCorrectionCollection" in ccc
    dctl = format_dctl(3200.0, 1.0)
    assert "acescct_decode" in dctl
    assert "bypass_wb" in dctl
    assert "cat_ap0" in dctl
    assert "ACES2065-1" in dctl
    assert "input_aces2065" in dctl
    assert "davinci" not in dctl.lower()
    assert "intermediate" not in dctl.lower()


def test_cubes_have_lattice(tmp_path: Path):
    export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], lut_size=5, cct=3200.0
    )
    for name in ("03_WB.cube", "04_ODT_Rec709.cube", "01_IDT_arri_logc4_awg4.cube"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "LUT_3D_SIZE 5" in text
        rgb_lines = [
            ln
            for ln in text.splitlines()
            if ln.strip()
            and not ln.startswith("#")
            and not ln.startswith("TITLE")
            and not ln.startswith("LUT_")
            and not ln.startswith("DOMAIN")
        ]
        assert len(rgb_lines) == 125


def test_skips_unknown_idt_ids(tmp_path: Path):
    written = export_resolve_bundle(
        tmp_path, idt_ids=["canon_clog2", "arri_logc4_awg4"], lut_size=5
    )
    names = {p.name for p in written}
    assert "01_IDT_arri_logc4_awg4.cube" in names
    assert not any("canon" in n for n in names)


def test_wb_acescct_wrap_is_ap0_cat_not_encoded_cat():
    """WB on ACEScct timeline decodes to ACES2065-1, CATs in AP0, encodes."""
    ap0 = np.array([0.10, 0.18, 0.30])
    enc = aces2065_to_acescct(ap0)
    wrapped = wb_in_acescct(enc, 3200.0)
    direct = aces2065_to_acescct(wb_in_aces2065(ap0, 3200.0))
    np.testing.assert_allclose(wrapped, direct, atol=1e-10)
    # CAT applied to ACEScct codes is a different (wrong) operator.
    wrong = apply_white_balance(enc, 3200.0, rgb_space="AP0")
    assert not np.allclose(wrapped, wrong, atol=1e-3)


def test_export_default_odt_off_acescct_deliverable(tmp_path: Path):
    written = export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], lut_size=5
    )
    xml = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    assert 'name="ODT_Rec709" type="LUT_or_CST" bypassable="true" enabled="false"' in xml
    assert "ACEScct deliverable" in xml
    assert "preview" in xml.lower()
    readme = (tmp_path / "README_RESOLVE.md").read_text(encoding="utf-8")
    assert "preview only" in readme.lower()
    assert "most standard" not in readme.lower()
    names = {p.name for p in written}
    assert "03_WB.dctl" in names
    dctl = (tmp_path / "03_WB.dctl").read_text(encoding="utf-8")
    assert "AP0" in dctl or "ACES2065-1" in dctl


def _cube_rgb_lines(text: str) -> list[str]:
    return [
        ln
        for ln in text.splitlines()
        if ln.strip()
        and not ln.startswith("#")
        and not ln.startswith("TITLE")
        and not ln.startswith("LUT_")
        and not ln.startswith("DOMAIN")
    ]


def _dctl_cat_is_identity(text: str, atol: float = 1e-8) -> bool:
    start = text.find("cat_ap0[9]")
    if start < 0:
        start = text.find("const float m[9]")
    assert start >= 0, "DCTL is missing the AP0 CAT matrix"
    brace = text.find("{", start)
    end = text.find("}", brace)
    nums = [
        float(tok.replace("f", ""))
        for tok in text[brace + 1 : end].replace("\n", " ").split(",")
        if tok.strip()
    ]
    assert len(nums) == 9
    ident = np.eye(3).reshape(-1)
    return bool(np.allclose(nums, ident, atol=atol))


def _assert_chengpian_not_a_deliverable_claim(text: str) -> None:
    cleaned = (
        text.replace("预览·非成片", "")
        .replace("不是全精度成片", "")
        .replace("不是整段成片", "")
        .replace("不是成片", "")
        .replace("成片预览关", "")
    )
    assert "成片" not in cleaned
    assert "精准" not in cleaned
    assert "一键还原" not in cleaned
    assert "一键校准" not in cleaned


def test_unlocked_never_exported(tmp_path: Path):
    clips = [
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
        BatchClip("stub.mov", idt="future", is_stub=True),
    ]
    dest = tmp_path / "empty_pkg"
    report = export_locked_resolve_bundle(dest, clips, lut_size=5)
    assert report.written == ()
    assert not dest.exists()
    assert report.skipped_reasons["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert report.skipped_reasons["empty.mov"] == REASON_PICK_LOG_GAMUT
    assert report.skipped_reasons["stub.mov"] == REASON_PICK_PAIRED_IDT


def test_locked_session_package_skips_pending(tmp_path: Path):
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3"),
        BatchClip("also.mov", idt="arri_logc4_awg4"),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
    ]
    dest = tmp_path / "pkg"
    report = export_locked_resolve_bundle(dest, clips, lut_size=5)
    names = set(report.written_names)
    assert "graph.xml" in names
    assert "03_WB.dctl" in names
    assert "04_ODT_Rec709.cube" in names
    assert "01_IDT_sony_slog3_sgamut3.cube" in names
    assert "01_IDT_arri_logc4_awg4.cube" in names
    assert not any("pending" in n for n in names)
    assert not any("empty" in n for n in names)
    assert report.skipped_reasons["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert report.skipped_reasons["empty.mov"] == REASON_PICK_LOG_GAMUT
    xml = (dest / "graph.xml").read_text(encoding="utf-8")
    assert "sony_slog3_sgamut3" in xml
    assert "arri_logc4_awg4" in xml
    assert "pending.mov" not in xml


def test_wb_off_has_no_baked_cat(tmp_path: Path):
    """WB off + grey-card CCT must not bake CAT(user) into DCTL/cube/CDL."""
    g = SerialGraph(
        idt_id="arri_logc4_awg4",
        wb_enabled=False,
        wb_cct=3200.0,
        wb_tint=0.4,
        wb_source=WB_SOURCE_GREY,
    )
    assert g.effective_wb_cct == pytest.approx(3200.0)
    export_resolve_bundle(tmp_path / "off", idt_ids=["arri_logc4_awg4"], graph=g, lut_size=5)
    off_dctl = (tmp_path / "off" / "03_WB.dctl").read_text(encoding="utf-8")
    off_cube = (tmp_path / "off" / "03_WB.cube").read_text(encoding="utf-8")
    off_cdl = (tmp_path / "off" / "03_WB.cdl").read_text(encoding="utf-8")
    xml = (tmp_path / "off" / "graph.xml").read_text(encoding="utf-8")
    assert 'name="WB" type="Corrector" bypassable="true" enabled="false"' in xml
    assert _dctl_cat_is_identity(off_dctl)
    identity_cube = wb_cube_bytes(None, 0.0, size=5)
    assert _cube_rgb_lines(off_cube) == _cube_rgb_lines(identity_cube)
    baked = wb_cube_bytes(3200.0, 0.4, size=5)
    assert _cube_rgb_lines(off_cube) != _cube_rgb_lines(baked)
    assert "<Slope>1.0000000000 1.0000000000 1.0000000000</Slope>" in off_cdl

    export_resolve_bundle(
        tmp_path / "flag",
        idt_ids=["arri_logc4_awg4"],
        include_wb=False,
        cct=3200.0,
        tint=0.4,
        lut_size=5,
    )
    flag_dctl = (tmp_path / "flag" / "03_WB.dctl").read_text(encoding="utf-8")
    assert _dctl_cat_is_identity(flag_dctl)
    xml_flag = (tmp_path / "flag" / "graph.xml").read_text(encoding="utf-8")
    assert 'enabled="false"' in xml_flag

    on = SerialGraph(
        idt_id="arri_logc4_awg4",
        wb_enabled=True,
        wb_cct=3200.0,
        wb_tint=0.4,
        wb_source=WB_SOURCE_GREY,
    )
    export_resolve_bundle(tmp_path / "on", idt_ids=["arri_logc4_awg4"], graph=on, lut_size=5)
    on_dctl = (tmp_path / "on" / "03_WB.dctl").read_text(encoding="utf-8")
    on_cube = (tmp_path / "on" / "03_WB.cube").read_text(encoding="utf-8")
    assert not _dctl_cat_is_identity(on_dctl)
    assert _cube_rgb_lines(on_cube) == _cube_rgb_lines(baked)


def test_readme_resolve_chinese_honesty_notes(tmp_path: Path):
    """高级 Resolve 导出 README：中文诚实说明，不改色彩数字。"""
    export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], include_wb=False, lut_size=5
    )
    readme = (tmp_path / "README_RESOLVE.md").read_text(encoding="utf-8")
    assert "709 预览" in readme
    assert "整段代理，不是全精度成片" in readme
    assert "已实现（未验证）" in readme
    assert RESOLVE_README_HONESTY.strip() in readme
    assert "identity / `enabled=false`" in readme
    assert "不烘焙 CAT" in readme
    assert "机内色温只填旋钮，默认 CAT 是单位阵。" in readme
    assert "用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。" in readme
    assert "灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。" in readme
    assert "机内白转到 D65" not in readme
    assert "精准" not in readme
    assert "一键还原" not in readme
    assert readme.index("诚实说明") < readme.index("Graph (serial nodes)")
    _assert_chengpian_not_a_deliverable_claim(readme)
    assert "DIY BT.709 OETF" in readme
    assert "不是** ACES OT / RRT" in readme
    assert "Not an ACES Output Transform" in readme
    cube = (tmp_path / "04_ODT_Rec709.cube").read_text(encoding="utf-8")
    assert REC709_PREVIEW_LABEL in cube
    assert "ACES Output Transform" not in cube.replace("Not an ACES Output Transform", "")
    assert "ACES OT" not in cube.replace("not ACES OT", "")
    _assert_chengpian_not_a_deliverable_claim(cube)

    root = Path(__file__).resolve().parents[1]
    swift = (root / "macos/LogBridge/LogBridge/Export/ResolveExporter.swift").read_text(
        encoding="utf-8"
    )
    note_fn = swift.split("static func exportNote")[1].split("static func export(")[0]
    readme_fn = swift.split("private static func readme")[1].split("/// Proxy sequence folder")[0]
    for blob in (note_fn, readme_fn):
        assert "709 预览" in blob
        assert "整段代理，不是全精度成片" in blob
        assert "已实现（未验证）" in blob
        assert "identity" in blob and "enabled=false" in blob
        assert "机内色温只填旋钮，默认 CAT 是单位阵。" in blob
        assert "CAT(user→D65)·inv(CAT(as→D65))" in blob
        assert "3200→5600 变暖" in blob
        assert "不猜 5600" in blob
        assert "机内白转到 D65" not in blob
        assert "精准" not in blob
        assert "一键还原" not in blob
        stripped = blob.replace("CAT(user→D65)·inv(CAT(as→D65))", "")
        assert "CAT(as→D65)" not in stripped
        _assert_chengpian_not_a_deliverable_claim(blob)


def test_709_cube_labeled_preview_not_aces_ot(tmp_path: Path):
    export_resolve_bundle(tmp_path, idt_ids=["arri_logc4_awg4"], lut_size=5)
    cube = (tmp_path / "04_ODT_Rec709.cube").read_text(encoding="utf-8")
    xml = (tmp_path / "graph.xml").read_text(encoding="utf-8")
    readme = (tmp_path / "README_RESOLVE.md").read_text(encoding="utf-8")
    assert REC709_PREVIEW_LABEL in cube
    assert REC709_CUBE_TITLE in cube
    assert "ACES Output Transform" not in cube.replace("Not an ACES Output Transform", "")
    assert "ACES OT" not in cube.replace("not ACES OT", "")
    assert "成片" not in cube.replace("预览·非成片", "")
    assert REC709_PREVIEW_LABEL in xml
    assert 'type="ACES_OT"' not in xml
    assert "Not an ACES Output Transform" in xml
    assert "预览·非成片" in xml
    assert REC709_PREVIEW_LABEL in readme
    assert "Not an ACES Output Transform" in readme
    generated = odt_cube_bytes(size=5)
    assert generated.splitlines()[0] == f'TITLE "{REC709_CUBE_TITLE}"'
    _assert_chengpian_not_a_deliverable_claim(cube)
    _assert_chengpian_not_a_deliverable_claim(xml)
    _assert_chengpian_not_a_deliverable_claim(readme)


def test_resolve_copy_has_no_precision_or_chengpian_claims(tmp_path: Path):
    written = export_resolve_bundle(
        tmp_path, idt_ids=["arri_logc4_awg4"], include_wb=False, lut_size=5
    )
    blob = "\n".join(p.read_text(encoding="utf-8") for p in written)
    _assert_chengpian_not_a_deliverable_claim(blob)
    assert "implemented (unverified)" in blob.lower() or "已实现（未验证）" in blob
    root = Path(__file__).resolve().parents[1]
    swift = (root / "macos/LogBridge/LogBridge/Export/ResolveExporter.swift").read_text(
        encoding="utf-8"
    )
    clip = (root / "macos/LogBridge/LogBridge/Models/Clip.swift").read_text(encoding="utf-8")
    idt_fn = swift.split("func uniqueImplementedIDTs")[1].split("ap0ToXYZ")[0]
    assert "hasLockedPair" in idt_fn
    assert "includeWBNode" in swift
    assert "matrixCCT = nil" in swift
    assert REC709_PREVIEW_LABEL in swift
    assert "not ACES OT" in swift
    export_fn = clip.split("func exportResolve()")[1]
    assert "先选择成对 IDT" in export_fn
    assert "先选择 Log 与色域" in export_fn
    _assert_chengpian_not_a_deliverable_claim(
        swift.split("enum ResolveExporter")[1].split("Proxy sequence folder")[0]
    )
    _assert_chengpian_not_a_deliverable_claim(export_fn)

