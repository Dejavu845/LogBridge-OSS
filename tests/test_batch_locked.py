"""Locked-IDT batch: walk locked clips only. Unlocked stay listed."""

import inspect
import struct
from pathlib import Path

import numpy as np
import pytest

from color.as_shot import WB_SOURCE_AS_SHOT, WB_SOURCE_ESTIMATE, WB_SOURCE_GREY
from color.batch import (
    ADVANCED_DISCLOSURE,
    ADVANCED_DISCLOSURE_HELP,
    ADVANCED_EXPORT_HELP,
    BYTES_PER_EXR_PIXEL,
    CANCEL_BUTTON,
    CANCELLED_NOTE,
    CANCELLED_STATUS_TEMPLATE,
    CONSERVATIVE_FPS,
    CONSERVATIVE_HEIGHT,
    CONSERVATIVE_SECONDS,
    CONSERVATIVE_WIDTH,
    DELIVERABLE_DIR_SUFFIX,
    DELIVERABLE_SUFFIX,
    DISK_ESTIMATE_ASSUMPTION,
    DISK_SHORT_STATUS,
    DISK_SHORT_STATUS_TEMPLATE,
    FOLDER_PICKER_MESSAGE,
    FAILED_BUCKET,
    FRAME_MISMATCH_CHIP,
    HONEST_PROXY_NOTE,
    LAST_EXPORT_DIRECTORY_KEY,
    MISSING_DURATION_CHIP,
    MISSING_FPS_CHIP,
    PROCESS_BUTTON,
    PROCESS_BUTTON_HELP,
    BATCH_SUMMARY_TEMPLATE,
    PROCESSED_STATUS_TEMPLATE,
    SKIPPED_BUCKET,
    PROGRESS_PREFIX,
    REASON_PICK_LOG_GAMUT,
    REASON_PICK_PAIRED_IDT,
    REVEAL_IN_FINDER,
    WRITTEN_CHIP,
    WRITE_FAILED_CHIP,
    WRITE_LONG_EDGE_CEILING,
    WRITE_OVERSIZE_CHIP,
    DECODE_FAILED_CHIP,
    BatchClip,
    count_proxy_exrs,
    expected_source_frames,
    frames_count_matches,
    verify_locked_proxy_sequence,
    cancelled_status_text,
    confirm_auto_wb,
    deliverable_dir_name,
    deliverable_name,
    batch_summary_text,
    dest_has_space,
    estimate_chip_lit,
    estimate_locked_proxy_bytes,
    folder_picker_message_with_estimate,
    has_locked_idt,
    never_guess_cct,
    plan_locked_batch,
    process_locked_names,
    process_locked_writes,
    processed_status_text,
    progress_text,
    propose_auto_wb,
    sequence_frame_name,
    short_export_chip,
    short_export_path,
    sidebar_export_chips,
    sidebar_status_chip,
    clip_sequence_reveal_path,
    require_write_source_pixels,
    skip_reason,
    ycbcr_to_preview_u8,
    ycbcr_to_rgb_float,
    preview_u8_promoted_float,
    MISSING_YCBCR_TAGS_CHIP,
    parse_source_ycbcr_matrix,
    parse_source_ycbcr_range,
    require_source_ycbcr_tags,
    ycbcr_range_offsets,
)
from color.curves import linear_to_slog3
from color.exr_write import (
    ACES2065_1_CHROMATICITIES,
    read_exr_attributes,
    read_exr_chromaticities,
    read_rgb_exr,
    write_rgb_exr,
)
from color.graph import SerialGraph

# SMPTE ST 2065-1 / ACES AP0 + ACES white. Tests fail if D65 or AP1 is written.
ST2065_1_CHROMATICITIES = (
    0.73470,
    0.26530,
    0.00000,
    1.00000,
    0.00010,
    -0.07700,
    0.32168,
    0.33767,
)
D65_XY = (0.3127, 0.329)
AP1_PRIMARIES_XY = (0.713, 0.293, 0.165, 0.830, 0.128, 0.044)

ROOT = Path(__file__).resolve().parents[1]
SWIFT_ROOT = ROOT / "macos"
CLIP = SWIFT_ROOT / "LogBridge/LogBridge/Models/Clip.swift"
CONTENT = SWIFT_ROOT / "LogBridge/LogBridge/ContentView.swift"
INSPECTOR = SWIFT_ROOT / "LogBridge/LogBridge/Views/InspectorView.swift"
SIDEBAR = SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _all_swift() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SWIFT_ROOT.rglob("*.swift"))


def test_batch_walks_locked_only_skips_unlocked():
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
        BatchClip("stub.mov", idt="future", is_stub=True),
    ]
    plan = plan_locked_batch(clips)
    assert process_locked_names(clips) == ["locked.mov"]
    assert plan.locked_count == 1
    assert plan.pending_count == 3
    assert plan.lock_status_text == "1 条已锁定 / 3 条待选"
    assert plan.shows_process_button is True
    reasons = {c.name: reason for c, reason in plan.skipped}
    assert reasons["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert reasons["empty.mov"] == REASON_PICK_LOG_GAMUT
    assert reasons["stub.mov"] == REASON_PICK_PAIRED_IDT
    assert skip_reason(clips[0]) is None
    assert has_locked_idt(clips[1]) is False


def test_no_process_button_when_nothing_locked():
    clips = [
        BatchClip("a.mov"),
        BatchClip("b.mov", detected_curve="C-Log2", needs_user_picker=True),
    ]
    plan = plan_locked_batch(clips)
    assert plan.shows_process_button is False
    assert process_locked_names(clips) == []
    assert plan.lock_status_text == "0 条已锁定 / 2 条待选"


def test_needs_picker_even_with_idt_is_skipped():
    clip = BatchClip("half.mov", idt="sony_slog3_sgamut3", needs_user_picker=True)
    assert has_locked_idt(clip) is False
    assert skip_reason(clip) == REASON_PICK_PAIRED_IDT


def test_estimate_chip_lights_only_after_confirm():
    state = {"wb_source": WB_SOURCE_AS_SHOT, "wb_cct": 3200.0, "auto_wb_cct": None}
    proposed = propose_auto_wb(state, 4100.0, 0.2)
    assert proposed["auto_wb_cct"] == 4100.0
    assert proposed["wb_source"] == WB_SOURCE_AS_SHOT
    assert proposed["wb_cct"] == 3200.0
    assert estimate_chip_lit(proposed["wb_source"]) is False
    confirmed = confirm_auto_wb(proposed)
    assert confirmed["wb_source"] == WB_SOURCE_ESTIMATE
    assert confirmed["wb_cct"] == 4100.0
    assert estimate_chip_lit(confirmed["wb_source"]) is True


def test_grey_card_overrides_estimate_and_no_5600_guess():
    grey = {
        "wb_source": WB_SOURCE_GREY,
        "wb_cct": 4800.0,
        "auto_wb_cct": 4100.0,
    }
    assert confirm_auto_wb(grey)["wb_source"] == WB_SOURCE_GREY
    assert confirm_auto_wb(grey)["wb_cct"] == 4800.0
    empty = propose_auto_wb({"wb_source": WB_SOURCE_AS_SHOT}, None)
    assert empty["auto_wb_cct"] is None
    assert confirm_auto_wb(empty)["wb_source"] == WB_SOURCE_AS_SHOT
    assert "wb_cct" not in confirm_auto_wb(empty)
    assert never_guess_cct(None) is True
    assert never_guess_cct(5600) is False


def test_swift_mirrors_locked_batch_and_one_button():
    clip = _read(CLIP)
    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    sidebar = _read(SIDEBAR)
    swift = _all_swift()
    assert "func processLockedClips()" in clip
    assert "processLockedClips()" in clip.split("func processSelected()")[1]
    assert "processLockedClips()" in clip.split("func applyGraph()")[1]
    assert "lockedClipCount" in clip
    assert "lockStatusText" in clip
    assert "showsProcessLockedButton" in clip
    assert "processSkipReason" in clip
    assert "先选择成对 IDT" in clip
    assert "先选择 Log 与色域" in clip
    assert "条已锁定" in clip and "条待选" in clip
    assert "处理已锁定片段" in content
    assert "showsProcessLockedButton" in content
    assert "ProcessLockedBar" in content
    assert content.count("处理已锁定片段") >= 1
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "showsBatchSummary" in bar
    assert "showsBatchSummary" in clip
    assert SKIPPED_BUCKET in clip
    assert FAILED_BUCKET in clip
    assert 'Button("处理已锁定片段")' not in content.split("struct StatusBar")[1]
    assert 'Button("导出 ACEScct / EXR")' in content.split("struct AdvancedPanel")[1]
    assert ADVANCED_DISCLOSURE in content
    assert 'DisclosureGroup("高级"' in content
    assert "showAdvanced = false" in content
    assert "PairedIDTBar" in content
    assert "InspectorView" in content
    assert PROCESS_BUTTON in swift
    assert "机内 as-shot" in inspector
    assert "白平衡（估计）" in inspector
    assert "灰卡" in inspector
    assert "on: session.graph.wbSource == .estimate" in inspector
    assert "proposeAutoWB" in inspector
    assert "确认估计" in inspector
    assert "processSkipReason" in sidebar
    assert "exportChip" in sidebar
    assert WRITTEN_CHIP in sidebar
    assert "一键还原" not in content or "Never 一键还原" in content


def test_inspector_is_exposure_and_wb_only():
    inspector = _read(INSPECTOR)
    content = _read(CONTENT)
    assert "ExposureInspector" in inspector
    assert "WBInspector" in inspector
    assert "struct InspectorView" in inspector
    body = inspector.split("struct InspectorView")[1].split("struct WBInspector")[0]
    assert "ExposureInspector" in body
    assert "WBInspector" in body
    assert "IDTInspector" not in body
    assert "ODTInspector" not in body
    advanced = content.split("struct AdvancedPanel")[1].split("struct SplitPreview")[0]
    assert "NodeStripView" in advanced
    assert "导出 ACEScct / EXR" in advanced
    assert "ODTInspector" not in advanced
    assert "PairedIDTBar" not in advanced
    assert "成对 IDT" not in advanced


def _slog3_grey(shape=(2, 2, 3)):
    return np.full(shape, float(linear_to_slog3(0.18)), dtype=np.float64)


def test_unlocked_never_write_locked_writes_and_counter(tmp_path: Path):
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
        BatchClip("stub.mov", idt="future", is_stub=True),
    ]
    grey = _slog3_grey()
    frames = {c.name: grey for c in clips}
    called: list[str] = []

    def spy(path: Path, rgb) -> None:
        called.append(Path(path).name)
        path.write_bytes(b"x")

    report = process_locked_writes(clips, tmp_path, frames=frames, write_fn=spy)
    assert called == [sequence_frame_name(0)]
    assert report.processed_count == 1
    assert report.skipped_count == 3
    assert "1 条已写出代理" in report.processed_status_text
    assert "3 条待选跳过" in report.processed_status_text
    assert "0 条失败" in report.processed_status_text
    assert batch_summary_text(1, 3, 0, dest=tmp_path) == report.processed_status_text
    assert short_export_path(tmp_path) in report.processed_status_text
    assert (tmp_path / deliverable_name("locked.mov")).is_file()
    assert not (tmp_path / deliverable_dir_name("pending.mov")).exists()
    assert not (tmp_path / deliverable_dir_name("empty.mov")).exists()
    assert not (tmp_path / deliverable_dir_name("stub.mov")).exists()
    assert list(tmp_path.glob("*" + DELIVERABLE_DIR_SUFFIX)) == [
        tmp_path / deliverable_dir_name("locked.mov")
    ]


