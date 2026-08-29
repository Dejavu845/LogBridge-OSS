import Foundation
import AppKit
import simd
import AVFoundation
import CoreGraphics
import ImageIO
import VideoToolbox
import Metal
import CoreVideo
import CoreMedia
import Combine

/// Downscaled preview (max 1920 long edge). Not a full-resolution render.
///
/// Cache (selected clip only — not every clip in a mixed bin):
///   - decoded camera/log thumbnail (VideoToolbox, no VT 709)
///   - IDT ACES2065-1 linear buffer
///   - graded linear (IDT+exposure+WB) so scrub / ODT change only re-runs ODT
/// Selection change drops source/linear/graded for clips that are no longer
/// selected. Current clip stays so #35 ODT-only still hits; a later visit
/// re-decodes once, then ODT-only again. Write path does not use these
/// dictionaries and is not evicted here.
/// Metal applies the same locked matrices/LUT/ACES OT as CPU. No Core Image P3.
/// Heavy work runs off the main thread on one serial queue — not a thread pool.
/// Arrow / click can outrun first-frame decode. Only the latest selected
/// clip's preview may publish. Queued preview work is cancelled; an already
/// running first-frame (one AVAssetReader sample) is dropped by generation
/// + selected-id. Write path does not use this cancel.
final class PreviewEngine: ObservableObject {
    static let maxLongEdge: CGFloat = 1920

    @Published var sourceImage: CGImage?
    @Published var odtImage: CGImage?
    @Published var status: String = "没有素材"
    @Published var isWorking = false

    private let queue = DispatchQueue(label: "app.logbridge.preview", qos: .userInitiated)
    private let genLock = NSLock()
    private var generation: UInt64 = 0
    private var requestedClipID: UUID?
    private var pendingPreviewWork: DispatchWorkItem?

    private var sourceCache: [UUID: SourceFrame] = [:]
    private var linearCache: [UUID: LinearFrame] = [:]
    private var gradedCache: [UUID: GradedFrame] = [:]

    struct SourceFrame {
        let url: URL
        let width: Int
        let height: Int
        let rgb: [Float]
        let cgImage: CGImage
    }

    struct LinearFrame {
        let idtID: String
        let width: Int
        let height: Int
        let rgb: [Float]
    }

    struct GradedFrame {
        let key: String
        let width: Int
        let height: Int
        let rgb: [Float]
    }

    func invalidateIDT(clipID: UUID) {
        linearCache[clipID] = nil
        gradedCache[clipID] = nil
    }

    func invalidateWBODT() {
        // IDT linear reused; drop graded so exposure/WB recompute.
        gradedCache.removeAll()
    }

    /// Preview dictionaries only. Does not touch write-path decode buffers.
    func evict(clipID: UUID) {
        sourceCache[clipID] = nil
        linearCache[clipID] = nil
        gradedCache[clipID] = nil
    }

    /// Keep the selected clip's preview source / linear / graded.
    /// Drop the rest so a mixed bin does not hold every visit forever.
    /// Write path (`exportGradedAP0` / sequence) does not read these
    /// dictionaries and is not evicted here.
    func retainPreviewCaches(keeping clipID: UUID?) {
        let ids = Set(sourceCache.keys)
            .union(linearCache.keys)
            .union(gradedCache.keys)
        for id in ids where id != clipID {
            evict(clipID: id)
        }
    }

    /// Bump generation, remember the selected clip, cancel queued preview work.
    /// Does not cancel a write (`exportGradedAP0` / sequence stays `queue.sync`).
    @discardableResult
    private func beginPreviewRequest(clipID: UUID?) -> UInt64 {
        pendingPreviewWork?.cancel()
        pendingPreviewWork = nil
        // Write stays queue.sync (exportGradedAP0 / sequence). Not this cancel.
        genLock.lock()
        generation += 1
        requestedClipID = clipID
        let gen = generation
        genLock.unlock()
        return gen
    }

    /// Latest selection + generation. Stale first-frame must not publish.
    private func isCurrentPreview(generation gen: UInt64, clipID: UUID?) -> Bool {
        genLock.lock()
        defer { genLock.unlock() }
        if generation != gen { return false }
        if requestedClipID != clipID { return false }
        return true
    }

    /// One serial queue. Cancel drops work that has not started. No thread pool.
    private func enqueuePreview(_ body: @escaping () -> Void) {
        let work = DispatchWorkItem(block: body)
        pendingPreviewWork = work
        queue.async(execute: work)
    }

    func refresh(clip: Clip?, graph: SerialGraph) {
        let gen = beginPreviewRequest(clipID: clip?.id)
        retainPreviewCaches(keeping: clip?.id)
        guard let clip else {
            sourceImage = nil
            odtImage = nil
            status = "没有素材"
            isWorking = false
            // In-flight first-frame may refill after this; drop again on the queue.
            enqueuePreview { [weak self] in
                self?.retainPreviewCaches(keeping: nil)
            }
            return
        }
        isWorking = true
        status = "正在解码预览…"
        let graphCopy = graph
        enqueuePreview { [weak self] in
            self?.build(clip: clip, graph: graphCopy, generation: gen)
        }
    }

    /// Scrub / ODT switch: reuse graded linear (IDT+exposure+WB). Only re-run ODT.
    func refreshODT(clip: Clip?, graph: SerialGraph) {
        let gen = beginPreviewRequest(clipID: clip?.id)
        retainPreviewCaches(keeping: clip?.id)
        guard let clip else {
            sourceImage = nil
            odtImage = nil
            status = "没有素材"
            isWorking = false
            enqueuePreview { [weak self] in
                self?.retainPreviewCaches(keeping: nil)
            }
            return
        }
        let graphCopy = graph
        enqueuePreview { [weak self] in
            self?.applyODTFromGradedOrRebuild(clip: clip, graph: graphCopy, generation: gen)
        }
    }

    /// Cache hit: ODT only on existing graded linear.
    /// Does not decode Y′CbCr. Does not re-run IDT. Does not re-run exposure/WB.
    /// Does not go through the write-path unpack. Preview stays 8-bit-first.
    /// Cache miss (new clip, exposure/WB/IDT change, or no graded buffer):
    /// rebuild linear once, then ODT-only again.
    private func applyODTFromGradedOrRebuild(clip: Clip, graph: SerialGraph, generation: UInt64) {
        guard isCurrentPreview(generation: generation, clipID: clip.id) else { return }
        // Stale work may have refilled another clip after the main-thread retain.
        retainPreviewCaches(keeping: clip.id)
        if let idt = clip.idt, !idt.isStub,
           let graded = gradedCacheHit(clipID: clip.id, idt: idt, graph: graph) {
            let (odtCG, note) = renderODTFromGraded(graded: graded, graph: graph, cacheHit: true)
            publishODTOnly(generation: generation, clipID: clip.id, odt: odtCG, status: note)
            return
        }
        build(clip: clip, graph: graph, generation: generation)
    }

    private func gradedCacheHit(clipID: UUID, idt: IDT, graph: SerialGraph) -> GradedFrame? {
        let key = Self.gradeKey(idt: idt, graph: graph)
        guard let hit = gradedCache[clipID], hit.key == key else { return nil }
        return hit
    }

    /// ODT from a graded linear buffer. No decode, no IDT, no exposure/WB.
    private func renderODTFromGraded(graded: GradedFrame, graph: SerialGraph, cacheHit: Bool) -> (CGImage?, String) {
        var work = graded.rgb
        var odtCG: CGImage?
        var note = "预览代理，不是成片"
        if cacheHit {
            // Scrub does not re-run IDT. Visible status is 只重跑 ODT.
            note = "只重跑 ODT"
        }
        if graph.odt == .rec709 {
            PreviewColor.applyODT(rgb: &work)
            odtCG = PreviewColor.makeCGImage(
                rgb: work,
                width: graded.width,
                height: graded.height,
                colorSpace: CGColorSpace(name: CGColorSpace.itur_709)
            )
        } else if graph.odt.isHDR {
            // ColorSync itur_2100. Not the 709 8-bit path. Fail closed.
            if let hdr = HDRPreviewColor.encodeFromGradedAP0(
                rgb: graded.rgb,
                width: graded.width,
                height: graded.height,
                odt: graph.odt
            ) {
                odtCG = hdr
                note = "预览·非成片"
            } else {
                odtCG = nil
                note = "HDR 预览建不出"
            }
        } else {
            note = "709 预览关"
        }
        return (odtCG, note)
    }

