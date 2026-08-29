import Foundation
import AVFoundation
import CoreMedia
import ImageIO

/// Container / codec probe. Decode policy only — no color numbers.
///
/// Tried: MOV/MP4 ProRes / H.264 / HEVC; stills TIFF/DPX/EXR via ImageIO.
/// MXF: try if the system recognizes ProRes/AVC/HEVC. ARRI MXF (ARRIRAW) is refused.
/// Never claim 全格式已支持.
enum MediaDecision: String {
    case accept
    case tryDecode = "try"
    case refuse
}

enum MediaKind: String {
    case movie
    case still
    case mxf
    case refuse
}

struct MediaProbe: Equatable {
    let decision: MediaDecision
    let container: String
    let codec: String?
    let kind: MediaKind
    let note: String
}

/// Timing / size for dest-disk estimate. Decode policy only — no color numbers.
struct MediaExtent: Equatable {
    var frameCount: Int?
    var durationSeconds: Double?
    var fps: Double?
    var width: Int?
    var height: Int?
}

enum MediaFormat {
    static let movieExt: Set<String> = ["mov", "mp4", "m4v"]
    static let stillExt: Set<String> = ["tif", "tiff", "dpx", "exr"]
    static let mxfExt = "mxf"
    static let refusedExt: Set<String> = [
        "r3d", "braw", "ari", "arx", "avi", "mkv", "dng", "bmd", "crm", "nev", "nraw", "xocn"
    ]
    /// Folder expand lists these so a refuse note can fire.
    static let expandExt: Set<String> = movieExt.union(stillExt).union(refusedExt).union([mxfExt])

    static let proresFourCC: Set<String> = ["apcn", "apch", "apcs", "apco", "ap4h", "ap4x"]
    static let h264FourCC: Set<String> = ["avc1", "avc3", "ai5p", "ai5q"]
    static let hevcFourCC: Set<String> = ["hvc1", "hev1", "dvhe", "dvh1"]
    /// Locked refuse copy (沟通).
    static let noteARRIMxf = "ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入"
    static let noteCameraRaw = "R3D / BRAW：暂不支持，请在相机软件转 ProRes / EXR"
    static let noteUnknownCodec = "这个编码不接。能试的是 ProRes / H.264 / HEVC。"

    static func probe(url: URL) -> MediaProbe {
        let ext = url.pathExtension.lowercased()
        let codec = codecFourCC(url: url)
        return classify(ext: ext, codec: codec)
    }

