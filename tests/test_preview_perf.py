"""Preview perf locks: VT decode, Metal same matrices, scrub ODT-only, stale drop."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "macos/LogBridge/LogBridge/Preview/PreviewEngine.swift"
CLIP = ROOT / "macos/LogBridge/LogBridge/Models/Clip.swift"
SOURCE = ROOT / "macos/LogBridge/LogBridge/Color/Rec709PreviewView.swift"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_vt_decode_not_709():
    engine = _read(ENGINE)
    assert "import VideoToolbox" in engine
    assert "decodeMovieVideoToolbox" in engine
    assert "do not let VT emit Rec.709" in engine or "No VT color convert to 709" in engine
    assert "AVAssetReader" in engine
    assert "YpCbCr" in engine
    assert "no 709 transfer" in engine
    decode = engine.split("decodeMovieVideoToolbox")[1].split("decodeStillImageIO")[0]
    assert "copyCGImage(" not in decode
    assert "Never copyCGImage" in decode or "no copyCGImage" in decode
    assert "MediaFormat.probe" in engine
    assert "AVVideoColorPropertiesKey:" not in engine
    assert "Never set AVVideoColorPropertiesKey" in engine


def test_metal_same_locked_matrices():
    engine = _read(ENGINE)
    assert "enum PreviewMetal" in engine
    assert "applyMatrix" in engine
    assert "0.018053968510807" in engine
    assert "1.09929682680944" in engine
    assert "No Core Image" in engine or "no Core Image" in engine.lower()
    assert "Display P3" in engine


def test_graded_cache_scrub_skips_idt():
    engine = _read(ENGINE)
    clip = _read(CLIP)
    assert "gradedCache" in engine
    assert "refreshODT" in engine
    assert "Scrub does not re-run IDT" in engine
    assert "func refreshODTOnly()" in clip
    assert "setODT" in clip
    assert "refreshODTOnly()" in clip


def test_set_odt_uses_refresh_odt_only():
    """setODT / setODTEnabled must call refreshODTOnly, not a full rebuild."""
    clip = _read(CLIP)
    set_odt = clip.split("func setODT(")[1].split("func setWBParams")[0]
    assert "refreshODTOnly()" in set_odt
    assert "refreshPreview()" not in set_odt
    assert "invalidateWBODT" not in set_odt
    assert "invalidateIDT" not in set_odt
    set_en = clip.split("func setODTEnabled")[1].split("func setODT(")[0]
    assert "refreshODTOnly()" in set_en
    assert "refreshPreview()" not in set_en
    assert "invalidateWBODT" not in set_en
    only = clip.split("func refreshODTOnly()")[1].split("var pendingPickerCount")[0]
    assert "preview.refreshODT" in only
    assert "preview.refresh(" not in only
    exp = clip.split("func setExposureStops")[1].split("func setWBEnabled")[0]
    assert "invalidateWBODT" in exp
    assert "refreshPreview()" in exp
    assert "refreshODTOnly()" not in exp


def test_odt_only_refresh_skips_decode_and_write_unpack():
    """Scrub / ODT hit: ODT only. No Y′CbCr decode, IDT, exposure/WB, or #31 unpack."""
    engine = _read(ENGINE)
    odt_hit = engine.split("func refreshODT(")[1].split("private func build(")[0]
    assert "applyODTFromGradedOrRebuild" in odt_hit
    assert "gradedCacheHit" in odt_hit
    assert "renderODTFromGraded" in odt_hit
    assert "publishODTOnly" in odt_hit
    assert "PreviewColor.applyODT" in odt_hit
    assert "decodeMovieAllFrames" not in odt_hit
    assert "rgbFloatFromLogPixelBuffer" not in odt_hit
    assert "requireSourceYCbCrUnpack" not in odt_hit
    assert "decodeAllSourceFrames" not in odt_hit
    assert "decodeMovieVideoToolbox" not in odt_hit
    assert "decodeDownscaled" not in odt_hit
    assert "cachedSource" not in odt_hit
    assert "applyIDT" not in odt_hit
    assert "applyExposure" not in odt_hit
    assert "applyWB" not in odt_hit
    assert "extractRGB" not in odt_hit
    assert "正在解码预览" not in odt_hit
    key = engine.split("func gradeKey")[1].split("func cachedGraded")[0]
    assert "graph.odt" not in key
    assert "exposureStops" in key
    assert "wbEnabled" in key