def test_locked_exr_is_aces2065_and_mixed_bin_writes(tmp_path: Path):
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
    ]
    report = process_locked_writes(
        clips, tmp_path, frames={"locked.mov": _slog3_grey(), "pending.mov": _slog3_grey()}
    )
    assert report.processed_count == 1
    assert "1 条已写出代理" in report.processed_status_text
    path = tmp_path / deliverable_name("locked.mov")
    assert path.is_file()
    rgb = read_rgb_exr(path)
    assert rgb.shape == (2, 2, 3)
    np.testing.assert_allclose(rgb[0, 0], 0.18, atol=5e-3)
    _assert_st2065_1_chromaticities_on_disk(path)
    assert not (tmp_path / deliverable_dir_name("pending.mov")).exists()


def test_exr_writers_lock_st2065_1_ap0_chromaticities(tmp_path: Path):
    """Both write paths emit ST 2065-1 AP0 + ACES white. Not D65, not AP1."""
    assert ACES2065_1_CHROMATICITIES == ST2065_1_CHROMATICITIES
    rgb = np.array([[[0.18, 0.09, 0.04]]], dtype=np.float32)
    direct = tmp_path / "direct.exr"
    write_rgb_exr(direct, rgb)
    _assert_st2065_1_chromaticities_on_disk(direct)
    np.testing.assert_allclose(read_rgb_exr(direct)[0, 0], rgb[0, 0])

    clips = [BatchClip("clip.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)]
    report = process_locked_writes(
        clips, tmp_path / "batch", frames={"clip.mov": _slog3_grey()}
    )
    seq = Path(report.written[0].path)
    assert seq.name.endswith("_ACES2065-1_proxy")
    _assert_st2065_1_chromaticities_on_disk(seq / sequence_frame_name(0))

    exporter = _read(SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift")
    _assert_swift_exr_writer_chromaticities(exporter)


def test_wb_off_identity_still_writes_exr(tmp_path: Path):
    """Existing WB toggle: off / identity must still write. Never required."""
    clips = [BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)]
    frames = {"locked.mov": _slog3_grey()}
    off = SerialGraph(wb_enabled=False, wb_cct=None)
    assert off.wb_enabled is False
    report = process_locked_writes(clips, tmp_path / "off", frames=frames, graph=off)
    assert report.processed_count == 1
    assert len(report.written) == 1
    off_rgb = read_rgb_exr(Path(report.written[0].path) / sequence_frame_name(0))
    on = SerialGraph(wb_enabled=True, wb_cct=3200.0, wb_source=WB_SOURCE_GREY)
    report_on = process_locked_writes(clips, tmp_path / "on", frames=frames, graph=on)
    assert report_on.processed_count == 1
    on_rgb = read_rgb_exr(Path(report_on.written[0].path) / sequence_frame_name(0))
    assert not np.allclose(on_rgb, off_rgb, atol=1e-3)
    assert HONEST_PROXY_NOTE in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)


def test_write_error_counts_as_processed_no_file(tmp_path: Path):
    clips = [BatchClip("locked.mov", idt="sony_slog3_sgamut3")]
    report = process_locked_writes(clips, tmp_path, frames={})
    assert report.processed_count == 1
    assert report.written == ()
    assert report.errors[0].name == "locked.mov"
    assert "0 条已写出代理" in report.processed_status_text
    assert "1 条失败" in report.processed_status_text
    assert FAILED_BUCKET in report.processed_status_text
    assert DECODE_FAILED_CHIP in report.processed_status_text
    assert list(tmp_path.glob("*.exr")) == []
    assert list(tmp_path.glob("*" + DELIVERABLE_DIR_SUFFIX)) == []


def test_swift_process_writes_exr_and_counter_is_writes():
    clip = _read(CLIP)
    content = _read(CONTENT)
    exporter = _read(SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift")
    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    body = clip.split("func processLockedClips()")[1].split("func processSelected()")[0]
    assert "writeLockedDeliverables" in body
    assert "条已写出代理" in body or "条已写出代理" in clip.split("func writeLockedDeliverables")[1]
    write_body = clip.split("func writeLockedDeliverables")[1].split("func exportLockedEXR")[0]
    assert "batchSummaryText" in write_body
    assert "let wrote = written.count" in write_body
    assert "processed = locked.count" not in write_body
    assert HONEST_PROXY_NOTE in write_body
    assert HONEST_PROXY_NOTE in body
    _assert_chengpian_not_a_deliverable_claim(write_body)
    _assert_chengpian_not_a_deliverable_claim(body)
    assert "exportLockedEXR" in clip
    assert "writeACES2065EXR" in clip
    assert "exportGradedAP0Sequence" in clip
    _assert_swift_exr_writer_chromaticities(exporter)
    assert "_ACES2065-1_proxy" in exporter
    assert "frame_%06d.exr" in exporter
    assert "_proxy_frame0.exr" not in exporter
    assert "ACES2065-1.exr\"" not in exporter
    assert "exportGradedAP0" in engine
    assert "exportGradedAP0Sequence" in engine
    assert "decodeMovieAllFrames" in engine
    assert "while let sample = output.copyNextSampleBuffer()" in engine
    _assert_export_sequence_tries_10bit_first(engine)
    _assert_export_decode_is_source_ycbcr_float(engine)
    grade = engine.split("func gradeAP0")[1].split("func exportGradedAP0(")[0]
    assert "applyODT" not in grade
    assert "if graph.wbEnabled" in grade
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split("func decodeAllSourceFrames")[0]
    assert "applyODT" not in export_seq
    assert "gradeAP0" in export_seq
    assert "extractRGB" not in export_seq
    assert "decodeDownscaled" not in export_seq
    assert "decodeAllSourceFrames" in engine.split("func exportGradedAP0Sequence")[1]
    export_body = clip.split("func exportLockedEXR")[1].split("func processSelected()")[0]
    assert "writeACES2065EXR" in export_body
    assert "sequenceFrameURL" in export_body
    assert "AVAssetExport" not in export_body
    assert "AVAssetWriter" not in export_body
    can = clip.split("var canProcess")[1].split("var canProcessSelected")[0]
    assert "pendingPickerCount == 0" not in can
    assert "lockedClipCount" in can
    export = clip.split("func exportResolve()")[1]
    assert "lockedClips" in export.split("panel.begin")[0]
    assert "clips: locked" in export or "clips: lockedClips" in export
    assert "先选择成对 IDT" in export
    assert "先选择 Log 与色域" in export
    assert "hasLockedPair" in exporter.split("func uniqueImplementedIDTs")[1]
    assert "matrixCCT = nil" in exporter
    assert "709 预览" in exporter
    assert "not ACES OT" in exporter
    assert HONEST_PROXY_NOTE in content
    assert "不是 ACEScct" in content
    assert ADVANCED_EXPORT_HELP in content
    assert ADVANCED_DISCLOSURE_HELP in content
    assert "不必全部锁定" in content
    assert "Does not require the whole bin" not in content
    _assert_chengpian_not_a_deliverable_claim(content)


def _assert_export_sequence_tries_10bit_first(engine: str) -> None:
    """Export sequence prefers 10-bit Y′CbCr; preview/scrub stays 8-bit-first."""
    export_decode = engine.split("func decodeMovieAllFrames")[1].split(
        "func readAllYpCbCrFrames"
    )[0]
    preview_decode = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func readFirstYpCbCrFrame"
    )[0]
    ten = "kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange"
    eight_420 = "kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange"
    eight_422 = "kCVPixelFormatType_422YpCbCr8"
    assert export_decode.index(ten) < export_decode.index(eight_420)
    assert export_decode.index(eight_420) < export_decode.index(eight_422)
    assert preview_decode.index(eight_420) < preview_decode.index(eight_422)
    assert preview_decode.index(eight_422) < preview_decode.index(ten)
    assert "copyCGImage(" not in export_decode
    assert "AVVideoColorPropertiesKey:" not in export_decode
    assert HONEST_PROXY_NOTE in engine


def _assert_export_decode_is_source_ycbcr_float(engine: str) -> None:
    """Write path is source Y′CbCr → float, not preview 8-bit promoted."""
    export_first = engine.split("func exportGradedAP0(")[1].split(
        "func exportGradedAP0Sequence"
    )[0]
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    movie = engine.split("func decodeMovieAllFrames")[1].split(
        "func linearAP0Frame"
    )[0]
    ten_src = engine.split("func rgbFloatFromLogPixelBuffer")[1].split(
        "kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange"
    )[1].split("} else {")[0]
    preview_cg = engine.split("func cgImageFromLogPixelBuffer")[1].split(
        "func writeMatrixRGB"
    )[0]
    preview_extract = engine.split("static func extractRGB")[1].split(
        "static func makeCGImage"
    )[0]
    assert "decodeFirstSourceRGB" in export_first
    assert "decodeDownscaled" not in export_first
    assert "extractRGB" not in export_first
    assert "extractRGB" not in export_seq
    assert "maxLongEdge" not in export_first
    assert "maxLongEdge" not in export_seq
    assert "exportMaxLongEdge" not in engine
    assert "static let writeLongEdgeCeiling = 16384" in engine
    assert "requireWriteSourcePixels" in engine
    assert "片源边长超过 16384，未写出" in engine
    assert "rgbFloatFromLogPixelBuffer" in movie
    assert "cgImageFromLogPixelBuffer(" not in movie
    assert "extractRGB" not in movie
    assert "applyYCbCrMatrixToFloat" in movie
    assert "requireSourceYCbCrUnpack" in movie
    assert "missingYCbCrTagsChip" in movie
    assert MISSING_YCBCR_TAGS_CHIP in movie
    assert "rec709OETF" not in movie
    assert "applyODT" not in movie
    assert "writeMatrixRGB(" not in movie
    assert "applyYCbCrMatrixToFloat" in ten_src
    assert "/ 255" not in ten_src
    assert "writeMatrixRGB(" not in ten_src
    assert "/ 1023" not in engine.split("func ycbcrRangeOffsets")[1].split(
        "func readSourceYCbCrMatrix"
    )[0]
    assert "bitsPerComponent: 8" in preview_cg
    assert "writeMatrixRGB" in preview_cg
    assert "requireSourceYCbCrUnpack" in preview_cg
    assert "missingYCbCrTagsChip" in preview_cg
    assert MISSING_YCBCR_TAGS_CHIP in preview_cg
    assert "yOff: 16" not in preview_cg
    assert "yOff: 64" not in preview_cg
    assert "/ 255" in preview_extract
    assert HONEST_PROXY_NOTE in engine
    _assert_chengpian_not_a_deliverable_claim(engine.split("func exportGradedAP0Sequence")[0][-400:])


def _f32(*values: float) -> tuple[float, ...]:
    return struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values))


