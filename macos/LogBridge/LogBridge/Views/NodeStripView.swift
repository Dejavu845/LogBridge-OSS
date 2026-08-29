import SwiftUI

/// Compact serial node strip: IDT → Exposure → WB → ODT.
/// Shown inside 「高级」 (hidden by default). The graph is not removed.
struct NodeStripView: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        HStack(spacing: 0) {
            Text("节点")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.trailing, 8)
            ForEach(NodeSlot.allCases) { slot in
                if slot != .idt {
                    NodeConnector()
                }
                NodeChip(
                    slot: slot,
                    selected: session.selectedNode == slot,
                    enabled: session.graph.isEnabled(slot),
                    detail: chipDetail(slot)
                )
                .onTapGesture { session.selectedNode = slot }
            }
            Spacer(minLength: 8)
            Text("已实现（未验证）")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private func chipDetail(_ slot: NodeSlot) -> String {
        switch slot {
        case .idt:
            return session.selectedClip?.lockedPairLabel ?? "没有素材"
        case .exposure:
            if session.graph.exposureEnabled {
                return String(format: "%+.2f st", session.graph.exposureStops)
            }
            return "已旁路"
        case .wb:
            if !session.graph.wbEnabled { return "已旁路" }
            if session.graph.wbSource == .grey { return "灰卡" }
            if session.graph.wbSource == .estimate {
                if let cct = session.graph.wbCCT { return "估计 \(Int(cct)) K" }
                return "白平衡（估计）"
            }
            if session.graph.asShotUnknown { return "机内未知" }
            if let cct = session.graph.wbCCT { return "as-shot \(Int(cct)) K" }
            return "as-shot"
        case .odt:
            return session.graph.odt.title
        }
    }
}

private struct NodeConnector: View {
    var body: some View {
        Rectangle()
            .fill(Color.secondary.opacity(0.45))
            .frame(width: 18, height: 2)
            .padding(.horizontal, 4)
    }
}

private struct NodeChip: View {
    let slot: NodeSlot
    let selected: Bool
    let enabled: Bool
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text("\(slot.rawValue)")
                    .font(.caption2.monospacedDigit().weight(.bold))
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(enabled ? Color.accentColor.opacity(0.85) : Color.secondary.opacity(0.35))
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
                Text(slot.title)
                    .font(.caption.weight(.semibold))
                if slot.isBypassable && !enabled {
                    Text("关")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Text(detail)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(selected ? Color.accentColor.opacity(0.14) : Color.primary.opacity(0.04))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(selected ? Color.accentColor : Color.primary.opacity(0.12), lineWidth: selected ? 1.5 : 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .opacity(enabled || slot == .idt ? 1 : 0.7)
    }
}