def test_source_not_tagged_709_extract_device_rgb():
    engine = _read(ENGINE)
    source = _read(SOURCE)
    assert "Device RGB" in engine
    assert "not Display P3" in engine
    assert "itur_709" in engine
    assert "Never `CGColorSpace.itur_709`" in source or "Never CGColorSpace.itur_709" in source


def test_stale_preview_decode_dropped_on_selection_change():
    """Arrow / click can outrun first-frame decode. Drop stale preview, not export."""
    engine = _read(ENGINE)
    clip = _read(CLIP)

    assert "beginPreviewRequest" in engine
    assert "isCurrentPreview" in engine
    assert "requestedClipID" in engine
    assert "pendingPreviewWork" in engine
    assert "DispatchWorkItem" in engine
    assert "enqueuePreview" in engine
    assert "pendingPreviewWork?.cancel()" in engine
    assert "OperationQueue" not in engine
    assert "ThreadPool" not in engine
    assert 'DispatchQueue(label: "app.logbridge.preview"' in engine
    assert "not a thread pool" in engine

    begin = engine.split("func beginPreviewRequest")[1].split("func isCurrentPreview")[0]
    assert "generation += 1" in begin
    assert "requestedClipID = clipID" in begin
    assert "pendingPreviewWork?.cancel()" in begin
    assert "exportGradedAP0" in begin
    assert "queue.sync" in begin
    assert "精准" not in begin

    current = engine.split("func isCurrentPreview")[1].split("func enqueuePreview")[0]
    assert "generation != gen" in current
    assert "requestedClipID != clipID" in current
    assert "精准" not in current

    refresh = engine.split("func refresh(")[1].split("func refreshODT(")[0]
    assert "beginPreviewRequest(clipID: clip?.id)" in refresh
    assert "enqueuePreview" in refresh
    assert "self?.build(" in refresh
    assert "OperationQueue" not in refresh
    assert "精准" not in refresh

    refresh_odt = engine.split("func refreshODT(")[1].split("private func applyODTFromGradedOrRebuild")[0]
    assert "beginPreviewRequest(clipID: clip?.id)" in refresh_odt
    assert "enqueuePreview" in refresh_odt
    assert "applyODTFromGradedOrRebuild" in refresh_odt
    assert "精准" not in refresh_odt

    build = engine.split("private func build(")[1].split("private static func gradeKey")[0]
    assert build.count("isCurrentPreview") >= 2
    assert "cachedSource(clip: clip, generation: generation)" in build
    assert "clipID: clip.id" in build
    assert "精准" not in build

    cached = engine.split("func cachedSource")[1].split("func cachedLinear")[0]
    assert "isCurrentPreview" in cached
    assert "decodeDownscaled" in cached
    assert cached.index("isCurrentPreview") < cached.index("decodeDownscaled")

    publish = engine.split("private func publish(")[1].split("/// Graded ACES2065-1")[0]
    assert "isCurrentPreview(generation: generation, clipID: clipID)" in publish
    assert "self.sourceImage = source" in publish
    assert "self.odtImage = odt" in publish

    publish_odt = engine.split("private func publishODTOnly")[1].split("private func build(")[0]
    assert "isCurrentPreview(generation: generation, clipID: clipID)" in publish_odt
    assert "self.odtImage = odt" in publish_odt
    assert "self.sourceImage" not in publish_odt

    export_first = engine.split("func exportGradedAP0(")[1].split(
        "func exportGradedAP0Sequence"
    )[0]
    assert "queue.sync" in export_first
    assert "beginPreviewRequest" not in export_first
    assert "pendingPreviewWork" not in export_first
    assert "isCurrentPreview" not in export_first

    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    assert "queue.sync" in export_seq
    assert "beginPreviewRequest" not in export_seq
    assert "pendingPreviewWork" not in export_seq
    assert "isCurrentPreview" not in export_seq
    assert "writeCAT" in export_seq

    odt_hit = engine.split("func refreshODT(")[1].split("private func build(")[0]
    assert "gradedCacheHit" in odt_hit
    assert "publishODTOnly" in odt_hit
    assert "decodeDownscaled" not in odt_hit
    assert "decodeMovieVideoToolbox" not in odt_hit
    assert "rgbFloatFromLogPixelBuffer" not in odt_hit

    session_refresh = clip.split("func refreshPreview()")[1].split("func refreshODTOnly()")[0]
    assert "preview.refresh(clip: selectedClip" in session_refresh
    assert "stale" in session_refresh.lower() or "selected" in session_refresh.lower()

    assert "预览·非成片" in engine
    assert "整段代理，不是全精度成片" in engine
    assert "精准" not in session_refresh


