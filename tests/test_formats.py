"""Container / codec policy. No color numbers. Never 全格式已支持."""

from pathlib import Path

from color.formats import (
    ACCEPT,
    REFUSE,
    TRY,
    classify,
    empty_metadata_note,
)

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "macos/LogBridge/LogBridge/Preview/PreviewEngine.swift"
CLIP = ROOT / "macos/LogBridge/LogBridge/Models/Clip.swift"
MEDIA = ROOT / "macos/LogBridge/LogBridge/Models/MediaFormat.swift"
DETECTOR = ROOT / "macos/LogBridge/LogBridge/Detection/ClipDetector.swift"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_mov_mp4_prores_h264_hevc_accept():
    assert classify("A.mov").action == ACCEPT
    assert classify("A.mp4", "avc1").action == ACCEPT
    assert classify("A.m4v", "hvc1").action == ACCEPT
    assert classify("A.mov", "apch").action == ACCEPT
    assert classify("A.mov", "ap4x").action == ACCEPT
    assert classify("A.mp4", "hevc").action == ACCEPT


def test_stills_tiff_dpx_exr_accept():
    for name in ("plate.tif", "plate.tiff", "plate.dpx", "plate.exr"):
        d = classify(name)
        assert d.action == ACCEPT
        assert d.kind == "still"
        assert "ImageIO" in d.note


def test_stills_preview_and_write_skip_ycbcr_unpack():
    """TIFF / DPX / EXR are already RGB. ImageIO only. #31 unpack is movies."""
    engine = _read(ENGINE)
    media = _read(MEDIA)
    assert 'stillExt: Set<String> = ["tif", "tiff", "dpx", "exr"]' in media
    assert "静帧" in media
    assert "ImageIO" in media
    down = engine.split("func decodeDownscaled")[1].split(
        "return try decodeMovieVideoToolbox"
    )[0]
    assert "decodeStillImageIO" in down
    assert "requireSourceYCbCrUnpack" not in down
    still = engine.split("func decodeStillImageIO")[1].split("enum PreviewColor")[0]
    assert "Already RGB" in still or "already RGB" in engine
    assert "requireSourceYCbCrUnpack" not in still
    assert "CGImageSourceCreateThumbnailAtIndex" in still
    full = engine.split("func decodeStillFullImageIO")[1].split(
        "/// Preview stills thumbnail"
    )[0]
    assert "CGImageSourceCreateImageAtIndex" in full
    assert "Thumbnail" not in full
    assert "maxLongEdge" not in full
    write_stills = engine.split("func decodeAllSourceFrames")[1].split(
        "func decodeFirstSourceRGB"
    )[0]
    assert "decodeStillFullImageIO" in write_stills
    assert "decodeStillImageIO(" not in write_stills


def test_arri_mxf_refused():
    d = classify("A001C001.mxf", "ARRIRAW")
    assert d.action == REFUSE
    assert d.note == "ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入"


def test_mxf_known_codec_is_try_not_claim():
    d = classify("clip.mxf", "apcn")
    assert d.action == TRY
    assert "ARRI MXF" in d.note
    d2 = classify("clip.mxf")
    assert d2.action == TRY


NOTE_RAW = "R3D / BRAW：暂不支持，请在相机软件转 ProRes / EXR"
NOTE_ARRI = "ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入"


def test_refused_containers():
    for name in ("clip.r3d", "clip.braw", "clip.crm", "clip.dng", "clip.nev", "clip.xocn"):
        d = classify(name)
        assert d.action == REFUSE, name
        assert d.note == NOTE_RAW
    for name in ("clip.ari", "clip.arx"):
        d = classify(name)
        assert d.action == REFUSE, name
        assert d.note == NOTE_RAW
    for name, token in (("clip.avi", "AVI"), ("clip.mkv", "MKV")):
        d = classify(name)
        assert d.action == REFUSE, name
        assert token in d.note


def test_crm_xocn_nraw_prores_raw_same_r3d_copy():
    for path, codec in (
        ("clip.crm", None),
        ("clip.mxf", "xocn"),
        ("clip.mov", "nraw"),
        ("clip.mov", "aprn"),
        ("clip.mov", "ProRes RAW"),
        ("clip.mov", "aprh"),
    ):
        d = classify(path, codec)
        assert d.action == REFUSE, (path, codec)
        assert d.note == NOTE_RAW


def test_unknown_codec_in_mov_refused():
    d = classify("weird.mov", "r210")
    assert d.action == REFUSE
    assert d.note == "这个编码不接。能试的是 ProRes / H.264 / HEVC。"
    assert "R3D" not in d.note
    assert "BRAW" not in d.note


def test_empty_metadata_prompts_paired_idt():
    note = empty_metadata_note()
    assert note == "先选择 Log 与色域"
    assert "5600" not in note


def test_never_claim_all_formats():
    blob = (
        _read(ROOT / "README.md")
        + _read(ROOT / "ACCEPTANCE.md")
        + _read(MEDIA)
        + _read(ENGINE)
        + _read(CLIP)
    )
    # Phrase is named so reviewers can grep. Only allowed as a prohibition.
    for i, line in enumerate(blob.splitlines()):
        if "全格式已支持" in line:
            assert any(tok in line for tok in ("不写", "Not ", "never", "Never", "Do **not**", "Claiming")), line
    assert "ARRI MXF" in blob
    assert "不接" in blob


def test_swift_probe_and_decode_locks():
    media = _read(MEDIA)
    engine = _read(ENGINE)
    clip = _read(CLIP)
    detector = _read(DETECTOR)
    assert "enum MediaFormat" in media
    assert "ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入" in media
    assert "R3D / BRAW：暂不支持，请在相机软件转 ProRes / EXR" in media
    assert "aprn" in media
    assert "这个编码不接。能试的是 ProRes / H.264 / HEVC。" in media
    assert "ImageIO" in media
    assert "AVAssetReader" in engine
    assert "YpCbCr" in engine
    decode = engine.split("decodeMovieVideoToolbox")[1].split("decodeStillImageIO")[0]
    assert "copyCGImage(" not in decode
    assert "Never copyCGImage" in decode or "no copyCGImage" in decode
    assert "AVVideoColorPropertiesKey:" not in engine
    assert "Never set AVVideoColorPropertiesKey" in engine
    assert "MediaFormat.probe" in clip
    assert "lastImportNote" in clip
    assert "读不到元数据，先选择 Log 与色域" in detector
    assert "D-Log M" in detector
    assert "Apple Log 2" in detector
