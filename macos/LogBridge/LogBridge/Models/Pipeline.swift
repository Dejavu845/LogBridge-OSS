import Foundation

/// Fixed M1 pipeline. Not a node editor.
///
///   IDT (log → ACES2065-1 via OCIO Builtin or white-paper reference)
///     → Exposure (stops; rgb * 2**stops in ACES2065-1 linear; default 0)
///     → optional WB node (Bradford/CAT02, CCT + tint, ACES2065-1 / AP0)
///     → ACEScct encode for timeline / grading display
///     → optional ODT: Off | Rec.709 preview | Rec.2100 HLG | Rec.2100 PQ
///
/// Resolve export keeps WB as a toggleable AP0 matrix rather than baking it.
/// Standard deliverable: ACEScct or ACES2065-1 EXR / ACES workflow.
/// Rec.709 is preview only.
struct FixedPipeline {
    var idt: IDT
    var workingSpace: WorkingSpace = .acescct
    var whiteBalance: WhiteBalanceSettings = .identity
    var applyWhiteBalance: Bool = false
    var exposureStops: Double = 0
    var applyExposure: Bool = true

    enum WorkingSpace: String {
        case acescct = "ACEScct"
        case aces2065 = "ACES2065-1"
    }
}

struct WhiteBalanceSettings {
    var cct: Double?
    var tint: Double
    var method: String
    var source: WBSource

    /// Explicit D65 identity CAT (6504 K). Not a 5600 K guess. As-shot knobs
    /// must not use this as a filled-in default (UI only; CAT stays identity).
    static let identity = WhiteBalanceSettings(cct: 6504, tint: 0, method: "bradford", source: .user)
    /// As-shot unknown: apply identity, do not guess 5600 K.
    static let unknown = WhiteBalanceSettings(cct: nil, tint: 0, method: "bradford", source: .unknown)
}

enum PipelineStage: String, CaseIterable {
    case idt = "IDT"
    case exposure = "Exposure (stops)"
    case whiteBalance = "WB (scene-linear)"
    case odt = "ODT"
}