    /// Scrub / ODT hit: replace the 709 / HDR pane only. Source thumbnail stays.
    private func publishODTOnly(generation: UInt64, clipID: UUID, odt: CGImage?, status: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isCurrentPreview(generation: generation, clipID: clipID) else { return }
            self.odtImage = odt
            self.status = Self.resolvedPreviewStatus(odt: odt, status: status)
            self.isWorking = false
        }
    }

    /// Layer could not enable EDR. Empty HDR pane. Never show 709 pixels.
    func failClosedHDRPreview() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.odtImage = nil
            self.status = "HDR 预览建不出"
            self.isWorking = false
        }
    }

    /// HDR success + no display EDR → exact 「屏幕无 EDR，预览被压到 SDR」.
    /// 709 notes are unchanged. Fail string stays 「HDR 预览建不出」.
    private static func resolvedPreviewStatus(odt: CGImage?, status: String) -> String {
        if status == "HDR 预览建不出" { return status }
        if status == "预览·非成片", odt != nil, !HDRPreviewColor.displayHasEDR() {
            return "屏幕无 EDR，预览被压到 SDR"
        }
        return status
    }

    private func build(clip: Clip, graph: SerialGraph, generation: UInt64) {
        guard isCurrentPreview(generation: generation, clipID: clip.id) else { return }
        retainPreviewCaches(keeping: clip.id)
        let source: SourceFrame?
        do {
            source = try cachedSource(clip: clip, generation: generation)
        } catch {
            publish(
                generation: generation,
                clipID: clip.id,
                source: nil,
                odt: nil,
                status: (error as NSError).localizedDescription
            )
            return
        }
        guard isCurrentPreview(generation: generation, clipID: clip.id) else { return }
        guard let source else {
            publish(generation: generation, clipID: clip.id, source: nil, odt: nil, status: "解不出预览帧")
            return
        }
        guard let idt = clip.idt, !idt.isStub else {
            publish(
                generation: generation,
                clipID: clip.id,
                source: source.cgImage,
                odt: nil,
                status: clip.processSkipReason ?? "先选择成对 IDT"
            )
            return
        }
        let linear = cachedLinear(clipID: clip.id, idt: idt, source: source)
        let graded = cachedGraded(clipID: clip.id, idt: idt, linear: linear, graph: graph)
        let (odtCG, note) = renderODTFromGraded(graded: graded, graph: graph, cacheHit: false)
        publish(generation: generation, clipID: clip.id, source: source.cgImage, odt: odtCG, status: note)
    }

    private static func gradeKey(idt: IDT, graph: SerialGraph) -> String {
        let cct = graph.effectiveWBCCT.map { String($0) } ?? "id"
        let src = graph.effectiveSrcCCT.map { String($0) } ?? "-"
        return "\(idt.rawValue)|\(graph.exposureEnabled)|\(graph.exposureStops)|\(graph.wbEnabled)|\(cct)|\(src)|\(graph.wbTint)|\(graph.wbMethod)"
    }

    private func cachedGraded(clipID: UUID, idt: IDT, linear: LinearFrame, graph: SerialGraph) -> GradedFrame {
        let key = Self.gradeKey(idt: idt, graph: graph)
        if let hit = gradedCache[clipID], hit.key == key,
           hit.width == linear.width, hit.height == linear.height {
            return hit
        }
        var work = linear.rgb
        if graph.exposureEnabled {
            PreviewColor.applyExposure(rgb: &work, stops: graph.exposureStops)
        }
        if graph.wbEnabled, let cct = graph.effectiveWBCCT {
            if let src = graph.effectiveSrcCCT {
                PreviewColor.applyWB(
                    rgb: &work,
                    srcCCT: src,
                    dstCCT: cct,
                    srcTint: graph.asShotTint,
                    dstTint: graph.wbTint,
                    method: graph.wbMethod
                )
            } else {
                PreviewColor.applyWB(
                    rgb: &work,
                    cct: cct,
                    tint: graph.wbTint,
                    method: graph.wbMethod
                )
            }
        }
        let frame = GradedFrame(key: key, width: linear.width, height: linear.height, rgb: work)
        gradedCache[clipID] = frame
        return frame
    }

    private func cachedSource(clip: Clip, generation: UInt64) throws -> SourceFrame? {
        if let hit = sourceCache[clip.id], hit.url == clip.url {
            return hit
        }
        // Selection already moved: do not start a stale first-frame decode.
        guard isCurrentPreview(generation: generation, clipID: clip.id) else { return nil }
        guard let cg = try Self.decodeDownscaled(url: clip.url, maxLongEdge: Self.maxLongEdge) else {
            return nil
        }
        let rgb = PreviewColor.extractRGB(cg)
        let frame = SourceFrame(
            url: clip.url,
            width: cg.width,
            height: cg.height,
            rgb: rgb,
            cgImage: cg
        )
        sourceCache[clip.id] = frame
        return frame
    }

    private func cachedLinear(clipID: UUID, idt: IDT, source: SourceFrame) -> LinearFrame {
        if let hit = linearCache[clipID], hit.idtID == idt.rawValue,
           hit.width == source.width, hit.height == source.height {
            return hit
        }
        var rgb = source.rgb
        PreviewColor.applyIDT(rgb: &rgb, idt: idt)
        let frame = LinearFrame(idtID: idt.rawValue, width: source.width, height: source.height, rgb: rgb)
        linearCache[clipID] = frame
        return frame
    }

    private func publish(generation: UInt64, clipID: UUID, source: CGImage?, odt: CGImage?, status: String) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isCurrentPreview(generation: generation, clipID: clipID) else { return }
            self.sourceImage = source
            self.odtImage = odt
            self.status = Self.resolvedPreviewStatus(odt: odt, status: status)
            self.isWorking = false
        }
    }

    /// Graded ACES2065-1 (AP0) linear proxy frames. Reuses PreviewColor.
    /// ODT is not applied. Not ACEScct.
    /// Movie write path reads source 10-bit / native-depth Y′CbCr and
    /// matrix-converts to float RGB. Matrix and full/video range follow
    /// the pixel-buffer / format-description / nclc attachments — not a
    /// hardcoded BT.709 + video-range for every clip. No Rec.709 transfer
    /// before IDT. Video-range 10-bit is not /1023. It does not use the
    /// preview 8-bit path and then promote those 8-bit pixels
    /// (`extractRGB` / 255). Still a proxy — 整段代理，不是全精度成片.
    /// Bit-depth going up is still 整段代理，不是全精度成片.
    /// Movies: AVAssetReader ``copyNextSampleBuffer`` loop. Stills: one frame.
    /// Write is source pixels 1:1. ``writeLongEdgeCeiling`` (16384) is refuse
    /// only — do not scale export to 16384 or 1920.
    /// Preview display stays ``maxLongEdge`` 1920 / 8-bit.
    static let writeLongEdgeCeiling = 16384
    static let writeOversizeChip = "片源边长超过 16384，未写出"

    /// 16384 is a refuse ceiling. Write stays 1:1. Do not scale to 16384 or 1920.
    static func requireWriteSourcePixels(width: Int, height: Int) throws {
        if max(width, height) > writeLongEdgeCeiling {
            throw NSError(domain: "LogBridge", code: 4, userInfo: [
                NSLocalizedDescriptionKey: writeOversizeChip
            ])
        }
    }

    /// Clip-constant CAT for a locked write. Nil = WB off / identity (same as gradeAP0).
    /// Built once per sequence — do not rebuild the CAT per write frame.
    private static func writeCAT(graph: SerialGraph) -> simd_double3x3? {
        guard graph.wbEnabled, let cct = graph.effectiveWBCCT else { return nil }
        if let src = graph.effectiveSrcCCT {
            return WhiteBalanceNode.relativeCatMatrix(
                srcCCT: src,
                dstCCT: cct,
                srcTint: graph.asShotTint,
                dstTint: graph.wbTint,
                method: graph.wbMethod
            )
        }
        return WhiteBalanceNode.catMatrix(cct: cct, tint: graph.wbTint, method: graph.wbMethod)
    }

    /// Same IDT / exposure / WB as the first-frame helper. No ODT.
    /// Optional ``cat`` is the clip-constant matrix from ``writeCAT`` so a
    /// long sequence does not rebuild Bradford/CAT02 per frame.
    private static func gradeAP0(
        rgb: inout [Float],
        idt: IDT,
        graph: SerialGraph,
        cat: simd_double3x3? = nil
    ) {
        PreviewColor.applyIDT(rgb: &rgb, idt: idt)
        if graph.exposureEnabled {
            PreviewColor.applyExposure(rgb: &rgb, stops: graph.exposureStops)
        }
        if let cat {
            PreviewColor.applyPreparedCAT(rgb: &rgb, cat: cat)
            return
        }
        if graph.wbEnabled, let cct = graph.effectiveWBCCT {
            if let src = graph.effectiveSrcCCT {
                PreviewColor.applyWB(
                    rgb: &rgb,
                    srcCCT: src,
                    dstCCT: cct,
                    srcTint: graph.asShotTint,
                    dstTint: graph.wbTint,
                    method: graph.wbMethod
                )
            } else {
                PreviewColor.applyWB(
                    rgb: &rgb,
                    cct: cct,
                    tint: graph.wbTint,
                    method: graph.wbMethod
                )
            }
        }
    }

    /// First-frame graded ACES2065-1 (AP0) linear proxy. Reuses PreviewColor.
    /// Movies: same source Y′CbCr → float as the sequence (not preview 8-bit).
    func exportGradedAP0(clip: Clip, graph: SerialGraph) -> (rgb: [Float], width: Int, height: Int)? {
        queue.sync {
            guard let idt = clip.idt, !idt.isStub, !clip.needsUserPicker else { return nil }
            guard let decoded = Self.decodeFirstSourceRGB(url: clip.url) else {
                return nil
            }
            var rgb = decoded.rgb
            Self.gradeAP0(rgb: &rgb, idt: idt, graph: graph)
            return (rgb, decoded.width, decoded.height)
        }
    }

    /// Whole-clip proxy sequence. Writes as frames are decoded (no full-timeline buffer).
    /// Sequential ``copyNextSampleBuffer`` — do not seek randomly.
    /// After ``gradeAP0`` of frame N, one ``writeFrame`` task of N starts on
    /// the existing global queue so the next ``copyNextSampleBuffer`` + unpack
    /// + grade can proceed (one write overlap). Join write N after grade of
    /// N+1 and before write N+1. Frame indices stay sequential.
    /// One ``gradeAP0`` per write frame on the decode buffer (in-place).
    /// Clip-constant CAT via ``writeCAT``. Does not reuse preview
    /// graded linear cache (8-bit / 1920, not write source-res / 10-bit).
    /// Does not promote preview 8-bit. Does not apply ODT.
    /// Returns the number of frames handed to ``writeFrame``. Linux cannot run this.
    func exportGradedAP0Sequence(
        clip: Clip,
        graph: SerialGraph,
        writeFrame: @escaping (Int, [Float], Int, Int) throws -> Void
    ) throws -> Int {
        try queue.sync {
            guard let idt = clip.idt, !idt.isStub, !clip.needsUserPicker else {
                throw NSError(domain: "LogBridge", code: 1, userInfo: [
                    NSLocalizedDescriptionKey: clip.processSkipReason ?? "先选择成对 IDT"
                ])
            }
            let cat = Self.writeCAT(graph: graph)
            var count = 0
            // one write overlap: disk of N with sequential copyNext of N+1
            var pendingWrite: DispatchWorkItem?
            var writeError: Error?
            func joinExportWrite() throws {
                pendingWrite?.wait()
                pendingWrite = nil
                if let writeError { throw writeError }
            }
            do {
                try Self.decodeAllSourceFrames(url: clip.url) { rgb, width, height in
                    Self.gradeAP0(rgb: &rgb, idt: idt, graph: graph, cat: cat)
                    // Join write N-1 after grade of N; then one write task for N.
                    try joinExportWrite()
                    let index = count
                    let pixels = rgb
                    let w = width
                    let h = height
                    let work = DispatchWorkItem {
                        do {
                            try writeFrame(index, pixels, w, h)
                        } catch {
                            writeError = error
                        }
                    }
                    pendingWrite = work
                    DispatchQueue.global(qos: .userInitiated).async(execute: work)
                    count += 1
                }
                try joinExportWrite()
            } catch {
                pendingWrite?.wait()
                throw error
            }
            if count < 1 {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            return count
        }
    }

    /// Movies: every sample as source Y′CbCr → float (#31 unpack).
    /// Stills: one full-resolution ImageIO frame (TIFF / DPX / EXR already RGB — no Y′CbCr unpack).
    /// Not the preview 8-bit / 1920 path. Same matrix-only convert (no transfer).
    /// ``onFrame`` mutates the decode buffer in place so the write loop
    /// does not copy float RGB before IDT/WB.
    static func decodeAllSourceFrames(
        url: URL,
        onFrame: (inout [Float], Int, Int) throws -> Void
    ) throws {
        let probe = MediaFormat.probe(url: url)
        if probe.decision == .refuse {
            throw NSError(domain: "LogBridge", code: 2, userInfo: [
                NSLocalizedDescriptionKey: probe.note
            ])
        }
        if probe.kind == .still {
            guard let img = decodeStillFullImageIO(url: url) else {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            try requireWriteSourcePixels(width: img.width, height: img.height)
            var rgb = PreviewColor.extractRGB(img)
            try onFrame(&rgb, img.width, img.height)
            return
        }
        try decodeMovieAllFrames(url: url, onFrame: onFrame)
    }

    /// First frame only. Movies: same 10-bit-first source Y′CbCr → float as the sequence.
    /// Stills: full-resolution ImageIO (already RGB). Preview first-frame stays the 8-bit-first CGImage path.
    static func decodeFirstSourceRGB(url: URL) -> (rgb: [Float], width: Int, height: Int)? {
        let probe = MediaFormat.probe(url: url)
        if probe.decision == .refuse { return nil }
        if probe.kind == .still {
            guard let img = decodeStillFullImageIO(url: url) else { return nil }
            do {
                try requireWriteSourcePixels(width: img.width, height: img.height)
            } catch {
                return nil
            }
            return (PreviewColor.extractRGB(img), img.width, img.height)
        }
        let formats: [OSType] = [
            kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange,
            kCVPixelFormatType_420YpCbCr10BiPlanarFullRange,
            kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
            kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelFormatType_422YpCbCr8
        ]
        for fmt in formats {
            if let decoded = readFirstYpCbCrRGB(url: url, pixelFormat: fmt) {
                return decoded
            }
        }
        return nil
    }

    /// VideoToolbox / AVAssetReader: all frames as source Y′CbCr → float RGB.
    /// Export: 10-bit 420 (video then full) first, then native 8-bit 420, then 8-bit 422.
    /// Preview/scrub keeps the 8-bit-first list and the 8-bit CGImage writer,
    /// sharing ``requireSourceYCbCrUnpack``. Write stays source pixels / native-depth.
    /// Matrix-only — no transfer. Never copyCGImage. Never set AVVideoColorPropertiesKey.
    static func decodeMovieAllFrames(
        url: URL,
        onFrame: (inout [Float], Int, Int) throws -> Void
    ) throws {
        let formats: [OSType] = [
            kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange,
            kCVPixelFormatType_420YpCbCr10BiPlanarFullRange,
            kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
            kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelFormatType_422YpCbCr8
        ]
        for fmt in formats {
            let count = try readAllYpCbCrFrames(
                url: url,
                pixelFormat: fmt,
                onFrame: onFrame
            )
            if count > 0 { return }
        }
        throw NSError(domain: "LogBridge", code: 2, userInfo: [
            NSLocalizedDescriptionKey: "decode/grade failed"
        ])
    }

    /// AVAssetReader loop. Returns 0 when this pixel format produced no frames
    /// (caller tries the next format). Mid-sequence convert failure throws.
    /// Writes float RGB from source Y′CbCr — not the preview 8-bit CGImage writer.
    private static func readAllYpCbCrFrames(
        url: URL,
        pixelFormat: OSType,
        onFrame: (inout [Float], Int, Int) throws -> Void
    ) throws -> Int {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              let reader = try? AVAssetReader(asset: asset) else { return 0 }
        // Pixel format only. No AVVideoColorPropertiesKey Rec.709.
        let settings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: pixelFormat
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { return 0 }
        reader.add(output)
        guard reader.startReading() else { return 0 }
        var count = 0
        while let sample = output.copyNextSampleBuffer() {
            guard let pb = CMSampleBufferGetImageBuffer(sample) else {
                if count == 0 { return 0 }
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            var decoded: (rgb: [Float], width: Int, height: Int)
            do {
                decoded = try rgbFloatFromLogPixelBuffer(
                    pb,
                    format: CMSampleBufferGetFormatDescription(sample)
                )
            } catch {
                throw error
            }
            try onFrame(&decoded.rgb, decoded.width, decoded.height)
            count += 1
        }
        return count
    }

    /// First sample, source Y′CbCr → float. Preview first-frame stays 8-bit CGImage.
    private static func readFirstYpCbCrRGB(
        url: URL,
        pixelFormat: OSType
    ) -> (rgb: [Float], width: Int, height: Int)? {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              let reader = try? AVAssetReader(asset: asset) else { return nil }
        let settings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: pixelFormat
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { return nil }
        reader.add(output)
        guard reader.startReading(),
              let sample = output.copyNextSampleBuffer(),
              let pb = CMSampleBufferGetImageBuffer(sample) else { return nil }
        return try? rgbFloatFromLogPixelBuffer(
            pb,
            format: CMSampleBufferGetFormatDescription(sample)
        )
    }

    static let missingYCbCrTagsChip = "无法读取片源 Y′CbCr 矩阵/范围，未写出"

    private struct SourceYCbCrUnpack {
        let yOff: Double
        let ySpan: Double
        let cOff: Double
        let cSpan: Double
        let rv: Double
        let gu: Double
        let gv: Double
        let bu: Double
    }

    /// nclc / colr / vui matrix + full/video. Missing → fail. No 709-video default.
    /// Does not read primaries or transfer to change an IDT or apply a 709 curve.
    private static func requireSourceYCbCrUnpack(
        pixelBuffer pb: CVPixelBuffer,
        format: CMFormatDescription?,
        bitDepth: Int
    ) throws -> SourceYCbCrUnpack {
        let matrix = readSourceYCbCrMatrix(pixelBuffer: pb, format: format)
        let isFull = readSourceYCbCrFullRange(pixelBuffer: pb, format: format)
        guard let matrix, let isFull else {
            throw NSError(domain: "LogBridge", code: 3, userInfo: [
                NSLocalizedDescriptionKey: missingYCbCrTagsChip
            ])
        }
        guard let coeffs = ycbcrMatrixCoeffs(matrix) else {
            throw NSError(domain: "LogBridge", code: 3, userInfo: [
                NSLocalizedDescriptionKey: missingYCbCrTagsChip
            ])
        }
        let offs = ycbcrRangeOffsets(bitDepth: bitDepth, fullRange: isFull)
        return SourceYCbCrUnpack(
            yOff: offs.yOff, ySpan: offs.ySpan, cOff: offs.cOff, cSpan: offs.cSpan,
            rv: coeffs.rv, gu: coeffs.gu, gv: coeffs.gv, bu: coeffs.bu
        )
    }

    /// BT.601 / BT.709 / BT.2020 Kr/Kb expand. Matrix-only — no transfer.
    static func ycbcrMatrixCoeffs(_ name: String) -> (rv: Double, gu: Double, gv: Double, bu: Double)? {
        switch name {
        case "bt601":
            return (1.402, 0.344136, 0.714136, 1.772)
        case "bt2020":
            return (1.4746, 0.164553, 0.571353, 1.8814)
        case "bt709":
            return (1.5748, 0.1873, 0.4681, 1.8556)
        default:
            return nil
        }
    }

    /// Video n-bit is 16<<(n-8)…235<<(n-8), not a literal /1023 for every 10-bit clip.
    /// 10-bit video is 64/876. Full n-bit is 0…2^n-1.
    static func ycbcrRangeOffsets(bitDepth: Int, fullRange: Bool) -> (yOff: Double, ySpan: Double, cOff: Double, cSpan: Double) {
        let depth = max(bitDepth, 8)
        let maxCode = Double((1 << depth) - 1)
        let mid = Double(1 << (depth - 1))
        if fullRange {
            return (0, maxCode, mid, maxCode)
        }
        let shift = depth - 8
        let yOff = Double(16 << shift)
        let ySpan = Double((235 << shift) - (16 << shift))
        let cSpan = Double((240 << shift) - (16 << shift))
        return (yOff, ySpan, mid, cSpan)
    }

    private static func readSourceYCbCrMatrix(pixelBuffer pb: CVPixelBuffer, format: CMFormatDescription?) -> String? {
        if let raw = cvAttachment(pb, kCVImageBufferYCbCrMatrixKey) {
            return normalizeYCbCrMatrix(raw)
        }
        if let format,
           let raw = CMFormatDescriptionGetExtension(
            format, extensionKey: kCMFormatDescriptionExtension_YCbCrMatrix
           ) {
            return normalizeYCbCrMatrix(raw)
        }
        if let trip = nclcTriplet(pixelBuffer: pb, format: format) {
            return matrixFromCode(trip.2)
        }
        return nil
    }

    /// Same CFString as CoreVideo kCVImageBufferFullRangeVideo (not in this runner overlay).
    private static let kCVImageBufferFullRangeVideo: CFString =
        kCMFormatDescriptionExtension_FullRangeVideo

    private static func readSourceYCbCrFullRange(pixelBuffer pb: CVPixelBuffer, format: CMFormatDescription?) -> Bool? {
        if let flag = boolAttachment(pb, kCVImageBufferFullRangeVideo) {
            return flag
        }
        if let format,
           let raw = CMFormatDescriptionGetExtension(
            format, extensionKey: kCMFormatDescriptionExtension_FullRangeVideo
           ) {
            return boolFromTag(raw)
        }
        if let flag = nclxFullRangeFlag(pixelBuffer: pb, format: format) {
            return flag
        }
        return nil
    }

    private static func cvAttachment(_ pb: CVPixelBuffer, _ key: CFString) -> Any? {
        var mode = CVAttachmentMode.shouldNotPropagate
        return CVBufferGetAttachment(pb, key, &mode)
    }

    private static func boolAttachment(_ pb: CVPixelBuffer, _ key: CFString) -> Bool? {
        boolFromTag(cvAttachment(pb, key))
    }

    private static func boolFromTag(_ raw: Any?) -> Bool? {
        guard let raw else { return nil }
        if let b = raw as? Bool { return b }
        if CFGetTypeID(raw as CFTypeRef) == CFBooleanGetTypeID() {
            return CFBooleanGetValue((raw as! CFBoolean))
        }
        if let n = raw as? NSNumber { return n.boolValue }
        if let s = raw as? String {
            let low = s.lowercased()
            if ["1", "true", "yes", "full"].contains(low) { return true }
            if ["0", "false", "no", "video", "limited"].contains(low) { return false }
        }
        return nil
    }

    private static func normalizeYCbCrMatrix(_ raw: Any) -> String? {
        if let n = raw as? NSNumber { return matrixFromCode(n.intValue) }
        let s = String(describing: raw).lowercased()
        if s.contains("2020") { return "bt2020" }
        if s.contains("601") || s.contains("240m") { return "bt601" }
        if s.contains("709") { return "bt709" }
        return nil
    }

    private static func matrixFromCode(_ code: Int) -> String? {
        // ITU / H.273. 0 and 2 are unspecified — fail, do not default 709.
        if code == 1 { return "bt709" }
        if code == 4 || code == 5 || code == 6 || code == 7 { return "bt601" }
        if code == 9 || code == 10 { return "bt2020" }
        return nil
    }

    /// nclc / nclx / colr triplet (primaries, transfer, matrix). Matrix only.
    private static func nclcTriplet(pixelBuffer pb: CVPixelBuffer, format: CMFormatDescription?) -> (Int, Int, Int)? {
        let keys = ["nclc", "nclx", "colr", "vui"]
        for key in keys {
            if let parsed = parseNCLC(cvAttachment(pb, key as CFString)) { return parsed }
        }
        if let format, let exts = CMFormatDescriptionGetExtensions(format) as? [String: Any] {
            for key in keys {
                if let parsed = parseNCLC(exts[key]) { return parsed }
            }
        }
        return nil
    }

    private static func nclxFullRangeFlag(pixelBuffer pb: CVPixelBuffer, format: CMFormatDescription?) -> Bool? {
        if let flag = parseNCLXRange(cvAttachment(pb, "nclx" as CFString)) { return flag }
        if let format, let exts = CMFormatDescriptionGetExtensions(format) as? [String: Any] {
            if let flag = parseNCLXRange(exts["nclx"]) { return flag }
            if let flag = parseNCLXRange(exts["colr"]) { return flag }
            if let flag = parseNCLXRange(exts["vui"]) { return flag }
        }
        return nil
    }

    private static func parseNCLC(_ raw: Any?) -> (Int, Int, Int)? {
        guard let raw else { return nil }
        if let s = raw as? String {
            let parts = s.replacingOccurrences(of: ",", with: "-").replacingOccurrences(of: ":", with: "-").split(separator: "-")
            if parts.count >= 3, let p = Int(parts[0]), let t = Int(parts[1]), let m = Int(parts[2]) {
                return (p, t, m)
            }
        }
        if let arr = raw as? [Any], arr.count >= 3,
           let p = intFromTag(arr[0]), let t = intFromTag(arr[1]), let m = intFromTag(arr[2]) {
            return (p, t, m)
        }
        if let data = raw as? Data, data.count >= 6 {
            let p = Int(data[0]) << 8 | Int(data[1])
            let t = Int(data[2]) << 8 | Int(data[3])
            let m = Int(data[4]) << 8 | Int(data[5])
            return (p, t, m)
        }
        return nil
    }

    private static func parseNCLXRange(_ raw: Any?) -> Bool? {
        if let data = raw as? Data, data.count >= 7 {
            return (data[6] & 0x80) != 0
        }
        if let dict = raw as? [String: Any] {
            if let flag = boolFromTag(dict["full_range"] ?? dict["video_full_range_flag"]) { return flag }
        }
        return nil
    }

    private static func intFromTag(_ raw: Any?) -> Int? {
        if let n = raw as? Int { return n }
        if let n = raw as? NSNumber { return n.intValue }
        if let s = raw as? String { return Int(s) }
        return nil
    }

    /// Matrix-only Y′CbCr → float R′G′B′ at the buffer's native sample depth.
    /// Source pixels 1:1. ``requireWriteSourcePixels`` refuses above 16384.
    /// Do not scale. Matrix + full/video come from nclc / colr / vui. Missing tags throw
    /// 「无法读取片源 Y′CbCr 矩阵/范围，未写出」. No 709-video default.
    /// Video-range 10-bit uses 64/876, not /1023. No Rec.709 transfer.
    static func rgbFloatFromLogPixelBuffer(
        _ pb: CVPixelBuffer,
        format: CMFormatDescription? = nil
    ) throws -> (rgb: [Float], width: Int, height: Int) {
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        let w = CVPixelBufferGetWidth(pb)
        let h = CVPixelBufferGetHeight(pb)
        guard w > 0, h > 0 else {
            throw NSError(domain: "LogBridge", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "decode/grade failed"
            ])
        }
        try requireWriteSourcePixels(width: w, height: h)
        var rgb = [Float](repeating: 0, count: w * h * 3)
        let fmt = CVPixelBufferGetPixelFormatType(pb)
        if fmt == kCVPixelFormatType_32BGRA || fmt == kCVPixelFormatType_32ARGB {
            throw NSError(domain: "LogBridge", code: 3, userInfo: [
                NSLocalizedDescriptionKey: missingYCbCrTagsChip
            ])
        }
        let bitDepth: Int = (
            fmt == kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
            || fmt == kCVPixelFormatType_420YpCbCr10BiPlanarFullRange
        ) ? 10 : 8
        let unpack = try requireSourceYCbCrUnpack(pixelBuffer: pb, format: format, bitDepth: bitDepth)
        if fmt == kCVPixelFormatType_422YpCbCr8 {
            guard let base = CVPixelBufferGetBaseAddress(pb) else {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            let stride = CVPixelBufferGetBytesPerRow(pb)
            let src = base.assumingMemoryBound(to: UInt8.self)
            for y in 0..<h {
                for x in 0..<w {
                    let si = y * stride + (x & ~1) * 2
                    let Y = Double(src[y * stride + x * 2 + 1])
                    let Cb = Double(src[si + 0])
                    let Cr = Double(src[si + 2])
                    applyYCbCrMatrixToFloat(
                        &rgb, di: (y * w + x) * 3,
                        Y: Y, Cb: Cb, Cr: Cr, unpack: unpack
                    )
                }
            }
        } else if fmt == kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
                    || fmt == kCVPixelFormatType_420YpCbCr10BiPlanarFullRange {
            guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 0),
                  let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 1) else {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            let yStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
            let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 1)
            let yPtr = yPlane.assumingMemoryBound(to: UInt16.self)
            let uvPtr = uvPlane.assumingMemoryBound(to: UInt16.self)
            let yRow = yStride / 2
            let uvRow = uvStride / 2
            for y in 0..<h {
                for x in 0..<w {
                    let Y = Double(yPtr[y * yRow + x])
                    let uv = (y / 2) * uvRow + (x / 2) * 2
                    let Cb = Double(uvPtr[uv])
                    let Cr = Double(uvPtr[uv + 1])
                    // 10-bit samples. Range/matrix from tags. Matrix only — no 709 transfer.
                    applyYCbCrMatrixToFloat(
                        &rgb, di: (y * w + x) * 3,
                        Y: Y, Cb: Cb, Cr: Cr, unpack: unpack
                    )
                }
            }
        } else {
            guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 0),
                  let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 1) else {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            let yStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
            let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 1)
            let yPtr = yPlane.assumingMemoryBound(to: UInt8.self)
            let uvPtr = uvPlane.assumingMemoryBound(to: UInt8.self)
            for y in 0..<h {
                for x in 0..<w {
                    let Y = Double(yPtr[y * yStride + x])
                    let uv = (y / 2) * uvStride + (x / 2) * 2
                    let Cb = Double(uvPtr[uv])
                    let Cr = Double(uvPtr[uv + 1])
                    applyYCbCrMatrixToFloat(
                        &rgb, di: (y * w + x) * 3,
                        Y: Y, Cb: Cb, Cr: Cr, unpack: unpack
                    )
                }
            }
        }
        return (rgb, w, h)
    }

    /// Matrix-only Y′CbCr → float R′G′B′. No OETF/EOTF. No 8-bit clamp.
    /// Write path only — preview display quantize stays ``writeMatrixRGB``.
    /// Both call ``requireSourceYCbCrUnpack`` (nclc / colr / vui).
    private static func applyYCbCrMatrixToFloat(
        _ rgb: inout [Float],
        di: Int,
        Y: Double,
        Cb: Double,
        Cr: Double,
        unpack: SourceYCbCrUnpack
    ) {
        let yp = (Y - unpack.yOff) / unpack.ySpan
        let pbv = (Cb - unpack.cOff) / unpack.cSpan
        let prv = (Cr - unpack.cOff) / unpack.cSpan
        rgb[di] = Float(yp + unpack.rv * prv)
        rgb[di + 1] = Float(yp - unpack.gu * pbv - unpack.gv * prv)
        rgb[di + 2] = Float(yp + unpack.bu * pbv)
    }

    /// Full cached post-IDT AP0 linear buffer. Never Rec.709 / ACEScct / log.
    func linearAP0Frame(clipID: UUID) -> (rgb: [Float], width: Int, height: Int)? {
        guard let linear = linearCache[clipID] else { return nil }
        return (linear.rgb, linear.width, linear.height)
    }

    /// Sample cached post-IDT (post-exposure if enabled) linear AP0 RGB at a normalized point.
    func sampleLinearRGB(clipID: UUID, nx: Double, ny: Double, exposureStops: Double, exposureEnabled: Bool) -> SIMD3<Double>? {
        guard let linear = linearCache[clipID] else { return nil }
        let x = min(max(Int((nx * Double(linear.width)).rounded(.down)), 0), max(linear.width - 1, 0))
        let y = min(max(Int((ny * Double(linear.height)).rounded(.down)), 0), max(linear.height - 1, 0))
        let i = (y * linear.width + x) * 3
        guard i + 2 < linear.rgb.count else { return nil }
        var r = Double(linear.rgb[i])
        var g = Double(linear.rgb[i + 1])
        var b = Double(linear.rgb[i + 2])
        if exposureEnabled && exposureStops != 0 {
            let gain = pow(2.0, exposureStops)
            r *= gain; g *= gain; b *= gain
        }
        return SIMD3(r, g, b)
    }

    /// Movies: AVAssetReader Y′CbCr + ``requireSourceYCbCrUnpack`` (#31).
    /// Stills: ImageIO only (TIFF / DPX / EXR are already RGB).
    /// Do not run Y′CbCr unpack on stills. Policy in MediaFormat.
    /// VT decode only — do not let VT emit Rec.709. No Core Image Display P3.
    static func decodeDownscaled(url: URL, maxLongEdge: CGFloat) throws -> CGImage? {
        let probe = MediaFormat.probe(url: url)
        if probe.decision == .refuse {
            return nil
        }
        if probe.kind == .still {
            return decodeStillImageIO(url: url, maxLongEdge: maxLongEdge)
        }
        return try decodeMovieVideoToolbox(url: url, maxLongEdge: maxLongEdge)
    }

    /// VideoToolbox / AVAssetReader: first frame as Y′CbCr.
    /// YUV→RGB is matrix-only via ``requireSourceYCbCrUnpack`` (nclc / colr / vui).
    /// No transfer (tags often say 709; Log is not). No nclc→709 display convert.
    /// Missing tags throw 「无法读取片源 Y′CbCr 矩阵/范围，未写出」. No 709-video default.
    /// Then quantize to 8-bit for display (long-edge ``maxLongEdge``, preview 1920).
    /// Try 8-bit 420, then 8-bit 422, then 10-bit 420. Bit-depth only — no transfer.
    /// Never set AVVideoColorPropertiesKey. Never copyCGImage.
    static func decodeMovieVideoToolbox(url: URL, maxLongEdge: CGFloat) throws -> CGImage? {
        let formats: [OSType] = [
            kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
            kCVPixelFormatType_422YpCbCr8,
            kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
        ]
        for fmt in formats {
            if let img = try readFirstYpCbCrFrame(url: url, pixelFormat: fmt, maxLongEdge: maxLongEdge) {
                return img
            }
        }
        return nil
    }

    private static func readFirstYpCbCrFrame(url: URL, pixelFormat: OSType, maxLongEdge: CGFloat) throws -> CGImage? {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first,
              let reader = try? AVAssetReader(asset: asset) else { return nil }
        // Pixel format only. No AVVideoColorPropertiesKey Rec.709.
        let settings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: pixelFormat
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { return nil }
        reader.add(output)
        guard reader.startReading(),
              let sample = output.copyNextSampleBuffer(),
              let pb = CMSampleBufferGetImageBuffer(sample) else { return nil }
        return try cgImageFromLogPixelBuffer(
            pb,
            format: CMSampleBufferGetFormatDescription(sample),
            maxLongEdge: maxLongEdge
        )
    }

    /// Matrix-only Y′CbCr → R′G′B′ then 8-bit quantize. Same
    /// ``requireSourceYCbCrUnpack`` as write (nclc / colr / vui).
    /// Does not apply an OETF/EOTF. nclc transfer (often 709) is not applied.
    /// Missing tags throw 「无法读取片源 Y′CbCr 矩阵/范围，未写出」. No 709-video default.
    static func cgImageFromLogPixelBuffer(
        _ pb: CVPixelBuffer,
        format: CMFormatDescription? = nil,
        maxLongEdge: CGFloat
    ) throws -> CGImage? {
        // 「无法读取片源 Y′CbCr 矩阵/范围，未写出」 when nclc / colr / vui cannot be read.
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        let srcW = CVPixelBufferGetWidth(pb)
        let srcH = CVPixelBufferGetHeight(pb)
        guard srcW > 0, srcH > 0 else { return nil }
        let scale = min(1.0, Double(maxLongEdge) / Double(max(srcW, srcH)))
        let w = max(1, Int((Double(srcW) * scale).rounded()))
        let h = max(1, Int((Double(srcH) * scale).rounded()))
        var rgb = [UInt8](repeating: 0, count: w * h * 4)
        let fmt = CVPixelBufferGetPixelFormatType(pb)
        if fmt == kCVPixelFormatType_32BGRA || fmt == kCVPixelFormatType_32ARGB {
            throw NSError(domain: "LogBridge", code: 3, userInfo: [
                NSLocalizedDescriptionKey: missingYCbCrTagsChip
            ])
        }
        let bitDepth: Int = (
            fmt == kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
            || fmt == kCVPixelFormatType_420YpCbCr10BiPlanarFullRange
        ) ? 10 : 8
        let unpack = try requireSourceYCbCrUnpack(pixelBuffer: pb, format: format, bitDepth: bitDepth)
        if fmt == kCVPixelFormatType_422YpCbCr8 {
            guard let base = CVPixelBufferGetBaseAddress(pb) else { return nil }
            let stride = CVPixelBufferGetBytesPerRow(pb)
            let src = base.assumingMemoryBound(to: UInt8.self)
            for y in 0..<h {
                let sy = min(srcH - 1, Int((Double(y) / Double(h) * Double(srcH)).rounded(.down)))
                for x in 0..<w {
                    let sx = min(srcW - 1, Int((Double(x) / Double(w) * Double(srcW)).rounded(.down)))
                    let si = sy * stride + (sx & ~1) * 2
                    let Y = Double(src[sy * stride + sx * 2 + 1])
                    let Cb = Double(src[si + 0])
                    let Cr = Double(src[si + 2])
                    writeMatrixRGB(&rgb, di: (y * w + x) * 4, Y: Y, Cb: Cb, Cr: Cr, unpack: unpack)
                }
            }
        } else if fmt == kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
                    || fmt == kCVPixelFormatType_420YpCbCr10BiPlanarFullRange {
            guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 0),
                  let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 1) else { return nil }
            let yStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
            let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 1)
            let yPtr = yPlane.assumingMemoryBound(to: UInt16.self)
            let uvPtr = uvPlane.assumingMemoryBound(to: UInt16.self)
            let yRow = yStride / 2
            let uvRow = uvStride / 2
            for y in 0..<h {
                let sy = min(srcH - 1, Int((Double(y) / Double(h) * Double(srcH)).rounded(.down)))
                for x in 0..<w {
                    let sx = min(srcW - 1, Int((Double(x) / Double(w) * Double(srcW)).rounded(.down)))
                    let Y = Double(yPtr[sy * yRow + sx])
                    let uv = (sy / 2) * uvRow + (sx / 2) * 2
                    let Cb = Double(uvPtr[uv])
                    let Cr = Double(uvPtr[uv + 1])
                    // 10-bit samples. Range/matrix from tags. Matrix only — no 709 transfer.
                    writeMatrixRGB(&rgb, di: (y * w + x) * 4, Y: Y, Cb: Cb, Cr: Cr, unpack: unpack)
                }
            }
        } else {
            guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 0),
                  let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pb, 1) else { return nil }
            let yStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
            let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pb, 1)
            let yPtr = yPlane.assumingMemoryBound(to: UInt8.self)
            let uvPtr = uvPlane.assumingMemoryBound(to: UInt8.self)
            for y in 0..<h {
                let sy = min(srcH - 1, Int((Double(y) / Double(h) * Double(srcH)).rounded(.down)))
                for x in 0..<w {
                    let sx = min(srcW - 1, Int((Double(x) / Double(w) * Double(srcW)).rounded(.down)))
                    let Y = Double(yPtr[sy * yStride + sx])
                    let uv = (sy / 2) * uvStride + (sx / 2) * 2
                    let Cb = Double(uvPtr[uv])
                    let Cr = Double(uvPtr[uv + 1])
                    // Y′CbCr → R′G′B′ from tags. Matrix only — no 709 transfer.
                    writeMatrixRGB(&rgb, di: (y * w + x) * 4, Y: Y, Cb: Cb, Cr: Cr, unpack: unpack)
                }
            }
        }
        let cs = CGColorSpaceCreateDeviceRGB()
        let info = CGImageAlphaInfo.premultipliedLast.rawValue
        guard let ctx = CGContext(
            data: &rgb,
            width: w,
            height: h,
            bitsPerComponent: 8,
            bytesPerRow: w * 4,
            space: cs,
            bitmapInfo: info
        ) else { return nil }
        return ctx.makeImage()
    }


    /// Matrix-only Y′CbCr → R′G′B′. No OETF/EOTF. Preview 8-bit quantize.
    /// Offsets / coeffs from ``requireSourceYCbCrUnpack`` — not hardcoded 709 video.
    private static func writeMatrixRGB(
        _ rgb: inout [UInt8],
        di: Int,
        Y: Double,
        Cb: Double,
        Cr: Double,
        unpack: SourceYCbCrUnpack
    ) {
        let yp = (Y - unpack.yOff) / unpack.ySpan
        let pbv = (Cb - unpack.cOff) / unpack.cSpan
        let prv = (Cr - unpack.cOff) / unpack.cSpan
        let r = yp + unpack.rv * prv
        let g = yp - unpack.gu * pbv - unpack.gv * prv
        let b = yp + unpack.bu * pbv
        rgb[di] = UInt8(clamping: Int((min(max(r, 0), 1) * 255).rounded()))
        rgb[di + 1] = UInt8(clamping: Int((min(max(g, 0), 1) * 255).rounded()))
        rgb[di + 2] = UInt8(clamping: Int((min(max(b, 0), 1) * 255).rounded()))
        rgb[di + 3] = 255
    }

    /// Write stills: source pixel dimensions. Not the preview long-edge thumbnail.
    /// TIFF / DPX / EXR already RGB. No Y′CbCr unpack.
    static func decodeStillFullImageIO(url: URL) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        guard CGImageSourceGetCount(src) > 0 else { return nil }
        let uti = (CGImageSourceGetType(src) as String?) ?? ""
        if uti.contains("mpeg") || uti.contains("quicktime") || uti.contains("video") {
            return nil
        }
        let opts: [CFString: Any] = [
            kCGImageSourceShouldCache: false
        ]
        return CGImageSourceCreateImageAtIndex(src, 0, opts as CFDictionary)
    }

    /// Preview stills thumbnail (long-edge ``maxLongEdge``, 1920). Already RGB.
    /// No nclc / colr / vui. No Y′CbCr unpack.
    /// Device RGB extract later — never itur_709 / displayP3 dest.
    static func decodeStillImageIO(url: URL, maxLongEdge: CGFloat) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        guard CGImageSourceGetCount(src) > 0 else { return nil }
        let uti = (CGImageSourceGetType(src) as String?) ?? ""
        if uti.contains("mpeg") || uti.contains("quicktime") || uti.contains("video") {
            return nil
        }
        let opts: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: maxLongEdge,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCache: false
        ]
        return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
    }
}

