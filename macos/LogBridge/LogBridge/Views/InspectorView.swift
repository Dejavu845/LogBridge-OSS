import SwiftUI

/// Paired IDT picker pinned under the preview. Always visible.
/// Visible during write; picker is not swappable mid-write.
/// Do not bury this in 「高级」. Unlocked IDT blocks / skips process.
struct PairedIDTBar: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("成对 IDT")
                    .font(.caption.weight(.semibold))
                Text("先选 Log 与色域，才能处理")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
            }
            if let clip = session.selectedClip {
                // One locked pair per row. Never two independent curve/gamut dropdowns.
                Picker("Paired IDT", selection: Binding(
                    get: { clip.idt },
                    set: { newValue in
                        if let idt = newValue {
                            session.setIDT(clip.id, idt)
                        }
                    }
                )) {
                    Text("— 先选择成对 IDT —").tag(Optional<IDT>.none)
                    ForEach(clip.pickerPairs) { pair in
                        Text(pair.pairLabel).tag(Optional(pair))
                    }
                }
                .labelsHidden()
                .controlSize(.small)
                .frame(maxWidth: 420)
                .disabled(session.isExporting)
                // S-Log3 + S-Gamut3 vs S-Log3 + S-Gamut3.Cine. C-Log2 / C-Log3 + Cinema Gamut vs BT.2020. Venice pair only if detected.
                .help("S-Log3 + S-Gamut3 vs S-Log3 + S-Gamut3.Cine. C-Log2 / C-Log3 + Cinema Gamut vs BT.2020. Venice pair only if detected.")
                HStack(spacing: 6) {
                    Text(clip.verificationBadge)
                        .font(.caption2)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(clip.isPending ? Color.yellow.opacity(0.28) : Color.orange.opacity(0.2))
                        .clipShape(Capsule())
                    Text("来源：\(clip.detectionSource.rawValue)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if clip.veniceDetected {
                        Text("检测到 Venice")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                if let reason = clip.processSkipReason {
                    Text(reason)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                }
                Text(clip.detectionNote)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            } else {
                Text("先点一条素材。读不到元数据就在这里选成对 IDT，不猜。")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.03))
    }
}

/// Right inspector: Exposure + WB three states only.
/// IDT lives under the preview — not in 「高级」. Node strip / export only.
struct InspectorView: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                ExposureInspector(session: session)
                Divider()
                WBInspector(session: session)
            }
            .disabled(session.isExporting)
            .opacity(session.isExporting ? 0.45 : 1)
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color.primary.opacity(0.02))
    }
}