def test_preview_caches_keep_only_selected_clip():
    """Mixed-bin preview must not keep every clip's source/linear/graded forever."""
    engine = _read(ENGINE)
    clip = _read(CLIP)

    assert "func retainPreviewCaches" in engine
    assert "func evict(clipID:" in engine
    retain_blob = engine.split("/// Preview dictionaries only.")[1].split(
        "func beginPreviewRequest"
    )[0]
    assert "func evict(clipID:" in retain_blob
    assert "func retainPreviewCaches" in retain_blob
    retain = retain_blob.split("func retainPreviewCaches")[1]
    assert "evict(clipID:" in retain
    assert "sourceCache" in retain
    assert "linearCache" in retain
    assert "gradedCache" in retain
    assert "not evicted here" in retain_blob
    assert "decodeAllSourceFrames" not in retain
    assert "精准" not in retain

    refresh = engine.split("func refresh(")[1].split("func refreshODT(")[0]
    assert "retainPreviewCaches(keeping: clip?.id)" in refresh
    assert "beginPreviewRequest(clipID: clip?.id)" in refresh
    assert "enqueuePreview" in refresh
    assert "OperationQueue" not in refresh
    assert "精准" not in refresh

    refresh_odt = engine.split("func refreshODT(")[1].split(
        "private func applyODTFromGradedOrRebuild"
    )[0]
    assert "retainPreviewCaches(keeping: clip?.id)" in refresh_odt
    assert "beginPreviewRequest(clipID: clip?.id)" in refresh_odt
    assert "精准" not in refresh_odt

    odt = engine.split("private func applyODTFromGradedOrRebuild")[1].split(
        "private func gradedCacheHit"
    )[0]
    assert "retainPreviewCaches(keeping: clip.id)" in odt
    assert odt.index("isCurrentPreview") < odt.index("retainPreviewCaches")
    assert "gradedCacheHit" in odt
    assert "精准" not in odt

    build = engine.split("private func build(")[1].split("private static func gradeKey")[0]
    assert "retainPreviewCaches(keeping: clip.id)" in build
    assert build.index("isCurrentPreview") < build.index("retainPreviewCaches")
    assert "cachedSource" in build
    assert "精准" not in build

    odt_hit = engine.split("func refreshODT(")[1].split("private func build(")[0]
    assert "gradedCacheHit" in odt_hit
    assert "publishODTOnly" in odt_hit
    assert "decodeDownscaled" not in odt_hit
    assert "decodeMovieVideoToolbox" not in odt_hit
    assert "rgbFloatFromLogPixelBuffer" not in odt_hit

    export_first = engine.split("func exportGradedAP0(")[1].split(
        "func exportGradedAP0Sequence"
    )[0]
    assert "retainPreviewCaches" not in export_first
    assert "evict(" not in export_first
    assert "beginPreviewRequest" not in export_first
    assert "pendingPreviewWork" not in export_first

    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    assert "retainPreviewCaches" not in export_seq
    assert "evict(" not in export_seq
    assert "beginPreviewRequest" not in export_seq
    assert "pendingPreviewWork" not in export_seq
    assert "writeCAT" in export_seq

    remove = clip.split("func removeSelectedClipFromSession")[1].split(
        "func isArrowConsumedByTextInput"
    )[0]
    assert "preview.evict(clipID:" in remove
    assert "retainPreviewCaches" not in remove
    assert "exportGradedAP0" not in remove
    assert "FileManager" not in "\n".join(
        line.split("//", 1)[0]
        for line in remove.splitlines()
        if not line.lstrip().startswith("//")
    )

    assert "OperationQueue" not in engine
    assert "ThreadPool" not in engine
    assert 'DispatchQueue(label: "app.logbridge.preview"' in engine
    assert "not a thread pool" in engine
    assert "预览·非成片" in engine
    assert "整段代理，不是全精度成片" in engine

    session_refresh = clip.split("func refreshPreview()")[1].split("func refreshODTOnly()")[0]
    assert "preview.refresh(clip: selectedClip" in session_refresh
    assert "preview.exportGradedAP0" not in session_refresh
    assert "精准" not in session_refresh