/// Preview-only color apply. Constants must match ResolveExporter / color/*.py.
/// Do not "improve" manufacturer numbers here — color science is audited separately.
enum PreviewColor {
    static func extractRGB(_ image: CGImage) -> [Float] {
        let w = image.width
        let h = image.height
        var rgba = [UInt8](repeating: 0, count: w * h * 4)
        // Device RGB — not Display P3, not itur_709. Camera/log code values.
        let cs = CGColorSpaceCreateDeviceRGB()
        let info = CGImageAlphaInfo.premultipliedLast.rawValue
        guard let ctx = CGContext(
            data: &rgba,
            width: w,
            height: h,
            bitsPerComponent: 8,
            bytesPerRow: w * 4,
            space: cs,
            bitmapInfo: info
        ) else {
            return [Float](repeating: 0, count: w * h * 3)
        }
        // Reinterpret bytes. Do not let a 709-tagged CGImage color-match into this context.
        if let provider = image.dataProvider, let data = provider.data {
            let src = CFDataGetBytePtr(data)
            let bpp = max(image.bitsPerPixel / 8, 1)
            let stride = max(image.bytesPerRow, w * bpp)
            if src != nil && (image.bitsPerPixel == 32 || image.bitsPerPixel == 24) {
                for y in 0..<h {
                    for x in 0..<w {
                        let si = y * stride + x * bpp
                        let di = (y * w + x) * 4
                        rgba[di] = src![si]
                        rgba[di + 1] = src![si + 1]
                        rgba[di + 2] = src![si + 2]
                        rgba[di + 3] = 255
                    }
                }
            } else {
                ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            }
        } else {
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        }
        var rgb = [Float](repeating: 0, count: w * h * 3)
        for i in 0..<(w * h) {
            rgb[i * 3 + 0] = Float(rgba[i * 4 + 0]) / 255
            rgb[i * 3 + 1] = Float(rgba[i * 4 + 1]) / 255
            rgb[i * 3 + 2] = Float(rgba[i * 4 + 2]) / 255
        }
        return rgb
    }

