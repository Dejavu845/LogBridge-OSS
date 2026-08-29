import Foundation
import simd

/// Scene-linear white-balance node (Bradford CAT, CCT + green-magenta tint).
///
/// Scene-linear ACES2065-1 (AP0) after IDT. Never a CAT on ACEScct-encoded values.
/// This math is applied in AP0 scene-linear RGB, never in log. The node can be
/// toggled off for Resolve export so WB is not baked (disable WB = IDT → Exposure → ACEScct).
enum WhiteBalanceNode {
    /// Bradford cone-response matrix (CIE).
    static let bradford = simd_double3x3(rows: [
        SIMD3(0.8951, 0.2664, -0.1614),
        SIMD3(-0.7502, 1.7135, 0.0367),
        SIMD3(0.0389, -0.0685, 1.0296)
    ])

    static let cat02 = simd_double3x3(rows: [
        SIMD3(0.7328, 0.4296, -0.1624),
        SIMD3(-0.7036, 1.6975, 0.0061),
        SIMD3(0.0030, 0.0136, 0.9834)
    ])

    static let d65 = SIMD2<Double>(0.3127, 0.3290)

    /// ACES2065-1 (AP0) → XYZ. Matches color/gamuts.py / PreviewColor.
    static let ap0ToXYZ = simd_double3x3(rows: [
        SIMD3(0.952552395938186, 0.000000000000000, 0.000093678631660),
        SIMD3(0.343966449765075, 0.728166096613486, -0.072132546378561),
        SIMD3(0.000000000000000, 0.000000000000000, 1.008825184351586)
    ])

    static func xy(cct: Double, tint: Double = 0) -> SIMD2<Double> {
        // Daylight locus at T >= 4000 K so 6504 K ≈ D65 identity.
        // Planckian below 4000 K (tungsten). Full implementation matches color/wb.py.
        let t = max(cct, 1000)
        var x: Double
        var y: Double
        if t >= 4000 {
            let xd: Double
            if t <= 7000 {
                xd = 0.244063 + 0.09911e3 / t + 2.9678e6 / (t * t) - 4.6070e9 / (t * t * t)
            } else {
                xd = 0.237040 + 0.24748e3 / t + 1.9018e6 / (t * t) - 2.0064e9 / (t * t * t)
            }
            x = xd
            y = -3.0 * xd * xd + 2.870 * xd - 0.275
        } else {
            let inv = 1.0e3 / t
            let inv2 = 1.0e6 / (t * t)
            let inv3 = 1.0e9 / (t * t * t)
            x = -0.2661239 * inv3 - 0.2343580 * inv2 + 0.8776956 * inv + 0.179910
            y = -0.9549476 * x * x * x - 1.37418593 * x * x + 2.09137015 * x - 0.16748867
        }
        if tint != 0 {
            let denom = -2.0 * x + 12.0 * y + 3.0
            var u = 4.0 * x / denom
            var v = 6.0 * y / denom
            v += tint * 1.0e-3
            let d = 2.0 * u - 8.0 * v + 4.0
            x = 3.0 * u / d
            y = 2.0 * v / d
        }
        return SIMD2(x, y)
    }

    /// XYZ CAT taking src white to dst white (Bradford / CAT02).
    static func catMatrix(srcXY: SIMD2<Double>, dstXY: SIMD2<Double>, method: String = "bradford") -> simd_double3x3 {
        let m = method == "cat02" ? cat02 : bradford
        let srcXYZ = xyToXYZ(srcXY)
        let dstXYZ = xyToXYZ(dstXY)
        let srcCone = m * srcXYZ
        let dstCone = m * dstXYZ
        let scale = simd_double3x3(diagonal: SIMD3(
            dstCone.x / srcCone.x,
            dstCone.y / srcCone.y,
            dstCone.z / srcCone.z
        ))
        return simd_mul(simd_mul(m.inverse, scale), m)
    }

    static func catMatrix(cct: Double, tint: Double = 0, method: String = "bradford") -> simd_double3x3 {
        catMatrix(srcXY: xy(cct: cct, tint: tint), dstXY: d65, method: method)
    }

    /// Relative: CAT(user→D65)·inv(CAT(as→D65)) == CAT(user→as).
    /// 3200 as-shot → 5600 user warms (in-camera Kelvin).
    /// Not CAT(as→user), not CAT(user→D65) alone.
    static func relativeCatMatrix(
        srcCCT: Double,
        dstCCT: Double,
        srcTint: Double = 0,
        dstTint: Double = 0,
        method: String = "bradford"
    ) -> simd_double3x3 {
        let mUser = catMatrix(cct: dstCCT, tint: dstTint, method: method)
        let mShot = catMatrix(cct: srcCCT, tint: srcTint, method: method)
        return simd_mul(mUser, mShot.inverse)
    }

    /// Apply CAT in scene-linear RGB of a D65 space (XYZ CAT conjugated by RGB<->XYZ).
    /// `cct == nil` is pending / identity — do not guess 5600 or 6504.
    static func apply(rgb: SIMD3<Double>, rgbToXYZ: simd_double3x3, cct: Double?, tint: Double) -> SIMD3<Double> {
        guard let cct else { return rgb }
        let cat = catMatrix(cct: cct, tint: tint)
        let xyz = rgbToXYZ * rgb
        let adapted = cat * xyz
        return rgbToXYZ.inverse * adapted
    }

    private static func xyToXYZ(_ xy: SIMD2<Double>) -> SIMD3<Double> {
        SIMD3(xy.x / xy.y, 1.0, (1.0 - xy.x - xy.y) / xy.y)
    }

    private static func xyToUV(_ xy: SIMD2<Double>) -> SIMD2<Double> {
        let denom = -2.0 * xy.x + 12.0 * xy.y + 3.0
        return SIMD2(4.0 * xy.x / denom, 6.0 * xy.y / denom)
    }

