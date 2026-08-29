import Foundation

/// Serial graph: IDT → Exposure → WB → selectable ODT. Not a general node editor.
///
/// Slots match `color/graph.py` and Resolve export
/// (01_IDT / 02_Exposure / 03_WB / 04_ODT).
/// Exposure is stops in ACES2065-1 linear (rgb * 2**stops). Default 0.
/// WB off = IDT → Exposure → ACEScct, no bake. ODT: Off (ACEScct) |
/// Rec.709 preview | Rec.2100 HLG | Rec.2100 PQ. Default Off.
enum NodeSlot: Int, CaseIterable, Identifiable, Hashable {
    case idt = 1
    case exposure = 2
    case wb = 3
    case odt = 4

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .idt: return "输入"
        case .exposure: return "曝光"
        case .wb: return "白平衡"
        case .odt: return "输出"
        }
    }

    var exportBasename: String {
        switch self {
        case .idt: return "01_IDT"
        case .exposure: return "02_Exposure"
        case .wb: return "03_WB"
        case .odt: return "04_ODT"
        }
    }

    var subtitle: String {
        switch self {
        case .idt: return "Log + 色域"
        case .exposure: return "档（线性增益）"
        case .wb: return "线性 CAT"
        case .odt: return "关 / 709 / HLG / PQ"
        }
    }

    var isBypassable: Bool {
        self != .idt
    }
}

/// ODT slot selector. Default Off = ACEScct deliverable.
enum ODTMode: String, CaseIterable, Identifiable, Hashable {
    case off = "off"
    case rec709 = "rec709"
    case hlg = "hlg"
    case pq = "pq"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off: return "关（ACEScct）"
        case .rec709: return "Rec.709 预览"
        case .hlg: return "Rec.2100 HLG"
        case .pq: return "Rec.2100 PQ"
        }
    }

    var isPreviewOnly: Bool { self == .rec709 }
    var isHDR: Bool { self == .hlg || self == .pq }
    var isEnabled: Bool { self != .off }

    /// ACES Output Transform / BT.2100 BuiltinTransform (no homemade curve).
    var acesOTNote: String {
        switch self {
        case .off:
            return "ACEScct timeline / ACES2065-1 EXR deliverable."
        case .rec709:
            return "Rec.709 preview only (DIY BT.709 OETF, no RRT). Implemented (unverified)."
        case .hlg:
            return "Rec.2100 HLG via ACES Output Transform / BT.2100. Implemented (unverified). Not supported."
        case .pq:
            return "Rec.2100 PQ via ACES Output Transform / BT.2100. Implemented (unverified). Not supported."
        }
    }
}

/// As-shot / grey / user / unknown. Unknown = pending / identity. Do not guess 5600 or 6504.
enum WBSource: String, Hashable {
    case asShot = "as_shot"
    case grey = "grey"
    case estimate = "estimate"
    case user = "user"
    case unknown = "unknown"

    var title: String {
        switch self {
        case .asShot: return "as-shot"
        case .grey: return "grey-card"
        case .estimate: return "白平衡（估计）"
        case .user: return "user"
        case .unknown: return "as-shot unknown"
        }
    }
}

/// Session-level WB / ODT. IDT lives on the selected clip.
/// As-shot camera-private CCT/tint (not nclc) fills knobs (UI only).
/// Default CAT is identity — do not CAT as-shot 5600/6504 toward D65.
/// Missing CCT is pending / identity — do not guess 5600 or 6504.
struct SerialGraph: Equatable {
    var exposureEnabled: Bool = true
    var exposureStops: Double = 0
    var wbEnabled: Bool = false
    var wbCCT: Double? = nil
    var wbTint: Double = 0
    var wbMethod: String = "bradford"
    var wbSource: WBSource = .unknown
    var asShotCCT: Double? = nil
    var asShotTint: Double = 0
    var autoWBCCT: Double? = nil
    var autoWBTint: Double = 0
    var odt: ODTMode = .off
    var workingSpace: FixedPipeline.WorkingSpace = .acescct

    /// CCT applied by the CAT, or nil for identity.
    /// As-shot knobs are UI only — do not CAT as-shot 5600/6504 toward D65
    /// (double WB). Apply CAT when the user moves knobs away from as-shot,
    /// or on a grey-card override. Missing CCT: identity, no 5600 guess.
    var effectiveWBCCT: Double? {
        guard let cct = wbCCT else { return nil }
        switch wbSource {
        case .asShot:
            return nil
        case .user:
            // First typed CCT with no as-shot is a label, not an illuminant.
            guard let shot = asShotCCT else { return nil }
            if abs(cct - shot) <= 0.5,
               abs(wbTint - asShotTint) <= 1e-3 {
                return nil
            }
            return cct
        case .grey, .estimate, .unknown:
            return cct
        }
    }

    /// As-shot CCT for relative CAT, or nil for absolute / identity.
    var effectiveSrcCCT: Double? {
        guard effectiveWBCCT != nil, wbSource == .user, let shot = asShotCCT else {
            return nil
        }
        return shot
    }

    var asShotUnknown: Bool { wbCCT == nil }

    /// Slider park only when knobs are empty. Not a 5600/6504 metadata guess.
    var wbCCTDisplay: Double { wbCCT ?? 6504 }

    var odtEnabled: Bool {
        get { odt != .off }
        set { odt = newValue ? (odt == .off ? .rec709 : odt) : .off }
    }

    func isEnabled(_ slot: NodeSlot) -> Bool {
        switch slot {
        case .idt: return true
        case .exposure: return exposureEnabled
        case .wb: return wbEnabled
        case .odt: return odtEnabled
        }
    }

    mutating func setEnabled(_ slot: NodeSlot, _ enabled: Bool) {
        switch slot {
        case .idt:
            break
        case .exposure:
            exposureEnabled = enabled
        case .wb:
            wbEnabled = enabled
        case .odt:
            odtEnabled = enabled
        }
    }
}