struct WBInspector: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("白平衡")
                .font(.subheadline.weight(.semibold))
            Toggle("启用白平衡（可旁路，不烘焙）", isOn: Binding(
                get: { session.graph.wbEnabled },
                set: { session.setWBEnabled($0) }
            ))
            .controlSize(.small)
            // Three states only. Estimate chip lights AFTER confirm, never on propose.
            HStack(spacing: 4) {
                WBStateChip(title: "机内 as-shot", on: session.graph.wbSource == .asShot)
                WBStateChip(
                    title: "白平衡（估计）",
                    on: session.graph.wbSource == .estimate
                )
                WBStateChip(title: "灰卡", on: session.graph.wbSource == .grey)
                if session.graph.asShotUnknown {
                    Text("机内未知")
                        .font(.caption2)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Color.yellow.opacity(0.28))
                        .clipShape(Capsule())
                }
            }
            if session.graph.asShotUnknown {
                Text("读不到机内色温。保持未填、单位阵，不猜 5600 或 6504。点灰卡或手填。已实现（未验证）。")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
            Button(session.pickingNeutral ? "在预览上点灰卡…" : "点灰卡") {
                session.pickingNeutral.toggle()
            }
            .controlSize(.small)
            .help("Pick neutral / 点灰卡: sample after IDT in ACES2065-1 (AP0) linear; overrides metadata. Writes the existing CAT node.")
            Button("估计白平衡") {
                session.proposeAutoWB()
            }
            .controlSize(.small)
            .help("白平衡（估计）: SoG p=6 in ACEScg after IDT. Does not write CAT. Low confidence stays empty. Not 精准.")
            if session.graph.autoWBCCT != nil {
                Text("白平衡（估计） \(Int(session.graph.autoWBCCT ?? 0)) K — 确认后才写入，一点不会写入")
                    .font(.caption2)
                Button("确认估计") {
                    session.confirmAutoWB()
                }
                .controlSize(.small)
            }
            if session.graph.wbEnabled {
                HStack {
                    Text("CCT")
                        .font(.caption)
                        .frame(width: 36, alignment: .leading)
                    Slider(
                        value: Binding(
                            get: { session.graph.wbCCTDisplay },
                            set: { session.setWBParams(cct: $0) }
                        ),
                        in: 2000...10000,
                        step: 10
                    )
                    .controlSize(.small)
                    Text(session.graph.wbCCT.map { "\(Int($0)) K" } ?? "机内未知")
                        .font(.caption.monospacedDigit())
                        .frame(width: 72, alignment: .trailing)
                }
                HStack {
                    Text("绿品")
                        .font(.caption)
                        .frame(width: 36, alignment: .leading)
                    Slider(
                        value: Binding(
                            get: { session.graph.wbTint },
                            set: { session.setWBParams(tint: $0) }
                        ),
                        in: -10...10,
                        step: 0.1
                    )
                    .controlSize(.small)
                    Text(String(format: "%.1f", session.graph.wbTint))
                        .font(.caption.monospacedDigit())
                        .frame(width: 52, alignment: .trailing)
                }
                Picker("CAT", selection: Binding(
                    get: { session.graph.wbMethod },
                    set: { session.setWBParams(method: $0) }
                )) {
                    Text("Bradford").tag("bradford")
                    Text("CAT02").tag("cat02")
                }
                .controlSize(.small)
                .frame(maxWidth: 200)
            }
            Text("机内色温只填旋钮，默认 CAT 是单位阵。用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

private struct WBStateChip: View {
    let title: String
    let on: Bool
    var body: some View {
        Text(title)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(on ? Color.accentColor.opacity(0.18) : Color.primary.opacity(0.05))
            .foregroundStyle(on ? Color.accentColor : Color.secondary)
            .clipShape(Capsule())
    }
}

struct ODTInspector: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("输出")
                .font(.subheadline.weight(.semibold))
            Picker("ODT", selection: Binding(
                get: { session.graph.odt },
                set: { session.setODT($0) }
            )) {
                ForEach(ODTMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .frame(maxWidth: 280)
            Text(session.graph.odt.acesOTNote)
                .font(.caption)
                .foregroundStyle(.secondary)
            if session.graph.odt == .rec709 {
                Text("Rec.709 is preview only, not the standard deliverable. Tagged CGColorSpace.itur_709 only when this node is Rec.709. No RRT. Implemented (unverified).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if session.graph.odt.isHDR {
                Text("ColorSync itur_2100. 预览·非成片，未与 709 匹配. 已实现（未验证）. Not an ACES Output Transform. No homemade HLG/PQ. Not supported. Not 一键精准.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text("Working space: \(session.graph.workingSpace.rawValue). 导出 ACEScct / EXR is the timeline deliverable. Rec.709 / HLG / PQ panes are 预览·非成片 — not a finished grade.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

struct ExposureInspector: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("曝光")
                .font(.subheadline.weight(.semibold))
            Toggle("启用曝光（0 档 = 不动）", isOn: Binding(
                get: { session.graph.exposureEnabled },
                set: { session.setExposureEnabled($0) }
            ))
            .controlSize(.small)
            if session.graph.exposureEnabled {
                HStack {
                    Text("档（Stops）")
                        .font(.caption)
                        .frame(width: 64, alignment: .leading)
                    Slider(
                        value: Binding(
                            get: { session.graph.exposureStops },
                            set: { session.setExposureStops($0) }
                        ),
                        in: -8...8,
                        step: 0.05
                    )
                    .controlSize(.small)
                    Text(String(format: "%+.2f st", session.graph.exposureStops))
                        .font(.caption.monospacedDigit())
                        .frame(width: 60, alignment: .trailing)
                }
                Text(String(format: "Linear gain 2^stops = %.4f", pow(2.0, session.graph.exposureStops)))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Text("User-facing unit is stops. After IDT, in ACES2065-1 linear: rgb × (2^stops). Do not add/subtract Log code values. Preview cache stores post-IDT linear; exposure applies in linear before WB.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text("预览·非成片 — Rec.709 / HLG / PQ are preview only, not a finished picture.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}
