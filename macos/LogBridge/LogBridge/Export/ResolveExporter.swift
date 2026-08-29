import Foundation
import simd

/// DaVinci Resolve export: a real bypassable WB node, not a prose sidecar.
///
/// Serial graph on an ACEScct timeline (ACES2065-1 interchange):
///   1. IDT       — camera log → ACES2065-1 → ACEScct (`.cube` and/or ACES IDT / CST)
///   2. Exposure  — stops; ACES2065-1 linear rgb * (2**stops). Own 1D / DCTL.
///   3. WB        — linear AP0 Bradford/CAT02 (CCT + tint) in ACES2065-1. Own LUT / CDL / DCTL.
///   4. ODT       — Rec.709 preview only (off by default)
///
/// Export ACEScct or ACES2065-1 EXR / ACES workflow. Do not bake DWG.
/// WB is never baked into the IDT or ODT cubes. Status: implemented (unverified).
enum ResolveExporter {
    static let lutSize = 17

    private static func cctLabel(_ cct: Double?) -> String {
        cct.map { "\(Int($0)) K" } ?? "pending / identity"
    }

    static func exportNote(clips: [Clip], includeWBNode: Bool, cct: Double?, tint: Double) -> String {
        var lines: [String] = []
        lines.append("LogBridge M1 Resolve 导出（已实现（未验证））")
        lines.append("工作空间：ACEScct 时间线 / ACES2065-1 交换。")
        lines.append("Rec.709 cube 是 709 预览，DIY BT.709 OETF，不是 ACES OT / RRT，不是成片。")
        lines.append("关闭白平衡时写出 identity / enabled=false，不烘焙 CAT。")
        lines.append("主按钮时间线/EXR 是整段代理，不是全精度成片（ACES2065-1 _proxy 序列），不是 ACEScct。")
        lines.append("机内色温只填旋钮，默认 CAT 是单位阵。用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。")
        let cctLabel = cct.map { "\(Int($0)) K" } ?? "pending / identity（不猜 5600 或 6504）"
        lines.append("WB 节点：\(includeWBNode ? "开（AP0 Bradford CAT，\(cctLabel)，tint \(tint)）" : "已写出但默认旁路（identity / enabled=false，不烘焙 CAT）")")
        lines.append("ODT：709 预览（BT.709 OETF preview，不是 ACES OT），默认关。预览·非成片。")
        lines.append("文件：graph.xml, graph.dot, 01_IDT_*.cube, 02_Exposure.{cube,dctl}, 03_WB.{cube,cdl,ccc,dctl}, 04_ODT_Rec709.cube, README_RESOLVE.md")
        lines.append("仅已锁定成对 IDT 片段。待选仍列出（先选择成对 IDT / 先选择 Log 与色域）。")
        lines.append("Exposure 是独立节点（stops；0 时不烘焙进 IDT/WB）。旁路 WB：关掉 WB 节点（或 DCTL Bypass WB）。")
        lines.append("片段：")
        for clip in clips {
            let name = clip.idt?.ocioName ?? clip.lockedPairLabel
            lines.append("  - \(clip.url.lastPathComponent): \(name) [\(clip.verificationBadge)]")
        }
        return lines.joined(separator: "\n")
    }

    /// Write a Resolve-importable node graph into `directory`.
    @discardableResult
    static func export(
        to directory: URL,
        clips: [Clip],
        includeWBNode: Bool,
        cct: Double?,
        tint: Double,
        lutSize: Int = lutSize,
        catCCT: Double? = nil,
        useEffectiveCAT: Bool = false,
        srcCCT: Double? = nil,
        srcTint: Double = 0,
        odtEnabled: Bool = false,
        exposureStops: Double = 0,
        exposureEnabled: Bool = true
    ) throws -> [URL] {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let idts = uniqueImplementedIDTs(clips)
        var written: [URL] = []
        // Knobs (`cct`) stay in XML/README. CAT files use effective CCT so
        // as-shot-unmoved exports identity (no double WB).
        // WB off: identity CAT — do not bake the knob CCT into cube/DCTL/CDL.
        let matrixCCT: Double?
        let matrixSrc: Double?
        if includeWBNode {
            matrixCCT = useEffectiveCAT ? catCCT : cct
            matrixSrc = srcCCT
        } else {
            matrixCCT = nil
            matrixSrc = nil
        }

        func write(_ name: String, _ body: String) throws {
            let url = directory.appendingPathComponent(name)
            try body.write(to: url, atomically: true, encoding: .utf8)
            written.append(url)
        }

        try write("README_RESOLVE.md", readme(idts: idts, cct: cct, tint: tint, includeWB: includeWBNode, exposureStops: exposureStops))
        try write("graph.xml", graphXML(idts: idts, cct: cct, tint: tint, includeWB: includeWBNode, odtEnabled: odtEnabled, exposureStops: exposureStops, exposureEnabled: exposureEnabled))
        try write("graph.dot", graphDOT(idts: idts, cct: cct, tint: tint, includeWB: includeWBNode, exposureStops: exposureStops))
        try write("02_Exposure.cube", exposureCube(stops: exposureEnabled ? exposureStops : 0))
        try write("02_Exposure.dctl", exposureDCTL(stops: exposureEnabled ? exposureStops : 0))
        try write("03_WB.cdl", cdlXML(cct: matrixCCT, tint: tint, collection: false, srcCCT: matrixSrc, srcTint: srcTint))
        try write("03_WB.ccc", cdlXML(cct: matrixCCT, tint: tint, collection: true, srcCCT: matrixSrc, srcTint: srcTint))
        try write("03_WB.dctl", dctl(cct: matrixCCT, tint: tint, srcCCT: matrixSrc, srcTint: srcTint))
        try write("03_WB.cube", wbCube(cct: matrixCCT, tint: tint, size: lutSize, srcCCT: matrixSrc, srcTint: srcTint))
        try write("04_ODT_Rec709.cube", odtCube(size: lutSize))
        for idt in idts {
            try write("01_IDT_\(idt.rawValue).cube", idtCube(idt: idt, size: lutSize))
        }
        return written
    }

