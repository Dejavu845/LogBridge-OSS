import Foundation
import Combine
import AppKit
import simd

/// One imported clip with a locked curve+gamut pair (or a pending picker).
///
/// `idt` is nil until metadata/filename/model locks a pair or the user picks
/// a paired IDT. Never default S-Log3 to S-Gamut3.Cine, or C-Log2/C-Log3 to Cinema Gamut.
struct Clip: Identifiable, Hashable {
    let id: UUID
    let url: URL
    var idt: IDT?
    var detectedCurve: String?
    var detectedGamut: String?
    var detectionSource: DetectionSource
    var needsUserPicker: Bool
    var detectionNote: String
    var veniceDetected: Bool
    var asShotCCT: Double?
    var asShotTint: Double
    var wbSource: WBSource
    var wbCCT: Double?
    var wbTint: Double
    var formatNote: String
    /// Sidebar chip after 「处理已锁定片段」. `已写出代理`, a short Chinese error, or nil.
    /// Cleared on re-export. Cancelled in-progress stays nil. 不是成片.
    var exportChip: String? = nil

    var filename: String { url.lastPathComponent }

    var asShotUnknown: Bool { asShotCCT == nil && wbSource == .unknown }

    var lockedPairLabel: String {
        if let idt {
            return idt.pairLabel
        }
        if let curve = detectedCurve {
            return "\(curve) + (pick pair)"
        }
        return "先选择成对 IDT"
    }

    /// Paired IDTs only. Venice rows appear only if this clip is a Venice body.
    var pickerPairs: [IDT] {
        IDT.pickerPairs(
            curveHint: displayCurve,
            veniceDetected: veniceDetected,
            needsPicker: needsUserPicker || idt == nil
        )
    }

    /// No locked implemented pair — stays pending; batch skips this clip.
    var isPending: Bool { idt == nil || needsUserPicker }

    var hasLockedPair: Bool {
        guard let idt, !idt.isStub else { return false }
        return !needsUserPicker
    }

    /// Unlocked / pending stay in the list with this reason. Never guess an IDT.
    var processSkipReason: String? {
        if hasLockedPair { return nil }
        if detectedCurve != nil || idt != nil || needsUserPicker {
            return "先选择成对 IDT"
        }
        return "先选择 Log 与色域"
    }

    var verificationBadge: String {
        if let idt, idt.isStub { return "stub" }
        if isPending { return "待选" }
        return "已实现（未验证）"
    }

    /// Sidebar row under the pair. Pending keep skip reasons.
    /// After a write: 已写出代理 or a short Chinese error.
    var sidebarStatusChip: String? { processSkipReason ?? exportChip }

    /// Preview chrome when selected and not mid-export. Existing phrases only.
    /// Pending / unlocked → that clip's processSkipReason. Failed / success → exportChip.
    var previewCaption: String? { processSkipReason ?? exportChip }

    var displayCurve: String? { idt?.curve ?? detectedCurve }
    var displayGamut: String? { idt?.gamut ?? detectedGamut }
}

enum DetectionSource: String, Hashable {
    case metadata
    case filename
    case model
    case user
    case unresolved
}

/// Locked-clip dest estimate. Uncompressed float32 RGB EXR (12 bytes / pixel).
/// Header / offset table is covered by the 10% + 64 MiB margin. 不是成片.
struct ProxyDiskEstimate {
    var bytes: Int64
    var usedFrameGuess: Bool
    var usedDurationFps: Bool

    var neededWithMargin: Int64 {
        bytes + bytes / 10 + 64 * 1024 * 1024
    }

    var note: String {
        let size = SessionModel.formatProxyBytes(bytes)
        if usedFrameGuess {
            return "约 \(size)（float32 RGB 未压缩；帧数按每秒 24 帧估算）"
        }
        if usedDurationFps {
            return "约 \(size)（float32 RGB 未压缩；帧数按时长×帧率估算）"
        }
        return "约 \(size)（float32 RGB 未压缩）"
    }

    var pickerSuffix: String { note + "。" }
}

final class SessionModel: ObservableObject {
    @Published var clips: [Clip] = []
    @Published var selectedID: UUID?
    @Published var selectedNode: NodeSlot = .idt
    @Published var graph = SerialGraph()
    @Published var showImporter = false
    @Published var dropTargeted = false
    @Published var lastExportNote: String = ""
    @Published var lastImportNote: String = ""
    @Published var pickingNeutral: Bool = false
    @Published var showSettings = false
    @Published var isWritingDeliverables = false
    /// Same busy flag. Preview progress + inspector / IDT lock read this.
    var isExporting: Bool { isWritingDeliverables }
    /// Completed `{stem}_ACES2065-1_proxy` folders from the last successful write.
    /// Empty while writing, after cancel, or when nothing was written.
    @Published var lastExportRevealURLs: [URL] = []
    /// Tiny-disk / test mock. When set, dest free-space check uses this
    /// instead of the volume. Nil reads the real volume.
    var destFreeBytesOverride: Int64? = nil

    let preview = PreviewEngine()
    let settings = AppSettings.shared
    private let writeCancel = WriteCancelFlag()
    private var lastProgressUptime: TimeInterval = 0

    init() {
        graph.odt = settings.defaultPreviewODT
    }