def _assert_st2065_1_chromaticities_on_disk(path: Path) -> None:
    """Python write path: header chromaticities are ST 2065-1 AP0 + ACES white."""
    expected = _f32(*ST2065_1_CHROMATICITIES)
    chroma = read_exr_chromaticities(path)
    assert chroma == expected
    assert chroma[6:8] != _f32(*D65_XY)
    assert chroma[:6] != _f32(*AP1_PRIMARIES_XY)
    attrs = read_exr_attributes(path)
    assert "chromaticities" in attrs
    assert attrs["chromaticities"][0] == "chromaticities"
    assert "acesImageContainerFlag" not in attrs


def _assert_swift_exr_writer_chromaticities(exporter: str) -> None:
    """Swift write path: same 8 numbers. Fail if D65 or AP1 chromas are used."""
    assert ACES2065_1_CHROMATICITIES == ST2065_1_CHROMATICITIES
    const = exporter.split("aces2065_1Chromaticities: [Float] = [")[1].split("]")[0]
    writer = exporter.split("static func writeACES2065EXR")[1]
    assert "aces2065_1Chromaticities" in writer
    assert 'putAttr("chromaticities", "chromaticities"' in writer
    assert 'putAttr("acesImageContainerFlag"' not in writer
    assert 'putAttr("acesImageContainerFlag"' not in exporter
    for number in (
        "0.73470",
        "0.26530",
        "0.00000",
        "1.00000",
        "0.00010",
        "-0.07700",
        "0.32168",
        "0.33767",
    ):
        assert number in const
    for forbidden in (
        "0.3127",
        "0.3290",
        "0.329",
        "0.713",
        "0.293",
        "0.165",
        "0.830",
        "0.128",
        "0.044",
    ):
        assert forbidden not in const
        assert forbidden not in writer.split("putAttr(\"compression\"")[0]


def _assert_chengpian_not_a_deliverable_claim(text: str) -> None:
    """成片 may only appear as 预览·非成片 / 不是全精度成片 / 不是整段成片 / 不是成片."""
    cleaned = (
        text.replace("预览·非成片", "")
        .replace("不是全精度成片", "")
        .replace("不是整段成片", "")
        .replace("不是成片", "")
        .replace("成片预览关", "")
    )
    assert "成片" not in cleaned


def test_export_sequence_prefers_10bit_ycbcr():
    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    assert HONEST_PROXY_NOTE in engine
    _assert_export_sequence_tries_10bit_first(engine)
    _assert_export_decode_is_source_ycbcr_float(engine)
    assert "writeMatrixRGB" in engine
    ten_block = engine.split("kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange")[-1]
    assert "writeMatrixRGB" in ten_block.split("func writeMatrixRGB")[0]
    matrix = engine.split("func writeMatrixRGB")[1].split("func decodeStillImageIO")[0]
    assert "unpack.rv" in matrix
    assert "unpack.gu" in matrix
    assert "unpack.gv" in matrix
    assert "unpack.bu" in matrix
    assert "1.5748" not in matrix
    source_matrix = engine.split("func ycbcrMatrixCoeffs")[1].split(
        "func ycbcrRangeOffsets"
    )[0]
    assert "1.5748" in source_matrix
    assert "0.1873" in source_matrix
    assert "0.4681" in source_matrix
    assert "1.8556" in source_matrix
    assert "1.4746" in source_matrix
    assert "1.402" in source_matrix
    assert "return nil" in source_matrix
    clip = _read(CLIP)
    export_doc = clip.split("func exportLockedEXR")[1].split("func cancelLockedDeliverables")[0]
    assert "Source Y′CbCr" in clip
    assert "exportGradedAP0Sequence" in export_doc


def test_export_ycbcr_is_source_codes_not_preview_8bit():
    """10-bit source codes must not be preview-8-bit then /255."""
    # Neutral chroma, 10-bit Y=372 (not an 8-bit grid point after matrix).
    source = ycbcr_to_rgb_float(
        372, 512, 512, bit_depth=10, sample_range="video", matrix="bt709"
    )
    promoted = preview_u8_promoted_float(372, 512, 512, bit_depth=10)
    preview_u8 = ycbcr_to_preview_u8(372, 512, 512, bit_depth=10)
    assert abs(source[0] - promoted[0]) > 1e-4
    assert source[0] == source[1] == source[2]
    assert preview_u8 == (90, 90, 90)
    assert promoted == (90 / 255.0, 90 / 255.0, 90 / 255.0)
    yp = (372.0 - 64.0) / 876.0
    np.testing.assert_allclose(source, (yp, yp, yp), atol=1e-12)

    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    _assert_export_decode_is_source_ycbcr_float(engine)
    assert "ycbcr_to_rgb_float" in _read(ROOT / "color/batch.py")
    assert HONEST_PROXY_NOTE in engine
    status = processed_status_text(1, 0)
    assert HONEST_PROXY_NOTE in status
    assert "整段代理，不是全精度成片" in status
    _assert_chengpian_not_a_deliverable_claim(status)
    assert "精准" not in status
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "preview 8-bit path promoted" in readme
    assert "preview 8-bit path promoted" in acceptance
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)


def test_missing_ycbcr_tags_fails_closed_no_709_default(tmp_path: Path):
    """Missing nclc/colr/vui → Chinese failure. No silent 709-video default."""
    assert MISSING_YCBCR_TAGS_CHIP == "无法读取片源 Y′CbCr 矩阵/范围，未写出"
    assert ycbcr_range_offsets(10, "video") == (64.0, 876.0, 512.0, 896.0)
    assert ycbcr_range_offsets(10, "full") == (0.0, 1023.0, 512.0, 1023.0)
    nlog_video = ycbcr_to_rgb_float(
        372, 512, 512, bit_depth=10, sample_range="video", matrix="bt709"
    )
    assert abs(nlog_video[0] - 372.0 / 1023.0) > 1e-3
    m709 = ycbcr_to_rgb_float(
        400, 400, 600, bit_depth=10, sample_range="video", matrix="bt709"
    )
    m2020 = ycbcr_to_rgb_float(
        400, 400, 600, bit_depth=10, sample_range="video", matrix="bt2020"
    )
    assert m709 != m2020

    with pytest.raises(ValueError, match=MISSING_YCBCR_TAGS_CHIP):
        require_source_ycbcr_tags(None)
    with pytest.raises(ValueError, match=MISSING_YCBCR_TAGS_CHIP):
        require_source_ycbcr_tags({})
    with pytest.raises(ValueError, match=MISSING_YCBCR_TAGS_CHIP):
        require_source_ycbcr_tags({"nclc": "1-1-1"})
    with pytest.raises(ValueError, match=MISSING_YCBCR_TAGS_CHIP):
        require_source_ycbcr_tags({"full_range": False})
    with pytest.raises(ValueError, match=MISSING_YCBCR_TAGS_CHIP):
        require_source_ycbcr_tags({"nclc": "2-2-2", "full_range": False})
    assert parse_source_ycbcr_matrix({}) is None
    assert parse_source_ycbcr_range({}) is None
    assert parse_source_ycbcr_matrix({"nclc": "1-1-1"}) == "bt709"
    assert parse_source_ycbcr_range({"nclc": "1-1-1"}) is None

    tagged = require_source_ycbcr_tags({"nclc": "1-1-1", "full_range": False})
    assert tagged == ("bt709", "video")
    tagged2020 = require_source_ycbcr_tags(
        {"YCbCrMatrix": "ITU_R_2020", "FullRangeVideo": True}
    )
    assert tagged2020 == ("bt2020", "full")
    # Transfer 16 / primaries 9 must not become an IDT or a 709 curve.
    pq_nclc = require_source_ycbcr_tags({"nclc": "9-16-9", "full_range": False})
    assert pq_nclc == ("bt2020", "video")

    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)
    ]
    dest = tmp_path / "notags"
    report = process_locked_writes(
        clips, dest, frames={"locked.mov": _slog3_grey()}, ycbcr_tags={}
    )
    assert report.written == ()
    assert report.errors[0].error == MISSING_YCBCR_TAGS_CHIP
    assert not (dest / deliverable_dir_name("locked.mov")).exists()
    assert list(dest.glob("**/*.exr")) == []
    assert sidebar_export_chips(clips, report)["locked.mov"] == MISSING_YCBCR_TAGS_CHIP
    assert HONEST_PROXY_NOTE in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    assert "精准" not in report.processed_status_text

    ok = process_locked_writes(
        clips,
        tmp_path / "tags",
        frames={"locked.mov": _slog3_grey()},
        ycbcr_tags={"locked.mov": {"nclc": "9-16-9", "full_range": False}},
    )
    assert ok.written
    assert (tmp_path / "tags" / deliverable_dir_name("locked.mov")).is_dir()
    rgb = read_rgb_exr(Path(ok.written[0].path) / sequence_frame_name(0))
    np.testing.assert_allclose(rgb[0, 0], 0.18, atol=5e-3)

    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    clip = _read(CLIP)
    detector = _read(SWIFT_ROOT / "LogBridge/LogBridge/Detection/ClipDetector.swift")
    require = engine.split("func requireSourceYCbCrUnpack")[1].split(
        "func ycbcrMatrixCoeffs"
    )[0]
    assert "missingYCbCrTagsChip" in require
    assert MISSING_YCBCR_TAGS_CHIP in engine
    assert "kCVImageBufferYCbCrMatrixKey" in engine
    assert "kCMFormatDescriptionExtension_YCbCrMatrix" in engine
    assert "kCVImageBufferFullRangeVideo" in engine
    assert "rec709OETF" not in require
    assert "applyODT" not in require
    assert "applyIDT" not in require
    movie = engine.split("func decodeMovieAllFrames")[1].split("func linearAP0Frame")[0]
    assert "requireSourceYCbCrUnpack" in movie
    assert "rec709OETF" not in movie
    preview = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func decodeStillImageIO"
    )[0]
    preview_cg = engine.split("func cgImageFromLogPixelBuffer")[1].split(
        "func writeMatrixRGB"
    )[0]
    assert "requireSourceYCbCrUnpack" in preview
    assert "requireSourceYCbCrUnpack" in preview_cg
    assert MISSING_YCBCR_TAGS_CHIP in preview
    assert "No 709-video default" in preview
    assert "rec709OETF" not in preview
    assert "yOff: 16" not in preview_cg
    assert "yOff: 64" not in preview_cg
    assert MISSING_YCBCR_TAGS_CHIP in clip
    assert "missingYCbCrTagsChip" in clip.split("static func shortExportChip")[1]
    assert "writeOversizeChip" in clip.split("static func shortExportChip")[1]
    assert "Do not map nclc color primaries / transfer / matrix to an IDT" in detector
    _assert_chengpian_not_a_deliverable_claim(MISSING_YCBCR_TAGS_CHIP)
    _assert_chengpian_not_a_deliverable_claim(require)