def test_preview_decode_stays_8bit_first_and_scrub_odt_only():
    """Preview may stay 8-bit. Write-path 10-bit float must not steal scrub caches."""
    engine = _read(ENGINE)
    preview = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func readFirstYpCbCrFrame"
    )[0]
    eight_420 = "kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange"
    eight_422 = "kCVPixelFormatType_422YpCbCr8"
    ten = "kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange"
    assert preview.index(eight_420) < preview.index(eight_422)
    assert preview.index(eight_422) < preview.index(ten)
    cached = engine.split("func cachedSource")[1].split("func cachedLinear")[0]
    assert "decodeDownscaled" in cached
    assert "extractRGB" in cached
    assert "maxLongEdge: Self.maxLongEdge" in cached
    assert "gradedCache" in engine
    assert "Scrub does not re-run IDT" in engine
    assert "rgbFloatFromLogPixelBuffer" not in cached
    assert "预览·非成片" in engine
    assert "整段代理，不是全精度成片" in engine


def test_preview_unpack_shares_source_ycbcr_helper():
    """Movie preview first-frame uses #31 nclc/colr/vui matrix+range. Display stays 8-bit/1920."""
    engine = _read(ENGINE)
    assert "static let maxLongEdge: CGFloat = 1920" in engine
    assert "exportMaxLongEdge" not in engine
    assert "static let writeLongEdgeCeiling = 16384" in engine
    assert "requireWriteSourcePixels" in engine
    assert "片源边长超过 16384，未写出" in engine
    require = engine.split("func requireWriteSourcePixels")[1].split(
        "func writeCAT"
    )[0]
    assert "writeLongEdgeCeiling" in require
    assert "scale" not in require
    assert "maxLongEdge" not in require
    assert "1920" not in require

    preview = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func decodeStillImageIO"
    )[0]
    preview_cg = engine.split("func cgImageFromLogPixelBuffer")[1].split(
        "func writeMatrixRGB"
    )[0]
    write_matrix = engine.split("func writeMatrixRGB")[1].split(
        "func decodeStillImageIO"
    )[0]
    require = engine.split("func requireSourceYCbCrUnpack")[1].split(
        "func ycbcrMatrixCoeffs"
    )[0]
    movie = engine.split("func decodeMovieAllFrames")[1].split(
        "func linearAP0Frame"
    )[0]
    export_first = engine.split("func exportGradedAP0(")[1].split(
        "func exportGradedAP0Sequence"
    )[0]
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    cached = engine.split("func cachedSource")[1].split("func cachedLinear")[0]
    build = engine.split("private func build(")[1].split("private static func gradeKey")[0]
    odt_hit = engine.split("func refreshODT(")[1].split("private func build(")[0]

    assert "requireSourceYCbCrUnpack" in preview
    assert "requireSourceYCbCrUnpack" in preview_cg
    assert "missingYCbCrTagsChip" in preview
    assert "无法读取片源 Y′CbCr 矩阵/范围，未写出" in preview
    assert "No 709-video default" in preview
    assert "no 709 transfer" in preview.lower() or "no 709 transfer" in preview_cg.lower()
    assert "rec709OETF" not in preview
    assert "applyODT" not in preview
    assert "applyIDT" not in preview
    assert "bitsPerComponent: 8" in preview_cg
    assert "writeMatrixRGB" in preview_cg
    assert "yOff: 16" not in preview_cg
    assert "yOff: 64" not in preview_cg
    assert "1.5748" not in write_matrix
    assert "unpack.rv" in write_matrix
    assert "unpack.gu" in write_matrix
    assert "nclc / colr / vui" in engine
    assert "missingYCbCrTagsChip" in require

    assert "maxLongEdge: Self.maxLongEdge" in cached
    assert "decodeDownscaled" in cached
    assert "extractRGB" in cached
    assert "rgbFloatFromLogPixelBuffer" not in cached
    assert "exportMaxLongEdge" not in cached
    assert "localizedDescription" in build
    assert "无法读取片源 Y′CbCr 矩阵/范围，未写出" in engine

    assert "requireSourceYCbCrUnpack" in movie
    assert "rgbFloatFromLogPixelBuffer" in movie
    assert "writeMatrixRGB(" not in movie
    assert "cgImageFromLogPixelBuffer(" not in movie
    assert "maxLongEdge" not in export_first
    assert "exportMaxLongEdge" not in export_first
    assert "maxLongEdge" not in export_seq
    assert "exportMaxLongEdge" not in export_seq
    assert "decodeDownscaled" not in export_first
    assert "decodeDownscaled" not in export_seq
    assert "extractRGB" not in export_seq
    assert "/ 255" not in export_seq
    assert "gradedCache" not in export_seq

    assert "requireSourceYCbCrUnpack" not in odt_hit
    assert "decodeMovieVideoToolbox" not in odt_hit
    assert "rgbFloatFromLogPixelBuffer" not in odt_hit
    assert "publishODTOnly" in odt_hit
    assert "预览·非成片" in engine
    assert "整段代理，不是全精度成片" in engine


