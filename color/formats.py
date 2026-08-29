"""Container / codec policy. Decode only — no color numbers.

Tried: MOV/MP4 ProRes / H.264 / HEVC; stills TIFF/DPX/EXR via ImageIO.
MXF: try if the system recognizes ProRes/AVC/HEVC. ARRI MXF (ARRIRAW) is refused.
CRM / X-OCN / N-RAW / ProRes RAW refused with the R3D line.
Never claim 全格式已支持.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ACCEPT = "accept"
TRY = "try"
REFUSE = "refuse"

MOVIE_CONTAINERS = frozenset({"mov", "mp4", "m4v"})
STILL_CONTAINERS = frozenset({"tif", "tiff", "dpx", "exr"})
MXF_CONTAINER = "mxf"

# Seen in a drop, then refused with a note. Not "全格式已支持".
REFUSED_CONTAINERS = frozenset(
    {"r3d", "braw", "ari", "arx", "avi", "mkv", "dng", "bmd", "crm", "nev", "nraw", "xocn"}
)

# ProRes 422 family + 4444 / XQ. Not ProRes RAW (aprn / aprh).
PRORES_FOURCC = frozenset({"apcn", "apch", "apcs", "apco", "ap4h", "ap4x"})
H264_FOURCC = frozenset({"avc1", "avc3", "ai5p", "ai5q"})
HEVC_FOURCC = frozenset({"hvc1", "hev1", "dvhe", "dvh1"})

PRORES_NAMES = frozenset(
    {
        "prores",
        "apple prores",
        "prores 422",
        "prores 422 hq",
        "prores 422 lt",
        "prores 422 proxy",
        "prores 4444",
        "prores 4444 xq",
    }
)
H264_NAMES = frozenset({"h264", "h.264", "avc", "x264"})
HEVC_NAMES = frozenset({"hevc", "h.265", "h265", "x265"})

ACCEPTED_CODECS = PRORES_FOURCC | H264_FOURCC | HEVC_FOURCC | PRORES_NAMES | H264_NAMES | HEVC_NAMES

ARRI_MXF_EXACT = frozenset({"ari", "arx"})
CAMERA_RAW_MARKERS = (
    "prores raw",
    "aprn",
    "aprh",
    "xocn",
    "x-ocn",
    "nraw",
    "n-raw",
    "crm",
)

# Locked refuse copy (沟通).
NOTE_ARRI_MXF = "ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入"
NOTE_CAMERA_RAW = "R3D / BRAW：暂不支持，请在相机软件转 ProRes / EXR"
NOTE_UNKNOWN_CODEC = "这个编码不接。能试的是 ProRes / H.264 / HEVC。"

# Folder expand lists these so a refuse note can fire. Not a support claim.
EXPAND_EXTENSIONS = (
    MOVIE_CONTAINERS | STILL_CONTAINERS | {MXF_CONTAINER} | REFUSED_CONTAINERS
)


@dataclass(frozen=True)
class FormatDecision:
    action: str
    container: str
    codec: str | None
    note: str
    kind: str  # movie | still | mxf | refuse


def _norm_codec(codec: str | None) -> str | None:
    if codec is None:
        return None
    return codec.strip().lower().replace("_", " ")


def classify(path: str | Path, codec: str | None = None) -> FormatDecision:
    """Classify a dropped file. Does not decode. Does not guess an IDT."""
    ext = Path(path).suffix.lower().lstrip(".")
    codec_n = _norm_codec(codec)

    if ext in REFUSED_CONTAINERS:
        return FormatDecision(
            action=REFUSE,
            container=ext,
            codec=codec_n,
            note=_refuse_note(ext),
            kind="refuse",
        )

    if ext in STILL_CONTAINERS:
        return FormatDecision(
            action=ACCEPT,
            container=ext,
            codec=codec_n,
            note=f"静帧 {ext.upper()} 走 ImageIO。不是成片。",
            kind="still",
        )

    if ext in MOVIE_CONTAINERS:
        if codec_n and _is_camera_raw(codec_n):
            return FormatDecision(
                action=REFUSE,
                container=ext,
                codec=codec_n,
                note=NOTE_CAMERA_RAW,
                kind="movie",
            )
        if codec_n and not _codec_ok(codec_n):
            return FormatDecision(
                action=REFUSE,
                container=ext,
                codec=codec_n,
                note=NOTE_UNKNOWN_CODEC,
                kind="movie",
            )
        return FormatDecision(
            action=ACCEPT,
            container=ext,
            codec=codec_n,
            note="MOV/MP4：ProRes / H.264 / HEVC 走 AVAssetReader Y′CbCr。不走 copyCGImage。",
            kind="movie",
        )

    if ext == MXF_CONTAINER:
        if codec_n and _is_arri_mxf(codec_n):
            return FormatDecision(
                action=REFUSE,
                container=ext,
                codec=codec_n,
                note=NOTE_ARRI_MXF,
                kind="mxf",
            )
        if codec_n and _is_camera_raw(codec_n):
            return FormatDecision(
                action=REFUSE,
                container=ext,
                codec=codec_n,
                note=NOTE_CAMERA_RAW,
                kind="mxf",
            )
        if codec_n and not _codec_ok(codec_n):
            return FormatDecision(
                action=REFUSE,
                container=ext,
                codec=codec_n,
                note=NOTE_UNKNOWN_CODEC,
                kind="mxf",
            )
        return FormatDecision(
            action=TRY,
            container=ext,
            codec=codec_n,
            note="MXF 只试系统认得出的 ProRes / AVC / HEVC。" + NOTE_ARRI_MXF,
            kind="mxf",
        )

    return FormatDecision(
        action=REFUSE,
        container=ext or "unknown",
        codec=codec_n,
        note="这个容器不接。不写「全格式已支持」。",
        kind="refuse",
    )


def _codec_ok(codec: str) -> bool:
    if _is_camera_raw(codec):
        return False
    if codec in ACCEPTED_CODECS:
        return True
    return any(
        token in codec
        for token in ("prores 422", "prores 4444", "h.264", "h264", "avc", "hevc", "h.265", "h265")
    ) or codec == "prores" or codec == "apple prores"


def _is_arri_mxf(codec: str) -> bool:
    # Exact "ari"/"arx" — do not substring-match (Swift: == "ari" || == "arx").
    if codec in ARRI_MXF_EXACT:
        return True
    return "arri" in codec


def _is_camera_raw(codec: str) -> bool:
    return any(m in codec for m in CAMERA_RAW_MARKERS)


def _refuse_note(ext: str) -> str:
    if ext in {"ari", "arx", "r3d", "braw", "bmd", "crm", "nev", "nraw", "xocn", "dng"}:
        return NOTE_CAMERA_RAW
    if ext in {"avi", "mkv"}:
        return f"{ext.upper()} 不接。请用 MOV/MP4。"
    return f".{ext} 不接。不写「全格式已支持」。"


def empty_metadata_note() -> str:
    """No camera-private metadata → paired IDT picker. Do not guess."""
    return "先选择 Log 与色域"
