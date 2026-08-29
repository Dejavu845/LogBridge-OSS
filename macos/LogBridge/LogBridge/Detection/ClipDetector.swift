import Foundation
import AVFoundation

/// Detection order:
///  1. Camera-private metadata (ARRI MXF, Sony Acquisition, Canon vendor, RED RMD)
///  2. Filename / model hint
///  3. User picker
///
/// NEVER trust QuickTime nclc / nclx / colr to identify S-Log3 or LogC4.
/// NEVER default S-Log3 to S-Gamut3.Cine.
struct DetectionResult {
    var idt: IDT?
    var curve: String?
    var gamut: String?
    var source: DetectionSource
    var needsUserPicker: Bool
    var note: String
    var veniceDetected: Bool = false
    var asShotCCT: Double? = nil
    var asShotTint: Double = 0
}

enum ClipDetector {
    static func detect(url: URL, modelHint: String? = nil) -> DetectionResult {
        var result: DetectionResult
        if let meta = detectMetadata(url: url), !meta.needsUserPicker {
            result = meta
        } else if let fn = detectFilename(url: url), !fn.needsUserPicker {
            result = fn
        } else if let model = detectModel(modelHint) {
            result = model
        } else if let partial = detectMetadata(url: url) ?? detectFilename(url: url) {
            result = partial
        } else {
            result = DetectionResult(
                idt: nil,
                curve: nil,
                gamut: nil,
                source: .unresolved,
                needsUserPicker: true,
                note: "读不到元数据，先选择 Log 与色域。QuickTime nclc is never used."
            )
        }
        let shot = readAsShotWB(url: url)
        result.asShotCCT = shot.cct
        result.asShotTint = shot.tint
        return result
    }

    /// Camera-private CCT/tint only. QuickTime nclc is never an illuminant.
    /// Missing CCT/tint → pending / identity. Do not guess 5600 or 6504.
    static func readAsShotWB(from meta: [String: Any]) -> (cct: Double?, tint: Double) {
        let forbidden: Set<String> = [
            "nclc", "nclx", "colr", "quicktime_nclc", "qt_nclc",
            "quicktime_nclx", "qt_nclx", "quicktime_colr", "qt_colr"
        ]
        var cleaned: [String: Any] = [:]
        for (k, v) in meta {
            if !forbidden.contains(k.lowercased()) {
                cleaned[k.lowercased()] = v
            }
        }
        let cctKeys = [
            "arri_wb_kelvin", "arri_white_balance_kelvin", "arri_color_temperature", "arri_cct",
            "sony_wb_kelvin", "sony_white_balance", "sony_acquisition_white_balance",
            "sony_acquisition_cct", "sony_colortemp", "sony_color_temperature",
            "canon_wb_kelvin", "canon_white_balance", "canon_color_temperature", "canon_cct",
            "red_kelvin", "red_wb_kelvin", "red_color_temp", "red_rmd_kelvin", "red_rmd_wb_kelvin",
            "apple_wb_kelvin", "apple_white_balance", "apple_color_temperature",
            "dji_wb_kelvin", "dji_white_balance", "dji_color_temperature",
            "as_shot_cct", "as_shot_kelvin", "white_balance_kelvin", "wb_kelvin", "cct", "kelvin", "color_temperature"
        ]
        let tintKeys = [
            "arri_wb_tint", "arri_tint", "arri_cc_shift", "sony_wb_tint", "sony_tint",
            "canon_wb_tint", "canon_tint", "red_tint", "red_wb_tint", "red_rmd_tint",
            "apple_tint", "dji_tint", "as_shot_tint", "wb_tint"
        ]
        var cct: Double?
        for key in cctKeys {
            if let v = cleaned[key], let parsed = parseCCT(v) {
                cct = parsed
                break
            }
        }
        var tint: Double = 0
        for key in tintKeys {
            if let v = cleaned[key], let parsed = parseTint(v) {
                tint = parsed
                break
            }
        }
        return (cct, tint)
    }

    private static func parseCCT(_ value: Any) -> Double? {
        let n: Double?
        if let d = value as? Double { n = d }
        else if let i = value as? Int { n = Double(i) }
        else if let s = value as? String {
            let digits = s.split(whereSeparator: { !$0.isNumber && $0 != "." })
            n = digits.first.flatMap { Double($0) }
        } else { n = nil }
        guard let cct = n, cct >= 1000, cct <= 25000 else { return nil }
        return cct
    }

    private static func parseTint(_ value: Any) -> Double? {
        if let d = value as? Double { return d }
        if let i = value as? Int { return Double(i) }
        if let s = value as? String { return Double(s) }
        return nil
    }

