import SwiftUI
import AppKit
import CoreGraphics
import QuartzCore
import simd

// MARK: - HDR preview encode (ColorSync itur_2100)
//
// Graded ACES2065-1 (AP0) linear → Rec.2020 linear (existing BT.2020→AP0
// matrix, inverted) → ColorSync-encode to CGColorSpace.itur_2100_HLG or
// itur_2100_PQ. System BT.2100 transfer. Not an ACES Output Transform.
// No OCIO. No homemade HLG/PQ OETF. Never the 709 8-bit path.

enum HDRPreviewColor {
    static let buildFailStatus = "HDR 预览建不出"
    static let noEDRStatus = "屏幕无 EDR，预览被压到 SDR"

    /// Same 9 numbers as `PreviewColor.cameraToAP0` BT.2020 cases
    /// (F-Log2 / N-Log / C-Log2+BT.2020 / C-Log3+BT.2020 / Apple Log).
    /// Invert for AP0 linear → Rec.2020 linear. Do not invent a new matrix.
    private static let bt2020ToAP0 = simd_double3x3(rows: [
        SIMD3(0.679085634707, 0.157700914643, 0.163213450650),
        SIMD3(0.046002003080, 0.859054673003, 0.094943323917),
        SIMD3(-0.000573943188, 0.028467768408, 0.972106174780)
    ])

    static func destColorSpaceName(_ odt: ODTMode) -> CFString? {
        switch odt {
        case .hlg: return CGColorSpace.itur_2100_HLG
        case .pq: return CGColorSpace.itur_2100_PQ
        case .off, .rec709: return nil
        }
    }

    /// HDR-tagged 16-bit float pixels, or nil (fail closed — never 709).
    static func encodeFromGradedAP0(
        rgb: [Float],
        width: Int,
        height: Int,
        odt: ODTMode
    ) -> CGImage? {
        guard odt.isHDR else { return nil }
        guard let destName = destColorSpaceName(odt),
              let dest = CGColorSpace(name: destName) else { return nil }
        var rec2020 = rgb
        applyAP0ToRec2020Linear(&rec2020)
        guard let linear = makeLinearRec2020FloatImage(
            rgb: rec2020,
            width: width,
            height: height
        ) else { return nil }
        return colorsyncEncode(linear, dest: dest)
    }

    /// Existing BT.2020→AP0 inverted. Linear only — no 709 OETF.
    private static func applyAP0ToRec2020Linear(_ rgb: inout [Float]) {
        let m = bt2020ToAP0.inverse
        let n = rgb.count / 3
        for i in 0..<n {
            let v = m * SIMD3(
                Double(rgb[i * 3 + 0]),
                Double(rgb[i * 3 + 1]),
                Double(rgb[i * 3 + 2])
            )
            rgb[i * 3 + 0] = Float(v.x)
            rgb[i * 3 + 1] = Float(v.y)
            rgb[i * 3 + 2] = Float(v.z)
        }
    }

    /// Rec.2020 scene-linear float image. Not the 709 8-bit preview path.
    private static func makeLinearRec2020FloatImage(
        rgb: [Float],
        width: Int,
        height: Int
    ) -> CGImage? {
        guard let cs = CGColorSpace(name: CGColorSpace.extendedLinearITUR_2020)
                ?? CGColorSpace(name: CGColorSpace.linearITUR_2020) else {
            return nil
        }
        var rgba = [Float](repeating: 1, count: width * height * 4)
        for i in 0..<(width * height) {
            rgba[i * 4 + 0] = rgb[i * 3 + 0]
            rgba[i * 4 + 1] = rgb[i * 3 + 1]
            rgba[i * 4 + 2] = rgb[i * 3 + 2]
            rgba[i * 4 + 3] = 1
        }
        let info = CGBitmapInfo.byteOrder32Little
            .union(.floatComponents)
            .union(CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue))
        guard let ctx = CGContext(
            data: &rgba,
            width: width,
            height: height,
            bitsPerComponent: 32,
            bytesPerRow: width * 16,
            space: cs,
            bitmapInfo: info.rawValue
        ) else { return nil }
        return ctx.makeImage()
    }

    /// ColorSync: draw linear Rec.2020 into itur_2100_HLG / PQ.
    /// System BT.2100 transfer. rgba16Float, or 32-bit float if 16-bit
    /// cannot be created. Never the 709 8-bit preview path.
    private static func colorsyncEncode(_ src: CGImage, dest: CGColorSpace) -> CGImage? {
        if let img = drawColorSync(src, dest: dest, bitsPerComponent: 16) {
            return img
        }
        return drawColorSync(src, dest: dest, bitsPerComponent: 32)
    }

    private static func drawColorSync(
        _ src: CGImage,
        dest: CGColorSpace,
        bitsPerComponent: Int
    ) -> CGImage? {
        let w = src.width
        let h = src.height
        let bytesPerPixel = bitsPerComponent == 16 ? 8 : 16
        let byteOrder: CGBitmapInfo = bitsPerComponent == 16
            ? .byteOrder16Little
            : .byteOrder32Little
        let alphas: [CGImageAlphaInfo] = [
            .premultipliedLast, .noneSkipLast, .premultipliedFirst
        ]
        for alpha in alphas {
            let info = byteOrder
                .union(.floatComponents)
                .union(CGBitmapInfo(rawValue: alpha.rawValue))
            guard let ctx = CGContext(
                data: nil,
                width: w,
                height: h,
                bitsPerComponent: bitsPerComponent,
                bytesPerRow: w * bytesPerPixel,
                space: dest,
                bitmapInfo: info.rawValue
            ) else { continue }
            ctx.draw(src, in: CGRect(x: 0, y: 0, width: w, height: h))
            if let img = ctx.makeImage() {
                return img
            }
        }
        return nil
    }

    /// Key-window / main screen. > 1 means the display can do EDR.
    static func displayHasEDR() -> Bool {
        let screen = NSApp.keyWindow?.screen ?? NSScreen.main
        guard let screen else { return false }
        return screen.maximumPotentialExtendedDynamicRangeColorComponentValue > 1.0
    }
}