def test_write_16384_is_ceiling_refuse_not_downsample(tmp_path: Path):
    """16384 refuses larger sources. Write stays 1:1. No scale to 16384/1920."""
    assert WRITE_LONG_EDGE_CEILING == 16384
    assert WRITE_OVERSIZE_CHIP == "片源边长超过 16384，未写出"
    require_write_source_pixels(16384, 1)
    require_write_source_pixels(1, 16384)
    with pytest.raises(ValueError, match=WRITE_OVERSIZE_CHIP):
        require_write_source_pixels(16385, 1)
    with pytest.raises(ValueError, match=WRITE_OVERSIZE_CHIP):
        require_write_source_pixels(1, 16385)
    assert short_export_chip(WRITE_OVERSIZE_CHIP) == WRITE_OVERSIZE_CHIP
    _assert_chengpian_not_a_deliverable_claim(WRITE_OVERSIZE_CHIP)
    assert "精准" not in WRITE_OVERSIZE_CHIP
    assert "完善" not in WRITE_OVERSIZE_CHIP

    clips = [
        BatchClip("huge.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)
    ]
    huge = np.zeros((2, 16385, 3), dtype=np.float32)
    dest = tmp_path / "oversize"
    dest.mkdir()
    report = process_locked_writes(clips, dest, frames={"huge.mov": [huge]})
    assert report.written == ()
    assert report.errors[0].error == WRITE_OVERSIZE_CHIP
    assert list(dest.glob("**/*.exr")) == []
    assert list(dest.glob("*" + DELIVERABLE_DIR_SUFFIX)) == []
    chips = sidebar_export_chips(clips, report)
    assert chips["huge.mov"] == WRITE_OVERSIZE_CHIP

    ok = np.zeros((2, 4, 3), dtype=np.float32)
    ok.fill(0.18)
    dest_ok = tmp_path / "ok"
    dest_ok.mkdir()
    report_ok = process_locked_writes(
        [BatchClip("ok.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)],
        dest_ok,
        frames={"ok.mov": [ok]},
    )
    assert len(report_ok.written) == 1
    written = Path(report_ok.written[0].path)
    assert written.name.endswith("_ACES2065-1_proxy")
    assert (written / "frame_000000.exr").is_file()

    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    clip = _read(CLIP)
    write_float = engine.split("func rgbFloatFromLogPixelBuffer")[1].split(
        "func applyYCbCrMatrixToFloat"
    )[0]
    require = engine.split("func requireWriteSourcePixels")[1].split(
        "func writeCAT"
    )[0]
    assert "static let writeLongEdgeCeiling = 16384" in engine
    assert "requireWriteSourcePixels" in write_float
    assert "scale =" not in write_float
    assert "maxLongEdge" not in write_float
    assert "exportMaxLongEdge" not in engine
    assert "writeLongEdgeCeiling" in require
    assert "scale =" not in require
    assert "maxLongEdge" not in require
    assert WRITE_OVERSIZE_CHIP in engine
    assert WRITE_OVERSIZE_CHIP in clip
    assert "writeOversizeChip" in clip.split("static func shortExportChip")[1]
    cached = engine.split("func cachedSource")[1].split("func cachedLinear")[0]
    assert "maxLongEdge: Self.maxLongEdge" in cached
    assert "rgbFloatFromLogPixelBuffer" not in cached
    assert "requireWriteSourcePixels" not in cached
    assert HONEST_PROXY_NOTE in engine
    assert "_ACES2065-1_proxy" in clip


def test_write_loop_one_pass_no_preview_8bit_no_odt(tmp_path: Path, monkeypatch):
    """Locked write: one IDT+WB per frame, no preview /255, no ODT, still 代理."""
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=4.0, fps=1.0)
    ]
    grey = _slog3_grey()
    frames = {"locked.mov": [grey, grey, grey, grey]}
    off = SerialGraph(idt_id="sony_slog3_sgamut3", odt_enabled=False)
    on = SerialGraph(idt_id="sony_slog3_sgamut3", odt_enabled=True)
    dest_off = tmp_path / "off"
    dest_on = tmp_path / "on"
    report_off = process_locked_writes(clips, dest_off, frames=frames, graph=off)
    report_on = process_locked_writes(clips, dest_on, frames=frames, graph=on)
    assert report_off.processed_count == 1
    assert report_on.processed_count == 1
    assert report_off.written[0].frame_count == 4
    off_rgb = read_rgb_exr(Path(report_off.written[0].path) / sequence_frame_name(0))
    on_rgb = read_rgb_exr(Path(report_on.written[0].path) / sequence_frame_name(0))
    np.testing.assert_allclose(off_rgb, on_rgb, atol=1e-12)
    np.testing.assert_allclose(off_rgb[0, 0], 0.18, atol=5e-3)
    preview_709 = on.apply(grey)
    assert not np.allclose(on_rgb[0, 0], preview_709, atol=1e-2)
    assert Path(report_on.written[0].path).name.endswith("_ACES2065-1_proxy")
    assert HONEST_PROXY_NOTE in report_on.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report_on.processed_status_text)
    assert "精准" not in report_on.processed_status_text

    wb_calls: list[int] = []
    orig = SerialGraph.wb_matrix

    def counted(self):
        wb_calls.append(1)
        return orig(self)

    monkeypatch.setattr(SerialGraph, "wb_matrix", counted)
    wb = SerialGraph(
        idt_id="sony_slog3_sgamut3",
        wb_enabled=True,
        wb_cct=3200.0,
        wb_source=WB_SOURCE_GREY,
    )
    process_locked_writes(clips, tmp_path / "wb", frames=frames, graph=wb)
    assert len(wb_calls) == 1

    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    clip = _read(CLIP)
    batch = _read(ROOT / "color/batch.py")
    graph_py = _read(ROOT / "color/graph.py")
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    movie = engine.split("func decodeMovieAllFrames")[1].split(
        "func linearAP0Frame"
    )[0]
    write_py = batch.split("write_setup = graph.ap0_write_setup()")[1].split(
        "if cancelled:"
    )[0]
    assert "apply_ap0" in write_py
    assert "graph.apply(" not in write_py
    assert "ap0_write_setup" in graph_py
    assert "Never ODT" in graph_py.split("def apply_ap0")[1].split("def apply(")[0]
    assert "writeCAT" in export_seq
    assert "gradeAP0" in export_seq
    assert "joinExportWrite" in export_seq
    assert "DispatchQueue.global" in export_seq
    assert "exportWriteQueue" not in export_seq
    assert "one write overlap" in export_seq
    on_frame = export_seq.split("decodeAllSourceFrames")[1]
    assert on_frame.index("gradeAP0") < on_frame.index("joinExportWrite")
    assert on_frame.index("joinExportWrite") < on_frame.index(
        "DispatchQueue.global"
    )
    assert "writeFrame(index, pixels, w, h)" in on_frame.split("DispatchWorkItem")[1]
    assert "try writeFrame(count, rgb, width, height)" not in export_seq
    assert "applyODT" not in export_seq
    assert "extractRGB" not in export_seq
    assert "/ 255" not in export_seq
    assert "gradedCache" not in export_seq
    assert "refreshODT" not in export_seq
    assert "retainPreviewCaches" not in export_seq
    assert "copyNextSampleBuffer" in movie
    assert "requestedTime" not in movie
    assert "AVAssetImageGenerator" not in movie
    assert "seek(" not in movie
    assert "applyODT" not in movie
    assert "rec709OETF" not in movie
    assert "writeMatrixRGB(" not in movie
    assert "applyYCbCrMatrixToFloat" in movie
    grade = engine.split("func gradeAP0")[1].split("func exportGradedAP0(")[0]
    assert "applyODT" not in grade
    assert "applyPreparedCAT" in grade
    export_body = clip.split("func exportLockedEXR")[1].split(
        "func cancelLockedDeliverables"
    )[0]
    assert "exportGradedAP0Sequence" in export_body
    assert "writeACES2065EXR" in export_body
    assert "applyODT" not in export_body
    _assert_export_decode_is_source_ycbcr_float(engine)


def test_honest_proxy_copy_and_filename():
    assert HONEST_PROXY_NOTE == "整段代理，不是全精度成片"
    assert DELIVERABLE_SUFFIX == "_ACES2065-1_proxy"
    assert DELIVERABLE_DIR_SUFFIX == "_ACES2065-1_proxy"
    assert "proxy" in DELIVERABLE_SUFFIX
    assert "_proxy" in DELIVERABLE_SUFFIX
    assert "acescct" not in DELIVERABLE_SUFFIX.lower()
    assert deliverable_name("clip.mov") == "clip_ACES2065-1_proxy/frame_000000.exr"
    assert sequence_frame_name(1) == "frame_000001.exr"
    assert "_proxy" in deliverable_name("clip.mov")
    status = processed_status_text(2, 1)
    assert HONEST_PROXY_NOTE in status
    assert "整段代理，不是全精度成片" in status
    assert "预览·非成片" in status
    assert "已实现（未验证）" in status
    assert "2 条已处理" in status
    _assert_chengpian_not_a_deliverable_claim(status)
    assert HONEST_PROXY_NOTE in PROCESSED_STATUS_TEMPLATE
    assert HONEST_PROXY_NOTE in FOLDER_PICKER_MESSAGE
    assert "整段代理，不是全精度成片" in FOLDER_PICKER_MESSAGE
    assert "ACES2065-1" in FOLDER_PICKER_MESSAGE
    assert "ACEScct" not in FOLDER_PICKER_MESSAGE
    assert HONEST_PROXY_NOTE in PROCESS_BUTTON_HELP
    assert "不是 ACEScct" in PROCESS_BUTTON_HELP
    assert SKIPPED_BUCKET in PROCESS_BUTTON_HELP
    assert REASON_PICK_LOG_GAMUT in PROCESS_BUTTON_HELP
    assert REASON_PICK_PAIRED_IDT in PROCESS_BUTTON_HELP
    assert "Unlocked stay listed" not in PROCESS_BUTTON_HELP
    assert "Never 一键还原" not in PROCESS_BUTTON_HELP
    clip = _read(CLIP)
    content = _read(CONTENT)
    exporter = _read(SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift")
    assert PROCESS_BUTTON_HELP in content
    assert FOLDER_PICKER_MESSAGE in clip
    assert processed_status_text(0, 0).replace("0 条已处理 / 0 条已跳过", "") in clip or HONEST_PROXY_NOTE in clip
    assert HONEST_PROXY_NOTE in content
    assert "_ACES2065-1_proxy" in exporter
    assert "frame_%06d.exr" in exporter
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert HONEST_PROXY_NOTE in readme
    assert HONEST_PROXY_NOTE in acceptance
    assert "_ACES2065-1_proxy/frame_000000.exr" in readme
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)
    _assert_chengpian_not_a_deliverable_claim(clip)
    _assert_chengpian_not_a_deliverable_claim(content)