    /// Sidecar JSON next to the clip (camera-private keys). Not nclc. Not a demo reel.
    static func readAsShotWB(url: URL) -> (cct: Double?, tint: Double) {
        let jsonURL = url.deletingPathExtension().appendingPathExtension("json")
        guard let data = try? Data(contentsOf: jsonURL),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let dict = obj as? [String: Any] else {
            return (nil, 0)
        }
        return readAsShotWB(from: dict)
    }

    /// Camera-private boxes only. QuickTime nclc is read then discarded.
    static func detectMetadata(url: URL) -> DetectionResult? {
        let asset = AVURLAsset(url: url)
        // Intentionally do not use asset.formatDescriptions / nclc / nclx / colr
        // as an identity for S-Log3 or LogC4. Those tags are often Rec.709 or unset.
        _ = discardQuickTimeNCLC(asset)

        if let arri = readARRIColorSpace(url: url) {
            return locked(.arriLogC4AWG4, source: .metadata, note: "ARRI MXF \(arri)")
        }
        if let sony = readSonyAcquisition(url: url) {
            return sony
        }
        if let canon = readCanonVendor(url: url) {
            return canon
        }
        if let red = readREDRMD(url: url) {
            return red
        }
        return nil
    }

    /// nclc is inspected only so we can prove we did not use it.
    private static func discardQuickTimeNCLC(_ asset: AVURLAsset) -> Void {
        // Do not map nclc color primaries / transfer / matrix to an IDT.
        // Common trap: nclc 1-1-1 (Rec.709) on an S-Log3 file.
        _ = asset
    }

    static func detectFilename(url: URL) -> DetectionResult? {
        let name = url.lastPathComponent.lowercased()
        let cineTokens = ["sgamut3.cine", "s-gamut3.cine", "sgamut3cine", "sgamut3_cine"]
        let venice = name.contains("venice")
        if cineTokens.contains(where: { name.contains($0) }) {
            return locked(venice ? .sonySLog3SGamut3CineVenice : .sonySLog3SGamut3Cine, source: .filename, note: "filename S-Gamut3.Cine")
        }
        if name.contains("sgamut3") || name.contains("s-gamut3") {
            return locked(venice ? .sonySLog3SGamut3Venice : .sonySLog3SGamut3, source: .filename, note: "filename S-Gamut3")
        }
        if name.contains("logc4") || name.contains("awg4") {
            return locked(.arriLogC4AWG4, source: .filename, note: "filename LogC4/AWG4")
        }
        if name.contains("v-log") || name.contains("vlog") || name.contains("vgamut") {
            return locked(.panasonicVLogVGamut, source: .filename, note: "filename V-Log")
        }
        if name.contains("f-log2") || name.contains("flog2") {
            return locked(.fujiFLog2BT2020, source: .filename, note: "filename F-Log2")
        }
        if name.contains("n-log") || name.contains("nlog") {
            return locked(.nikonNLogBT2020, source: .filename, note: "filename N-Log")
        }
        if name.contains("log3g10") || name.contains("redwidegamut") {
            return locked(.redLog3G10RWG, source: .filename, note: "filename Log3G10")
        }
        if name.contains("d-log m") || name.contains("dlog m") || name.contains("dlogm") || name.contains("d-logm") {
            return DetectionResult(
                idt: nil, curve: nil, gamut: nil, source: .filename, needsUserPicker: true,
                note: "D-Log M is unsupported. D-Log + D-Gamut (2017) is implemented (unverified)."
            )
        }
        if name.contains("apple log 2") || name.contains("applelog2") || name.contains("apple-log-2") {
            return locked(.appleLog2AWG, source: .filename, note: "filename Apple Log 2 + Apple Wide Gamut")
        }
        if name.contains("logc3") && !name.contains("logc4") {
            return locked(.arriLogC3EI800AWG3, source: .filename, note: "filename LogC3 EI800 + AWG3")
        }
        if name.contains("awg3") && !name.contains("awg4") {
            return locked(.arriLogC3EI800AWG3, source: .filename, note: "filename AWG3 (LogC3 EI800 + AWG3)")
        }
        if name.contains("c-log2") || name.contains("clog2") {
            if name.contains("cinema") || name.contains("cgamut") || name.contains("c-gamut") {
                return locked(.canonCLog2CGamut, source: .filename, note: "filename C-Log2 + Cinema Gamut")
            }
            if name.contains("bt.2020") || name.contains("bt2020") || name.contains("rec2020") || name.contains("rec.2020") {
                return locked(.canonCLog2BT2020, source: .filename, note: "filename C-Log2 + BT.2020")
            }
            return DetectionResult(
                idt: nil,
                curve: "C-Log2",
                gamut: nil,
                source: .filename,
                needsUserPicker: true,
                note: "C-Log2 in filename without gamut; pick C-Log2 + Cinema Gamut or C-Log2 + BT.2020. Never default Cinema Gamut."
            )
        }
        if name.contains("c-log3") || name.contains("clog3") {
            if name.contains("cinema") || name.contains("cgamut") || name.contains("c-gamut") {
                return locked(.canonCLog3CGamut, source: .filename, note: "filename C-Log3 + Cinema Gamut")
            }
            if name.contains("bt.2020") || name.contains("bt2020") || name.contains("rec2020") || name.contains("rec.2020") {
                return locked(.canonCLog3BT2020, source: .filename, note: "filename C-Log3 + BT.2020")
            }
            return DetectionResult(
                idt: nil,
                curve: "C-Log3",
                gamut: nil,
                source: .filename,
                needsUserPicker: true,
                note: "C-Log3 in filename without gamut; pick C-Log3 + Cinema Gamut or C-Log3 + BT.2020. Never default Cinema Gamut."
            )
        }
        if name.contains("apple log") || name.contains("applelog") {
            return locked(.appleLogBT2020, source: .filename, note: "filename Apple Log")
        }
        if name.contains("d-log") || name.contains("dlog") || name.contains("d-gamut") || name.contains("dgamut") {
            return locked(.djiDLogDGamut, source: .filename, note: "filename D-Log")
        }
        if name.contains("s-log3") || name.contains("slog3") {
            return DetectionResult(
                idt: nil,
                curve: "S-Log3",
                gamut: nil,
                source: .filename,
                needsUserPicker: true,
                note: venice
                    ? "S-Log3 in filename without gamut; Venice detected — pick S-Log3 + S-Gamut3 or S-Log3 + S-Gamut3.Cine (Venice). Never default Cine."
                    : "S-Log3 in filename without gamut; pick S-Log3 + S-Gamut3 or S-Log3 + S-Gamut3.Cine. Never default Cine.",
                veniceDetected: venice
            )
        }
        return nil
    }