    var selectedClip: Clip? {
        clips.first { $0.id == selectedID }
    }

    func refreshPreview() {
        // Selected clip (or grade) changed. PreviewEngine keeps only this
        // clip's preview source/linear/graded and drops a stale first-frame
        // if selection already moved on. Write path is not this cache.
        preview.refresh(clip: selectedClip, graph: graph)
    }

    /// ODT / scrub: do not invalidate graded linear (IDT+exposure+WB).
    func refreshODTOnly() {
        preview.refreshODT(clip: selectedClip, graph: graph)
    }

    /// HDR layer could not enable EDR. Empty right pane. Never fall back to 709.
    func failClosedHDRPreviewLayer() {
        guard graph.odt.isHDR else { return }
        preview.failClosedHDRPreview()
    }

    var pendingPickerCount: Int {
        clips.filter { $0.needsUserPicker || $0.idt == nil }.count
    }

    var lockedClips: [Clip] { clips.filter(\.hasLockedPair) }
    var lockedClipCount: Int { lockedClips.count }
    var pendingClipCount: Int { clips.filter { !$0.hasLockedPair }.count }

    /// 「N 条已锁定 / M 条待选」
    var lockStatusText: String {
        "\(lockedClipCount) 条已锁定 / \(pendingClipCount) 条待选"
    }

    /// Primary button is shown only when at least one paired IDT is locked.
    var showsProcessLockedButton: Bool {
        settings.blockUnlockedIDT && lockedClipCount > 0
    }

    /// ACEScct / EXR export for locked clips. Pending clips in the same bin
    /// do not block — they stay listed and are skipped.
    var canProcess: Bool {
        !clips.isEmpty && lockedClipCount > 0
    }

    /// Selected clip has a locked pair (preview / inspector).
    var canProcessSelected: Bool {
        selectedClip?.hasLockedPair == true
    }

    var processBlockedReason: String? {
        if clips.isEmpty { return "把混源文件夹拖进来" }
        if lockedClipCount == 0 {
            return clips.first?.processSkipReason ?? "先选择 Log 与色域"
        }
        return nil
    }

    var processSelectedBlockedReason: String? {
        guard let clip = selectedClip else { return "No clip selected" }
        return clip.processSkipReason
    }

    /// Batch: write one ACES2065-1 AP0 proxy EXR sequence per locked clip.
    /// Unlocked stay listed with a Chinese reason. After the batch,
    /// lastExportNote is 「N 条已写出代理 / M 条待选跳过 / K 条失败」.
    /// Never guess an IDT. Never 一键还原. One process entry point.
    /// Mixed bins are allowed. 整段代理，不是全精度成片.
    func processLockedClips() {
        if isWritingDeliverables { return }
        let locked = clips.filter(\.hasLockedPair)
        let skipped = clips.filter { !$0.hasLockedPair }
        guard !locked.isEmpty else {
            lastExportNote = skipped.first?.processSkipReason ?? "先选择 Log 与色域"
            return
        }
        if selectedClip?.hasLockedPair == true {
            refreshPreview()
        }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "写出"
        let estimate = Self.estimateLockedProxyBytes(urls: locked.map(\.url))
        panel.message = "已锁定片段写出 ACES2065-1 代理 EXR 序列（AP0 线性）。整段代理，不是全精度成片。未锁定的跳过（先选择 Log 与色域 / 先选择成对 IDT）。预览·非成片。已实现（未验证）。" + estimate.pickerSuffix
        if let remembered = settings.lastExportDirectoryURL {
            panel.directoryURL = remembered
        }
        panel.begin { [weak self] response in
            guard let self, response == .OK, let dest = panel.url else { return }
            _ = dest.startAccessingSecurityScopedResource()
            self.settings.rememberExportDirectory(dest)
            self.writeLockedDeliverables(locked: locked, skippedCount: skipped.count, dest: dest)
        }
    }