def test_unlocked_never_writes_sequence(tmp_path: Path):
    clips = [
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
        BatchClip("stub.mov", idt="future", is_stub=True),
    ]
    stack = np.stack([_slog3_grey(), _slog3_grey()], axis=0)
    frames = {c.name: stack for c in clips}
    report = process_locked_writes(clips, tmp_path, frames=frames)
    assert report.processed_count == 0
    assert report.written == ()
    assert report.skipped_count == 3
    assert list(tmp_path.glob("**/*.exr")) == []
    assert list(tmp_path.glob("*" + DELIVERABLE_DIR_SUFFIX)) == []


def test_locked_writes_more_than_one_frame(tmp_path: Path):
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=2.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
    ]
    frame_a = _slog3_grey()
    frame_b = np.full((2, 2, 3), float(linear_to_slog3(0.09)), dtype=np.float64)
    report = process_locked_writes(
        clips,
        tmp_path,
        frames={"locked.mov": [frame_a, frame_b], "pending.mov": [frame_a, frame_b]},
    )
    assert report.processed_count == 1
    assert report.written[0].frame_count == 2
    seq = tmp_path / deliverable_dir_name("locked.mov")
    assert seq.is_dir()
    assert (seq / sequence_frame_name(0)).is_file()
    assert (seq / sequence_frame_name(1)).is_file()
    assert not (seq / sequence_frame_name(2)).exists()
    rgb0 = read_rgb_exr(seq / sequence_frame_name(0))
    rgb1 = read_rgb_exr(seq / sequence_frame_name(1))
    np.testing.assert_allclose(rgb0[0, 0], 0.18, atol=5e-3)
    assert not np.allclose(rgb0, rgb1, atol=1e-3)
    assert not (tmp_path / deliverable_dir_name("pending.mov")).exists()
    assert "_proxy" in seq.name
    assert HONEST_PROXY_NOTE in report.processed_status_text
    assert "整段代理，不是全精度成片" in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    assert list(tmp_path.glob("**/*.mov")) == []
    assert list(tmp_path.glob("**/*.mp4")) == []


def test_progress_and_cancel_copy_is_honest_not_chengpian():
    """Cancel/progress strings exist. 成片 is not a success claim."""
    assert PROCESS_BUTTON == "处理已锁定片段"
    assert CANCEL_BUTTON == "取消"
    assert CANCELLED_NOTE == "已取消"
    assert PROGRESS_PREFIX == "写出代理"
    assert progress_text(2, 5, 120) == "写出代理 2/5 · frame 120"
    assert progress_text(2, 5, 120, 240) == "写出代理 2/5 · frame 120/240"
    assert progress_text(1, 3) == "写出代理 1/3"
    cancelled = cancelled_status_text(1, 2)
    assert CANCELLED_NOTE in cancelled
    assert HONEST_PROXY_NOTE in cancelled
    assert "整段代理，不是全精度成片" in cancelled
    assert "1 条已处理" in cancelled
    assert "2 条已跳过" in cancelled
    assert CANCELLED_NOTE in CANCELLED_STATUS_TEMPLATE
    assert HONEST_PROXY_NOTE in CANCELLED_STATUS_TEMPLATE
    _assert_chengpian_not_a_deliverable_claim(cancelled)
    _assert_chengpian_not_a_deliverable_claim(progress_text(2, 5, 120))
    _assert_chengpian_not_a_deliverable_claim(CANCELLED_STATUS_TEMPLATE)

    clip = _read(CLIP)
    content = _read(CONTENT)
    assert "写出代理" in clip
    assert "已取消" in clip
    assert "exportProgressText" in clip
    assert "cancelledExportNote" in clip
    assert "cancelLockedDeliverables" in clip
    assert "isWritingDeliverables" in clip
    assert "LockedWriteCancel" in clip
    assert HONEST_PROXY_NOTE in clip.split("func cancelledExportNote")[1]
    assert CANCELLED_NOTE in clip.split("func cancelledExportNote")[1]
    _assert_chengpian_not_a_deliverable_claim(clip.split("func cancelledExportNote")[1].split("func publishExportProgress")[0])
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "cancelLockedDeliverables" in bar
    assert "processLockedClips" in bar
    assert 'Button("处理已锁定片段")' not in content.split("struct StatusBar")[1]
    assert 'Button("处理已锁定片段")' not in content.split("struct AdvancedPanel")[1]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "写出代理" in readme and "已取消" in readme
    assert "写出代理" in acceptance and "已取消" in acceptance
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)
    _assert_chengpian_not_a_deliverable_claim(content)


def test_cancel_removes_in_progress_folder_keeps_completed(tmp_path: Path):
    """Safer cancel: drop the current half `_proxy` folder. Completed clips stay."""
    clips = [
        BatchClip("done.mov", idt="sony_slog3_sgamut3", duration_seconds=2.0, fps=1.0),
        BatchClip("long.mov", idt="sony_slog3_sgamut3", duration_seconds=4.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
    ]
    frame = _slog3_grey()
    frames = {
        "done.mov": [frame, frame],
        "long.mov": [frame, frame, frame, frame],
        "pending.mov": [frame, frame],
    }
    notes: list[str] = []
    seen_long = {"n": 0}

    def should_cancel() -> bool:
        return seen_long["n"] >= 2

    def spy(path: Path, rgb) -> None:
        path.write_bytes(b"x")
        if "long" in path.parts[-2]:
            seen_long["n"] += 1

    report = process_locked_writes(
        clips,
        tmp_path,
        frames=frames,
        write_fn=spy,
        should_cancel=should_cancel,
        on_progress=notes.append,
    )
    assert report.cancelled is True
    assert report.processed_count == 1
    assert report.written[0].name == "done.mov"
    assert (tmp_path / deliverable_dir_name("done.mov")).is_dir()
    assert (tmp_path / deliverable_name("done.mov", 0)).is_file()
    assert (tmp_path / deliverable_name("done.mov", 1)).is_file()
    assert not (tmp_path / deliverable_dir_name("long.mov")).exists()
    assert not (tmp_path / deliverable_dir_name("pending.mov")).exists()
    assert CANCELLED_NOTE in report.processed_status_text
    assert HONEST_PROXY_NOTE in report.processed_status_text
    assert report.last_reveal_paths == ()
    assert REVEAL_IN_FINDER not in report.processed_status_text
    assert short_export_path(tmp_path) not in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    assert any(n.startswith("写出代理 1/2") for n in notes)
    assert any("frame" in n for n in notes)
    clip = _read(CLIP)
    export_body = clip.split("func exportLockedEXR")[1].split("func cancelLockedDeliverables")[0]
    assert "LockedWriteCancel" in export_body
    assert "removeItem(at: seqDir)" in export_body


def test_last_export_folder_and_finder_reveal(tmp_path: Path):
    """Last dest is remembered. Finder reveal is success-only. 成片 is not a success claim."""
    assert REVEAL_IN_FINDER == "在 Finder 中显示"
    assert LAST_EXPORT_DIRECTORY_KEY == "logbridge.lastExportDirectory"
    dest = tmp_path / "Exports"
    dest.mkdir()
    assert short_export_path(dest) == "Exports"
    clips = [BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0)]
    report = process_locked_writes(clips, dest, frames={"locked.mov": _slog3_grey()})
    assert report.cancelled is False
    assert report.written
    assert short_export_path(dest) in report.processed_status_text
    assert HONEST_PROXY_NOTE in report.processed_status_text
    assert report.last_reveal_paths == report.written_paths
    assert all(Path(p).name.endswith("_ACES2065-1_proxy") for p in report.last_reveal_paths)
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    _assert_chengpian_not_a_deliverable_claim(REVEAL_IN_FINDER)

    settings = _read(SWIFT_ROOT / "LogBridge/LogBridge/Models/AppSettings.swift")
    clip = _read(CLIP)
    content = _read(CONTENT)
    assert LAST_EXPORT_DIRECTORY_KEY in settings
    assert "lastExportDirectoryPath" in settings
    assert "lastExportDirectoryURL" in settings
    assert "rememberExportDirectory" in settings
    assert "directoryURL" in clip.split("func processLockedClips()")[1].split(
        "func writeLockedDeliverables"
    )[0]
    assert "rememberExportDirectory" in clip.split("func processLockedClips()")[1]
    write_body = clip.split("func writeLockedDeliverables")[1].split("func exportLockedEXR")[0]
    assert "lastExportRevealURLs" in write_body
    assert "shortExportPath" in write_body
    assert "cancelled" in write_body
    assert REVEAL_IN_FINDER in clip
    assert "revealLastExportInFinder" in clip
    assert "activateFileViewerSelecting" in clip
    assert "canRevealLastExport" in clip
    assert REVEAL_IN_FINDER in content
    assert "revealLastExportInFinder" in content
    assert "canRevealLastExport" in content
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    status = content.split("struct StatusBar")[1]
    assert 'Button("处理已锁定片段")' not in status
    assert REVEAL_IN_FINDER in status
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert REVEAL_IN_FINDER in readme
    assert REVEAL_IN_FINDER in acceptance
    assert LAST_EXPORT_DIRECTORY_KEY.split(".")[-1] in clip or "lastExportDirectory" in clip
    _assert_chengpian_not_a_deliverable_claim(write_body)
    _assert_chengpian_not_a_deliverable_claim(content)
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)


