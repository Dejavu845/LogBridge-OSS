import Foundation

/// Locked curve + gamut pair. Sony S-Log3 has two gamuts; never default to Cine.
/// C-Log2 and C-Log3 each have two gamuts; never default to Cinema Gamut.
enum IDT: String, CaseIterable, Identifiable, Hashable {
    case arriLogC4AWG4 = "arri_logc4_awg4"
    case sonySLog3SGamut3 = "sony_slog3_sgamut3"
    case sonySLog3SGamut3Cine = "sony_slog3_sgamut3cine"
    case panasonicVLogVGamut = "panasonic_vlog_vgamut"
    case fujiFLog2BT2020 = "fujifilm_flog2_bt2020"
    case nikonNLogBT2020 = "nikon_nlog_bt2020"
    case redLog3G10RWG = "red_log3g10_rwg"
    case sonySLog3SGamut3Venice = "sony_slog3_sgamut3_venice"
    case sonySLog3SGamut3CineVenice = "sony_slog3_sgamut3cine_venice"
    case canonCLog2CGamut = "canon_clog2_cgamut"
    case canonCLog2BT2020 = "canon_clog2_bt2020"
    case canonCLog3CGamut = "canon_clog3_cgamut"
    case canonCLog3BT2020 = "canon_clog3_bt2020"
    case appleLogBT2020 = "apple_log_bt2020"
    case appleLog2AWG = "apple_log2_awg"
    case djiDLogDGamut = "dji_dlog_dgamut"
    case arriLogC3EI800AWG3 = "arri_logc3_ei800_awg3"
    // Explicitly unsupported — not implemented.
    case djiDLogMStub = "dji_dlog_m"

    var id: String { rawValue }

    var isStub: Bool {
        switch self {
        case .djiDLogMStub:
            return true
        default:
            return false
        }
    }

    var curve: String {
        switch self {
        case .arriLogC4AWG4: return "LogC4"
        case .sonySLog3SGamut3, .sonySLog3SGamut3Cine, .sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice: return "S-Log3"
        case .panasonicVLogVGamut: return "V-Log"
        case .fujiFLog2BT2020: return "F-Log2"
        case .nikonNLogBT2020: return "N-Log"
        case .redLog3G10RWG: return "Log3G10"
        case .canonCLog2CGamut, .canonCLog2BT2020: return "C-Log2"
        case .canonCLog3CGamut, .canonCLog3BT2020: return "C-Log3"
        case .appleLogBT2020: return "Apple Log"
        case .appleLog2AWG: return "Apple Log 2"
        case .djiDLogDGamut: return "D-Log"
        case .arriLogC3EI800AWG3: return "LogC3 EI800"
        case .djiDLogMStub: return "D-Log M"
        }
    }

    var gamut: String {
        switch self {
        case .arriLogC4AWG4: return "AWG4"
        case .sonySLog3SGamut3, .sonySLog3SGamut3Venice: return "S-Gamut3"
        case .sonySLog3SGamut3Cine, .sonySLog3SGamut3CineVenice: return "S-Gamut3.Cine"
        case .panasonicVLogVGamut: return "V-Gamut"
        case .fujiFLog2BT2020, .nikonNLogBT2020: return "BT.2020"
        case .redLog3G10RWG: return "REDWideGamutRGB"
        case .canonCLog2CGamut, .canonCLog3CGamut: return "Cinema Gamut"
        case .canonCLog2BT2020, .canonCLog3BT2020, .appleLogBT2020: return "BT.2020"
        case .appleLog2AWG: return "Apple Wide Gamut"
        case .djiDLogDGamut: return "D-Gamut"
        case .arriLogC3EI800AWG3: return "AWG3"
        case .djiDLogMStub: return "(unsupported)"
        }
    }

    var isVenice: Bool {
        switch self {
        case .sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice:
            return true
        default:
            return false
        }
    }

    /// Paired picker row. Never split into independent curve / gamut menus.
    var pairLabel: String {
        switch self {
        case .sonySLog3SGamut3Venice:
            return "S-Log3 + S-Gamut3 (Venice)"
        case .sonySLog3SGamut3CineVenice:
            return "S-Log3 + S-Gamut3.Cine (Venice)"
        default:
            return "\(curve) + \(gamut)"
        }
    }

    var menuLabel: String {
        if isStub {
            return "\(pairLabel) — stub, not implemented"
        }
        return "\(pairLabel) — implemented (unverified)"
    }

