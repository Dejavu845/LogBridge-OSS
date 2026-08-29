import SwiftUI

/// Drop zone + virtualized clip list. Badge is never "supported".
/// 待选 / 已锁定 are two glanceable states (type, weight, chip, left accent).
/// No lock button — existing paired-IDT picker stays the lock flow.
struct ClipSidebarView: View {
    @ObservedObject var session: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("素材")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button("添加…") { session.showImporter = true }
                    .controlSize(.small)
                Button("设置") { session.showSettings = true }
                    .controlSize(.small)
            }
            .padding(.horizontal, 10)
            .padding(.top, 8)
            .padding(.bottom, 4)

            DropZone(targeted: session.dropTargeted, empty: session.clips.isEmpty)
                .padding(.horizontal, 10)
                .padding(.bottom, 6)

            Text("拖入 → 锁 IDT → 曝光/WB → 处理已锁定片段。未锁定的跳过，不猜。")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10)
                .padding(.bottom, 4)

            if !session.lastImportNote.isEmpty {
                Text(session.lastImportNote)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 10)
                    .padding(.bottom, 4)
            }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(session.clips) { clip in
                            ClipRow(
                                clip: clip,
                                selected: session.selectedID == clip.id,
                                onRevealWritten: { session.revealClipExportInFinder(clip) }
                            )
                            .id(clip.id)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                session.selectedID = clip.id
                                session.refreshPreview()
                                session.revealClipExportInFinder(clip)
                            }
                        }
                    }
                }
                .onChange(of: session.selectedID) { _, id in
                    if let id {
                        proxy.scrollTo(id, anchor: .center)
                    }
                }
            }
        }
    }
}

private struct DropZone: View {
    let targeted: Bool
    let empty: Bool

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "square.and.arrow.down")
                .font(empty ? .title2 : .body)
            Text(empty ? "把混源文件夹拖进来" : "把文件夹拖进来")
                .font(empty ? .subheadline.weight(.semibold) : .caption)
                .foregroundStyle(.primary)
            if empty {
                Text("拖入自己的 Log，不内置厂商样片 — no bundled manufacturer demos")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                Text("已实现（未验证）")
                    .font(.caption2)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.orange.opacity(0.2))
                    .clipShape(Capsule())
            }
        }
        .frame(maxWidth: .infinity)
        .padding(empty ? 22 : 6)
        .background(targeted ? Color.accentColor.opacity(0.15) : Color.primary.opacity(0.04))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(style: StrokeStyle(lineWidth: 1, dash: [5]))
                .foregroundStyle(targeted ? Color.accentColor : Color.secondary.opacity(0.4))
        )
    }
}

struct ClipRow: View {
    let clip: Clip
    var selected: Bool = false
    var onRevealWritten: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            RoundedRectangle(cornerRadius: 1)
                .fill(clip.isPending ? Color.yellow.opacity(0.9) : Color.accentColor)
                .frame(width: 3)
                .padding(.vertical, 2)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(clip.filename)
                        .font(clip.isPending ? .callout : .callout.weight(.semibold))
                        .foregroundStyle(clip.isPending ? Color.secondary : Color.primary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    Text(clip.isPending ? "待选" : "已锁定")
                        .font(.caption2.weight(clip.isPending ? .regular : .semibold))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(clip.isPending ? Color.yellow.opacity(0.28) : Color.accentColor.opacity(0.16))
                        .foregroundStyle(clip.isPending ? Color.primary : Color.accentColor)
                        .clipShape(Capsule())
                }
                Text(clip.lockedPairLabel)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                if let reason = clip.processSkipReason {
                    Text(reason)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                        .lineLimit(1)
                } else if let chip = clip.exportChip {
                    // 已写出代理 after a proxy write; failed write is a short Chinese error
                    if chip == SessionModel.wroteProxyChip {
                        Button(chip) { onRevealWritten?() }
                            .buttonStyle(.plain)
                            .font(.caption2)
                            .foregroundStyle(Color.secondary)
                            .lineLimit(1)
                    } else {
                        Text(chip)
                            .font(.caption2)
                            .foregroundStyle(Color.orange)
                            .lineLimit(1)
                    }
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(selected ? Color.accentColor.opacity(0.10) : Color.clear)
    }
}