def test_sidebar_export_chips_wrote_error_cancel_and_refresh(tmp_path: Path):
    """Sidebar/status: 已写出代理. Never claim 成片 as success. Pending stay 待选."""
    assert WRITTEN_CHIP == "已写出代理"
    assert WRITE_FAILED_CHIP == "写出失败"
    assert DECODE_FAILED_CHIP == "解码失败"
    assert "成片" not in WRITTEN_CHIP
    assert "成片" not in WRITE_FAILED_CHIP
    assert "成片" not in DECODE_FAILED_CHIP
    _assert_chengpian_not_a_deliverable_claim(WRITTEN_CHIP)
    _assert_chengpian_not_a_deliverable_claim(WRITE_FAILED_CHIP)
    _assert_chengpian_not_a_deliverable_claim(DECODE_FAILED_CHIP)
    assert short_export_chip(written=True) == WRITTEN_CHIP
    assert short_export_chip(cancelled=True) is None
    assert short_export_chip("decode/grade failed") == DECODE_FAILED_CHIP
    assert short_export_chip("no pixels") == DECODE_FAILED_CHIP
    assert short_export_chip("disk full") == WRITE_FAILED_CHIP
    assert "成片" not in (short_export_chip(written=True) or "")

    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
    ]
    assert sidebar_status_chip(clips[1]) == REASON_PICK_PAIRED_IDT
    assert sidebar_status_chip(clips[2]) == REASON_PICK_LOG_GAMUT
    assert sidebar_status_chip(clips[0]) is None
    report = process_locked_writes(
        clips, tmp_path / "ok", frames={"locked.mov": _slog3_grey()}
    )
    chips = sidebar_export_chips(clips, report)
    assert chips["locked.mov"] == WRITTEN_CHIP
    assert chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert chips["empty.mov"] == REASON_PICK_LOG_GAMUT
    assert HONEST_PROXY_NOTE in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    _assert_chengpian_not_a_deliverable_claim(chips["locked.mov"])

    fail = process_locked_writes(clips, tmp_path / "fail", frames={})
    fail_chips = sidebar_export_chips(clips, fail)
    assert fail_chips["locked.mov"] == DECODE_FAILED_CHIP
    assert fail_chips["locked.mov"] != WRITTEN_CHIP
    assert fail_chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    _assert_chengpian_not_a_deliverable_claim(fail_chips["locked.mov"])

    cancel_clips = [
        BatchClip("done.mov", idt="sony_slog3_sgamut3", duration_seconds=2.0, fps=1.0),
        BatchClip("long.mov", idt="sony_slog3_sgamut3", duration_seconds=4.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
    ]
    frame = _slog3_grey()
    seen_long = {"n": 0}

    def should_cancel() -> bool:
        return seen_long["n"] >= 2

    def spy(path: Path, rgb) -> None:
        path.write_bytes(b"x")
        if "long" in path.parts[-2]:
            seen_long["n"] += 1

    cancelled = process_locked_writes(
        cancel_clips,
        tmp_path / "cancel",
        frames={
            "done.mov": [frame, frame],
            "long.mov": [frame, frame, frame, frame],
            "pending.mov": [frame, frame],
        },
        write_fn=spy,
        should_cancel=should_cancel,
    )
    cancel_chips = sidebar_export_chips(cancel_clips, cancelled)
    assert cancel_chips["done.mov"] == WRITTEN_CHIP
    assert cancel_chips["long.mov"] is None
    assert cancel_chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert short_export_chip(cancelled=True) != WRITTEN_CHIP
    _assert_chengpian_not_a_deliverable_claim(cancel_chips["done.mov"])

    clip = _read(CLIP)
    sidebar = _read(SIDEBAR)
    content = _read(CONTENT)
    write_body = clip.split("func writeLockedDeliverables")[1].split("func exportLockedEXR")[0]
    assert WRITTEN_CHIP in clip
    assert WRITTEN_CHIP in sidebar
    assert "exportChip" in clip
    assert "sidebarStatusChip" in clip
    assert "clearExportChips" in write_body
    assert "setExportChip" in write_body
    assert "wroteProxyChip" in write_body
    assert "shortExportChip" in write_body
    assert "LockedWriteCancel" in write_body
    cancel_arm = write_body.split("catch is LockedWriteCancel")[1].split("} catch")[0]
    assert "wroteProxyChip" not in cancel_arm
    assert "setExportChip" not in cancel_arm
    assert "解码失败" in clip
    assert "写出失败" in clip
    assert "exportChip" in sidebar
    assert "processSkipReason" in sidebar
    assert "待选" in clip
    assert HONEST_PROXY_NOTE in clip
    assert "精准" not in clip.split("static let wroteProxyChip")[1].split("private func clearExportChips")[0]
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert WRITTEN_CHIP in (ROOT / "README.md").read_text(encoding="utf-8")
    assert WRITTEN_CHIP in (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    _assert_chengpian_not_a_deliverable_claim(clip)
    _assert_chengpian_not_a_deliverable_claim(sidebar)
    _assert_chengpian_not_a_deliverable_claim(content)


def test_sidebar_chip_row_reveals_clip_sequence_folder(tmp_path: Path):
    """Reveal-on-chip/row uses last dest + deliverable_dir_name. 成片 is not success."""
    dest = tmp_path / "Exports"
    dest.mkdir()
    clips = [
        BatchClip("locked.mov", idt="sony_slog3_sgamut3", duration_seconds=1.0, fps=1.0),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
    ]
    report = process_locked_writes(
        clips, dest, frames={"locked.mov": _slog3_grey()}
    )
    chips = sidebar_export_chips(clips, report)
    written = clip_sequence_reveal_path("locked.mov", dest, chips["locked.mov"])
    assert chips["locked.mov"] == WRITTEN_CHIP
    assert written == dest / deliverable_dir_name("locked.mov")
    assert written is not None
    assert written.name.endswith("_ACES2065-1_proxy")
    assert written == dest / "locked_ACES2065-1_proxy"
    assert written.is_dir()
    assert "成片" not in WRITTEN_CHIP
    _assert_chengpian_not_a_deliverable_claim(WRITTEN_CHIP)
    _assert_chengpian_not_a_deliverable_claim(str(written))

    assert clip_sequence_reveal_path("pending.mov", dest, chips["pending.mov"]) is None
    assert clip_sequence_reveal_path("empty.mov", dest, chips["empty.mov"]) is None
    fail = process_locked_writes(clips, tmp_path / "fail", frames={})
    fail_chips = sidebar_export_chips(clips, fail)
    assert fail_chips["locked.mov"] == DECODE_FAILED_CHIP
    assert clip_sequence_reveal_path(
        "locked.mov", tmp_path / "fail", fail_chips["locked.mov"]
    ) is None
    assert clip_sequence_reveal_path("locked.mov", dest, short_export_chip(cancelled=True)) is None
    assert clip_sequence_reveal_path("locked.mov", dest, WRITE_FAILED_CHIP) is None
    assert clip_sequence_reveal_path("locked.mov", dest, None) is None
    assert clip_sequence_reveal_path("locked.mov", None, WRITTEN_CHIP) is None

    clip = _read(CLIP)
    sidebar = _read(SIDEBAR)
    content = _read(CONTENT)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "clip_sequence_reveal_path" in _read(ROOT / "color/batch.py")
    assert "clipSequenceRevealURL" in clip
    assert "revealClipExportInFinder" in clip
    assert "lastExportDirectoryURL" in clip.split("func revealClipExportInFinder")[1].split(
        "private func publishExportProgress"
    )[0]
    assert "deliverableSequenceDirectory" in clip.split("clipSequenceRevealURL")[1].split(
        "func revealClipExportInFinder"
    )[0]
    assert "wroteProxyChip" in clip.split("clipSequenceRevealURL")[1].split(
        "func revealClipExportInFinder"
    )[0]
    assert "revealClipExportInFinder" in sidebar
    assert "onRevealWritten" in sidebar
    assert WRITTEN_CHIP in sidebar
    assert "onTapGesture" in sidebar
    row_tap = sidebar.split(".onTapGesture")[1].split("}")[0]
    assert "revealClipExportInFinder" in row_tap
    chip = sidebar.split("if chip == SessionModel.wroteProxyChip")[1].split("} else {")[0]
    assert "onRevealWritten" in chip
    assert "Button(" in chip
    assert WRITTEN_CHIP not in sidebar.split("if let reason = clip.processSkipReason")[1].split(
        "} else if let chip"
    )[0]
    status = content.split("struct StatusBar")[1]
    assert REVEAL_IN_FINDER in status
    assert "revealLastExportInFinder" in status
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert WRITTEN_CHIP in readme
    assert WRITTEN_CHIP in acceptance
    assert "deliverable_dir_name" in readme or "_ACES2065-1_proxy" in readme
    assert HONEST_PROXY_NOTE in clip
    assert "精准" not in clip.split("func revealClipExportInFinder")[1].split(
        "private func publishExportProgress"
    )[0]
    _assert_chengpian_not_a_deliverable_claim(clip.split("func revealClipExportInFinder")[0][-400:])
    _assert_chengpian_not_a_deliverable_claim(sidebar)
    _assert_chengpian_not_a_deliverable_claim(content)
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)


def test_too_small_dest_fails_closed_no_files(tmp_path: Path):
    """Too-small dest: do not start writing. No EXR / no _proxy folder."""
    assert BYTES_PER_EXR_PIXEL == 12
    assert DISK_ESTIMATE_ASSUMPTION == "float32 RGB 未压缩"
    assert DISK_SHORT_STATUS == "磁盘空间不足，未写出"
    assert HONEST_PROXY_NOTE in DISK_SHORT_STATUS_TEMPLATE
    _assert_chengpian_not_a_deliverable_claim(DISK_SHORT_STATUS)
    _assert_chengpian_not_a_deliverable_claim(DISK_SHORT_STATUS_TEMPLATE)
    assert "精准" not in DISK_SHORT_STATUS
    assert "精准" not in DISK_SHORT_STATUS_TEMPLATE

    clips = [
        BatchClip(
            "locked.mov",
            idt="sony_slog3_sgamut3",
            frame_count=100,
            width=1920,
            height=1080,
            duration_seconds=1.0,
            fps=1.0,
        ),
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip(
            "huge_pending.mov",
            detected_curve="S-Log3",
            needs_user_picker=True,
            frame_count=99_999,
            width=3840,
            height=2160,
        ),
    ]
    locked_only = estimate_locked_proxy_bytes(clips)
    assert locked_only.bytes == 100 * 1920 * 1080 * BYTES_PER_EXR_PIXEL
    assert dest_has_space(tmp_path, locked_only.needed_bytes, free_bytes=1) is False
    assert dest_has_space(tmp_path, locked_only.needed_bytes, free_bytes=locked_only.needed_bytes) is True

    duration = BatchClip(
        "dur.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        fps=24.0,
        width=100,
        height=50,
    )
    dur_est = estimate_locked_proxy_bytes([duration])
    assert dur_est.bytes == 48 * 100 * 50 * BYTES_PER_EXR_PIXEL
    assert dur_est.used_duration_fps is True
    assert "时长" in dur_est.note and "帧率" in dur_est.note
    assert DISK_ESTIMATE_ASSUMPTION in dur_est.note
    _assert_chengpian_not_a_deliverable_claim(dur_est.note)

    guessed = BatchClip("guess.mov", idt="sony_slog3_sgamut3")
    guess_est = estimate_locked_proxy_bytes([guessed])
    assert guess_est.used_frame_guess is True
    assert guess_est.bytes == (
        int(CONSERVATIVE_SECONDS * CONSERVATIVE_FPS)
        * CONSERVATIVE_WIDTH
        * CONSERVATIVE_HEIGHT
        * BYTES_PER_EXR_PIXEL
    )
    assert "每秒" in guess_est.note
    assert str(int(CONSERVATIVE_FPS)) in guess_est.note
    _assert_chengpian_not_a_deliverable_claim(guess_est.note)

    picker = folder_picker_message_with_estimate(locked_only)
    assert FOLDER_PICKER_MESSAGE in picker
    assert locked_only.note in picker
    _assert_chengpian_not_a_deliverable_claim(picker)

    grey = _slog3_grey()
    dest = tmp_path / "tiny"
    dest.mkdir()
    called: list[str] = []

    def spy(path: Path, rgb) -> None:
        called.append(Path(path).name)
        path.write_bytes(b"x")

    report = process_locked_writes(
        clips,
        dest,
        frames={"locked.mov": [grey, grey], "pending.mov": [grey]},
        write_fn=spy,
        free_bytes=1,
    )
    assert report.disk_short is True
    assert report.written == ()
    assert report.errors == ()
    assert report.processed_count == 0
    assert report.cancelled is False
    assert report.last_reveal_paths == ()
    assert called == []
    assert list(dest.glob("**/*.exr")) == []
    assert list(dest.glob("*" + DELIVERABLE_DIR_SUFFIX)) == []
    assert not (dest / deliverable_dir_name("locked.mov")).exists()
    assert not (dest / deliverable_dir_name("pending.mov")).exists()
    assert DISK_SHORT_STATUS in report.processed_status_text
    assert HONEST_PROXY_NOTE in report.processed_status_text
    assert "整段代理，不是全精度成片" in report.processed_status_text
    assert "条已处理" not in report.processed_status_text
    assert "精准" not in report.processed_status_text
    assert "0 条已写出代理" in report.processed_status_text
    assert "2 条待选跳过" in report.processed_status_text
    assert "1 条失败" in report.processed_status_text
    assert FAILED_BUCKET in report.processed_status_text
    assert str(int(CONSERVATIVE_FPS)) not in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    assert batch_summary_text(0, 2, 1, [DISK_SHORT_STATUS]) == report.processed_status_text

    # Missing pixels are a per-clip error, not a 4K×60s dest abort.
    empty = process_locked_writes(
        [BatchClip("locked.mov", idt="sony_slog3_sgamut3")],
        tmp_path / "empty",
        frames={},
    )
    assert empty.disk_short is False
    assert empty.processed_count == 1
    assert empty.written == ()
    assert empty.errors[0].name == "locked.mov"
    assert list((tmp_path / "empty").glob("**/*.exr")) == []

    ok_dest = tmp_path / "ok"
    ok = process_locked_writes(
        clips, ok_dest, frames={"locked.mov": [grey]}, write_fn=spy
    )
    assert ok.disk_short is False
    assert ok.written
    assert (ok_dest / deliverable_dir_name("locked.mov")).is_dir()
    assert not (ok_dest / deliverable_dir_name("pending.mov")).exists()

    clip = _read(CLIP)
    content = _read(CONTENT)
    media = _read(SWIFT_ROOT / "LogBridge/LogBridge/Models/MediaFormat.swift")
    write_body = clip.split("func writeLockedDeliverables")[1].split("func exportLockedEXR")[0]
    process_body = clip.split("func processLockedClips()")[1].split(
        "func writeLockedDeliverables"
    )[0]
    assert "estimateLockedProxyBytes" in write_body
    assert "destFreeBytesOverride" in write_body
    assert "destVolumeFreeBytes" in write_body
    assert "batchSummaryText" in write_body
    assert "diskShortStatus" in write_body
    assert "neededWithMargin" in write_body
    assert "return" in write_body.split("neededWithMargin")[1].split("let graphCopy")[0]
    assert "exportLockedEXR" not in write_body.split("neededWithMargin")[1].split(
        "let graphCopy"
    )[0]
    assert "clearExportChips" not in write_body.split("neededWithMargin")[1].split(
        "let graphCopy"
    )[0]
    assert "isWritingDeliverables = true" not in write_body.split("neededWithMargin")[1].split(
        "let graphCopy"
    )[0]
    assert DISK_SHORT_STATUS in clip
    assert DISK_ESTIMATE_ASSUMPTION in clip
    assert HONEST_PROXY_NOTE in clip.split("func diskShortExportNote")[1]
    assert "bytesPerEXRPixel" in clip
    assert "12" in clip.split("bytesPerEXRPixel")[1].split("conservativeFPS")[0]
    assert "destFreeBytesOverride" in clip
    assert "MediaFormat.extent" in clip
    assert "func extent(url:" in media
    assert "volumeAvailableCapacity" in clip
    assert FOLDER_PICKER_MESSAGE in process_body
    assert "pickerSuffix" in process_body
    assert "estimateLockedProxyBytes" in process_body
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert 'Button("处理已锁定片段")' not in content.split("struct StatusBar")[1]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert DISK_SHORT_STATUS in readme
    assert DISK_SHORT_STATUS in acceptance
    assert DISK_ESTIMATE_ASSUMPTION in readme or "float32 RGB" in readme
    _assert_chengpian_not_a_deliverable_claim(write_body)
    _assert_chengpian_not_a_deliverable_claim(clip.split("func diskShortExportNote")[1].split("static let wroteProxyChip")[0])
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)
    assert "精准" not in clip.split("static let diskShortStatus")[1].split(
        "static func formatProxyBytes"
    )[0]