def test_preview_stills_imageio_no_ycbcr_unpack():
    """TIFF / DPX / EXR stay ImageIO. Already RGB. Only movies share #31 unpack."""
    engine = _read(ENGINE)
    media = ROOT / "macos/LogBridge/LogBridge/Models/MediaFormat.swift"
    media_txt = _read(media)
    assert 'stillExt: Set<String> = ["tif", "tiff", "dpx", "exr"]' in media_txt

    down = engine.split("func decodeDownscaled")[1].split(
        "return try decodeMovieVideoToolbox"
    )[0]
    assert "probe.kind == .still" in down
    assert "decodeStillImageIO" in down
    assert down.index("probe.kind == .still") < down.index("decodeStillImageIO")
    assert "requireSourceYCbCrUnpack" not in down
    assert "rgbFloatFromLogPixelBuffer" not in down
    assert "cgImageFromLogPixelBuffer" not in down

    still = engine.split("func decodeStillImageIO")[1].split("enum PreviewColor")[0]
    assert "requireSourceYCbCrUnpack" not in still
    assert "rgbFloatFromLogPixelBuffer" not in still
    assert "writeMatrixRGB" not in still
    assert "nclc" not in still.lower()
    assert "colr" not in still.lower()
    assert "CGImageSourceCreateThumbnailAtIndex" in still
    full = engine.split("func decodeStillFullImageIO")[1].split(
        "/// Preview stills thumbnail"
    )[0]
    assert "CGImageSourceCreateImageAtIndex" in full
    assert "Thumbnail" not in full
    assert "maxLongEdge" not in full
    assert "1920" not in full

    all_src = engine.split("func decodeAllSourceFrames")[1].split(
        "func decodeFirstSourceRGB"
    )[0]
    still_all = all_src.split("if probe.kind == .still")[1].split(
        "try decodeMovieAllFrames"
    )[0]
    assert "decodeStillFullImageIO" in still_all
    assert "decodeStillImageIO(" not in still_all
    assert "maxLongEdge" not in still_all
    assert "extractRGB" in still_all
    assert "requireSourceYCbCrUnpack" not in still_all
    assert "rgbFloatFromLogPixelBuffer" not in still_all

    first = engine.split("func decodeFirstSourceRGB")[1].split(
        "func decodeMovieAllFrames"
    )[0]
    still_first = first.split("if probe.kind == .still")[1].split("let formats")[0]
    assert "decodeStillFullImageIO" in still_first
    assert "decodeStillImageIO(" not in still_first
    assert "maxLongEdge" not in still_first
    assert "requireSourceYCbCrUnpack" not in still_first
    assert "rgbFloatFromLogPixelBuffer" not in still_first

    movie_preview = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func decodeStillImageIO"
    )[0]
    assert "requireSourceYCbCrUnpack" in movie_preview
    assert "预览·非成片" in engine
    assert "整段代理，不是全精度成片" in engine