    static func makeCGImage(rgb: [Float], width: Int, height: Int, colorSpace: CGColorSpace?) -> CGImage? {
        var rgba = [UInt8](repeating: 255, count: width * height * 4)
        for i in 0..<(width * height) {
            rgba[i * 4 + 0] = u8(rgb[i * 3 + 0])
            rgba[i * 4 + 1] = u8(rgb[i * 3 + 1])
            rgba[i * 4 + 2] = u8(rgb[i * 3 + 2])
        }
        let cs = colorSpace ?? CGColorSpaceCreateDeviceRGB()
        let info = CGImageAlphaInfo.premultipliedLast.rawValue
        guard let ctx = CGContext(
            data: &rgba,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: cs,
            bitmapInfo: info
        ) else { return nil }
        return ctx.makeImage()
    }

    private static func u8(_ x: Float) -> UInt8 {
        UInt8(clamping: Int((min(max(x, 0), 1) * 255).rounded()))
    }

    static func applyIDT(rgb: inout [Float], idt: IDT) {
        guard let m = cameraToAP0(idt) else { return }
        let n = rgb.count / 3
        for i in 0..<n {
            let r = decodeLog(Double(rgb[i * 3 + 0]), idt: idt)
            let g = decodeLog(Double(rgb[i * 3 + 1]), idt: idt)
            let b = decodeLog(Double(rgb[i * 3 + 2]), idt: idt)
            let v = m * SIMD3(r, g, b)
            rgb[i * 3 + 0] = Float(v.x)
            rgb[i * 3 + 1] = Float(v.y)
            rgb[i * 3 + 2] = Float(v.z)
        }
    }