def _spy_exr(path: Path, rgb) -> None:
    path.write_bytes(b"x")


def test_verify_matching_count_marks_written_proxy(tmp_path: Path):
    """Matching EXR count (duration × fps) is 已写出代理. Unlocked stay skipped."""
    locked = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        fps=24.0,
    )
    pending = BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True)
    grey = _slog3_grey()
    dest = tmp_path / "ok"
    report = process_locked_writes(
        [locked, pending],
        dest,
        frames={"locked.mov": [grey] * 48, "pending.mov": [grey] * 48},
        write_fn=_spy_exr,
    )
    seq = dest / deliverable_dir_name("locked.mov")
    assert report.written
    assert report.written[0].name == "locked.mov"
    assert seq.is_dir()
    assert count_proxy_exrs(seq) == 48
    chips = sidebar_export_chips([locked, pending], report)
    assert chips["locked.mov"] == WRITTEN_CHIP
    assert chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert not (dest / deliverable_dir_name("pending.mov")).exists()
    assert HONEST_PROXY_NOTE in report.processed_status_text
    _assert_chengpian_not_a_deliverable_claim(report.processed_status_text)
    assert "精准" not in report.processed_status_text


def test_verify_off_by_one_still_success(tmp_path: Path):
    """Inclusive last-frame boundary: |written − expected| ≤ 1 is accepted."""
    locked = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        fps=24.0,
    )
    grey = _slog3_grey()
    dest = tmp_path / "off_by_one"
    report = process_locked_writes(
        [locked],
        dest,
        frames={"locked.mov": [grey] * 47},
        write_fn=_spy_exr,
    )
    assert report.written
    assert sidebar_export_chips([locked], report)["locked.mov"] == WRITTEN_CHIP
    assert frames_count_matches(47, 48) is True
    assert frames_count_matches(49, 48) is True
    assert frames_count_matches(0, 48) is False
    assert frames_count_matches(2, 48) is False


def test_verify_mismatch_is_not_written_proxy(tmp_path: Path):
    """Wrong EXR count: 帧数对不上, folder removed, not 已写出代理."""
    locked = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        fps=24.0,
    )
    pending = BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True)
    grey = _slog3_grey()
    dest = tmp_path / "mismatch"
    report = process_locked_writes(
        [locked, pending],
        dest,
        frames={"locked.mov": [grey, grey], "pending.mov": [grey, grey]},
        write_fn=_spy_exr,
    )
    assert report.written == ()
    assert report.errors[0].name == "locked.mov"
    assert report.errors[0].error == FRAME_MISMATCH_CHIP
    assert FRAME_MISMATCH_CHIP == "帧数对不上"
    chips = sidebar_export_chips([locked, pending], report)
    assert chips["locked.mov"] == FRAME_MISMATCH_CHIP
    assert chips["locked.mov"] != WRITTEN_CHIP
    assert chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert not (dest / deliverable_dir_name("locked.mov")).exists()
    assert list(dest.glob("**/*.exr")) == []
    assert short_export_chip(FRAME_MISMATCH_CHIP) == FRAME_MISMATCH_CHIP
    _assert_chengpian_not_a_deliverable_claim(FRAME_MISMATCH_CHIP)
    assert "精准" not in FRAME_MISMATCH_CHIP