def test_export_write_overlaps_next_copynext():
    """Locked write: EXR of N overlaps sequential copyNext of N+1. One write only."""
    engine = _read(ENGINE)
    clip = _read(CLIP)
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    movie = engine.split("func decodeMovieAllFrames")[1].split(
        "func linearAP0Frame"
    )[0]
    grade = engine.split("func gradeAP0")[1].split("func exportGradedAP0(")[0]
    read_all = engine.split("func readAllYpCbCrFrames")[1].split(
        "func readFirstYpCbCrRGB"
    )[0]
    export_body = clip.split("func exportLockedEXR")[1].split(
        "func cancelLockedDeliverables"
    )[0]

    assert "exportWriteQueue" not in engine
    assert 'DispatchQueue(label: "app.logbridge.export.write"' not in engine
    assert engine.count('DispatchQueue(label:') == 1
    assert 'DispatchQueue(label: "app.logbridge.preview"' in engine
    assert "one write overlap" in export_seq
    assert "joinExportWrite" in export_seq
    assert "writeFrame" in export_seq
    on_frame = export_seq.split("decodeAllSourceFrames")[1]
    assert "DispatchQueue.global" in on_frame
    assert on_frame.index("gradeAP0") < on_frame.index("joinExportWrite")
    assert on_frame.index("joinExportWrite") < on_frame.index(
        "DispatchQueue.global"
    )
    assert on_frame.index("DispatchQueue.global") < on_frame.index("count += 1")
    work = on_frame.split("DispatchWorkItem")[1].split("pendingWrite")[0]
    assert "writeFrame(index, pixels, w, h)" in work
    assert "DispatchQueue.global" in on_frame.split("DispatchWorkItem")[1]
    assert export_seq.count("joinExportWrite()") >= 2
    assert "try writeFrame(count, rgb, width, height)" not in export_seq

    assert "while let sample = output.copyNextSampleBuffer()" in read_all
    assert "requestedTime" not in movie
    assert "AVAssetImageGenerator" not in movie
    assert "seek(" not in movie
    assert "copyNextSampleBuffer" in movie

    assert "exportMaxLongEdge" not in engine
    assert "static let writeLongEdgeCeiling = 16384" in engine
    assert "requireWriteSourcePixels" in engine
    assert "maxLongEdge" not in export_seq
    assert "decodeDownscaled" not in export_seq
    assert "extractRGB" not in export_seq
    assert "/ 255" not in export_seq
    assert "gradedCache" not in export_seq

    assert "writeCAT" in export_seq
    assert "applyODT" not in export_seq
    assert "applyODT" not in grade
    assert "applyPreparedCAT" in grade
    assert "requireSourceYCbCrUnpack" in movie
    assert "rec709OETF" not in movie
    assert "writeMatrixRGB(" not in movie
    assert "applyYCbCrMatrixToFloat" in movie

    odt_hit = engine.split("func refreshODT(")[1].split("private func build(")[0]
    assert "publishODTOnly" in odt_hit
    assert "gradedCacheHit" in odt_hit
    assert "refreshODT" not in export_seq
    assert "retainPreviewCaches" not in export_seq
    assert "evict(" not in export_seq
    assert "func retainPreviewCaches" in engine
    assert "func evict(clipID:" in engine

    assert "writeACES2065EXR" in export_body
    assert "sequenceFrameURL" in export_body
    assert "removeItem" in export_body
    assert "LockedWriteCancel" in export_body
    assert "applyODT" not in export_body

    assert "OperationQueue" not in engine
    assert "ThreadPool" not in engine
    assert "not a thread pool" in engine
    assert "整段代理，不是全精度成片" in engine
    assert "预览·非成片" in engine
    assert "精准" not in export_seq
    assert "精准" not in export_body