    static func applyExposure(rgb: inout [Float], stops: Double) {
        // ACES2065-1 linear: rgb * (2 ** stops). Not a log-code add.
        if stops == 0 { return }
        let gain = Float(pow(2.0, stops))
        for i in 0..<rgb.count {
            rgb[i] *= gain
        }
    }

    static func applyWB(rgb: inout [Float], cct: Double, tint: Double, method: String) {
        // Absolute CAT (grey-card / CLI) in ACES2065-1 (AP0) scene-linear.
        let cat = WhiteBalanceNode.catMatrix(cct: cct, tint: tint, method: method)
        applyCAT(rgb: &rgb, cat: cat)
    }

    static func applyWB(
        rgb: inout [Float],
        srcCCT: Double,
        dstCCT: Double,
        srcTint: Double,
        dstTint: Double,
        method: String
    ) {
        // Relative: CAT(user→D65)·inv(CAT(as→D65)) == CAT(user→as). 3200→5600 warms.
        let cat = WhiteBalanceNode.relativeCatMatrix(
            srcCCT: srcCCT, dstCCT: dstCCT, srcTint: srcTint, dstTint: dstTint, method: method
        )
        applyCAT(rgb: &rgb, cat: cat)
    }

    /// Write-loop CAT. Same ``applyCAT`` as ``applyWB`` — matrix already built.
    static func applyPreparedCAT(rgb: inout [Float], cat: simd_double3x3) {
        applyCAT(rgb: &rgb, cat: cat)
    }

