import Foundation

/// Extension points for IDTs that stay unimplemented.
///
/// LogC3 EI800 + AWG3 and Apple Log 2 + Apple Wide Gamut are implemented
/// (unverified). This remains a stub:
///
/// - DJI D-Log M (unsupported; 2017 D-Log + D-Gamut only)
enum FutureIDTs {
    static let notes: [(String, String)] = [
        ("DJI D-Log M", "Unsupported. Use D-Log + D-Gamut (2017 white paper).")
    ]
}
