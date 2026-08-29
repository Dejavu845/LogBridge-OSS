import SwiftUI

/// Control Center–style liquid glass. Visual only — no copy or path changes.
/// macOS 14 materials (ultraThin / thin). Not a second process button.
enum GlassChrome {
    static let moduleRadius: CGFloat = 16
    static let tileRadius: CGFloat = 12
    static let hairline = Color.white.opacity(0.22)
    static let hairlineDim = Color.white.opacity(0.10)
    static let pending = Color(red: 1.0, green: 0.78, blue: 0.28)
    static let locked = Color(red: 0.45, green: 0.78, blue: 0.96)
    static let backdropTop = Color(red: 0.07, green: 0.09, blue: 0.12)
    static let backdropBottom = Color(red: 0.03, green: 0.04, blue: 0.06)
}

/// Window wash behind the three-column split.
struct LiquidBackdrop: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [GlassChrome.backdropTop, GlassChrome.backdropBottom],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [Color.white.opacity(0.08), Color.clear],
                center: .topLeading,
                startRadius: 20,
                endRadius: 520
            )
            RadialGradient(
                colors: [Color.cyan.opacity(0.07), Color.clear],
                center: .bottomTrailing,
                startRadius: 10,
                endRadius: 420
            )
        }
        .ignoresSafeArea()
    }
}

/// One Control Center module: material + inner highlight + hairline.
struct GlassModule<Content: View>: View {
    var radius: CGFloat = GlassChrome.moduleRadius
    var padding: CGFloat = 10
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .background {
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(.ultraThinMaterial)
            }
            .overlay {
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(
                            colors: [GlassChrome.hairline, GlassChrome.hairlineDim],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            }
            .overlay(alignment: .top) {
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [Color.white.opacity(0.14), Color.clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
                    .frame(height: 36)
                    .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
                    .allowsHitTesting(false)
            }
    }
}

struct GlassChip: View {
    let title: String
    var on: Bool
    var pending: Bool = false

    var body: some View {
        Text(title)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background {
                Capsule()
                    .fill(on
                          ? (pending ? GlassChrome.pending.opacity(0.28) : GlassChrome.locked.opacity(0.22))
                          : Color.white.opacity(0.06))
            }
            .overlay {
                Capsule()
                    .strokeBorder(Color.white.opacity(on ? 0.28 : 0.10), lineWidth: 0.8)
            }
            .foregroundStyle(on
                             ? (pending ? GlassChrome.pending : GlassChrome.locked)
                             : Color.secondary)
    }
}

/// Thin column wash so sidebar / inspector sit on glass, not a flat panel.
struct GlassRail: View {
    var edge: HorizontalAlignment = .trailing

    var body: some View {
        Rectangle()
            .fill(.ultraThinMaterial)
            .overlay {
                LinearGradient(
                    colors: [Color.white.opacity(0.05), Color.clear],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
            .overlay(alignment: Alignment(horizontal: edge, vertical: .center)) {
                Rectangle()
                    .fill(GlassChrome.hairlineDim)
                    .frame(width: 1)
            }
    }
}

struct GlassHairline: View {
    var body: some View {
        Rectangle()
            .fill(GlassChrome.hairlineDim)
            .frame(height: 1)
    }
}

/// Primary / cancel look without AppKit borderedProminent chrome.
struct GlassActionButtonStyle: ButtonStyle {
    var cancel: Bool = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 11)
            .padding(.vertical, 5)
            .background {
                Capsule()
                    .fill(.ultraThinMaterial)
                    .overlay {
                        Capsule()
                            .fill(
                                (cancel ? GlassChrome.pending : GlassChrome.locked)
                                    .opacity(configuration.isPressed ? 0.50 : 0.30)
                            )
                    }
            }
            .overlay {
                Capsule()
                    .strokeBorder(Color.white.opacity(0.32), lineWidth: 0.8)
            }
            .foregroundStyle(.white)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

extension View {
    func glassModule(radius: CGFloat = GlassChrome.moduleRadius, padding: CGFloat = 10) -> some View {
        GlassModule(radius: radius, padding: padding) { self }
    }
}