    private static func applyCAT(rgb: inout [Float], cat: simd_double3x3) {
        let m = ap0ToXYZ.inverse * cat * ap0ToXYZ
        if PreviewMetal.applyMatrix(&rgb, matrix: m, rec709OETF: false) { return }
        let n = rgb.count / 3
        for i in 0..<n {
            let v = m * SIMD3(Double(rgb[i * 3 + 0]), Double(rgb[i * 3 + 1]), Double(rgb[i * 3 + 2]))
            rgb[i * 3 + 0] = Float(v.x)
            rgb[i * 3 + 1] = Float(v.y)
            rgb[i * 3 + 2] = Float(v.z)
        }
    }

    static func applyODT(rgb: inout [Float]) {
        if PreviewMetal.applyMatrix(&rgb, matrix: ap0ToRec709, rec709OETF: true) { return }
        let n = rgb.count / 3
        for i in 0..<n {
            let v = ap0ToRec709 * SIMD3(Double(rgb[i * 3 + 0]), Double(rgb[i * 3 + 1]), Double(rgb[i * 3 + 2]))
            rgb[i * 3 + 0] = Float(rec709OETF(v.x))
            rgb[i * 3 + 1] = Float(rec709OETF(v.y))
            rgb[i * 3 + 2] = Float(rec709OETF(v.z))
        }
    }