    /// Placeholder on-disk export kept for callers that still pass a single URL.
    /// Writes the full graph into the file's parent directory (or creates a folder
    /// next to it). Prefer `export(to:clips:...)`.
    static func writeSidecar(to url: URL, includeWBNode: Bool) throws {
        let dir: URL
        var isDir: ObjCBool = false
        if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
            dir = url
        } else {
            dir = url.deletingPathExtension()
        }
        _ = try export(
            to: dir,
            clips: [],
            includeWBNode: includeWBNode,
            cct: nil,
            tint: 0
        )
    }

    private static func uniqueImplementedIDTs(_ clips: [Clip]) -> [IDT] {
        var seen = Set<IDT>()
        var out: [IDT] = []
        for clip in clips {
            guard clip.hasLockedPair, let idt = clip.idt, !idt.isStub else { continue }
            if seen.insert(idt).inserted {
                out.append(idt)
            }
        }
        return out
    }

    // MARK: - Matrices (row-major, match ocio/matrices/*.spimtx)

    private static let ap0ToXYZ = simd_double3x3(rows: [
        SIMD3(0.952552395938186, 0.000000000000000, 0.000093678631660),
        SIMD3(0.343966449765075, 0.728166096613486, -0.072132546378561),
        SIMD3(0.000000000000000, 0.000000000000000, 1.008825184351586)
    ])

    private static let ap1ToXYZ = simd_double3x3(rows: [
        SIMD3(0.662454181109, 0.134004206456, 0.156187687005),
        SIMD3(0.272228716781, 0.674081765811, 0.053689517408),
        SIMD3(-0.005574649490, 0.004060733529, 1.010339100313)
    ])

    private static let ap1ToAP0 = simd_double3x3(rows: [
        SIMD3(0.695452241357452, 0.140678696470294, 0.163869062172254),
        SIMD3(0.044794563372038, 0.859671118456422, 0.095534318171540),
        SIMD3(-0.005525882558114, 0.004025210305979, 1.001500672252135)
    ])

    private static let ap0ToAP1 = simd_double3x3(rows: [
        SIMD3(1.451439316146, -0.236510746894, -0.214928569252),
        SIMD3(-0.076553773396, 1.176229699834, -0.099675926438),
        SIMD3(0.008316148426, -0.006032449791, 0.997716301365)
    ])

    private static let ap1ToRec709 = simd_double3x3(rows: [
        SIMD3(1.705050992658, -0.621792120657, -0.083258872001),
        SIMD3(-0.130256417507, 1.140804736575, -0.010548319068),
        SIMD3(-0.024003356805, -0.128968976065, 1.152972332870)
    ])

    private static func cameraToAP0(_ idt: IDT) -> simd_double3x3? {
        switch idt {
        case .arriLogC4AWG4:
            return simd_double3x3(rows: [
                SIMD3(0.751244868485, 0.143007909499, 0.105747222016),
                SIMD3(0.001403392600, 1.005384442231, -0.006787834830),
                SIMD3(-0.000803152607, 0.003263851374, 0.997539301233)
            ])
        case .sonySLog3SGamut3, .sonySLog3SGamut3Venice:
            return simd_double3x3(rows: [
                SIMD3(0.753230840311, 0.141947913791, 0.104821245898),
                SIMD3(0.022234917350, 1.013293794080, -0.035528711431),
                SIMD3(-0.009600262790, 0.007505931314, 1.002094331476)
            ])
        case .sonySLog3SGamut3Cine, .sonySLog3SGamut3CineVenice:
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
            return simd_double3x3(rows: [
                SIMD3(0.680205505106, 0.236136601606, 0.083657893287),
                SIMD3(0.085414979742, 1.017470878607, -0.102885858349),
                SIMD3(0.002056521669, -0.062562500385, 1.060505978715)
            ])
        case .appleLog2AWG:
            return simd_double3x3(rows: [
                SIMD3(0.694961049318, 0.241405268785, 0.063633681897),
                SIMD3(0.047362746415, 1.004295925054, -0.051658671469),
                SIMD3(-0.021989789360, -0.028989104971, 1.050978894331)
            ])
        default:
            return nil
        }
    }

    /// Scene-linear ACES2065-1 (AP0) RGB CAT: XYZ_to_AP0 * Bradford_XYZ * AP0_to_XYZ.
    private static func wbRGBMatrix(
        cct: Double?,
        tint: Double,
        srcCCT: Double? = nil,
        srcTint: Double = 0
    ) -> simd_double3x3 {
        guard let cct else { return matrix_identity_double3x3 }
        let cat: simd_double3x3
        if let srcCCT {
            cat = WhiteBalanceNode.relativeCatMatrix(
                srcCCT: srcCCT, dstCCT: cct, srcTint: srcTint, dstTint: tint
            )
        } else {
            cat = WhiteBalanceNode.catMatrix(cct: cct, tint: tint)
        }
        return ap0ToXYZ.inverse * cat * ap0ToXYZ
    }

    // MARK: - Working-space / OETF

    private static let acescctLoS = 10.5402377416545
    private static let acescctLoO = 0.0729055341958355
    private static let acescctBreakLin = 0.0078125
    private static let acescctBreakLog = acescctLoS * acescctBreakLin + acescctLoO
    private static let rec709Beta = 0.018053968510807
    private static let rec709Alpha = 1.09929682680944

    private static func acescctEncode(_ lin: Double) -> Double {
        if lin <= acescctBreakLin {
            return acescctLoS * lin + acescctLoO
        }
        return (log2(max(lin, 1e-10)) + 9.72) / 17.52
    }

    private static func acescctDecode(_ enc: Double) -> Double {
        if enc <= acescctBreakLog {
            return (enc - acescctLoO) / acescctLoS
        }
        return pow(2.0, enc * 17.52 - 9.72)
    }

    private static func rec709OETF(_ lin: Double) -> Double {
        if lin < rec709Beta { return 4.5 * lin }
        return rec709Alpha * pow(max(lin, 0.0), 0.45) - (rec709Alpha - 1.0)
    }

    // MARK: - Log decode (0-1 buffers; N-Log expands to 10-bit codes)

    private static func decodeLog(_ x: Double, idt: IDT) -> Double {
        switch idt {
        case .arriLogC4AWG4:
            let a = (pow(2.0, 18.0) - 16.0) / 117.45
            let b = (1023.0 - 95.0) / 1023.0
            let c = 95.0 / 1023.0
            let p = 14.0 * (x - c) / b + 6.0
            return (pow(2.0, p) - 64.0) / a
        case .sonySLog3SGamut3, .sonySLog3SGamut3Cine, .sonySLog3SGamut3Venice, .sonySLog3SGamut3CineVenice:
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
            // White-paper x is 10-bit 0-1023. LUT domain is 0-1 = code/1023.
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

    private static func apply3(_ m: simd_double3x3, _ v: SIMD3<Double>) -> SIMD3<Double> {
        m * v
    }

    private static func idtToACEScct(_ logRGB: SIMD3<Double>, idt: IDT) -> SIMD3<Double> {
        let cam = SIMD3(decodeLog(logRGB.x, idt: idt),
                        decodeLog(logRGB.y, idt: idt),
                        decodeLog(logRGB.z, idt: idt))
        let ap0 = cameraToAP0(idt).map { apply3($0, cam) } ?? cam
        let ap1 = apply3(ap0ToAP1, ap0)
        return SIMD3(acescctEncode(ap1.x), acescctEncode(ap1.y), acescctEncode(ap1.z))
    }

    private static func wbInACEScct(_ enc: SIMD3<Double>, matrix: simd_double3x3) -> SIMD3<Double> {
        // Decode ACEScct → AP1 linear → AP0 → CAT (AP0 3x3) → AP1 → encode.
        let ap1 = SIMD3(acescctDecode(enc.x), acescctDecode(enc.y), acescctDecode(enc.z))
        let ap0 = apply3(ap1ToAP0, ap1)
        let adapted = apply3(matrix, ap0)
        let outAP1 = apply3(ap0ToAP1, adapted)
        return SIMD3(acescctEncode(outAP1.x), acescctEncode(outAP1.y), acescctEncode(outAP1.z))
    }

    private static func odtFromACEScct(_ di: SIMD3<Double>) -> SIMD3<Double> {
        let lin = SIMD3(acescctDecode(di.x), acescctDecode(di.y), acescctDecode(di.z))
        let rec = apply3(ap1ToRec709, lin)
        return SIMD3(rec709OETF(rec.x), rec709OETF(rec.y), rec709OETF(rec.z))
    }

    // MARK: - .cube (Adobe/IRIDAS: R fastest, then G, then B)

    private static func cubeFile(title: String, size: Int, extraComments: [String] = [], map: (SIMD3<Double>) -> SIMD3<Double>) -> String {
        var lines: [String] = [
            "TITLE \"\(title)\"",
            "# LogBridge M1 — implemented (unverified). Not a camera-support claim."
        ]
        lines.append(contentsOf: extraComments)
        lines.append(contentsOf: [
            "LUT_3D_SIZE \(size)",
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0"
        ])
        if size > 1 {
            let den = Double(size - 1)
            for bi in 0..<size {
                for gi in 0..<size {
                    for ri in 0..<size {
                        let rgb = SIMD3(Double(ri) / den, Double(gi) / den, Double(bi) / den)
                        let o = map(rgb)
                        lines.append(String(format: "%.8f %.8f %.8f", o.x, o.y, o.z))
                    }
                }
            }
        }
        return lines.joined(separator: "\n") + "\n"
    }

    private static func idtCube(idt: IDT, size: Int) -> String {
        cubeFile(title: "LogBridge IDT \(idt.rawValue) → ACEScct (no WB)", size: size) {
            idtToACEScct($0, idt: idt)
        }
    }

    private static func wbCube(cct: Double?, tint: Double, size: Int, srcCCT: Double? = nil, srcTint: Double = 0) -> String {
        let m = wbRGBMatrix(cct: cct, tint: tint, srcCCT: srcCCT, srcTint: srcTint)
        return cubeFile(title: "LogBridge WB AP0 CAT \(cctLabel(cct)) tint \(tint) (ACEScct decode→ACES2065-1→encode)", size: size) {
            wbInACEScct($0, matrix: m)
        }
    }

    private static func odtCube(size: Int) -> String {
        cubeFile(
            title: "LogBridge 709 预览 ACEScct → Rec.709 (BT.709 OETF preview, not ACES OT)",
            size: size,
            extraComments: [
                "# 709 预览. 预览·非成片. DIY BT.709 OETF preview. Not an ACES Output Transform / RRT."
            ]
        ) {
            odtFromACEScct($0)
        }
    }

    /// 1D cube: ACEScct decode → linear gain → encode. Identity at 0 stops.
    private static func exposureCube(stops: Double) -> String {
        let size = 65
        let gain = pow(2.0, stops)
        var lines: [String] = [
            "TITLE \"LogBridge Exposure \(String(format: "%+.3f", stops)) stops (gain \(String(format: "%.8f", gain)), ACEScct wrap)\"",
            "# ACES2065-1 linear gain rgb*(2**stops). Not a log-code add.",
            "# Own node — not baked into IDT or WB when stops=0.",
            "LUT_1D_SIZE \(size)",
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0"
        ]
        let den = Double(size - 1)
        for i in 0..<size {
            let x = Double(i) / den
            let lin = acescctDecode(x) * gain
            let y = acescctEncode(lin)
            lines.append(String(format: "%.8f %.8f %.8f", y, y, y))
        }
        return lines.joined(separator: "\n") + "\n"
    }

    private static func exposureDCTL(stops: Double) -> String {
        let gain = pow(2.0, stops)
        return """
        // LogBridge Exposure — ACES2065-1 linear gain rgb * (2 ** stops).
        // Not a log-code add. Own node; not baked into IDT or WB when stops=0.
        // Stops \(String(format: "%.6f", stops))  gain \(String(format: "%.10f", gain))
        DEFINE_UI_PARAMS(bypass_exposure, Bypass Exposure, DCTLUI_CHECK_BOX, 0, 0, 1)
        DEFINE_UI_PARAMS(input_aces2065, Input is ACES2065-1 linear, DCTLUI_CHECK_BOX, 0, 0, 1)
        __DEVICE__ float acescct_decode(float x) {
            const float LO_S = 10.5402377416545f;
            const float LO_O = 0.0729055341958355f;
            const float BREAK_LOG = LO_S * 0.0078125f + LO_O;
            if (x <= BREAK_LOG) return (x - LO_O) / LO_S;
            return _exp2f(x * 17.52f - 9.72f);
        }
        __DEVICE__ float acescct_encode(float lin) {
            const float LO_S = 10.5402377416545f;
            const float LO_O = 0.0729055341958355f;
            if (lin <= 0.0078125f) return LO_S * lin + LO_O;
            return (_log2f(lin > 1e-10f ? lin : 1e-10f) + 9.72f) / 17.52f;
        }
        __DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B) {
            if (bypass_exposure) return make_float3(p_R, p_G, p_B);
            const float gain = \(String(format: "%.10ff", gain));
            float r = p_R, g = p_G, b = p_B;
            if (!input_aces2065) { r = acescct_decode(p_R); g = acescct_decode(p_G); b = acescct_decode(p_B); }
            r *= gain; g *= gain; b *= gain;
            if (input_aces2065) return make_float3(r, g, b);
            return make_float3(acescct_encode(r), acescct_encode(g), acescct_encode(b));
        }
        """
    }

    // MARK: - CDL / CCC / DCTL / graph

    private static func cdlSlope(cct: Double?, tint: Double, srcCCT: Double? = nil, srcTint: Double = 0) -> SIMD3<Double> {
        wbRGBMatrix(cct: cct, tint: tint, srcCCT: srcCCT, srcTint: srcTint) * SIMD3(1.0, 1.0, 1.0)
    }

    private static func fmt3(_ v: SIMD3<Double>) -> String {
        String(format: "%.10f %.10f %.10f", v.x, v.y, v.z)
    }

    private static func cdlXML(cct: Double?, tint: Double, collection: Bool, srcCCT: Double? = nil, srcTint: Double = 0) -> String {
        let slope = fmt3(cdlSlope(cct: cct, tint: tint, srcCCT: srcCCT, srcTint: srcTint))
        let sop = """
              <SOPNode>
                <Slope>\(slope)</Slope>
                <Offset>0.0000000000 0.0000000000 0.0000000000</Offset>
                <Power>1.0000000000 1.0000000000 1.0000000000</Power>
              </SOPNode>
              <SatNode>
                <Saturation>1.0</Saturation>
              </SatNode>
        """
        if collection {
            return """
            <?xml version="1.0" encoding="UTF-8"?>
            <ColorCorrectionCollection xmlns="urn:ASC:CDL:v1.01">
              <ColorCorrection id="LogBridge_WB">
            \(sop)
              </ColorCorrection>
            </ColorCorrectionCollection>

            """
        }
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <ColorDecisionList xmlns="urn:ASC:CDL:v1.01">
          <ColorDecision>
            <ColorCorrection id="LogBridge_WB">
        \(sop)
            </ColorCorrection>
          </ColorDecision>
        </ColorDecisionList>

        """
    }

    private static func dctl(cct: Double?, tint: Double, srcCCT: Double? = nil, srcTint: Double = 0) -> String {
        let m = wbRGBMatrix(cct: cct, tint: tint, srcCCT: srcCCT, srcTint: srcTint)
        // simd_double3x3 is column-major. Flatten row-major for the DCTL 3x3.
        let r0c0 = m.columns.0.x, r0c1 = m.columns.1.x, r0c2 = m.columns.2.x
        let r1c0 = m.columns.0.y, r1c1 = m.columns.1.y, r1c2 = m.columns.2.y
        let r2c0 = m.columns.0.z, r2c1 = m.columns.1.z, r2c2 = m.columns.2.z
        let list = [r0c0, r0c1, r0c2, r1c0, r1c1, r1c2, r2c0, r2c1, r2c2]
            .map { String(format: "%.10ff", $0) }
            .joined(separator: ", ")
        return """
        // LogBridge M1 WB node — linear AP0 Bradford/CAT02 (ACES2065-1).
        // Timeline: ACEScct / ACES2065-1. CAT after ACEScct decode (AP1→AP0). Never on encoded ACEScct.
        // Disable node 2 (or Bypass WB) = IDT → ACEScct, no bake. Rec.709 is preview only.
        // CCT \(cctLabel(cct))  tint \(tint)  method bradford
        // Implemented (unverified). Not a camera-support claim.

        DEFINE_UI_PARAMS(bypass_wb, Bypass WB, DCTLUI_CHECK_BOX, 0, 0, 1)

        __DEVICE__ float acescct_decode(float x)
        {
            const float LO_S = 10.5402377416545f;
            const float LO_O = 0.0729055341958355f;
            const float BREAK_LIN = 0.0078125f;
            const float BREAK_LOG = LO_S * BREAK_LIN + LO_O;
            if (x <= BREAK_LOG)
                return (x - LO_O) / LO_S;
            return _exp2f(x * 17.52f - 9.72f);
        }

        __DEVICE__ float acescct_encode(float lin)
        {
            const float LO_S = 10.5402377416545f;
            const float LO_O = 0.0729055341958355f;
            const float BREAK_LIN = 0.0078125f;
            if (lin <= BREAK_LIN)
                return LO_S * lin + LO_O;
            if (lin < 1.0e-10f) lin = 1.0e-10f;
            return (_log2f(lin) + 9.72f) / 17.52f;
        }

        __DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B)
        {
            if (bypass_wb)
                return make_float3(p_R, p_G, p_B);

            float r = acescct_decode(p_R);
            float g = acescct_decode(p_G);
            float b = acescct_decode(p_B);

            const float ap1_to_ap0[9] = { 0.6954522414f, 0.1406786965f, 0.1638690622f, 0.0447945634f, 0.8596711185f, 0.0955343182f, -0.0055258826f, 0.0040252103f, 1.0015006723f };
            float ar = ap1_to_ap0[0] * r + ap1_to_ap0[1] * g + ap1_to_ap0[2] * b;
            float ag = ap1_to_ap0[3] * r + ap1_to_ap0[4] * g + ap1_to_ap0[5] * b;
            float ab = ap1_to_ap0[6] * r + ap1_to_ap0[7] * g + ap1_to_ap0[8] * b;

            const float m[9] = { \(list) };
            float or_ = m[0] * ar + m[1] * ag + m[2] * ab;
            float og  = m[3] * ar + m[4] * ag + m[5] * ab;
            float ob  = m[6] * ar + m[7] * ag + m[8] * ab;

            const float ap0_to_ap1[9] = { 1.4514393161f, -0.2365107469f, -0.2149285693f, -0.0765537734f, 1.1762296998f, -0.0996759264f, 0.0083161484f, -0.0060324498f, 0.9977163014f };
            float pr = ap0_to_ap1[0] * or_ + ap0_to_ap1[1] * og + ap0_to_ap1[2] * ob;
            float pg = ap0_to_ap1[3] * or_ + ap0_to_ap1[4] * og + ap0_to_ap1[5] * ob;
            float pb = ap0_to_ap1[6] * or_ + ap0_to_ap1[7] * og + ap0_to_ap1[8] * ob;

            return make_float3(acescct_encode(pr), acescct_encode(pg), acescct_encode(pb));
        }
        """
    }

    private static func resolveCST(_ idt: IDT) -> (space: String, gamma: String) {
        switch idt {
        case .arriLogC4AWG4: return ("ARRI Wide Gamut 4", "ARRI LogC4")
        case .sonySLog3SGamut3, .sonySLog3SGamut3Venice: return ("Sony S-Gamut3", "Sony S-Log3")
        case .sonySLog3SGamut3Cine, .sonySLog3SGamut3CineVenice: return ("Sony S-Gamut3.Cine", "Sony S-Log3")
        case .panasonicVLogVGamut: return ("Panasonic V-Gamut", "Panasonic V-Log")
        case .fujiFLog2BT2020: return ("Rec.2020", "Fujifilm F-Log2")
        case .nikonNLogBT2020: return ("Rec.2020", "Nikon N-Log")
        case .redLog3G10RWG: return ("REDWideGamutRGB", "RED Log3G10")
        case .canonCLog2CGamut: return ("Canon Cinema Gamut", "Canon C-Log2")
        case .canonCLog2BT2020: return ("Rec.2020", "Canon C-Log2")
        case .canonCLog3CGamut: return ("Canon Cinema Gamut", "Canon C-Log3")
        case .canonCLog3BT2020: return ("Rec.2020", "Canon C-Log3")
        case .appleLogBT2020: return ("Rec.2020", "Apple Log")
        case .appleLog2AWG: return ("Apple Wide Gamut", "Apple Log")
        case .arriLogC3EI800AWG3: return ("ARRI Wide Gamut 3", "ARRI LogC3 EI800")
        case .djiDLogDGamut: return ("DJI D-Gamut", "DJI D-Log")
        default: return (idt.ocioName, idt.curve)
        }
    }

    private static func xmlEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    private static func graphXML(idts: [IDT], cct: Double?, tint: Double, includeWB: Bool, odtEnabled: Bool = false, exposureStops: Double = 0, exposureEnabled: Bool = true) -> String {
        let enabled = includeWB ? "true" : "false"
        let odtOn = odtEnabled ? "true" : "false"
        let expOn = exposureEnabled ? "true" : "false"
        let gain = pow(2.0, exposureStops)
        var idtNodes = ""
        if idts.isEmpty {
            idtNodes = "    <IDT idt=\"(user picker)\" file=\"\" resolveOutputColorSpace=\"ACEScct\" resolveOutputGamma=\"ACEScct\"/>\n"
        } else {
            for idt in idts {
                let cst = resolveCST(idt)
                idtNodes += "    <IDT idt=\"\(xmlEscape(idt.rawValue))\" file=\"01_IDT_\(idt.rawValue).cube\" resolveInputColorSpace=\"\(xmlEscape(cst.space))\" resolveInputGamma=\"\(xmlEscape(cst.gamma))\" resolveOutputColorSpace=\"ACEScct\" resolveOutputGamma=\"ACEScct\"/>\n"
            }
        }
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <LogBridgeResolveGraph version="1" status="implemented (unverified)">
          <WorkingSpace gamut="AP0" encoding="ACEScct" white="ACES" interchange="ACES2065-1"/>
          <Node index="1" name="IDT" type="LUT_or_CST" bypassable="false">
            <Description>Camera log to ACEScct via ACES2065-1. No white balance, no exposure.</Description>
        \(idtNodes)  </Node>
          <Node index="2" name="Exposure" type="Gain_1D" bypassable="true" enabled="\(expOn)" stops="\(String(format: "%.6f", exposureStops))">
            <Description>ACES2065-1 linear gain: rgb * (2 ** stops). Not a log-code add. Own node — not baked into IDT or WB when stops=0.</Description>
            <Stops>\(String(format: "%.6f", exposureStops))</Stops>
            <Gain>\(String(format: "%.10f", gain))</Gain>
            <File role="lut1d">02_Exposure.cube</File>
            <File role="dctl">02_Exposure.dctl</File>
          </Node>
          <Node index="3" name="WB" type="Corrector" bypassable="true" enabled="\(enabled)" method="bradford">
            <Description>As-shot CCT/tint fills knobs (UI only); default CAT is identity — do not treat as-shot 5600/6504 as an illuminant (double WB). Missing CCT/tint is pending / identity (do not guess 5600 or 6504). Bypass WB = IDT → Exposure → ACEScct, no bake.</Description>
            \(cct == nil ? "<CCT pending=\"true\" source=\"unknown\"/>" : "<CCT>\(String(format: "%.4f", cct!))</CCT>")
            <Tint>\(String(format: "%.6f", tint))</Tint>
            <File role="lut">03_WB.cube</File>
            <File role="cdl">03_WB.cdl</File>
            <File role="ccc">03_WB.ccc</File>
            <File role="dctl">03_WB.dctl</File>
          </Node>
          <Node index="4" name="ODT_Rec709" type="LUT_or_CST" bypassable="true" enabled="\(odtOn)">
            <Description>Rec.709 预览 preview ODT only (BT.709 OETF, no RRT). Not an ACES Output Transform. 预览·非成片. Off = ACEScct deliverable (or ACES2065-1 EXR). Not a finished picture.</Description>
            <File role="lut">04_ODT_Rec709.cube</File>
            <ResolveCST inputColorSpace="ACEScct" inputGamma="ACEScct" outputColorSpace="Rec.709" outputGamma="Rec.709"/>
          </Node>
        </LogBridgeResolveGraph>

        """
    }

    private static func graphDOT(idts: [IDT], cct: Double?, tint: Double, includeWB: Bool, exposureStops: Double = 0) -> String {
        let idtLabel = idts.isEmpty ? "(per clip CST/LUT)" : idts.map(\.rawValue).joined(separator: ", ")
        let wbStyle = includeWB ? "solid" : "dashed"
        let wbFill = includeWB ? "lightgrey" : "white"
        return """
        digraph LogBridgeResolve {
          rankdir=LR;
          labelloc="t";
          label="LogBridge M1 Resolve graph — implemented (unverified)";
          node [shape=box, fontname="Helvetica"];

          clip [label="Clip\\ncamera log"];
          idt  [label="IDT\\n\(idtLabel)\\n01_IDT_<idt>.cube\\nor ACES IDT / CST → ACEScct"];
          exp  [label="Exposure (zeroable)\\n\(String(format: "%+.2f", exposureStops)) stops\\n02_Exposure.cube / .dctl"];
          wb   [label="WB (bypassable)\\nscene-linear Bradford/CAT02\\n\(cctLabel(cct))  tint \(tint)\\n03_WB.cube / .cdl / .ccc / .dctl", style="filled,\(wbStyle)", fillcolor="\(wbFill)"];
          odt  [label="709 预览 (later node)\\n04_ODT_Rec709.cube\\nor CST ACEScct → Rec.709\\nBT.709 OETF, not ACES OT"];
          timeline [shape=oval, label="Timeline\\nACEScct"];

          clip -> idt -> exp -> wb -> odt;
          idt -> timeline [style=dashed, label="working space"];
        }

        """
    }

    private static func readme(idts: [IDT], cct: Double?, tint: Double, includeWB: Bool, exposureStops: Double = 0) -> String {
        let idtList = idts.isEmpty ? "(none — assign IDT in Resolve CST)" : idts.map(\.rawValue).joined(separator: ", ")
        let wbState = includeWB ? "默认开启" : "已写出但默认旁路（identity / enabled=false，不烘焙 CAT）"
        return """
        # LogBridge Resolve 导出

        状态：**已实现（未验证）** / implemented (unverified)。不是相机支持声明。

        ## 诚实说明

        - Rec.709 cube 是 **709 预览**，DIY BT.709 OETF，**不是** ACES OT / RRT，不是成片。preview only. Not an ACES Output Transform.
        - 关闭白平衡时写出 identity / `enabled=false`，不烘焙 CAT。
        - 主按钮时间线/EXR 是 **整段代理，不是全精度成片**（ACES2065-1 `_proxy` 序列），不是 ACEScct。
        - 机内色温只填旋钮，默认 CAT 是单位阵。用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。

        ## Graph (serial nodes)

        Standard Resolve deliverable: **ACEScct** timeline or **ACES2065-1** EXR / ACES workflow. Rec.709 is **709 预览** only (not ACES OT).

        1. **IDT** — `01_IDT_<idt>.cube` or Color Space Transform
           - Input: camera log / camera gamut (`\(idtList)`)
           - Output: ACEScct (via ACES2065-1)
           - Contains **no** white balance.

        2. **WB** — own corrector, **\(wbState)**
           - `03_WB.cube` — ACEScct wrap of the linear AP0 Bradford/CAT02 3×3 (decode → ACES2065-1 CAT → encode).
           - `03_WB.dctl` — DI-free DCTL: decode ACEScct → AP1→AP0 → AP0 3×3 → encode. **Bypass WB** or disable node 2 = IDT → ACEScct, no bake.
           - `03_WB.cdl` / `03_WB.ccc` — ASC CDL Color Corrector for the same serial slot (slope = CAT × (1,1,1); offset 0; power 1). Prefer the cube/DCTL for the full 3×3; the CDL is the bypassable corrector form.
           - CCT \(cctLabel(cct)), tint \(tint), method Bradford. As-shot fills knobs (UI only); default CAT is identity (do not CAT as-shot 5600/6504 toward D65). Missing CCT is pending / identity (do not guess 5600 or 6504). Scene-linear only.

        3. **709 预览** — `04_ODT_Rec709.cube` or CST
           - Optional preview node, off by default. Off = ACEScct deliverable.
           - DIY BT.709 OETF, preview only, no RRT. Not an ACES Output Transform. 预览·非成片.

        ## How to bypass WB in Resolve

        Color page, serial node graph:

        - Apply **IDT** (node 1: LUT `01_IDT_*.cube`, or ACES IDT / CST camera → ACEScct).
        - Apply **WB** (node 3: LUT `03_WB.cube`, **or** DCTL `03_WB.dctl`, **or** import `03_WB.cdl` onto a Color Corrector).
        - Apply **ODT** (node 4: LUT `04_ODT_Rec709.cube`, or CST ACEScct → Rec.709) if you need a **709 预览** viewing node (not ACES OT). 预览·非成片.

        To bypass WB: disable node 2 (or tick DCTL **Bypass WB**, or skip the CDL/LUT). Remaining graph: **IDT → ACEScct**, no bake.

        ## Files

        | File | Role |
        | --- | --- |
        | `graph.xml` | Machine-readable node graph (bypassable WB) |
        | `graph.dot` | Graphviz of the same graph |
        | `01_IDT_<idt>.cube` | IDT LUT (no WB) |
        | `03_WB.cube` | WB LUT (Bradford CAT, ACEScct-wrapped) |
        | `03_WB.cdl` / `03_WB.ccc` | WB as ASC CDL Color Corrector |
        | `03_WB.dctl` | WB as DCTL (exact 3×3) |
        | `04_ODT_Rec709.cube` | 709 预览 (BT.709 OETF, not ACES OT) |
        | `README_RESOLVE.md` | This file |

        M1 is a serial node graph (IDT → Exposure → WB → ODT), not a general node editor. Golden grey-card samples are required before any accuracy claim. Implemented (unverified).
        """
    }

    /// Proxy sequence folder. Mirrors ``color.batch.deliverable_dir_name``.
    /// ``{stem}_ACES2065-1_proxy/frame_000000.exr``. Name must say proxy so it is not a 成片 claim.
    static func deliverableSequenceDirectory(for clip: Clip, in directory: URL) -> URL {
        let stem = clip.url.deletingPathExtension().lastPathComponent
        return directory.appendingPathComponent("\(stem)_ACES2065-1_proxy")
    }

    /// One frame of the proxy sequence: ``frame_%06d.exr``.
    static func sequenceFrameURL(in sequenceDirectory: URL, index: Int) -> URL {
        sequenceDirectory.appendingPathComponent(String(format: "frame_%06d.exr", index))
    }

    /// First frame of the proxy sequence. Not a lone ``_frame0`` file.
    static func deliverableURL(for clip: Clip, in directory: URL) -> URL {
        sequenceFrameURL(in: deliverableSequenceDirectory(for: clip, in: directory), index: 0)
    }

    /// SMPTE ST 2065-1 / ACES AP0 primaries + ACES white (not D65, not AP1).
    /// OpenEXR `chromaticities`: Rx Ry Gx Gy Bx By Wx Wy. Header only.
    static let aces2065_1Chromaticities: [Float] = [
        0.73470, 0.26530,
        0.00000, 1.00000,
        0.00010, -0.07700,
        0.32168, 0.33767,
    ]

    /// Uncompressed scanline RGB float32 EXR. Container only — no color math.
    /// Matches ``color.exr_write.write_rgb_exr``. Writes ST 2065-1 chromaticities.
    /// Does not write ``acesImageContainerFlag``.
    static func writeACES2065EXR(rgb: [Float], width: Int, height: Int, to url: URL) throws {
        guard width > 0, height > 0, rgb.count >= width * height * 3 else {
            throw NSError(domain: "LogBridge", code: 3, userInfo: [
                NSLocalizedDescriptionKey: "empty RGB buffer"
            ])
        }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var data = Data()
        func putU32(_ v: UInt32) {
            var le = v.littleEndian
            data.append(Data(bytes: &le, count: 4))
        }
        func putI32(_ v: Int32) {
            var le = v.littleEndian
            data.append(Data(bytes: &le, count: 4))
        }
        func putU64(_ v: UInt64) {
            var le = v.littleEndian
            data.append(Data(bytes: &le, count: 8))
        }
        func putAttr(_ name: String, _ type: String, _ payload: Data) {
            data.append(contentsOf: name.utf8)
            data.append(0)
            data.append(contentsOf: type.utf8)
            data.append(0)
            putI32(Int32(payload.count))
            data.append(payload)
        }
        func chlistChannel(_ name: String) -> Data {
            var ch = Data()
            ch.append(contentsOf: name.utf8)
            ch.append(0)
            var pixelType = Int32(2).littleEndian
            ch.append(Data(bytes: &pixelType, count: 4))
            ch.append(contentsOf: [0, 0, 0, 0])
            var samp = Int32(1).littleEndian
            ch.append(Data(bytes: &samp, count: 4))
            ch.append(Data(bytes: &samp, count: 4))
            return ch
        }

        putU32(20000630)
        putU32(2)
        var channels = Data()
        channels.append(chlistChannel("B"))
        channels.append(chlistChannel("G"))
        channels.append(chlistChannel("R"))
        channels.append(0)
        putAttr("channels", "chlist", channels)
        var chroma = Data()
        for v in aces2065_1Chromaticities {
            var bits = v.bitPattern.littleEndian
            chroma.append(Data(bytes: &bits, count: 4))
        }
        putAttr("chromaticities", "chromaticities", chroma)
        putAttr("compression", "compression", Data([0]))
        var box = Data()
        for v: Int32 in [0, 0, Int32(width - 1), Int32(height - 1)] {
            var le = v.littleEndian
            box.append(Data(bytes: &le, count: 4))
        }
        putAttr("dataWindow", "box2i", box)
        putAttr("displayWindow", "box2i", box)
        putAttr("lineOrder", "lineOrder", Data([0]))
        var par: UInt32 = Float(1.0).bitPattern.littleEndian
        putAttr("pixelAspectRatio", "float", Data(bytes: &par, count: 4))
        var center = Data()
        var z: UInt32 = Float(0).bitPattern.littleEndian
        center.append(Data(bytes: &z, count: 4))
        center.append(Data(bytes: &z, count: 4))
        putAttr("screenWindowCenter", "v2f", center)
        putAttr("screenWindowWidth", "float", Data(bytes: &par, count: 4))
        data.append(0)

        let rowBytes = width * 4
        var scanlines: [Data] = []
        for y in 0..<height {
            var planar = Data(count: rowBytes * 3)
            planar.withUnsafeMutableBytes { raw in
                let dst = raw.bindMemory(to: UInt32.self)
                for x in 0..<width {
                    let i = (y * width + x) * 3
                    dst[x] = rgb[i + 2].bitPattern.littleEndian
                    dst[width + x] = rgb[i + 1].bitPattern.littleEndian
                    dst[2 * width + x] = rgb[i].bitPattern.littleEndian
                }
            }
            var payload = Data()
            var yi = Int32(y).littleEndian
            var nbytes = UInt32(planar.count).littleEndian
            payload.append(Data(bytes: &yi, count: 4))
            payload.append(Data(bytes: &nbytes, count: 4))
            payload.append(planar)
            scanlines.append(payload)
        }
        var pos = UInt64(data.count + height * 8)
        for payload in scanlines {
            putU64(pos)
            pos += UInt64(payload.count)
        }
        for payload in scanlines {
            data.append(payload)
        }
        try data.write(to: url, options: .atomic)
    }
}
