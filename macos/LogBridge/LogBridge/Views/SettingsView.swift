import SwiftUI

/// 设置页。中文。不写精准 / 一键还原 / 全自动校准。
struct SettingsView: View {
    @ObservedObject var settings: AppSettings
    @ObservedObject var session: SessionModel

    var body: some View {
        Form {
            Section {
                Picker("默认预览", selection: Binding(
                    get: { settings.defaultPreviewODT },
                    set: { newValue in
                        settings.defaultPreviewODT = newValue
                        session.setODT(newValue)
                    }
                )) {
                    Text("Rec.709 预览·非成片").tag(ODTMode.rec709)
                    Text("Rec.2100 HLG 预览·非成片").tag(ODTMode.hlg)
                    Text("Rec.2100 PQ 预览·非成片").tag(ODTMode.pq)
                }
                Text("默认 Rec.709（DIY OETF，角标预览·非成片）。不是成片，未与 HDR 匹配。导出仍是 ACEScct / EXR。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                Text("预览")
            }

            Section {
                Toggle("导入后提示估计白平衡", isOn: $settings.promptEstimateWBOnImport)
                Text("默认关。打开后只提示「白平衡（估计）」，不写入 CAT，不猜 5600。确认后才写。灰卡覆盖估计。不是校准。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                Text("白平衡")
            }

            Section {
                Toggle("未锁 IDT 挡住处理", isOn: .constant(settings.blockUnlockedIDT))
                    .disabled(true)
                Text("不能关。「处理已锁定片段」只在已锁定条数 > 0 时出现。未锁定的片段跳过（先选择 Log 与色域 / 先选择成对 IDT），不猜 IDT。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                Text("处理")
            }

            Text("已实现（未验证）。不写精准 / 一键还原 / 全自动校准。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .formStyle(.grouped)
        .frame(minWidth: 420, minHeight: 320)
        .navigationTitle("设置")
    }
}