def test_verify_missing_fps_fails_and_never_guesses_24_or_30(tmp_path: Path):
    """No metadata fps: 读不到帧率，未核对. Checker does not fall back to 24/30."""
    checker = (
        inspect.getsource(expected_source_frames)
        + inspect.getsource(frames_count_matches)
        + inspect.getsource(verify_locked_proxy_sequence)
        + inspect.getsource(count_proxy_exrs)
    )
    assert "CONSERVATIVE_FPS" not in checker
    assert "CONSERVATIVE_SECONDS" not in checker
    assert "clip_frame_count" not in checker
    assert "frame_count" not in inspect.getsource(expected_source_frames)
    assert "24.0" not in checker
    assert "30.0" not in checker
    assert "24" not in inspect.getsource(expected_source_frames)
    assert "30" not in inspect.getsource(expected_source_frames)
    assert "conservative" not in checker.lower()

    no_fps = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
    )
    expected, err = expected_source_frames(no_fps)
    assert expected is None
    assert err == MISSING_FPS_CHIP
    assert expected != 48
    assert expected != 60
    assert MISSING_FPS_CHIP == "读不到帧率，未核对"

    # Disk-estimate known count / 24×60 bait must not substitute for metadata fps.
    bait = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        frame_count=48,
    )
    bait_n, bait_err = expected_source_frames(bait)
    assert bait_n is None
    assert bait_err == MISSING_FPS_CHIP
    assert bait_n != 48
    known_only = BatchClip(
        "locked.mov", idt="sony_slog3_sgamut3", frame_count=48
    )
    known_n, known_err = expected_source_frames(known_only)
    assert known_n is None
    assert known_err == MISSING_FPS_CHIP

    no_duration = BatchClip("locked.mov", idt="sony_slog3_sgamut3", fps=25.0)
    expected_d, err_d = expected_source_frames(no_duration)
    assert expected_d is None
    assert err_d == MISSING_DURATION_CHIP
    assert expected_d != 1500
    assert MISSING_DURATION_CHIP == "读不到时长，未核对"

    grey = _slog3_grey()
    dest = tmp_path / "no_fps"
    report = process_locked_writes(
        [no_fps],
        dest,
        frames={"locked.mov": [grey] * 48},
        write_fn=_spy_exr,
    )
    assert report.written == ()
    assert report.errors[0].error == MISSING_FPS_CHIP
    chips = sidebar_export_chips([no_fps], report)
    assert chips["locked.mov"] == MISSING_FPS_CHIP
    assert chips["locked.mov"] != WRITTEN_CHIP
    assert not (dest / deliverable_dir_name("locked.mov")).exists()
    assert short_export_chip(MISSING_FPS_CHIP) == MISSING_FPS_CHIP
    _assert_chengpian_not_a_deliverable_claim(MISSING_FPS_CHIP)
    _assert_chengpian_not_a_deliverable_claim(MISSING_DURATION_CHIP)
    assert "精准" not in MISSING_FPS_CHIP

    dest_d = tmp_path / "no_dur"
    report_d = process_locked_writes(
        [no_duration],
        dest_d,
        frames={"locked.mov": [grey] * 2},
        write_fn=_spy_exr,
    )
    assert report_d.written == ()
    assert report_d.errors[0].error == MISSING_DURATION_CHIP
    assert not (dest_d / deliverable_dir_name("locked.mov")).exists()

    orphan = tmp_path / "orphan_ACES2065-1_proxy"
    orphan.mkdir()
    (orphan / "frame_000000.exr").write_bytes(b"x")
    ok, why = verify_locked_proxy_sequence(orphan, no_fps)
    assert ok is False
    assert why == MISSING_FPS_CHIP

    clip_src = _read(CLIP)
    verify_swift = clip_src.split("static func expectedSourceFrames")[1].split(
        "private func clearExportChips"
    )[0]
    assert "conservativeFPS" not in verify_swift
    assert "conservativeSeconds" not in verify_swift
    assert "estimatedFrameCount" not in verify_swift
    assert "frameCount" not in verify_swift
    assert "24.0" not in verify_swift
    assert "30.0" not in verify_swift
    assert " 24" not in verify_swift
    assert " 30" not in verify_swift
    export_body = clip_src.split("func exportLockedEXR")[1].split(
        "func cancelLockedDeliverables"
    )[0]
    assert "verifyLockedProxySequence" in export_body
    assert "removeItem(at: seqDir)" in export_body
    assert "countProxyEXRs" in clip_src
    assert "framesCountMatches" in clip_src
    assert FRAME_MISMATCH_CHIP in clip_src
    assert MISSING_FPS_CHIP in clip_src
    assert MISSING_DURATION_CHIP in clip_src
    assert "MediaFormat.extent" in verify_swift
    chip_fn = clip_src.split("static func shortExportChip")[1].split(
        "static func expectedSourceFrames"
    )[0]
    assert "frameMismatchChip" in chip_fn
    assert "missingFpsChip" in chip_fn
    assert "missingYCbCrTagsChip" in chip_fn
    media = _read(SWIFT_ROOT / "LogBridge/LogBridge/Models/MediaFormat.swift")
    assert "post-write" in media or "EXR count" in media
    assert "func extent(url:" in media
    content = _read(CONTENT)
    assert "struct SummaryPage" not in content
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert FRAME_MISMATCH_CHIP in readme and FRAME_MISMATCH_CHIP in acceptance
    assert MISSING_FPS_CHIP in readme and MISSING_FPS_CHIP in acceptance
    assert "never guesses 24 or 30" in readme
    assert "never guesses 24 or 30" in acceptance
    assert HONEST_PROXY_NOTE in readme
    _assert_chengpian_not_a_deliverable_claim(clip_src.split("static func expectedSourceFrames")[1].split("private func clearExportChips")[0])
    _assert_chengpian_not_a_deliverable_claim(readme)
    assert "精准" not in verify_swift


def test_verify_unlocked_still_skipped(tmp_path: Path):
    """Unlocked clips are not verified and produce no folder."""
    clips = [
        BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True),
        BatchClip("empty.mov"),
        BatchClip("stub.mov", idt="future", is_stub=True),
    ]
    grey = _slog3_grey()
    report = process_locked_writes(
        clips,
        tmp_path,
        frames={c.name: [grey] * 24 for c in clips},
    )
    assert report.processed_count == 0
    assert report.written == ()
    assert report.errors == ()
    assert report.skipped_count == 3
    chips = sidebar_export_chips(clips, report)
    assert chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert chips["empty.mov"] == REASON_PICK_LOG_GAMUT
    assert chips["stub.mov"] == REASON_PICK_PAIRED_IDT
    assert WRITTEN_CHIP not in chips.values()
    assert list(tmp_path.glob("**/*.exr")) == []
    assert list(tmp_path.glob("*" + DELIVERABLE_DIR_SUFFIX)) == []


def test_post_batch_summary_three_buckets(tmp_path: Path):
    """After 处理已锁定片段: 已写出代理 / 待选跳过 / 失败原因. No 成片/精准/24/30."""
    assert SKIPPED_BUCKET == "待选跳过"
    assert FAILED_BUCKET == "失败原因"
    assert WRITTEN_CHIP == "已写出代理"
    assert BATCH_SUMMARY_TEMPLATE == "{wrote} 条已写出代理 / {skipped} 条待选跳过 / {failed} 条失败"
    summary_src = inspect.getsource(batch_summary_text)
    assert "CONSERVATIVE_FPS" not in summary_src
    assert "CONSERVATIVE_SECONDS" not in summary_src
    assert "24.0" not in summary_src
    assert "30.0" not in summary_src
    assert " 24" not in summary_src
    assert " 30" not in summary_src
    assert "clip_frame_count" not in summary_src
    assert "estimatedFrameCount" not in summary_src
    _assert_chengpian_not_a_deliverable_claim(BATCH_SUMMARY_TEMPLATE)
    _assert_chengpian_not_a_deliverable_claim(SKIPPED_BUCKET)
    _assert_chengpian_not_a_deliverable_claim(FAILED_BUCKET)
    assert "精准" not in BATCH_SUMMARY_TEMPLATE
    assert "精准" not in SKIPPED_BUCKET
    assert "精准" not in FAILED_BUCKET
    assert "成片" not in WRITTEN_CHIP
    assert "成片" not in SKIPPED_BUCKET
    assert "成片" not in FAILED_BUCKET

    wrote = BatchClip(
        "locked.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
        fps=24.0,
    )
    pending = BatchClip("pending.mov", detected_curve="S-Log3", needs_user_picker=True)
    no_fps = BatchClip(
        "still.mov",
        idt="sony_slog3_sgamut3",
        duration_seconds=2.0,
    )
    grey = _slog3_grey()
    dest = tmp_path / "mixed"
    report = process_locked_writes(
        [wrote, pending, no_fps],
        dest,
        frames={
            "locked.mov": [grey] * 48,
            "pending.mov": [grey] * 48,
            "still.mov": [grey],
        },
        write_fn=_spy_exr,
    )
    note = report.processed_status_text
    assert "1 条已写出代理" in note
    assert "1 条待选跳过" in note
    assert "1 条失败" in note
    assert WRITTEN_CHIP in note
    assert SKIPPED_BUCKET in note
    assert FAILED_BUCKET in note
    assert MISSING_FPS_CHIP in note
    assert "still.mov：读不到帧率，未核对" in note
    chips = sidebar_export_chips([wrote, pending, no_fps], report)
    assert chips["locked.mov"] == WRITTEN_CHIP
    assert chips["pending.mov"] == REASON_PICK_PAIRED_IDT
    assert chips["still.mov"] == MISSING_FPS_CHIP
    assert clip_sequence_reveal_path("locked.mov", dest, chips["locked.mov"]) == (
        dest / deliverable_dir_name("locked.mov")
    )
    assert clip_sequence_reveal_path("still.mov", dest, chips["still.mov"]) is None
    assert clip_sequence_reveal_path("pending.mov", dest, chips["pending.mov"]) is None
    assert HONEST_PROXY_NOTE in note
    _assert_chengpian_not_a_deliverable_claim(note)
    assert "精准" not in note
    assert "一键还原" not in note
    # Stills / missing fps: do not guess 24/30 or 1-frame.
    assert "24 fps" not in note
    assert "30 fps" not in note
    assert "每秒 24" not in note
    assert "每秒 30" not in note
    assert "24" not in note
    assert "30" not in note
    assert "48" not in note
    assert "1-frame" not in note
    assert "1 帧" not in note

    empty = BatchClip("empty.mov")
    empty_note = batch_summary_text(0, 1, 0)
    assert "0 条已写出代理" in empty_note
    assert "1 条待选跳过" in empty_note
    assert "0 条失败" in empty_note
    assert FAILED_BUCKET not in empty_note
    assert "24" not in empty_note
    assert "30" not in empty_note

    cancel_note = batch_summary_text(1, 1, 1, [CANCELLED_NOTE])
    assert CANCELLED_NOTE in cancel_note
    assert FAILED_BUCKET in cancel_note
    assert "1 条已写出代理" in cancel_note
    disk_note = batch_summary_text(0, 1, 1, [DISK_SHORT_STATUS])
    assert DISK_SHORT_STATUS in disk_note
    assert FAILED_BUCKET in disk_note
    assert "每秒 24" not in disk_note
    assert str(int(CONSERVATIVE_SECONDS)) not in disk_note

    clip = _read(CLIP)
    content = _read(CONTENT)
    summary_swift = clip.split("static func batchSummaryText")[1].split(
        "func exportLockedEXR"
    )[0]
    assert WRITTEN_CHIP in summary_swift
    assert SKIPPED_BUCKET in summary_swift
    assert "failedBucket" in summary_swift
    assert SKIPPED_BUCKET in clip
    assert FAILED_BUCKET in clip
    assert HONEST_PROXY_NOTE in summary_swift
    assert "conservativeFPS" not in summary_swift
    assert "conservativeSeconds" not in summary_swift
    assert "24.0" not in summary_swift
    assert "30.0" not in summary_swift
    assert " 24" not in summary_swift
    assert " 30" not in summary_swift
    assert "estimatedFrameCount" not in summary_swift
    _assert_chengpian_not_a_deliverable_claim(summary_swift)
    assert "精准" not in summary_swift
    write_body = clip.split("func writeLockedDeliverables")[1].split(
        "func exportLockedEXR"
    )[0]
    assert "batchSummaryText" in write_body
    assert "diskShortStatus" in write_body.split("neededWithMargin")[1]
    assert "cancelledNote" in write_body
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert "showsBatchSummary" in bar
    assert "lastExportNote" in bar
    assert 'Button("处理已锁定片段")' not in content.split("struct StatusBar")[1]
    assert "struct SummaryPage" not in content
    assert "revealClipExportInFinder" in _read(SIDEBAR)
    assert WRITTEN_CHIP in _read(SIDEBAR)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert SKIPPED_BUCKET in readme and SKIPPED_BUCKET in acceptance
    assert FAILED_BUCKET in readme and FAILED_BUCKET in acceptance
    assert "N 条已写出代理 / M 条待选跳过 / K 条失败" in readme
    assert "N 条已写出代理 / M 条待选跳过 / K 条失败" in acceptance
    _assert_chengpian_not_a_deliverable_claim(readme)
    _assert_chengpian_not_a_deliverable_claim(acceptance)
    _assert_chengpian_not_a_deliverable_claim(content)