    // MARK: Matrices / curves — copied from ResolveExporter (do not edit numbers)

    private static let ap0ToXYZ = simd_double3x3(rows: [
        SIMD3(0.952552395938186, 0.000000000000000, 0.000093678631660),
        SIMD3(0.343966449765075, 0.728166096613486, -0.072132546378561),
        SIMD3(0.000000000000000, 0.000000000000000, 1.008825184351586)
    ])

    private static let ap0ToRec709 = simd_double3x3(rows: [
        SIMD3(2.521686186743882, -1.134130988239719, -0.387555198504164),
        SIMD3(-0.276479914229922, 1.372719087668256, -0.096239173438334),
        SIMD3(-0.015378064966034, -0.152975335867399, 1.168353400833433)
    ])

    private static let rec709Beta = 0.018053968510807
    private static let rec709Alpha = 1.09929682680944

    private static func rec709OETF(_ lin: Double) -> Double {
        if lin < rec709Beta { return 4.5 * lin }
        return rec709Alpha * pow(max(lin, 0.0), 0.45) - (rec709Alpha - 1.0)
    }

    private static func cameraToAP0(_ idt: IDT) -> simd_double3x3? {
        switch idt {
        case .arriLogC4AWG4:
            return simd_double3x3(rows: [
                SIMD3(0.751244868485, 0.143007909499, 0.105747222016),
                SIMD3(0.001403392600, 1.005384442231, -0.006787834830),
                SIMD3(-0.000803152607, 0.003263851374, 0.997539301233)
            ])
        case .sonySLog3SGamut3:
            return simd_double3x3(rows: [
                SIMD3(0.753230840311, 0.141947913791, 0.104821245898),
                SIMD3(0.022234917350, 1.013293794080, -0.035528711431),
                SIMD3(-0.009600262790, 0.007505931314, 1.002094331476)
            ])
        case .sonySLog3SGamut3Cine:
            return simd_double3x3(rows: [
                SIMD3(0.639008308411, 0.270840678932, 0.090151012656),
                SIMD3(-0.003450727728, 1.085955398170, -0.082504670442),
                SIMD3(-0.030074188115, -0.021937342610, 1.052011530726)
            ])
        case .panasonicVLogVGamut:
            return simd_double3x3(rows: [
                SIMD3(0.724616704132, 0.166915288194, 0.108468007675),
                SIMD3(0.021390245413, 0.984908155703, -0.006298401116),
                SIMD3(-0.009235562871, -0.001056905639, 1.010292468510)
            ])
        case .fujiFLog2BT2020, .nikonNLogBT2020:
            return simd_double3x3(rows: [
                SIMD3(0.679085634707, 0.157700914643, 0.163213450650),
                SIMD3(0.046002003080, 0.859054673003, 0.094943323917),
                SIMD3(-0.000573943188, 0.028467768408, 0.972106174780)
            ])
        case .redLog3G10RWG:
            return simd_double3x3(rows: [
                SIMD3(0.785058804068, 0.083858756544, 0.131082439388),
                SIMD3(0.023173834845, 1.087897549192, -0.111071384038),
                SIMD3(-0.073760435368, -0.314590072290, 1.388350507658)
            ])
        case .canonCLog2CGamut, .canonCLog3CGamut:
            return simd_double3x3(rows: [
                SIMD3(0.763342923317, 0.147229267219, 0.089427809463),
                SIMD3(0.004230590136, 1.104451311582, -0.108681901718),
                SIMD3(-0.009670967662, -0.213042645554, 1.222713613216)
            ])
        case .canonCLog2BT2020, .canonCLog3BT2020, .appleLogBT2020:
            return simd_double3x3(rows: [
                SIMD3(0.679085634707, 0.157700914643, 0.163213450650),
                SIMD3(0.046002003080, 0.859054673003, 0.094943323917),
                SIMD3(-0.000573943188, 0.028467768408, 0.972106174780)
            ])
        case .djiDLogDGamut:
            return simd_double3x3(rows: [
                SIMD3(0.691430323906, 0.212906283248, 0.095663392846),
                SIMD3(0.066597281331, 1.009546581651, -0.076143862983),
                SIMD3(-0.017243534539, -0.072986432766, 1.090229967305)
            ])
        case .arriLogC3EI800AWG3:
            // ACES Lib.Arri.LogC3 / OCIO ARRI_ALEXA-LOGC-EI800-AWG CAT02 AWG3→AP0.
            return simd_double3x3(rows: [
                SIMD3(0.680205505106, 0.236136601606, 0.083657893287),
                SIMD3(0.085414979742, 1.017470878607, -0.102885858349),
                SIMD3(0.002056521669, -0.062562500385, 1.060505978715)
            ])
        case .appleLog2AWG:
            // ACES CSC.Apple.AppleLog2_to_ACES.ctl Bradford AWG→AP0. Not BT.2020.
            return simd_double3x3(rows: [
                SIMD3(0.694961049318, 0.241405268785, 0.063633681897),
                SIMD3(0.047362746415, 1.004295925054, -0.051658671469),
                SIMD3(-0.021989789360, -0.028989104971, 1.050978894331)
            ])
        default:
            return nil
        }
    }