    /// OCIO colorspace name in ocio/config.ocio.
    var ocioName: String {
        switch self {
        case .arriLogC4AWG4: return "ARRI LogC4 AWG4"
        case .sonySLog3SGamut3: return "Sony S-Log3 S-Gamut3"
        case .sonySLog3SGamut3Cine: return "Sony S-Log3 S-Gamut3.Cine"
        case .sonySLog3SGamut3Venice: return "Sony S-Log3 S-Gamut3 Venice"
        case .sonySLog3SGamut3CineVenice: return "Sony S-Log3 S-Gamut3.Cine Venice"
        case .panasonicVLogVGamut: return "Panasonic V-Log V-Gamut"
        case .fujiFLog2BT2020: return "Fujifilm F-Log2 BT.2020"
        case .nikonNLogBT2020: return "Nikon N-Log BT.2020"
        case .redLog3G10RWG: return "RED Log3G10 REDWideGamutRGB"
        case .canonCLog2CGamut: return "Canon C-Log2 Cinema Gamut"
        case .canonCLog2BT2020: return "Canon C-Log2 BT.2020"
        case .canonCLog3CGamut: return "Canon C-Log3 Cinema Gamut"
        case .canonCLog3BT2020: return "Canon C-Log3 BT.2020"
        case .appleLogBT2020: return "Apple Log BT.2020"
        case .appleLog2AWG: return "Apple Log 2 Apple Wide Gamut"
        case .djiDLogDGamut: return "DJI D-Log D-Gamut"
        case .arriLogC3EI800AWG3: return "ARRI LogC3 EI800 AWG3"
        case .djiDLogMStub: return "DJI D-Log M (unsupported)"
        }
    }

    /// Implemented (unverified) IDTs only — never stubs, never "supported".
    static var implemented: [IDT] {
        allCases.filter { !$0.isStub }
    }

    static var implementedCurves: [String] {
        var seen: [String] = []
        for idt in implemented where !idt.isVenice && !seen.contains(idt.curve) {
            seen.append(idt.curve)
        }
        return seen
    }

    static func pairs(forCurve curve: String, veniceDetected: Bool = false) -> [IDT] {
        pickerPairs(curveHint: curve, veniceDetected: veniceDetected, needsPicker: true)
    }

    static func gamuts(forCurve curve: String, veniceDetected: Bool = false) -> [String] {
        pairs(forCurve: curve, veniceDetected: veniceDetected).map(\.gamut)
    }

    /// Locked pair only. Nil if the curve+gamut combination is not an M1 IDT.
    /// Prefers the non-Venice pair unless `veniceDetected`.
    static func match(curve: String, gamut: String, veniceDetected: Bool = false) -> IDT? {
        let hits = implemented.filter { $0.curve == curve && $0.gamut == gamut }
        if veniceDetected {
            return hits.first(where: { $0.isVenice }) ?? hits.first
        }
        return hits.first(where: { !$0.isVenice }) ?? hits.first
    }

    /// Paired IDTs for the picker. Venice rows appear only if Venice is detected.
    /// S-Log3 needing a pick offers both gamuts — never a silent Cine default.
    /// C-Log2 / C-Log3 needing a pick offer Cinema Gamut and BT.2020 — never a silent Cinema Gamut default.
    static func pickerPairs(curveHint: String?, veniceDetected: Bool, needsPicker: Bool) -> [IDT] {
        let slog3 = Self.isSLog3(curveHint)
        if needsPicker && slog3 {
            return veniceDetected
                ? [.sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice]
                : [.sonySLog3SGamut3, .sonySLog3SGamut3Cine]
        }
        if needsPicker && Self.isCLog2(curveHint) {
            return [.canonCLog2CGamut, .canonCLog2BT2020]
        }
        if needsPicker && Self.isCLog3(curveHint) {
            return [.canonCLog3CGamut, .canonCLog3BT2020]
        }
        var pairs = implemented.filter { !$0.isVenice }
        if veniceDetected {
            if let idx = pairs.firstIndex(of: .sonySLog3SGamut3Cine) {
                pairs.insert(contentsOf: [.sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice], at: pairs.index(after: idx))
            } else {
                pairs.append(contentsOf: [.sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice])
            }
        }
        return pairs
    }

    static func isSLog3(_ curve: String?) -> Bool {
        guard let curve else { return false }
        let c = curve.lowercased().replacingOccurrences(of: "_", with: "-")
        return c == "slog3" || c == "s-log3"
    }

    static func isCLog2(_ curve: String?) -> Bool {
        guard let curve else { return false }
        let c = curve.lowercased().replacingOccurrences(of: "_", with: "-")
        return c == "clog2" || c == "c-log2"
    }

    static func isCLog3(_ curve: String?) -> Bool {
        guard let curve else { return false }
        let c = curve.lowercased().replacingOccurrences(of: "_", with: "-")
        return c == "clog3" || c == "c-log3"
    }
}