    /// Frame count / duration / fps / pixel size. Dest-disk estimate and
    /// post-write EXR count check. Does not decode pixels or invent fps.
    static func extent(url: URL) -> MediaExtent {
        let ext = url.pathExtension.lowercased()
        if stillExt.contains(ext) {
            var width: Int?
            var height: Int?
            if let src = CGImageSourceCreateWithURL(url as CFURL, nil),
               let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] {
                if let w = props[kCGImagePropertyPixelWidth] as? NSNumber { width = w.intValue }
                if let h = props[kCGImagePropertyPixelHeight] as? NSNumber { height = h.intValue }
            }
            return MediaExtent(frameCount: 1, durationSeconds: nil, fps: nil, width: width, height: height)
        }
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first else {
            return MediaExtent(frameCount: nil, durationSeconds: nil, fps: nil, width: nil, height: nil)
        }
        let fpsRaw = Double(track.nominalFrameRate)
        let durRaw = CMTimeGetSeconds(asset.duration)
        let size = track.naturalSize.applying(track.preferredTransform)
        let width = Int(abs(size.width).rounded())
        let height = Int(abs(size.height).rounded())
        let fps = fpsRaw.isFinite && fpsRaw > 0 ? fpsRaw : nil
        let duration = durRaw.isFinite && durRaw > 0 ? durRaw : nil
        return MediaExtent(
            frameCount: nil,
            durationSeconds: duration,
            fps: fps,
            width: width > 0 ? width : nil,
            height: height > 0 ? height : nil
        )
    }

    static func classify(ext: String, codec: String?) -> MediaProbe {
        let codecN = codec?.lowercased()
        if refusedExt.contains(ext) {
            return MediaProbe(
                decision: .refuse,
                container: ext,
                codec: codecN,
                kind: .refuse,
                note: refuseNote(ext)
            )
        }
        if stillExt.contains(ext) {
            return MediaProbe(
                decision: .accept,
                container: ext,
                codec: codecN,
                kind: .still,
                note: "静帧 \(ext.uppercased()) 走 ImageIO。不是成片。"
            )
        }
        if movieExt.contains(ext) {
            if let codecN, isCameraRaw(codecN) {
                return MediaProbe(
                    decision: .refuse,
                    container: ext,
                    codec: codecN,
                    kind: .movie,
                    note: noteCameraRaw
                )
            }
            if let codecN, !codecOK(codecN) {
                return MediaProbe(
                    decision: .refuse,
                    container: ext,
                    codec: codecN,
                    kind: .movie,
                    note: noteUnknownCodec
                )
            }
            return MediaProbe(
                decision: .accept,
                container: ext,
                codec: codecN,
                kind: .movie,
                note: "MOV/MP4：ProRes / H.264 / HEVC 走 AVAssetReader Y′CbCr。不走 copyCGImage。"
            )
        }
        if ext == mxfExt {
            if let codecN, isARRIMxf(codecN) {
                return MediaProbe(
                    decision: .refuse,
                    container: ext,
                    codec: codecN,
                    kind: .mxf,
                    note: noteARRIMxf
                )
            }
            if let codecN, isCameraRaw(codecN) {
                return MediaProbe(
                    decision: .refuse,
                    container: ext,
                    codec: codecN,
                    kind: .mxf,
                    note: noteCameraRaw
                )
            }
            if let codecN, !codecOK(codecN) {
                return MediaProbe(
                    decision: .refuse,
                    container: ext,
                    codec: codecN,
                    kind: .mxf,
                    note: noteUnknownCodec
                )
            }
            return MediaProbe(
                decision: .tryDecode,
                container: ext,
                codec: codecN,
                kind: .mxf,
                note: "MXF 只试系统认得出的 ProRes / AVC / HEVC。" + noteARRIMxf
            )
        }
        return MediaProbe(
            decision: .refuse,
            container: ext.isEmpty ? "unknown" : ext,
            codec: codecN,
            kind: .refuse,
            note: "这个容器不接。不写「全格式已支持」。"
        )
    }

    /// Camera fourcc from the first video track. Nil if the system cannot open it.
    static func codecFourCC(url: URL) -> String? {
        let asset = AVURLAsset(url: url)
        guard let track = asset.tracks(withMediaType: .video).first else { return nil }
        let descs = track.formatDescriptions as? [CMFormatDescription] ?? []
        for desc in descs {
            let subtype = CMFormatDescriptionGetMediaSubType(desc)
            let tag = fourCC(subtype)
            if !tag.isEmpty { return tag }
        }
        return nil
    }

    static func fourCC(_ raw: FourCharCode) -> String {
        let bytes: [UInt8] = [
            UInt8((raw >> 24) & 0xFF),
            UInt8((raw >> 16) & 0xFF),
            UInt8((raw >> 8) & 0xFF),
            UInt8(raw & 0xFF)
        ]
        return String(bytes: bytes, encoding: .ascii)?.trimmingCharacters(in: .whitespaces) ?? ""
    }

    static func codecOK(_ codec: String) -> Bool {
        let c = codec.lowercased()
        if isCameraRaw(c) { return false }
        if proresFourCC.contains(c) || h264FourCC.contains(c) || hevcFourCC.contains(c) {
            return true
        }
        if c == "prores" || c == "apple prores" { return true }
        return c.contains("prores 422") || c.contains("prores 4444")
            || c.contains("h264") || c.contains("h.264")
            || c.contains("avc") || c.contains("hevc") || c.contains("h265") || c.contains("h.265")
    }

    static func isCameraRaw(_ codec: String) -> Bool {
        let c = codec.lowercased()
        return c.contains("prores raw") || c == "aprn" || c == "aprh"
            || c.contains("xocn") || c.contains("x-ocn")
            || c.contains("nraw") || c.contains("n-raw")
            || c == "crm"
    }

    static func isARRIMxf(_ codec: String) -> Bool {
        let c = codec.lowercased()
        return c.contains("arri") || c == "ari" || c == "arx"
    }

    private static func refuseNote(_ ext: String) -> String {
        switch ext {
        case "ari", "arx", "r3d", "braw", "bmd", "crm", "nev", "nraw", "xocn", "dng": return noteCameraRaw
        case "avi", "mkv": return "\(ext.uppercased()) 不接。请用 MOV/MP4。"
        default: return ".\(ext) 不接。不写「全格式已支持」。"
        }
    }
}