    private static func decodeLog(_ x: Double, idt: IDT) -> Double {
        switch idt {
        case .arriLogC4AWG4:
            let a = (pow(2.0, 18.0) - 16.0) / 117.45
            let b = (1023.0 - 95.0) / 1023.0
            let c = 95.0 / 1023.0
            let p = 14.0 * (x - c) / b + 6.0
            return (pow(2.0, p) - 64.0) / a
        case .sonySLog3SGamut3, .sonySLog3SGamut3Cine:
            let cut = 171.2102946929 / 1023.0
            let cv = x * 1023.0
            if x >= cut {
                return pow(10.0, (cv - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
            }
            return (cv - 95.0) * 0.01125000 / (171.2102946929 - 95.0)
        case .panasonicVLogVGamut:
            if x >= 0.181 {
                return pow(10.0, (x - 0.598206) / 0.241514) - 0.00873
            }
            return (x - 0.125) / 5.6
        case .fujiFLog2BT2020:
            let a = 5.555556
            if x >= 0.100686685370811 {
                return pow(10.0, (x - 0.384316) / 0.245281) / a - 0.064829 / a
            }
            return (x - 0.092864) / 8.799461
        case .nikonNLogBT2020:
            let cv = x * 1023.0
            if cv < 452.0 {
                return pow(cv / 650.0, 3.0) - 0.0075
            }
            return exp((cv - 619.0) / 150.0)
        case .redLog3G10RWG:
            if x >= 0.0 {
                return (pow(10.0, x / 0.224282) - 1.0) / 155.975327 - 0.01
            }
            return x / 15.1927 - 0.01
        case .canonCLog2CGamut, .canonCLog2BT2020:
            let cut = 0.092864125
            let c1 = 0.24136077
            let c2 = 87.099375
            if x >= cut {
                return 0.9 * (pow(10.0, (x - cut) / c1) - 1.0) / c2
            }
            return -0.9 * (pow(10.0, (cut - x) / c1) - 1.0) / c2
        case .canonCLog3CGamut, .canonCLog3BT2020:
            let a = 0.36726845
            let b = 14.98325
            let ire: Double
            if x < 0.097465473 {
                ire = -(pow(10.0, (0.12783901 - x) / a) - 1.0) / b
            } else if x <= 0.15277891 {
                ire = (x - 0.12512219) / 1.9754798
            } else {
                ire = (pow(10.0, (x - 0.12240537) / a) - 1.0) / b
            }
            return ire * 0.9
        case .appleLogBT2020, .appleLog2AWG:
            // Apple Log 2 reuses the Apple Log 1 curve (ACES CSC.Apple.AppleLog2_to_ACES.ctl).
            let r0 = -0.05641088
            let c = 47.28711236
            let beta = 0.00964052
            let gamma = 0.08550479
            let delta = 0.69336945
            let pt = c * pow(0.01 - r0, 2.0)
            if x >= pt {
                return pow(2.0, (x - delta) / gamma) - beta
            }
            if x >= 0.0 {
                return sqrt(x / c) + r0
            }
            return r0
        case .arriLogC3EI800AWG3:
            // ACES Lib.Arri.LogC3 EI800 only. Same constants as color/curves.py.
            let black = 16.0 / 4095.0
            let cut = 1.0 / 9.0
            let slope = 1.0 / (cut * log(10.0))
            let offset = log10(cut) - slope * cut
            let encGain = 0.24718963831867058
            let encOffset = 0.38553699869244257
            let nz = 0.052272275025168784
            let gray = 0.005
            let out = (x - encOffset) / encGain
            let nsLin = (out - offset) / slope
            let nsRaw = nsLin > cut ? pow(10.0, out) : nsLin
            let ns = (nsRaw - nz) * gray + black
            return (ns - black) * (0.18 / (0.01 * 400.0 / 800.0))
        case .djiDLogDGamut:
            if x > 0.14 {
                return (pow(10.0, 3.89616 * x - 2.27752) - 0.0108) / 0.9892
            }
            return (x - 0.0929) / 6.025
        default:
            return x
        }
    }
}


/// Metal applies the same locked 3×3 (+ optional DIY 709 OETF) as CPU.
/// Numbers stay in PreviewColor. No Core Image, no Display P3.
enum PreviewMetal {
    private static let device = MTLCreateSystemDefaultDevice()
    private static let queue = device?.makeCommandQueue()
    private static let pipeline: MTLComputePipelineState? = {
        guard let device else { return nil }
        let src = """
        #include <metal_stdlib>
        using namespace metal;
        kernel void apply_mtx(
            device float *rgb [[buffer(0)]],
            constant float3x3 &m [[buffer(1)]],
            constant uint &count [[buffer(2)]],
            constant uint &oetf [[buffer(3)]],
            uint id [[thread_position_in_grid]]) {
            if (id >= count) return;
            float3 v = m * float3(rgb[id*3+0], rgb[id*3+1], rgb[id*3+2]);
            if (oetf != 0) {
                const float beta = 0.018053968510807f;
                const float alpha = 1.09929682680944f;
                for (int c = 0; c < 3; ++c) {
                    float x = c == 0 ? v.x : (c == 1 ? v.y : v.z);
                    float y = x < beta ? 4.5f * x : alpha * pow(max(x, 0.0f), 0.45f) - (alpha - 1.0f);
                    if (c == 0) v.x = y; else if (c == 1) v.y = y; else v.z = y;
                }
            }
            rgb[id*3+0] = v.x; rgb[id*3+1] = v.y; rgb[id*3+2] = v.z;
        }
        """
        guard let lib = try? device.makeLibrary(source: src, options: nil),
              let fn = lib.makeFunction(name: "apply_mtx") else { return nil }
        return try? device.makeComputePipelineState(function: fn)
    }()

    /// Same matrix / 709 OETF as CPU. Returns false to fall back.
    static func applyMatrix(_ rgb: inout [Float], matrix: simd_double3x3, rec709OETF: Bool) -> Bool {
        guard let queue, let pipeline, !rgb.isEmpty else { return false }
        let n = UInt32(rgb.count / 3)
        guard n > 0 else { return false }
        let m = simd_float3x3(
            SIMD3(Float(matrix[0, 0]), Float(matrix[0, 1]), Float(matrix[0, 2])),
            SIMD3(Float(matrix[1, 0]), Float(matrix[1, 1]), Float(matrix[1, 2])),
            SIMD3(Float(matrix[2, 0]), Float(matrix[2, 1]), Float(matrix[2, 2]))
        )
        guard let buf = device?.makeBuffer(bytes: &rgb, length: rgb.count * MemoryLayout<Float>.stride, options: .storageModeShared) else {
            return false
        }
        var mtx = m
        var count = n
        var oetf: UInt32 = rec709OETF ? 1 : 0
        guard let cmd = queue.makeCommandBuffer(),
              let enc = cmd.makeComputeCommandEncoder() else { return false }
        enc.setComputePipelineState(pipeline)
        enc.setBuffer(buf, offset: 0, index: 0)
        enc.setBytes(&mtx, length: MemoryLayout<simd_float3x3>.stride, index: 1)
        enc.setBytes(&count, length: MemoryLayout<UInt32>.stride, index: 2)
        enc.setBytes(&oetf, length: MemoryLayout<UInt32>.stride, index: 3)
        let w = pipeline.threadExecutionWidth
        let threads = MTLSize(width: Int(n), height: 1, depth: 1)
        let groups = MTLSize(width: (Int(n) + w - 1) / w, height: 1, depth: 1)
        enc.dispatchThreadgroups(groups, threadsPerThreadgroup: MTLSize(width: w, height: 1, depth: 1))
        enc.endEncoding()
        cmd.commit()
        cmd.waitUntilCompleted()
        let ptr = buf.contents().bindMemory(to: Float.self, capacity: rgb.count)
        rgb = Array(UnsafeBufferPointer(start: ptr, count: rgb.count))
        _ = threads
        return true
    }
}