def test_export_write_is_source_pixels_not_preview_1920_8bit():
    """Write decode is source pixels / native Y′CbCr. Preview stays 8-bit / 1920."""
    engine = _read(ENGINE)
    clip = _read(CLIP)
    hdr = _read(ROOT / "macos/LogBridge/LogBridge/Color/HDRPreview.swift")
    preview_709 = _read(SOURCE)
    graph = _read(ROOT / "macos/LogBridge/LogBridge/Models/NodeGraph.swift")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    batch = (ROOT / "color/batch.py").read_text(encoding="utf-8")

    assert "static let maxLongEdge: CGFloat = 1920" in engine
    assert "exportMaxLongEdge" not in engine
    assert "static let writeLongEdgeCeiling = 16384" in engine
    assert "requireWriteSourcePixels" in engine
    assert "片源边长超过 16384，未写出" in engine
    require = engine.split("func requireWriteSourcePixels")[1].split(
        "func writeCAT"
    )[0]
    assert "writeLongEdgeCeiling" in require
    assert "scale" not in require
    assert "maxLongEdge" not in require
    assert "1920" not in require

    export_first = engine.split("func exportGradedAP0(")[1].split(
        "func exportGradedAP0Sequence"
    )[0]
    export_seq = engine.split("func exportGradedAP0Sequence")[1].split(
        "func decodeAllSourceFrames"
    )[0]
    all_src = engine.split("func decodeAllSourceFrames")[1].split(
        "func decodeFirstSourceRGB"
    )[0]
    first = engine.split("func decodeFirstSourceRGB")[1].split(
        "func decodeMovieAllFrames"
    )[0]
    movie = engine.split("func decodeMovieAllFrames")[1].split(
        "func linearAP0Frame"
    )[0]
    write_float = engine.split("func rgbFloatFromLogPixelBuffer")[1].split(
        "func applyYCbCrMatrixToFloat"
    )[0]
    preview_cg = engine.split("func cgImageFromLogPixelBuffer")[1].split(
        "func writeMatrixRGB"
    )[0]
    preview_movie = engine.split("func decodeMovieVideoToolbox")[1].split(
        "func decodeStillImageIO"
    )[0]
    cached = engine.split("func cachedSource")[1].split("func cachedLinear")[0]
    odt = engine.split("func renderODTFromGraded")[1].split("func publishODTOnly")[0]

    assert "maxLongEdge" not in export_first
    assert "maxLongEdge" not in export_seq
    assert "maxLongEdge" not in all_src
    assert "maxLongEdge" not in first
    assert "maxLongEdge" not in write_float
    assert "decodeDownscaled" not in export_first
    assert "decodeDownscaled" not in export_seq
    assert "decodeStillFullImageIO" in all_src
    assert "decodeStillFullImageIO" in first
    assert "decodeStillImageIO(" not in all_src.split("if probe.kind == .still")[1]
    assert "CGImageSourceCreateThumbnailAtIndex" not in all_src
    assert "kCGImageSourceThumbnailMaxPixelSize" not in all_src
    assert "requireSourceYCbCrUnpack" in movie
    assert "applyYCbCrMatrixToFloat" in movie
    assert "writeMatrixRGB(" not in movie
    assert "cgImageFromLogPixelBuffer(" not in movie
    assert "/ 255" not in export_seq
    assert "gradedCache" not in export_seq
    assert "bitsPerComponent: 8" not in write_float
    assert "u8(" not in write_float
    assert "requireWriteSourcePixels" in write_float
    assert "requireWriteSourcePixels" in all_src
    assert "requireWriteSourcePixels" in first
    assert "scale =" not in write_float
    assert "Double(maxLongEdge)" not in write_float

    assert "maxLongEdge: Self.maxLongEdge" in cached
    assert "decodeDownscaled" in cached
    assert "rgbFloatFromLogPixelBuffer" not in cached
    assert "bitsPerComponent: 8" in preview_cg
    assert "writeMatrixRGB" in preview_cg
    assert "maxLongEdge" in preview_cg
    assert 'static let maxLongEdge: CGFloat = 1920' in engine
    eight_420 = "kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange"
    ten = "kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange"
    assert preview_movie.index(eight_420) < preview_movie.index(ten)
    assert movie.index(ten) < movie.index(eight_420)

    assert "PreviewColor.applyODT" in odt
    assert "HDRPreviewColor.encodeFromGradedAP0" in odt
    assert "itur_2100_HLG" in hdr
    assert "itur_2100_PQ" in hdr
    assert "ColorSync" in hdr
    assert "CGColorSpace.itur_709" in preview_709
    assert "var acesOTNote: String" in graph

    assert "_ACES2065-1_proxy" in clip
    assert "整段代理，不是全精度成片" in engine
    assert "整段代理，不是全精度成片" in clip
    assert "整段代理，不是全精度成片" in batch
    assert "source pixels 1:1" in readme
    assert "source pixels 1:1" in acceptance
    assert "source pixels 1:1" in batch
    assert "refuse ceiling" in readme
    assert "refuse ceiling" in acceptance
    assert "片源边长超过 16384，未写出" in readme
    assert "片源边长超过 16384，未写出" in acceptance
    assert "片源边长超过 16384，未写出" in batch
    assert "未验证" in readme or "unverified" in readme.lower()
    assert "成片" not in export_seq.replace("不是全精度成片", "")
    assert "完善" not in export_seq
    assert "精准" not in export_seq
    assert "acesImageContainerFlag" not in engine