    /// Writes ACES2065-1 AP0 proxy EXR sequences for locked clips only.
    func writeLockedDeliverables(locked: [Clip], skippedCount: Int, dest: URL) {
        let estimate = Self.estimateLockedProxyBytes(urls: locked.map(\.url))
        if let free = destFreeBytesOverride ?? Self.destVolumeFreeBytes(dest),
           free < estimate.neededWithMargin {
            lastExportRevealURLs = []
            lastExportNote = Self.batchSummaryText(
                wrote: 0,
                skipped: skippedCount,
                failed: locked.count,
                reasons: [Self.diskShortStatus]
            )
            return
        }
        let graphCopy = graph
        let clipTotal = locked.count
        writeCancel.reset()
        lastProgressUptime = 0
        lastExportRevealURLs = []
        clearExportChips(for: locked)
        isWritingDeliverables = true
        lastExportNote = Self.exportProgressText(clipIndex: 1, clipTotal: clipTotal)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            var written: [URL] = []
            var errors: [String] = []
            var cancelled = false
            for (offset, clip) in locked.enumerated() {
                if self.writeCancel.isRequested {
                    cancelled = true
                    break
                }
                let clipIndex = offset + 1
                self.publishExportProgress(
                    Self.exportProgressText(clipIndex: clipIndex, clipTotal: clipTotal),
                    force: true
                )
                do {
                    let url = try self.exportLockedEXR(
                        clip: clip,
                        graph: graphCopy,
                        dest: dest
                    ) { frame in
                        self.publishExportProgress(
                            Self.exportProgressText(
                                clipIndex: clipIndex,
                                clipTotal: clipTotal,
                                frame: frame
                            )
                        )
                    }
                    written.append(url)
                    self.setExportChip(clipID: clip.id, Self.wroteProxyChip)
                } catch is LockedWriteCancel {
                    cancelled = true
                    break
                } catch {
                    let chip = Self.shortExportChip(for: error)
                    errors.append("\(clip.filename)：\(chip)")
                    self.setExportChip(clipID: clip.id, chip)
                }
            }
            let wrote = written.count
            let failed = locked.count - wrote
            var reasons = errors
            if cancelled {
                reasons.append(Self.cancelledNote)
            }
            // Deleted half-folder is not a success. Do not reveal it.
            let reveal: [URL] = (cancelled || written.isEmpty) ? [] : written
            let destForNote: URL? = (cancelled || written.isEmpty) ? nil : dest
            let note = Self.batchSummaryText(
                wrote: wrote,
                skipped: skippedCount,
                failed: failed,
                reasons: reasons,
                dest: destForNote
            )
            DispatchQueue.main.async {
                self.lastExportNote = note
                self.lastExportRevealURLs = reveal
                self.isWritingDeliverables = false
            }
        }
    }

    /// 「N 条已写出代理 / M 条待选跳过 / K 条失败」 plus 失败原因.
    /// Existing Chinese chips only. Does not invent fps. No dest-disk frame guess.
    static func batchSummaryText(
        wrote: Int,
        skipped: Int,
        failed: Int,
        reasons: [String] = [],
        dest: URL? = nil
    ) -> String {
        var note = "\(wrote) 条已写出代理 / \(skipped) 条待选跳过 / \(failed) 条失败"
        if !reasons.isEmpty {
            note += "。\(failedBucket) " + reasons.joined(separator: " ")
        }
        note += "。整段代理，不是全精度成片。预览·非成片。已实现（未验证）。"
        if let dest, wrote > 0 {
            note += " " + shortExportPath(dest)
        }
        return note
    }

    /// One ACES2065-1 AP0 proxy EXR sequence. Source Y′CbCr → float + PreviewColor grade; no ODT.
    /// After write, count EXRs against duration × metadata fps only.
    /// Mismatch / missing timing is a Chinese failure; the folder is removed.
    /// Not ACEScct. Not a Rec.709 movie. 整段代理，不是全精度成片.
    func exportLockedEXR(
        clip: Clip,
        graph: SerialGraph,
        dest: URL,
        onFrame: ((Int) -> Void)? = nil
    ) throws -> URL {
        guard clip.hasLockedPair else {
            throw NSError(domain: "LogBridge", code: 1, userInfo: [
                NSLocalizedDescriptionKey: clip.processSkipReason ?? "先选择成对 IDT"
            ])
        }
        let seqDir = ResolveExporter.deliverableSequenceDirectory(for: clip, in: dest)
        if FileManager.default.fileExists(atPath: seqDir.path) {
            try FileManager.default.removeItem(at: seqDir)
        }
        try FileManager.default.createDirectory(at: seqDir, withIntermediateDirectories: true)
        do {
            let count = try preview.exportGradedAP0Sequence(clip: clip, graph: graph) { index, rgb, width, height in
                if self.writeCancel.isRequested {
                    throw LockedWriteCancel()
                }
                let url = ResolveExporter.sequenceFrameURL(in: seqDir, index: index)
                try ResolveExporter.writeACES2065EXR(
                    rgb: rgb,
                    width: width,
                    height: height,
                    to: url
                )
                onFrame?(index + 1)
            }
            if count < 1 {
                throw NSError(domain: "LogBridge", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "decode/grade failed"
                ])
            }
            try Self.verifyLockedProxySequence(clip: clip, seqDir: seqDir)
        } catch {
            try? FileManager.default.removeItem(at: seqDir)
            throw error
        }
        return seqDir
    }

    /// Same primary button becomes 取消 while writing. Not a second process button.
    func cancelLockedDeliverables() {
        writeCancel.request()
    }

    /// Escape while writing: same cancel as the 取消 control.
    /// Idle Escape does nothing (does not clear selection, does not quit).
    /// Sheets / alerts / settings keep Escape.
    @discardableResult
    func cancelWritingFromEscape() -> Bool {
        guard isWritingDeliverables else { return false }
        guard !showSettings, !showImporter else { return false }
        cancelLockedDeliverables()
        return true
    }

    /// 「写出代理 2/5 · frame 120」. Frame total omitted when unknown.
    static func exportProgressText(clipIndex: Int, clipTotal: Int, frame: Int? = nil, frameTotal: Int? = nil) -> String {
        var note = "写出代理 \(clipIndex)/\(clipTotal)"
        if let frame {
            if let frameTotal {
                note += " · frame \(frame)/\(frameTotal)"
            } else {
                note += " · frame \(frame)"
            }
        }
        return note
    }

    /// Cancelled batch. 已取消 + honesty. Partial output is 不是成片.
    static func cancelledExportNote(processed: Int, skipped: Int) -> String {
        "处理已锁定片段 — 已取消。\(processed) 条已处理 / \(skipped) 条已跳过（先选择 Log 与色域 / 先选择成对 IDT）。整段代理，不是全精度成片。预览·非成片。已实现（未验证）。"
    }

    /// Uncompressed float32 RGB (3 × 4). Matches color/batch.py.
    static let bytesPerEXRPixel: Int64 = 12
    static let conservativeFPS = 24.0
    static let conservativeSeconds = 60.0
    static let conservativeWidth = 3840
    static let conservativeHeight = 2160
    static let diskShortStatus = "磁盘空间不足，未写出"
    static let diskEstimateAssumption = "float32 RGB 未压缩"
    static let cancelledNote = "已取消"
    static let skippedBucket = "待选跳过"
    static let failedBucket = "失败原因"

    static func formatProxyBytes(_ n: Int64) -> String {
        let v = max(Int64(0), n)
        if v >= 1_000_000_000 {
            return String(format: "%.1f GB", Double(v) / 1_000_000_000.0)
        }
        if v >= 1_000_000 {
            return String(format: "%.0f MB", Double(v) / 1_000_000.0)
        }
        if v >= 1000 {
            return String(format: "%.0f KB", Double(v) / 1000.0)
        }
        return "\(v) B"
    }

    static func estimatedFrameCount(_ ext: MediaExtent) -> (Int, String) {
        if let n = ext.frameCount, n > 0 { return (n, "known") }
        if let duration = ext.durationSeconds, duration > 0, let fps = ext.fps, fps > 0 {
            return (max(1, Int((duration * fps).rounded(.up))), "duration_fps")
        }
        if let duration = ext.durationSeconds, duration > 0 {
            return (max(1, Int((duration * conservativeFPS).rounded(.up))), "guess")
        }
        if let fps = ext.fps, fps > 0 {
            return (max(1, Int((conservativeSeconds * fps).rounded(.up))), "guess")
        }
        return (max(1, Int((conservativeSeconds * conservativeFPS).rounded(.up))), "guess")
    }

    static func estimatedPixelCount(_ ext: MediaExtent) -> Int {
        if let w = ext.width, let h = ext.height, w > 0, h > 0 { return w * h }
        return conservativeWidth * conservativeHeight
    }

    /// Locked clips only. Pending URLs are not passed in.
    static func estimateLockedProxyBytes(urls: [URL]) -> ProxyDiskEstimate {
        var total: Int64 = 0
        var usedFrameGuess = false
        var usedDurationFps = false
        for url in urls {
            let ext = MediaFormat.extent(url: url)
            let (frames, frameSrc) = estimatedFrameCount(ext)
            let pixels = estimatedPixelCount(ext)
            total += Int64(frames) * Int64(pixels) * bytesPerEXRPixel
            if frameSrc == "guess" { usedFrameGuess = true }
            if frameSrc == "duration_fps" { usedDurationFps = true }
        }
        return ProxyDiskEstimate(
            bytes: total,
            usedFrameGuess: usedFrameGuess,
            usedDurationFps: usedDurationFps
        )
    }

    static func destVolumeFreeBytes(_ dest: URL) -> Int64? {
        let keys: Set<URLResourceKey> = [
            .volumeAvailableCapacityForImportantUsageKey,
            .volumeAvailableCapacityKey
        ]
        guard let values = try? dest.resourceValues(forKeys: keys) else { return nil }
        if let important = values.volumeAvailableCapacityForImportantUsage, important >= 0 {
            return important
        }
        if let cap = values.volumeAvailableCapacity {
            return Int64(cap)
        }
        return nil
    }

    /// 「磁盘空间不足，未写出」 + honesty. Did not write. No 精准.
    static func diskShortExportNote(estimate: ProxyDiskEstimate) -> String {
        "\(diskShortStatus)。\(estimate.note)。整段代理，不是全精度成片。"
    }

    /// Locked row after a proxy sequence write. Not a finished picture.
    static let wroteProxyChip = "已写出代理"
    static let decodeFailedChip = "解码失败"
    static let writeFailedChip = "写出失败"
    static let frameMismatchChip = "帧数对不上"
    static let missingFpsChip = "读不到帧率，未核对"
    static let missingDurationChip = "读不到时长，未核对"
    static let missingYCbCrTagsChip = "无法读取片源 Y′CbCr 矩阵/范围，未写出"
    static let writeOversizeChip = "片源边长超过 16384，未写出"

    /// Short Chinese sidebar / status error. Failed write is not silent.
    static func shortExportChip(for error: Error) -> String {
        if error is LockedWriteCancel { return writeFailedChip }
        let desc = error.localizedDescription
        if desc.hasPrefix("先选择") { return desc }
        if desc == frameMismatchChip || desc == missingFpsChip || desc == missingDurationChip
            || desc == missingYCbCrTagsChip || desc == writeOversizeChip {
            return desc
        }
        let lower = desc.lowercased()
        if lower.contains("decode") || lower.contains("grade") {
            return decodeFailedChip
        }
        return writeFailedChip
    }

    /// Expected EXR count: duration × metadata fps only. Never invent a frame rate.
    /// Missing fps / duration fail closed.
    static func expectedSourceFrames(_ ext: MediaExtent) -> (Int?, String?) {
        let duration: Double? = {
            guard let d = ext.durationSeconds, d.isFinite, d > 0 else { return nil }
            return d
        }()
        let fps: Double? = {
            guard let f = ext.fps, f.isFinite, f > 0 else { return nil }
            return f
        }()
        if let duration, let fps {
            return (max(1, Int((duration * fps).rounded(.up))), nil)
        }
        if fps == nil {
            return (nil, missingFpsChip)
        }
        return (nil, missingDurationChip)
    }

    /// How many ``.exr`` files are in the proxy folder. Missing folder → 0.
    static func countProxyEXRs(in seqDir: URL) -> Int {
        guard let items = try? FileManager.default.contentsOfDirectory(
            at: seqDir,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else { return 0 }
        return items.filter { $0.pathExtension.lowercased() == "exr" }.count
    }

    /// Off-by-one: inclusive last frame on duration × fps. Empty is never a match.
    static func framesCountMatches(written: Int, expected: Int) -> Bool {
        if written < 1 || expected < 1 { return false }
        return abs(written - expected) <= 1
    }

    /// Post-write check. Throws a Chinese chip. Caller removes the folder.
    static func verifyLockedProxySequence(clip: Clip, seqDir: URL) throws {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: seqDir.path, isDirectory: &isDir),
              isDir.boolValue else {
            throw NSError(domain: "LogBridge", code: 4, userInfo: [
                NSLocalizedDescriptionKey: frameMismatchChip
            ])
        }
        let written = countProxyEXRs(in: seqDir)
        let (expected, timingErr) = expectedSourceFrames(MediaFormat.extent(url: clip.url))
        if let timingErr {
            throw NSError(domain: "LogBridge", code: 4, userInfo: [
                NSLocalizedDescriptionKey: timingErr
            ])
        }
        guard let expected, framesCountMatches(written: written, expected: expected) else {
            throw NSError(domain: "LogBridge", code: 4, userInfo: [
                NSLocalizedDescriptionKey: frameMismatchChip
            ])
        }
    }

    /// Re-export clears the chip so a previous 已写出代理 does not linger.
    private func clearExportChips(for locked: [Clip]) {
        let ids = Set(locked.map(\.id))
        for i in clips.indices where ids.contains(clips[i].id) {
            clips[i].exportChip = nil
        }
    }

    private func setExportChip(clipID: UUID, _ chip: String?) {
        DispatchQueue.main.async { [weak self] in
            guard let self, let idx = self.clips.firstIndex(where: { $0.id == clipID }) else { return }
            self.clips[idx].exportChip = chip
        }
    }

    /// Status dest path (short). Parent folder name, not a deliverable claim.
    static func shortExportPath(_ url: URL) -> String {
        url.lastPathComponent
    }

    static let revealInFinderLabel = "在 Finder 中显示"

    var canRevealLastExport: Bool { !lastExportRevealURLs.isEmpty }

    /// Finished batch note near the process bar. Not a second process button.
    var showsBatchSummary: Bool {
        !isWritingDeliverables && lastExportNote.contains("条已写出代理")
    }

    /// Opens completed `{stem}_ACES2065-1_proxy` folders. Skips missing paths.
    func revealLastExportInFinder() {
        let existing = lastExportRevealURLs.filter {
            FileManager.default.fileExists(atPath: $0.path)
        }
        guard !existing.isEmpty else { return }
        NSWorkspace.shared.activateFileViewerSelecting(existing)
    }

    /// Last dest + `{stem}_ACES2065-1_proxy`. Success chip only.
    /// Pending / failed / cancelled do not reveal. 不是成片.
    static func clipSequenceRevealURL(for clip: Clip, dest: URL) -> URL? {
        guard clip.exportChip == wroteProxyChip else { return nil }
        return ResolveExporter.deliverableSequenceDirectory(for: clip, in: dest)
    }

    /// Sidebar row / 「已写出代理」 chip. Reuses last dest. No-op unless written.
    func revealClipExportInFinder(_ clip: Clip) {
        guard let dest = settings.lastExportDirectoryURL,
              let seqDir = Self.clipSequenceRevealURL(for: clip, dest: dest),
              FileManager.default.fileExists(atPath: seqDir.path)
        else { return }
        NSWorkspace.shared.activateFileViewerSelecting([seqDir])
    }

    private func publishExportProgress(_ note: String, force: Bool = false) {
        let now = ProcessInfo.processInfo.systemUptime
        if !force && (now - lastProgressUptime) < 0.12 { return }
        lastProgressUptime = now
        DispatchQueue.main.async { [weak self] in
            self?.lastExportNote = note
        }
    }

    /// Primary action alias. Label is "处理已锁定片段" — never 一键还原.
    func processSelected() {
        processLockedClips()
    }

    /// Same batch as processLockedClips. Never 一键还原. Not a second button.
    func applyGraph() {
        processLockedClips()
    }

    var odtPreviewTitle: String {
        switch graph.odt {
        case .off:
            return "709 预览关"
        case .rec709:
            return "Rec.709 预览·非成片"
        case .hlg:
            return "HLG 预览·非成片（未匹配 709）"
        case .pq:
            return "PQ 预览·非成片（未匹配 709）"
        }
    }

    var odtPreviewCaption: String {
        // Hover on the Rec.709 pane. Existing phrases only (#43 / #47).
        switch graph.odt {
        case .off:
            return "709 预览关"
        case .rec709, .hlg, .pq:
            return "预览·非成片"
        }
    }

    func setIDT(_ id: UUID, _ idt: IDT) {
        guard let idx = clips.firstIndex(where: { $0.id == id }) else { return }
        let wasPending = !clips[idx].hasLockedPair
        clips[idx].idt = idt
        clips[idx].detectedCurve = idt.curve
        clips[idx].detectedGamut = idt.gamut
        clips[idx].detectionSource = .user
        clips[idx].needsUserPicker = false
        clips[idx].detectionNote = "user picker (paired IDT)"
        preview.invalidateIDT(clipID: id)
        // Lock of the selected pending clip: land on the next 待选.
        // Mid-write (#32) does not change selection. Does not lock the next IDT.
        if wasPending, !isWritingDeliverables {
            selectNextPendingAfterLock(lockedID: id)
        }
        refreshPreview()
    }

    /// After locking the selected pending clip, select the next pending/unlocked
    /// (after current index, else wrap to the first pending that is not the
    /// one just locked). Stay if none remain. Does not lock IDT. Does not write.
    func selectNextPendingAfterLock(lockedID: UUID) {
        guard selectedID == lockedID else { return }
        guard let currentIdx = clips.firstIndex(where: { $0.id == lockedID }) else { return }
        if let next = clips.dropFirst(currentIdx + 1).first(where: { !$0.hasLockedPair }) {
            selectedID = next.id
            applyClipWBToGraph(next)
            return
        }
        if let wrap = clips.first(where: { $0.id != lockedID && !$0.hasLockedPair }) {
            selectedID = wrap.id
            applyClipWBToGraph(wrap)
        }
    }

    /// Up/Down in the main window: move selected clip in the sidebar list.
    /// Mid-write (#32 / #37) does not change selection. Does not lock IDT. Does not write.
    /// Stops at the ends (no wrap). Inspector numeric / search / text fields keep their arrows.
    @discardableResult
    func selectAdjacentClip(_ delta: Int) -> Bool {
        guard !isWritingDeliverables else { return false }
        guard !showSettings, !showImporter else { return false }
        guard !Self.isArrowConsumedByTextInput() else { return false }
        guard !clips.isEmpty, delta != 0 else { return false }
        let step = delta > 0 ? 1 : -1
        if let id = selectedID, let idx = clips.firstIndex(where: { $0.id == id }) {
            let next = idx + step
            guard clips.indices.contains(next) else { return false }
            selectedID = clips[next].id
            applyClipWBToGraph(clips[next])
            return true
        }
        let idx = step > 0 ? 0 : clips.count - 1
        selectedID = clips[idx].id
        applyClipWBToGraph(clips[idx])
        return true
    }

    /// Delete / Backspace: drop the selected clip from the SESSION only.
    /// Does not delete, trash, or move the source file. Does not delete an
    /// already-written `_proxy` folder — leave it on disk; just drop the row.
    /// After remove, select next, else previous. Preview chrome follows #33
    /// (`processSkipReason` / `exportChip` on the new selected clip).
    /// #40: evict the removed clip's preview cache.
    /// Mid-write (#32 / #41): ignore — do not change selection, do not cancel
    /// (Escape cancels). Text / numeric / search fields keep Delete.
    /// No confirm sheet. No extra button.
    @discardableResult
    func removeSelectedClipFromSession() -> Bool {
        guard !isWritingDeliverables else { return false }
        guard !showSettings, !showImporter else { return false }
        guard !Self.isArrowConsumedByTextInput() else { return false }
        guard let id = selectedID, let idx = clips.firstIndex(where: { $0.id == id }) else {
            return false
        }
        // Session list only. Source file and any already-written `_proxy` stay.
        clips.remove(at: idx)
        preview.evict(clipID: id)
        if clips.indices.contains(idx) {
            selectedID = clips[idx].id
            applyClipWBToGraph(clips[idx])
        } else if idx > 0, clips.indices.contains(idx - 1) {
            selectedID = clips[idx - 1].id
            applyClipWBToGraph(clips[idx - 1])
        } else {
            selectedID = nil
        }
        return true
    }

    /// Arrow keys stay with the focused text / search / numeric control.
    static func isArrowConsumedByTextInput() -> Bool {
        guard let responder = NSApp.keyWindow?.firstResponder else { return false }
        if responder is NSTextView || responder is NSTextField || responder is NSText {
            return true
        }
        if responder is NSSlider || responder is NSStepper || responder is NSSearchField {
            return true
        }
        if responder is NSPopUpButton || responder is NSComboBox {
            return true
        }
        return false
    }

    /// Sheets / alerts / other key windows keep Escape. Do not steal dismiss.
    static func isEscapeReservedByPresentedUI(event: NSEvent, monitorWindow: NSWindow?) -> Bool {
        if event.window !== monitorWindow { return true }
        if event.window?.attachedSheet != nil { return true }
        if NSApp.modalWindow != nil { return true }
        if let key = NSApp.keyWindow, key !== monitorWindow { return true }
        return false
    }

    func setExposureEnabled(_ enabled: Bool) {
        graph.setEnabled(.exposure, enabled)
        preview.invalidateWBODT()
        refreshPreview()
    }

    func setExposureStops(_ stops: Double) {
        graph.exposureStops = stops
        preview.invalidateWBODT()
        refreshPreview()
    }

    func setWBEnabled(_ enabled: Bool) {
        graph.setEnabled(.wb, enabled)
        preview.invalidateWBODT()
        refreshPreview()
    }

    func setODTEnabled(_ enabled: Bool) {
        graph.setEnabled(.odt, enabled)
        refreshODTOnly()
    }

    func setODT(_ mode: ODTMode) {
        graph.odt = mode
        refreshODTOnly()
    }

    func setWBParams(cct: Double? = nil, tint: Double? = nil, method: String? = nil) {
        if let cct {
            graph.wbCCT = cct
            graph.wbSource = .user
        }
        if let tint {
            graph.wbTint = tint
            if graph.wbCCT != nil {
                graph.wbSource = .user
            }
        }
        if let method { graph.wbMethod = method }
        persistGraphWBToSelectedClip()
        preview.invalidateWBODT()
        refreshPreview()
    }

    func applyClipWBToGraph(_ clip: Clip) {
        graph.asShotCCT = clip.asShotCCT
        graph.asShotTint = clip.asShotTint
        graph.wbSource = clip.wbSource
        graph.wbCCT = clip.wbCCT
        graph.wbTint = clip.wbTint
        if clip.wbSource == .asShot || clip.wbSource == .grey || clip.wbSource == .estimate {
            graph.wbEnabled = true
        }
    }

    func persistGraphWBToSelectedClip() {
        guard let id = selectedID, let idx = clips.firstIndex(where: { $0.id == id }) else { return }
        clips[idx].wbSource = graph.wbSource
        clips[idx].wbCCT = graph.wbCCT
        clips[idx].wbTint = graph.wbTint
    }

    /// Grey-card pick: sample after IDT in ACES2065-1 (AP0) linear. Overrides metadata.
    func pickNeutral(linearRGB: SIMD3<Double>) {
        guard let est = WhiteBalanceNode.pickNeutral(linearRGB: linearRGB, rgbToXYZ: WhiteBalanceNode.ap0ToXYZ) else { return }
        graph.wbCCT = est.cct
        graph.wbTint = est.tint
        graph.wbSource = .grey
        graph.wbEnabled = true
        persistGraphWBToSelectedClip()
        preview.invalidateWBODT()
        refreshPreview()
    }

    /// 白平衡（估计）: SoG on cached post-IDT AP0. Does not write CAT.
    func proposeAutoWB() {
        guard let clip = selectedClip, clip.hasLockedPair else { return }
        guard let frame = preview.linearAP0Frame(clipID: clip.id) else { return }
        if let est = WhiteBalanceNode.estimateAutoWB(ap0: frame.rgb, width: frame.width, height: frame.height) {
            graph.autoWBCCT = est.cct
            graph.autoWBTint = est.tint
        } else {
            graph.autoWBCCT = nil
            graph.autoWBTint = 0
        }
    }

    /// Confirm estimate → absolute AP0 CAT. Grey-card wins. Empty stays empty.
    func confirmAutoWB() {
        guard graph.wbSource != .grey, let cct = graph.autoWBCCT else { return }
        graph.wbCCT = cct
        graph.wbTint = graph.autoWBTint
        graph.wbSource = .estimate
        graph.wbEnabled = true
        persistGraphWBToSelectedClip()
        preview.invalidateWBODT()
        refreshPreview()
    }

    /// Click on the processed pane: sample cached post-IDT AP0 linear (not log, not ACEScct).
    func handlePreviewPick(nx: Double, ny: Double) {
        guard pickingNeutral, let clip = selectedClip else { return }
        guard let rgb = preview.sampleLinearRGB(
            clipID: clip.id,
            nx: nx,
            ny: ny,
            exposureStops: 0,
            exposureEnabled: false
        ) else { return }
        pickNeutral(linearRGB: rgb)
        pickingNeutral = false
    }

    func importProviders(_ providers: [NSItemProvider]) {
        for provider in providers {
            provider.loadItem(forTypeIdentifier: "public.file-url", options: nil) { item, _ in
                let url: URL?
                if let data = item as? Data {
                    url = URL(dataRepresentation: data, relativeTo: nil)
                } else if let u = item as? URL {
                    url = u
                } else {
                    url = nil
                }
                guard let url else { return }
                DispatchQueue.main.async {
                    self.importURL(url)
                }
            }
        }
    }

    func handleImporter(_ result: Result<[URL], Error>) {
        if case .success(let urls) = result {
            urls.forEach { importURL($0) }
        }
    }

    func importURL(_ url: URL) {
        // Keep the security scope for the session so preview decode can reopen the URL.
        _ = url.startAccessingSecurityScopedResource()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let files = Self.expandToClipURLs(url)
            var skipped: [String] = []
            var built: [Clip] = []
            for file in files {
                let probe = MediaFormat.probe(url: file)
                if probe.decision == .refuse {
                    skipped.append("\(file.lastPathComponent)：\(probe.note)")
                    continue
                }
                if probe.decision == .tryDecode {
                    // MXF: only keep if the system can open a video track.
                    if MediaFormat.codecFourCC(url: file) == nil {
                        skipped.append("\(file.lastPathComponent)：\(MediaFormat.noteARRIMxf)")
                        continue
                    }
                }
                let detection = ClipDetector.detect(url: file)
                // Never silently assign an IDT. S-Log3 without gamut stays nil.
                let shot = detection.asShotCCT
                built.append(Clip(
                    id: UUID(),
                    url: file,
                    idt: detection.idt,
                    detectedCurve: detection.curve,
                    detectedGamut: detection.gamut,
                    detectionSource: detection.source,
                    needsUserPicker: detection.needsUserPicker,
                    detectionNote: detection.note,
                    veniceDetected: detection.veniceDetected,
                    asShotCCT: shot,
                    asShotTint: detection.asShotTint,
                    wbSource: shot == nil ? .unknown : .asShot,
                    wbCCT: shot,
                    wbTint: detection.asShotTint,
                    formatNote: probe.note
                ))
            }
            DispatchQueue.main.async {
                guard let self else { return }
                for clip in built {
                    self.clips.append(clip)
                }
                // After drop/import: first pending/unlocked so 待选 is obvious.
                // All-locked keeps first / existing selection. Does not lock IDT.
                if let pending = built.first(where: { !$0.hasLockedPair }) {
                    self.selectedID = pending.id
                    self.applyClipWBToGraph(pending)
                } else if self.selectedID == nil, let first = built.first {
                    self.selectedID = first.id
                    self.applyClipWBToGraph(first)
                }
                if !skipped.isEmpty {
                    self.lastImportNote = skipped.joined(separator: "\n")
                }
                if self.settings.promptEstimateWBOnImport {
                    let locked = built.contains { $0.hasLockedPair }
                    let hint = "可点「估计白平衡」查看估计，确认后才写入。不是校准，不猜 5600。"
                    if locked {
                        self.lastImportNote = (self.lastImportNote.isEmpty ? hint : self.lastImportNote + "\n" + hint)
                    }
                }
                self.refreshPreview()
            }
        }
    }

    private static let clipExtensions: Set<String> = MediaFormat.expandExt

    /// Folder drop expands to media files. A single dropped file is kept as-is.
    static func expandToClipURLs(_ url: URL) -> [URL] {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) else {
            return [url]
        }
        if !isDir.boolValue {
            return [url]
        }
        var out: [URL] = []
        let keys: [URLResourceKey] = [.isRegularFileKey]
        if let enumerator = FileManager.default.enumerator(
            at: url,
            includingPropertiesForKeys: keys,
            options: [.skipsHiddenFiles]
        ) {
            for case let file as URL in enumerator {
                if clipExtensions.contains(file.pathExtension.lowercased()) {
                    out.append(file)
                }
            }
        }
        return out.sorted {
            $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending
        }
    }

    func exportResolve() {
        guard canProcess else {
            lastExportNote = processBlockedReason
                ?? clips.first?.processSkipReason
                ?? "先选择 Log 与色域"
            return
        }
        let locked = lockedClips
        let skipped = clips.filter { !$0.hasLockedPair }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "导出"
        panel.message = "已锁定片段写出 Resolve 节点图（XML / DCTL / .cube）。未锁定的跳过（先选择 Log 与色域 / 先选择成对 IDT）。709 预览。预览·非成片。已实现（未验证）。"
        panel.begin { [weak self] response in
            guard let self, response == .OK, let url = panel.url else { return }
            do {
                let written = try ResolveExporter.export(
                    to: url,
                    clips: locked,
                    includeWBNode: self.graph.wbEnabled,
                    cct: self.graph.wbCCT,
                    tint: self.graph.wbTint,
                    catCCT: self.graph.effectiveWBCCT,
                    useEffectiveCAT: true,
                    srcCCT: self.graph.effectiveSrcCCT,
                    srcTint: self.graph.asShotTint,
                    odtEnabled: self.graph.odtEnabled,
                    exposureStops: self.graph.exposureStops,
                    exposureEnabled: self.graph.exposureEnabled
                )
                var note = ResolveExporter.exportNote(
                    clips: locked,
                    includeWBNode: self.graph.wbEnabled,
                    cct: self.graph.wbCCT,
                    tint: self.graph.wbTint
                )
                note += "\nWrote \(written.count) files to \(url.path). \(locked.count) 条已锁定 / \(skipped.count) 条已跳过（先选择 Log 与色域 / 先选择成对 IDT）。709 预览。预览·非成片。已实现（未验证）。"
                self.lastExportNote = note
            } catch {
                self.lastExportNote = "Export failed: \(error.localizedDescription)"
            }
        }
    }
}

/// Thrown when the user cancels a locked-clip proxy write.
struct LockedWriteCancel: Error {}

/// Thread-safe cancel flag. Written from the button, read from the write queue.
final class WriteCancelFlag {
    private let lock = NSLock()
    private var flagged = false

    func reset() {
        lock.lock()
        flagged = false
        lock.unlock()
    }

    func request() {
        lock.lock()
        flagged = true
        lock.unlock()
    }

    var isRequested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return flagged
    }
}