// MARK: - HDR pane
//
// Separate from Rec709PreviewView. itur_2100 + rgba16Float + EDR.
// Fail closed: no 709 pixels if the layer cannot enable EDR.

/// Runner overlay: CALayer has no `colorspace` (CAMetalLayer does). KVC.
private func setHDRLayerColorSpace(_ layer: CALayer?, _ space: CGColorSpace?) {
    layer?.setValue(space, forKey: "colorspace")
}

/// rgba16Float via KVC so the runner overlay does not need the member.
private func setHDRLayerContentsFormat(_ layer: CALayer?) {
    layer?.setValue("RGBA16Float", forKey: "contentsFormat")
}

struct HDRPreviewView: View {
    let title: String
    let caption: String
    var image: CGImage? = nil
    var odt: ODTMode = .hlg
    var pickingNeutral: Bool = false
    var onPick: ((Double, Double) -> Void)? = nil
    var onLayerFail: (() -> Void)? = nil

    var body: some View {
        ZStack(alignment: .topLeading) {
            HDRTaggedHost(image: image, odt: odt, onLayerFail: onLayerFail)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.black)
            PreviewNotDeliverableBadge()
            HDRPaneTitle(title: title)
        }
        .help(caption)
        .overlay {
            GeometryReader { geo in
                Color.clear
                    .contentShape(Rectangle())
                    .allowsHitTesting(pickingNeutral)
                    .gesture(
                        DragGesture(minimumDistance: 0).onEnded { value in
                            guard pickingNeutral, let onPick else { return }
                            let w = max(geo.size.width, 1)
                            let h = max(geo.size.height, 1)
                            let nx = min(max(value.location.x / w, 0), 1)
                            let ny = min(max(value.location.y / h, 0), 1)
                            onPick(nx, ny)
                        }
                    )
            }
        }
    }
}

private struct HDRPaneTitle: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(.black.opacity(0.55))
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .padding(6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
    }
}

struct HDRTaggedHost: NSViewRepresentable {
    var image: CGImage?
    var odt: ODTMode
    var onLayerFail: (() -> Void)?

    func makeNSView(context: Context) -> HDRImageHost {
        HDRImageHost()
    }

    func updateNSView(_ nsView: HDRImageHost, context: Context) {
        nsView.onLayerFail = onLayerFail
        nsView.setImage(image, odt: odt)
    }
}

final class HDRImageHost: NSView {
    private let imageLayer = CALayer()
    private var pendingImage: CGImage?
    private var pendingODT: ODTMode = .hlg
    var onLayerFail: (() -> Void)?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer = CALayer()
        layer?.backgroundColor = CGColor(gray: 0.09, alpha: 1)
        imageLayer.contentsGravity = .resizeAspect
        setHDRLayerContentsFormat(imageLayer)
        layer?.addSublayer(imageLayer)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func setImage(_ img: CGImage?, odt: ODTMode) {
        pendingImage = img
        pendingODT = odt
        applyPending()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        applyPending()
    }

    private func applyPending() {
        let img = pendingImage
        let odt = pendingODT
        guard odt.isHDR else {
            imageLayer.contents = nil
            return
        }
        guard let destName = HDRPreviewColor.destColorSpaceName(odt),
              let dest = CGColorSpace(name: destName) else {
            failClosed(hadPixels: img != nil)
            return
        }
        guard enableEDR(layer), enableEDR(imageLayer) else {
            // Not in a window yet — retry in viewDidMoveToWindow.
            if window == nil {
                imageLayer.contents = nil
                return
            }
            failClosed(hadPixels: img != nil)
            return
        }
        setHDRLayerColorSpace(layer, dest)
        setHDRLayerColorSpace(imageLayer, dest)
        setHDRLayerContentsFormat(imageLayer)
        imageLayer.contents = img
    }

    private func failClosed(hadPixels: Bool) {
        imageLayer.contents = nil
        guard hadPixels else { return }
        DispatchQueue.main.async { [weak self] in
            self?.onLayerFail?()
        }
    }

    /// Layer wants EDR. Display-has-no-EDR is a different status
    /// (pixels still HDR-tagged). API reject → 「HDR 预览建不出」.
    /// KVC: runner CALayer overlay may omit the member (same as colorspace).
    private func enableEDR(_ layer: CALayer?) -> Bool {
        guard let layer else { return false }
        layer.setValue(true, forKey: "wantsExtendedDynamicRangeContent")
        return (layer.value(forKey: "wantsExtendedDynamicRangeContent") as? Bool) == true
    }

    override func layout() {
        super.layout()
        imageLayer.frame = bounds
    }
}