    static func detectModel(_ model: String?) -> DetectionResult? {
        guard let model else { return nil }
        let m = model.lowercased()
        if m.contains("venice") {
            return DetectionResult(
                idt: nil,
                curve: "S-Log3",
                gamut: nil,
                source: .model,
                needsUserPicker: true,
                note: "Venice camera detected; pick S-Log3 + S-Gamut3 (Venice) or S-Log3 + S-Gamut3.Cine (Venice). Never default.",
                veniceDetected: true
            )
        }
        if m.contains("alexa 35") || m.contains("alexa35") || m.contains("alexa 265") {
            return locked(.arriLogC4AWG4, source: .model, note: "model hint")
        }
        if m.contains("varicam") {
            return locked(.panasonicVLogVGamut, source: .model, note: "model hint")
        }
        if m.contains("komodo") || m.contains("v-raptor") || m.contains("dsmc2") {
            return locked(.redLog3G10RWG, source: .model, note: "model hint")
        }
        return nil
    }

    private static func locked(_ idt: IDT, source: DetectionSource, note: String) -> DetectionResult {
        DetectionResult(
            idt: idt,
            curve: idt.curve,
            gamut: idt.gamut,
            source: source,
            needsUserPicker: false,
            note: note,
            veniceDetected: idt.isVenice
        )
    }

    // MARK: Camera-private readers (scaffolded; return nil until parsers land)

    /// ARRI MXF camera metadata (AS-11 / ARRI specific). Not QuickTime nclc.
    private static func readARRIColorSpace(url: URL) -> String? {
        // M1 scaffold: look for a sidecar or MXF essence descriptor in a later slice.
        _ = url
        return nil
    }

    /// Sony Acquisition Metadata (RDD 18 / XML in MXF). Distinguishes S-Gamut3 vs Cine.
    private static func readSonyAcquisition(url: URL) -> DetectionResult? {
        _ = url
        return nil
    }

    /// Canon vendor metadata. C-Log2 / C-Log3 without gamut stay pending (no Cinema Gamut default).
    private static func readCanonVendor(url: URL) -> DetectionResult? {
        _ = url
        return nil
    }

    /// RED RMD sidecar / header. Log3G10 + REDWideGamutRGB.
    private static func readREDRMD(url: URL) -> DetectionResult? {
        let sidecar = url.deletingPathExtension().appendingPathExtension("rmd")
        if FileManager.default.fileExists(atPath: sidecar.path) {
            // Presence of RMD is a hint, not a parse. Later slice reads color_space.
            return locked(.redLog3G10RWG, source: .metadata, note: "RED RMD sidecar present")
        }
        return nil
    }
}