    /// Invert the same locus as `xy(cct:tint:)`. Grey-card / pick-neutral.
    static func cctTint(fromXY xy: SIMD2<Double>) -> (cct: Double, tint: Double) {
        let uv = xyToUV(xy)
        func err(_ cct: Double) -> Double {
            let lu = xyToUV(Self.xy(cct: cct, tint: 0))
            let du = uv.x - lu.x
            let dv = uv.y - lu.y
            return du * du + dv * dv
        }
        var best = 6504.0
        var bestE = err(best)
        var c = 1000.0
        while c <= 20000.0 {
            let e = err(c)
            if e < bestE {
                bestE = e
                best = c
            }
            c += 50.0
        }
        var lo = max(1000.0, best - 50.0)
        var hi = min(20000.0, best + 50.0)
        let phi = (1.0 + 5.0.squareRoot()) / 2.0
        for _ in 0..<40 {
            let a = hi - (hi - lo) / phi
            let b = lo + (hi - lo) / phi
            if err(a) < err(b) { hi = b } else { lo = a }
        }
        let cct = 0.5 * (lo + hi)
        let locusUV = xyToUV(Self.xy(cct: cct, tint: 0))
        let tint = (uv.y - locusUV.y) / 1.0e-3
        return (cct, tint)
    }

    /// Grey-card: sample after IDT in ACES2065-1 (AP0) linear. Overrides metadata.
    static func pickNeutral(linearRGB: SIMD3<Double>, rgbToXYZ: simd_double3x3) -> (cct: Double, tint: Double)? {
        let xyz = rgbToXYZ * linearRGB
        let s = xyz.x + xyz.y + xyz.z
        guard s > 1e-12 else { return nil }
        return cctTint(fromXY: SIMD2(xyz.x / s, xyz.y / s))
    }

    static let ap0ToAP1 = simd_double3x3(rows: [
        SIMD3(1.451439316146, -0.236510746894, -0.214928569252),
        SIMD3(-0.076553773396, 1.176229699834, -0.099675926438),
        SIMD3(0.008316148426, -0.006032449791, 0.997716301365)
    ])
    static let ap1ToAP0 = simd_double3x3(rows: [
        SIMD3(0.695452241357452, 0.140678696470294, 0.163869062172254),
        SIMD3(0.044794563372038, 0.859671118456422, 0.095534318171540),
        SIMD3(-0.005525882558114, 0.004025210305979, 1.001500672252135)
    ])
    static let ap1Y = SIMD3(0.272228716781, 0.674081765811, 0.053689517408)

    /// 白平衡（估计）: SoG p=6 in linear ACEScg. Empty on low confidence. Not calibration.
    static func estimateAutoWB(ap0: [Float], width: Int, height: Int) -> (cct: Double, tint: Double)? {
        guard width > 0, height > 0, ap0.count >= width * height * 3 else { return nil }
        func pixel(_ x: Int, _ y: Int) -> SIMD3<Double> {
            let i = (y * width + x) * 3
            let ap0p = SIMD3(Double(ap0[i]), Double(ap0[i + 1]), Double(ap0[i + 2]))
            return ap0ToAP1 * ap0p
        }
        func sog(_ x0: Int, _ y0: Int, _ x1: Int, _ y1: Int) -> (SIMD3<Double>, Double)? {
            var sum = SIMD3<Double>(repeating: 0)
            var n = 0
            var total = 0
            let p = 6.0
            for y in y0..<y1 {
                for x in x0..<x1 {
                    total += 1
                    let c = pixel(x, y)
                    let yv = simd_dot(c, ap1Y)
                    if yv >= 0.02, c.x <= 8, c.y <= 8, c.z <= 8, c.x >= 0, c.y >= 0, c.z >= 0,
                       c.x.isFinite, c.y.isFinite, c.z.isFinite {
                        sum += SIMD3(pow(c.x, p), pow(c.y, p), pow(c.z, p))
                        n += 1
                    }
                }
            }
            let frac = total == 0 ? 0.0 : Double(n) / Double(total)
            guard frac >= 0.15, n > 0 else { return nil }
            let mean = sum / Double(n)
            let illum = SIMD3(pow(max(mean.x, 0), 1 / p), pow(max(mean.y, 0), 1 / p), pow(max(mean.z, 0), 1 / p))
            return (illum, frac)
        }
        func angle(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double {
            let na = simd_length(a), nb = simd_length(b)
            guard na > 1e-12, nb > 1e-12 else { return 0 }
            let c = min(1, max(-1, simd_dot(a, b) / (na * nb)))
            return acos(c) * 180 / .pi
        }
        guard let (illum, _) = sog(0, 0, width, height) else { return nil }
        if angle(illum, SIMD3(1, 1, 1)) < 2 { return nil }
        if width >= 3, height >= 3 {
            var tiles: [SIMD3<Double>] = []
            let ys = [0, height / 3, 2 * height / 3, height]
            let xs = [0, width / 3, 2 * width / 3, width]
            for ty in 0..<3 {
                for tx in 0..<3 {
                    if let (t, _) = sog(xs[tx], ys[ty], xs[tx + 1], ys[ty + 1]) {
                        tiles.append(t)
                    }
                }
            }
            var mx = 0.0
            for i in 0..<tiles.count {
                for j in (i + 1)..<tiles.count {
                    mx = max(mx, angle(tiles[i], tiles[j]))
                }
            }
            if mx > 5 { return nil }
        }
        let ap0Illum = ap1ToAP0 * illum
        return pickNeutral(linearRGB: ap0Illum, rgbToXYZ: ap0ToXYZ)
    }
}

