"""Locked-IDT batch policy + ACES2065-1 proxy EXR sequence writes. No color-number changes.

A clip is processable only when its paired IDT is chosen / locked.
Batch walks locked clips only. Pending / unlocked stay in the list with a
Chinese reason. Never guess 5600 or 6504. Never invent a second process
button. Auto WB estimate does not write CAT until confirm; grey-card
overrides estimate.

「处理已锁定片段」 writes one ACES2065-1 (AP0 linear) **proxy EXR sequence**
per locked clip (ODT off): ``{stem}_ACES2065-1_proxy/frame_000000.exr``.
The write loop is decode → IDT → exposure → WB → EXR. It uses
``apply_ap0`` (clip-constant CAT via ``ap0_write_setup``), not
``graph.apply``, so a 709 preview ODT is never baked. Preview/scrub
still runs ODT only on the linear cache.
Movie write decode uses source 10-bit / native-depth Y′CbCr → float
(matrix-only; no Rec.709 transfer before IDT). YUV matrix and
full/video range follow the buffer / nclc attachments — not a
hardcoded BT.709 + video-range for every clip. Scale is bit-depth
+ range (video 10-bit is Y 64–940 / C 64–960, not /1023). 8-bit
Y′CbCr is only the fallback when 10-bit is unavailable. Still a
proxy, not camera-original — 整段代理，不是全精度成片. Not ACEScct.
Not a Rec.709 .mov/.mp4. Movie preview first-frame unpack shares the same
nclc/colr/vui matrix+range helper, then quantizes to 8-bit / 1920.
Stills (TIFF / DPX / EXR) stay ImageIO — already RGB, no Y′CbCr unpack.
Write is source pixels 1:1 and source-native bit depth. 16384 is a
refuse ceiling (「片源边长超过 16384，未写出」), not a downsample
target. Do not scale export to 16384 or 1920. Write does not use
the 8-bit preview buffer. Preview/scrub may stay 8-bit-first.
「N 条已处理」 is clips that produced a sequence, or locked clips attempted
with a per-clip error — not a preview refresh. Pending clips in the same
bin do not block.

While writing, progress is 「写出代理 i/N · frame k」 (k/total when known).
Cancel becomes the same primary button. The in-progress ``_proxy`` folder
is removed so a half sequence is not a finished deliverable; completed
clips stay. Cancelled status says 已取消 and still 整段代理，不是全精度成片.
Partial output is 不是成片. A successful write remembers the dest folder
(UserDefaults) and status offers 「在 Finder 中显示」. Cancel does not
treat a deleted half-folder as success. After a write, locked sidebar
rows show 「已写出代理」 (or a short Chinese error). Clicking that
row or chip reveals that clip's ``{stem}_ACES2065-1_proxy/`` from the
last dest (``deliverable_dir_name``). Pending / failed / cancelled
do not reveal. Pending stay 「先选择 Log 与色域」 / 「先选择成对 IDT」.
A cancelled in-progress clip is not 已写出; completed clips keep
已写出代理. Re-export clears or refreshes the chip. Session-level
「在 Finder 中显示」 stays.

After a locked write, count EXRs in ``{stem}_ACES2065-1_proxy/`` and
compare to source duration × metadata fps only. Off-by-one is accepted
(inclusive last frame). Missing fps is 「读不到帧率，未核对」; missing
duration is 「读不到时长，未核对」 — never default 24 or 30, and do
not reuse the dest-disk 24 fps × 60 s guess. A mismatch is
「帧数对不上」; the folder is removed so it is not 已写出代理.

When 「处理已锁定片段」 finishes (ok / cancel / disk abort / frame
check), ``lastExportNote`` is one Chinese three-bucket summary:
「N 条已写出代理 / M 条待选跳过 / K 条失败」 plus 失败原因
(existing chips only). Not a second process button. Not a summary page.
Do not reuse the dest-disk 24 fps × 60 s guess in this summary.

Before any EXR is written, estimate dest disk from **locked clips
only**: frame count × pixel count × 12 bytes (uncompressed float32
RGB; EXR header / offset table is covered by a small margin). If
frame count is unknown, use duration×fps, or a conservative 24 fps
× 60 s guess (said in the note). If free space < estimate + margin,
do not start writing. Status: 「磁盘空间不足，未写出」 +
「整段代理，不是全精度成片」.

Swift ``SessionModel.processLockedClips`` mirrors this module. Color is
``SerialGraph.apply`` (existing pipeline). Container is ``exr_write``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
import shutil
from typing import Callable, Sequence

import numpy as np

from .as_shot import WB_SOURCE_ESTIMATE, WB_SOURCE_GREY
from .exr_write import write_rgb_exr
from .graph import SerialGraph

REASON_PICK_LOG_GAMUT = "先选择 Log 与色域"
REASON_PICK_PAIRED_IDT = "先选择成对 IDT"
# preview.status (Swift PreviewEngine). Existing phrases only. No 精准.
PREVIEW_STATUS_EMPTY = "没有素材"
PREVIEW_STATUS_DECODING = "正在解码预览…"
PREVIEW_STATUS_DECODE_FAIL = "解不出预览帧"
PREVIEW_STATUS_ODT_CACHE_HIT = "只重跑 ODT"
PREVIEW_STATUS_PROXY = "预览代理，不是成片"
PREVIEW_STATUS_NOT_DELIVERABLE = "预览·非成片"
PREVIEW_STATUS_ODT_OFF = "709 预览关"
PREVIEW_STATUS_HDR_BUILD_FAIL = "HDR 预览建不出"
PREVIEW_STATUS_HDR_NO_EDR = "屏幕无 EDR，预览被压到 SDR"
PROCESS_BUTTON = "处理已锁定片段"
ADVANCED_DISCLOSURE = "高级"
LOCK_STATUS_TEMPLATE = "{locked} 条已锁定 / {pending} 条待选"
HONEST_PROXY_NOTE = "整段代理，不是全精度成片"
PROCESSED_STATUS_TEMPLATE = (
    "处理已锁定片段 — {processed} 条已处理 / {skipped} 条已跳过"
    "（先选择 Log 与色域 / 先选择成对 IDT）。"
    "整段代理，不是全精度成片。预览·非成片。已实现（未验证）。"
)
FOLDER_PICKER_MESSAGE = (
    "已锁定片段写出 ACES2065-1 代理 EXR 序列（AP0 线性）。"
    "整段代理，不是全精度成片。"
    "未锁定的跳过（先选择 Log 与色域 / 先选择成对 IDT）。"
    "预览·非成片。已实现（未验证）。"
)
PROCESS_BUTTON_HELP = (
    "整段代理，不是全精度成片。ACES2065-1 AP0 线性，不是 ACEScct。"
    "待选跳过（先选择 Log 与色域 / 先选择成对 IDT）。"
)
ADVANCED_EXPORT_HELP = (
    "只处理已锁定片段。待选跳过。709 预览。预览·非成片。不必全部锁定。"
)
ADVANCED_DISCLOSURE_HELP = "节点与导出 ACEScct / EXR。默认收起。预览·非成片。"
CANCEL_BUTTON = "取消"
CANCELLED_NOTE = "已取消"
PROGRESS_PREFIX = "写出代理"
CANCELLED_STATUS_TEMPLATE = (
    "处理已锁定片段 — 已取消。"
    "{processed} 条已处理 / {skipped} 条已跳过"
    "（先选择 Log 与色域 / 先选择成对 IDT）。"
    "整段代理，不是全精度成片。预览·非成片。已实现（未验证）。"
)
# Folder of per-frame EXRs. Names must include _proxy so this is not a 成片 claim.
DELIVERABLE_DIR_SUFFIX = "_ACES2065-1_proxy"
DELIVERABLE_SUFFIX = DELIVERABLE_DIR_SUFFIX
SEQUENCE_FRAME_PREFIX = "frame"
SEQUENCE_FRAME_WIDTH = 6
REVEAL_IN_FINDER = "在 Finder 中显示"
LAST_EXPORT_DIRECTORY_KEY = "logbridge.lastExportDirectory"
WRITTEN_CHIP = "已写出代理"
WRITE_FAILED_CHIP = "写出失败"
DECODE_FAILED_CHIP = "解码失败"
FRAME_MISMATCH_CHIP = "帧数对不上"
MISSING_FPS_CHIP = "读不到帧率，未核对"
MISSING_DURATION_CHIP = "读不到时长，未核对"
MISSING_YCBCR_TAGS_CHIP = "无法读取片源 Y′CbCr 矩阵/范围，未写出"
WRITE_LONG_EDGE_CEILING = 16384
WRITE_OVERSIZE_CHIP = "片源边长超过 16384，未写出"
DISK_SHORT_STATUS = "磁盘空间不足，未写出"
# Uncompressed float32 RGB scanline payload (3 × 4). Not ZIP/PIZ.
# Header + offset table are not per-pixel; DISK_MARGIN covers them.
BYTES_PER_EXR_PIXEL = 12
DISK_MARGIN_RATIO = 0.10
DISK_MARGIN_MIN_BYTES = 64 * 1024 * 1024
CONSERVATIVE_FPS = 24.0
CONSERVATIVE_SECONDS = 60.0
CONSERVATIVE_WIDTH = 3840
CONSERVATIVE_HEIGHT = 2160
DISK_ESTIMATE_ASSUMPTION = "float32 RGB 未压缩"
DISK_SHORT_STATUS_TEMPLATE = (
    "磁盘空间不足，未写出。整段代理，不是全精度成片。"
)
SKIPPED_BUCKET = "待选跳过"
FAILED_BUCKET = "失败原因"
BATCH_SUMMARY_TEMPLATE = "{wrote} 条已写出代理 / {skipped} 条待选跳过 / {failed} 条失败"

# Y′CbCr → R′G′B′ matrix-only. Coefficients follow the source matrix
# (BT.601 / BT.709 / BT.2020). Write path does not apply a Rec.709 transfer.
YCBCR_MATRIX_COEFFS = {
    "bt709": (1.5748, 0.1873, 0.4681, 1.8556),
    "bt601": (1.402, 0.344136, 0.714136, 1.772),
    "bt2020": (1.4746, 0.164553, 0.571353, 1.8814),
}
YCBCR_BT709_RV, YCBCR_BT709_GU, YCBCR_BT709_GV, YCBCR_BT709_BU = YCBCR_MATRIX_COEFFS[
    "bt709"
]
# Video-range 8/10-bit legal spans (ITU). Not a literal 1023 for every 10-bit clip.
YCBCR_OFF_8 = (16.0, 219.0, 128.0, 224.0)
YCBCR_OFF_10 = (64.0, 876.0, 512.0, 896.0)


def ycbcr_range_offsets(bit_depth: int, sample_range: str):
    """Y/C offsets from bit-depth AND full/video. Never always /1023.

    Video n-bit: Y 16<<(n-8) … 235<<(n-8), C 16<<(n-8) … 240<<(n-8).
    10-bit video is 64–940 / 64–960, not 0–1023. Full n-bit is 0…2^n-1.
    N-Log 10-bit video-range codes are wrong if blindly divided by 1023.
    """
    if int(bit_depth) < 8:
        raise ValueError(f"bit_depth must be >= 8, got {bit_depth}")
    max_code = float((1 << int(bit_depth)) - 1)
    mid = float(1 << (int(bit_depth) - 1))
    kind = str(sample_range).lower()
    if kind == "full":
        return (0.0, max_code, mid, max_code)
    if kind != "video":
        raise ValueError(f"sample_range must be video or full, got {sample_range}")
    shift = int(bit_depth) - 8
    y_off = float(16 << shift)
    y_span = float((235 << shift) - (16 << shift))
    c_span = float((240 << shift) - (16 << shift))
    return (y_off, y_span, mid, c_span)


def ycbcr_to_rgb_float(
    y,
    cb,
    cr,
    *,
    bit_depth: int,
    sample_range: str,
    matrix: str,
):
    """Source-code Y′CbCr → float R′G′B′. Matrix-only. No 8-bit RGB quantize.

    ``matrix`` / ``sample_range`` follow the source (attachments / nclc).
    No Rec.709 OETF/EOTF. Superwhite / superblack may leave 0-1.
    Still 整段代理，不是全精度成片.
    """
    key = str(matrix).lower().replace(".", "")
    if key not in YCBCR_MATRIX_COEFFS:
        raise ValueError(f"matrix must be bt709 / bt601 / bt2020, got {matrix}")
    rv, gu, gv, bu = YCBCR_MATRIX_COEFFS[key]
    y_off, y_span, c_off, c_span = ycbcr_range_offsets(bit_depth, sample_range)
    yp = (float(y) - y_off) / y_span
    pbv = (float(cb) - c_off) / c_span
    prv = (float(cr) - c_off) / c_span
    return (yp + rv * prv, yp - gu * pbv - gv * prv, yp + bu * pbv)


def _normalize_ycbcr_matrix(value) -> str | None:
    """Map nclc/colr/vui matrix to bt709 / bt601 / bt2020. Unspecified → None."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip().lower().replace(".", "").replace(" ", "")
        if raw in YCBCR_MATRIX_COEFFS:
            return raw
        if "2020" in raw:
            return "bt2020"
        if "601" in raw or "240m" in raw:
            return "bt601"
        if "709" in raw:
            return "bt709"
        if raw.isdigit():
            return _matrix_from_code(int(raw))
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _matrix_from_code(int(value))
    return None


def _matrix_from_code(code: int) -> str | None:
    """ITU/H.273 matrix_coefficients. 0/2 unspecified → None (no 709 default)."""
    if code == 1:
        return "bt709"
    if code in (4, 5, 6, 7):
        return "bt601"
    if code in (9, 10):
        return "bt2020"
    return None


def _nclc_triplet(value) -> tuple[int, int, int] | None:
    """nclc / nclx / colr as primaries-transfer-matrix. Do not use P/T for IDT."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        parts = value.replace(",", "-").replace(":", "-").split("-")
        if len(parts) >= 3:
            try:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                return None
    return None


def parse_source_ycbcr_matrix(tags) -> str | None:
    """Matrix from nclc / colr / vui only. Missing or unspecified → None."""
    if not isinstance(tags, dict):
        return None
    for key in (
        "ycbcr_matrix",
        "YCbCrMatrix",
        "vui_matrix",
        "matrix_coefficients",
        "nclc_matrix",
    ):
        if key in tags:
            got = _normalize_ycbcr_matrix(tags[key])
            if got:
                return got
            return None
    for key in ("nclc", "nclx", "colr"):
        trip = _nclc_triplet(tags.get(key))
        if trip is not None:
            return _matrix_from_code(trip[2])
    return None


def parse_source_ycbcr_range(tags) -> str | None:
    """Full/video from nclc/nclx/vui. Missing → None (not video by default)."""
    if not isinstance(tags, dict):
        return None
    for key in (
        "full_range",
        "FullRangeVideo",
        "video_full_range_flag",
        "nclx_full_range",
        "sample_range",
    ):
        if key not in tags:
            continue
        value = tags[key]
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("full", "1", "true", "yes"):
                return "full"
            if low in ("video", "limited", "tv", "0", "false", "no"):
                return "video"
            return None
        if value is True or value == 1:
            return "full"
        if value is False or value == 0:
            return "video"
        return None
    return None


def require_source_ycbcr_tags(tags) -> tuple[str, str]:
    """Write unpack: both matrix and range from tags, or Chinese failure.

    No silent BT.709 + video-range default. Does not read primaries/transfer
    to change an IDT or to apply a 709 curve.
    """
    matrix = parse_source_ycbcr_matrix(tags)
    sample_range = parse_source_ycbcr_range(tags)
    if matrix is None or sample_range is None:
        raise ValueError(MISSING_YCBCR_TAGS_CHIP)
    return matrix, sample_range


def ycbcr_to_preview_u8(y, cb, cr, *, bit_depth: int = 10, sample_range: str = "video", matrix: str = "bt709"):
    """Preview 8-bit path: matrix, then clamp and quantize to 0-255.

    Swift preview reads matrix+range from nclc/colr/vui (same helper as
    write). No silent 709-video default. ``extractRGB`` later does
    ``u8 / 255``. Write must not use this.
    """
    r, g, b = ycbcr_to_rgb_float(
        y, cb, cr, bit_depth=bit_depth, sample_range=sample_range, matrix=matrix
    )

    def _u8(x: float) -> int:
        return max(0, min(255, int(round(min(max(x, 0.0), 1.0) * 255.0))))

    return (_u8(r), _u8(g), _u8(b))


def preview_u8_promoted_float(y, cb, cr, *, bit_depth: int = 10):
    """What the old write path did: preview 8-bit, then /255 to float."""
    r, g, b = ycbcr_to_preview_u8(y, cb, cr, bit_depth=bit_depth)
    return (r / 255.0, g / 255.0, b / 255.0)


@dataclass(frozen=True)
class BatchClip:
    name: str
    idt: str | None = None
    needs_user_picker: bool = False
    is_stub: bool = False
    detected_curve: str | None = None
    frame_count: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None


@dataclass(frozen=True)
class BatchPlan:
    locked: tuple[BatchClip, ...]
    skipped: tuple[tuple[BatchClip, str], ...]

    @property
    def locked_count(self) -> int:
        return len(self.locked)

    @property
    def pending_count(self) -> int:
        return len(self.skipped)

    @property
    def lock_status_text(self) -> str:
        return LOCK_STATUS_TEMPLATE.format(
            locked=self.locked_count, pending=self.pending_count
        )

    @property
    def shows_process_button(self) -> bool:
        return self.locked_count > 0


def has_locked_idt(clip: BatchClip) -> bool:
    """Processable only when a non-stub paired IDT is locked."""
    if not clip.idt or clip.is_stub or clip.needs_user_picker:
        return False
    return True


def require_write_source_pixels(width: int, height: int) -> None:
    """16384 is a refuse ceiling. Write stays 1:1. Do not scale."""
    if max(int(width), int(height)) > WRITE_LONG_EDGE_CEILING:
        raise ValueError(WRITE_OVERSIZE_CHIP)


def skip_reason(clip: BatchClip) -> str | None:
    """Chinese reason for unlocked / pending clips. None when locked."""
    if has_locked_idt(clip):
        return None
    if clip.detected_curve or clip.is_stub or clip.needs_user_picker or clip.idt:
        return REASON_PICK_PAIRED_IDT
    return REASON_PICK_LOG_GAMUT


def short_export_chip(
    error: str | None = None, *, written: bool = False, cancelled: bool = False
) -> str | None:
    """Per-clip sidebar chip. 已写出代理 on success. Cancelled in-progress is nil."""
    if cancelled:
        return None
    if written:
        return WRITTEN_CHIP
    if not error:
        return None
    if error.startswith("先选择"):
        return error
    if error in (
        FRAME_MISMATCH_CHIP,
        MISSING_FPS_CHIP,
        MISSING_DURATION_CHIP,
        MISSING_YCBCR_TAGS_CHIP,
        WRITE_OVERSIZE_CHIP,
    ):
        return error
    low = error.lower()
    if "decode" in low or "grade" in low or "no pixels" in low:
        return DECODE_FAILED_CHIP
    return WRITE_FAILED_CHIP


def sidebar_status_chip(clip: BatchClip, export_chip: str | None = None) -> str | None:
    """Pending keep skip reasons. Locked rows use the export chip."""
    return skip_reason(clip) or export_chip


def sidebar_export_chips(
    clips: Sequence[BatchClip], report: "BatchWriteReport"
) -> dict[str, str | None]:
    """Sidebar chips after a batch. Cancelled in-progress is not 已写出代理."""
    written = {w.name for w in report.written}
    errors = {e.name: e.error for e in report.errors}
    out: dict[str, str | None] = {}
    for clip in clips:
        reason = skip_reason(clip)
        if reason:
            out[clip.name] = reason
            continue
        if clip.name in written:
            out[clip.name] = WRITTEN_CHIP
        elif clip.name in errors:
            out[clip.name] = short_export_chip(errors[clip.name])
        else:
            out[clip.name] = None
    return out


def clip_sequence_reveal_path(
    clip_name: str,
    dest,
    export_chip: str | None = None,
) -> Path | None:
    """Last dest + ``deliverable_dir_name``. Success chip only.

    Pending / failed / cancelled (not 「已写出代理」) do not reveal.
    """
    if export_chip != WRITTEN_CHIP or dest is None:
        return None
    return Path(dest) / deliverable_dir_name(clip_name)


def plan_locked_batch(clips: Sequence[BatchClip]) -> BatchPlan:
    """Walk locked clips only. Unlocked stay listed; never guessed."""
    locked: list[BatchClip] = []
    skipped: list[tuple[BatchClip, str]] = []
    for clip in clips:
        if has_locked_idt(clip):
            locked.append(clip)
        else:
            skipped.append((clip, skip_reason(clip) or REASON_PICK_LOG_GAMUT))
    return BatchPlan(locked=tuple(locked), skipped=tuple(skipped))


def process_locked_names(clips: Sequence[BatchClip]) -> list[str]:
    """Names the batch would process. Unlocked are omitted, not invented."""
    return [c.name for c in plan_locked_batch(clips).locked]


def _positive_int(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _positive_float(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n <= 0:  # noqa: PLR0124 — NaN check
        return None
    return n


def clip_frame_count(
    clip: BatchClip, rgb_frames: Sequence[np.ndarray] | None = None
) -> tuple[int, str]:
    """Frames for one locked clip. ``known`` / ``duration_fps`` / ``guess``.

    Known: provided frames or ``frame_count``. Else duration×fps.
    Else conservative 24 fps and/or 60 s (said in the estimate note).
    """
    if rgb_frames:
        return max(1, len(rgb_frames)), "known"
    known = _positive_int(clip.frame_count)
    if known is not None:
        return known, "known"
    duration = _positive_float(clip.duration_seconds)
    fps = _positive_float(clip.fps)
    if duration is not None and fps is not None:
        return max(1, int(ceil(duration * fps))), "duration_fps"
    if duration is not None:
        return max(1, int(ceil(duration * CONSERVATIVE_FPS))), "guess"
    if fps is not None:
        return max(1, int(ceil(CONSERVATIVE_SECONDS * fps))), "guess"
    return max(1, int(ceil(CONSERVATIVE_SECONDS * CONSERVATIVE_FPS))), "guess"


def expected_source_frames(clip: BatchClip) -> tuple[int | None, str | None]:
    """Expected EXR count: duration × metadata fps only. Never invent fps.

    Missing fps → 「读不到帧率，未核对」. Missing duration → 「读不到时长，未核对」.
    """
    duration = _positive_float(clip.duration_seconds)
    fps = _positive_float(clip.fps)
    if duration is not None and fps is not None:
        return max(1, int(ceil(duration * fps))), None
    if fps is None:
        return None, MISSING_FPS_CHIP
    return None, MISSING_DURATION_CHIP


def count_proxy_exrs(seq_dir) -> int:
    """How many ``.exr`` files are in the proxy folder. Missing folder → 0."""
    folder = Path(seq_dir)
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".exr")


def frames_count_matches(written: int, expected: int) -> bool:
    """True when counts match. Off-by-one: inclusive last frame on duration×fps.

    AVAsset / container duration × nominal fps (ceil) can land on the last
    sample boundary, so |written − expected| ≤ 1 is accepted when both ≥ 1.
    An empty folder is never a match.
    """
    if written < 1 or expected < 1:
        return False
    return abs(int(written) - int(expected)) <= 1


def verify_locked_proxy_sequence(seq_dir, clip: BatchClip) -> tuple[bool, str | None]:
    """Post-write check. Folder exists, EXRs exist, count matches metadata.

    Success → (True, None) so the caller may mark 已写出代理.
    Failure → (False, Chinese chip). Caller must drop the folder so it is
    not advertised as a finished sequence.
    """
    folder = Path(seq_dir)
    if not folder.is_dir():
        return False, FRAME_MISMATCH_CHIP
    written = count_proxy_exrs(folder)
    expected, timing_err = expected_source_frames(clip)
    if timing_err is not None:
        return False, timing_err
    if expected is None or not frames_count_matches(written, expected):
        return False, FRAME_MISMATCH_CHIP
    return True, None


def clip_pixel_count(
    clip: BatchClip, rgb_frames: Sequence[np.ndarray] | None = None
) -> tuple[int, str]:
    """Pixels per frame. Known size, else conservative 3840×2160."""
    if rgb_frames:
        arr = np.asarray(rgb_frames[0])
        if arr.ndim >= 2:
            return max(1, int(arr.shape[0]) * int(arr.shape[1])), "known"
    width = _positive_int(clip.width)
    height = _positive_int(clip.height)
    if width is not None and height is not None:
        return width * height, "known"
    return CONSERVATIVE_WIDTH * CONSERVATIVE_HEIGHT, "guess"


@dataclass(frozen=True)
class ProxyDiskEstimate:
    """Locked-only dest estimate. Uncompressed float32 RGB EXR."""

    bytes: int
    used_frame_guess: bool
    used_pixel_guess: bool
    used_duration_fps: bool = False

    @property
    def needed_bytes(self) -> int:
        """Estimate plus 10% and a 64 MiB floor so headers do not sneak past."""
        return int(self.bytes * (1.0 + DISK_MARGIN_RATIO)) + DISK_MARGIN_MIN_BYTES

    @property
    def note(self) -> str:
        """Folder-picker / abort suffix. 不是成片. No 精准."""
        size = format_proxy_bytes(self.bytes)
        if self.used_frame_guess:
            return (
                f"约 {size}（{DISK_ESTIMATE_ASSUMPTION}；"
                f"帧数按每秒 {int(CONSERVATIVE_FPS)} 帧估算）"
            )
        if self.used_duration_fps:
            return f"约 {size}（{DISK_ESTIMATE_ASSUMPTION}；帧数按时长×帧率估算）"
        return f"约 {size}（{DISK_ESTIMATE_ASSUMPTION}）"


def format_proxy_bytes(n: int) -> str:
    """Short size for the picker / abort note."""
    n = max(0, int(n))
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    if n >= 1000:
        return f"{n / 1000:.0f} KB"
    return f"{n} B"


def estimate_locked_proxy_bytes(
    clips: Sequence[BatchClip],
    frames: dict[str, np.ndarray | Sequence[np.ndarray]] | None = None,
) -> ProxyDiskEstimate:
    """Sum locked clips only. Pending / unlocked add nothing.

    When ``frames`` is passed (a real write), only clips with RGB frames
    are counted — missing pixels error without a folder and must not
    invent a 4K×60s guess. When ``frames`` is omitted (folder picker),
    use clip timing or the conservative per-second guess.
    """
    frames_supplied = frames is not None
    frames = frames or {}
    total = 0
    used_frame_guess = False
    used_pixel_guess = False
    used_duration_fps = False
    for clip in plan_locked_batch(clips).locked:
        rgb_frames = as_frame_sequence(frames.get(clip.name)) or None
        if frames_supplied and not rgb_frames:
            continue
        n_frames, frame_src = clip_frame_count(clip, rgb_frames)
        n_pixels, pixel_src = clip_pixel_count(clip, rgb_frames)
        total += n_frames * n_pixels * BYTES_PER_EXR_PIXEL
        if frame_src == "guess":
            used_frame_guess = True
        elif frame_src == "duration_fps":
            used_duration_fps = True
        if pixel_src == "guess":
            used_pixel_guess = True
    return ProxyDiskEstimate(
        bytes=int(total),
        used_frame_guess=used_frame_guess,
        used_pixel_guess=used_pixel_guess,
        used_duration_fps=used_duration_fps,
    )


def dest_free_bytes(dest, free_bytes: int | None = None) -> int | None:
    """Volume free space. ``free_bytes`` is the tiny-disk / test mock."""
    if free_bytes is not None:
        return int(free_bytes)
    probe = Path(dest)
    if not probe.exists():
        probe = probe.parent
    if not probe.exists():
        return None
    return int(shutil.disk_usage(probe).free)


def dest_has_space(
    dest,
    needed_bytes: int,
    free_bytes: int | None = None,
) -> bool:
    """False when free space is known and below the estimate. Unknown → True."""
    available = dest_free_bytes(dest, free_bytes)
    if available is None:
        return True
    return available >= int(needed_bytes)


def disk_short_status_text(estimate: ProxyDiskEstimate | None = None) -> str:
    """Abort status. 「磁盘空间不足，未写出」 + honesty. Did not write."""
    note = DISK_SHORT_STATUS_TEMPLATE
    if estimate is not None:
        return f"{DISK_SHORT_STATUS}。{estimate.note}。{HONEST_PROXY_NOTE}。"
    return note


def folder_picker_message_with_estimate(estimate: ProxyDiskEstimate) -> str:
    """Existing picker copy plus the dest-size note. Not a second button."""
    return f"{FOLDER_PICKER_MESSAGE}{estimate.note}。"


def estimate_chip_lit(wb_source: str) -> bool:
    """Estimate chip lights only AFTER confirm (wb_source == estimate)."""
    return wb_source == WB_SOURCE_ESTIMATE


def propose_auto_wb(state: dict, cct: float | None, tint: float = 0.0) -> dict:
    """Propose only. Does not write CAT / wb_source. Empty stays empty."""
    out = dict(state)
    out["auto_wb_cct"] = cct
    out["auto_wb_tint"] = tint
    return out


def confirm_auto_wb(state: dict) -> dict:
    """Write estimate CAT only after confirm. Grey-card wins. No 5600 guess."""
    out = dict(state)
    if out.get("wb_source") == WB_SOURCE_GREY:
        return out
    cct = out.get("auto_wb_cct")
    if cct is None:
        return out
    out["wb_cct"] = cct
    out["wb_tint"] = out.get("auto_wb_tint", 0.0)
    out["wb_source"] = WB_SOURCE_ESTIMATE
    return out


def never_guess_cct(cct: float | None) -> bool:
    """Missing CCT stays empty. Never fill 5600 or 6504."""
    return cct is None


def deliverable_dir_name(clip_name: str) -> str:
    """Sequence folder. ``{stem}_ACES2065-1_proxy`` — proxy, not 成片."""
    return f"{Path(clip_name).stem}{DELIVERABLE_DIR_SUFFIX}"


def sequence_frame_name(index: int) -> str:
    """One sequence frame: ``frame_000000.exr``. Zero-based."""
    return f"{SEQUENCE_FRAME_PREFIX}_{index:0{SEQUENCE_FRAME_WIDTH}d}.exr"


def deliverable_name(clip_name: str, index: int = 0) -> str:
    """Relative path of one proxy sequence frame. Not a lone ``_frame0`` file."""
    return f"{deliverable_dir_name(clip_name)}/{sequence_frame_name(index)}"


def as_frame_sequence(value) -> list[np.ndarray]:
    """Normalize a clip's pixels to a list of RGB frames.

    Accepts one RGB array (still / 1-frame), a sequence of RGB arrays, or
    an ``(N, H, W, 3)`` stack. Empty / missing → no frames.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [np.asarray(frame) for frame in value]
    arr = np.asarray(value)
    if arr.ndim == 4 and arr.shape[-1] == 3:
        return [arr[i] for i in range(arr.shape[0])]
    if arr.size == 0:
        return []
    return [arr]


def processed_status_text(processed: int, skipped: int, dest=None) -> str:
    """「N 条已处理」 is sequence writes / attempts, not preview refresh.

    ``dest`` (short last path component) is appended only for a successful
    write. Cancelled / empty writes omit it so a deleted half-folder is
    not treated as success.
    """
    note = PROCESSED_STATUS_TEMPLATE.format(processed=processed, skipped=skipped)
    if dest is not None:
        note += f" {short_export_path(dest)}"
    return note


def batch_summary_text(
    wrote: int,
    skipped: int,
    failed: int,
    failure_reasons: Sequence[str] | None = None,
    dest=None,
) -> str:
    """Post-batch three buckets. Existing Chinese chips only.

    「N 条已写出代理 / M 条待选跳过 / K 条失败」 plus 失败原因.
    Does not invent fps and does not reuse the dest-disk frame guess.
    """
    note = BATCH_SUMMARY_TEMPLATE.format(
        wrote=int(wrote), skipped=int(skipped), failed=int(failed)
    )
    reasons = [str(item) for item in (failure_reasons or ()) if item]
    if reasons:
        note += f"。{FAILED_BUCKET} " + " ".join(reasons)
    note += f"。{HONEST_PROXY_NOTE}。预览·非成片。已实现（未验证）。"
    if dest is not None and int(wrote) > 0:
        note += f" {short_export_path(dest)}"
    return note


def short_export_path(path) -> str:
    """Short dest shown in status. Parent name, not a deliverable claim."""
    return Path(path).name


def progress_text(
    clip_index: int,
    clip_total: int,
    frame: int | None = None,
    frame_total: int | None = None,
) -> str:
    """Chinese write progress. Example: 「写出代理 2/5 · frame 120」."""
    note = f"{PROGRESS_PREFIX} {clip_index}/{clip_total}"
    if frame is None:
        return note
    if frame_total is not None:
        return f"{note} · frame {frame}/{frame_total}"
    return f"{note} · frame {frame}"


def cancelled_status_text(processed: int, skipped: int) -> str:
    """Cancel status. 已取消 + honesty. Partial output is 不是成片."""
    return CANCELLED_STATUS_TEMPLATE.format(processed=processed, skipped=skipped)


@dataclass(frozen=True)
class ClipWrite:
    name: str
    path: str | None = None
    error: str | None = None
    frame_count: int = 0


@dataclass(frozen=True)
class BatchWriteReport:
    written: tuple[ClipWrite, ...]
    skipped: tuple[tuple[BatchClip, str], ...]
    errors: tuple[ClipWrite, ...]
    cancelled: bool = False
    dest: str | None = None
    disk_short: bool = False
    disk_estimate: ProxyDiskEstimate | None = None
    locked_count: int = 0

    @property
    def processed_count(self) -> int:
        """N in 「N 条已处理」: sequences written + per-clip write errors."""
        return len(self.written) + len(self.errors)

    @property
    def wrote_count(self) -> int:
        """N in 「N 条已写出代理」: write + frame-count verify passed."""
        return len(self.written)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        """K in 「K 条失败」: locked clips that did not become 已写出代理."""
        if self.disk_short:
            return max(int(self.locked_count), 0)
        if self.locked_count:
            return max(0, int(self.locked_count) - len(self.written))
        return len(self.errors)

    @property
    def failure_reason_lines(self) -> tuple[str, ...]:
        """Existing Chinese chips only. No 24×60 dest-disk guess."""
        if self.disk_short:
            return (DISK_SHORT_STATUS,)
        lines = []
        for item in self.errors:
            chip = short_export_chip(item.error) or WRITE_FAILED_CHIP
            lines.append(f"{item.name}：{chip}")
        if self.cancelled:
            lines.append(CANCELLED_NOTE)
        return tuple(lines)

    @property
    def last_reveal_paths(self) -> tuple[str, ...]:
        """Completed ``_proxy`` folders. Empty on cancel (half-folder deleted)."""
        if self.cancelled or self.disk_short:
            return ()
        return self.written_paths

    @property
    def processed_status_text(self) -> str:
        dest = (
            self.dest
            if self.written and not self.cancelled and not self.disk_short
            else None
        )
        return batch_summary_text(
            self.wrote_count,
            self.skipped_count,
            self.failed_count,
            self.failure_reason_lines,
            dest,
        )

    @property
    def written_paths(self) -> tuple[str, ...]:
        return tuple(w.path for w in self.written if w.path)


def process_locked_writes(
    clips: Sequence[BatchClip],
    dest,
    frames: dict[str, np.ndarray | Sequence[np.ndarray]] | None = None,
    graph: SerialGraph | None = None,
    write_fn: Callable[[Path, np.ndarray], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[str], None] | None = None,
    free_bytes: int | None = None,
    ycbcr_tags: dict[str, dict] | None = None,
) -> BatchWriteReport:
    """Write an ACES2065-1 proxy EXR sequence for locked clips only.

    Unlocked / pending stay listed and never produce a folder. A mixed bin
    (some locked, some pending) still writes the locked ones. ``graph`` is
    the existing serial graph (ODT off = ACES2065-1). ``frames`` maps clip
    name → one RGB array or a sequence of arrays. Missing pixels or a write
    failure count as processed (per-clip error), not as a skip reason.

    Output layout (DaVinci image sequence)::

        {stem}_ACES2065-1_proxy/frame_000000.exr
        {stem}_ACES2065-1_proxy/frame_000001.exr
        ...

    This is still a **proxy** sequence (source Y′CbCr → float, not
    preview 8-bit promoted). Not a Rec.709 movie.

    ``should_cancel`` stops the batch. The in-progress ``_proxy`` folder is
    removed (half sequence is not a finished deliverable). Completed clips
    stay. Cancelled clips are not 「已处理」.

    ``free_bytes`` mocks dest volume free space (tiny disk). If free space
    is below the locked-clip estimate + margin, no folder is created and
    no EXR is written.

    ``ycbcr_tags`` (when passed) is the nclc/colr/vui matrix + range for
    each clip. Missing tags fail that clip with
    「无法读取片源 Y′CbCr 矩阵/范围，未写出」 and write no folder.
    No silent BT.709 + video-range default.
    """
    dest = Path(dest)
    plan = plan_locked_batch(clips)
    frames = frames or {}
    estimate = estimate_locked_proxy_bytes(plan.locked, frames=frames)
    # Nothing to write (decode errors only) is not a dest-size abort.
    if estimate.bytes > 0 and not dest_has_space(
        dest, estimate.needed_bytes, free_bytes=free_bytes
    ):
        return BatchWriteReport(
            written=(),
            skipped=plan.skipped,
            errors=(),
            dest=str(dest),
            disk_short=True,
            disk_estimate=estimate,
            locked_count=len(plan.locked),
        )
    dest.mkdir(parents=True, exist_ok=True)
    graph = graph if graph is not None else SerialGraph()
    writer = write_fn or (lambda path, rgb: write_rgb_exr(path, rgb))

    written: list[ClipWrite] = []
    errors: list[ClipWrite] = []
    cancelled = False
    clip_total = len(plan.locked)
    for clip_index, clip in enumerate(plan.locked, start=1):
        if should_cancel and should_cancel():
            cancelled = True
            break
        seq_dir = dest / deliverable_dir_name(clip.name)
        rgb_frames = as_frame_sequence(frames.get(clip.name))
        if not rgb_frames:
            errors.append(ClipWrite(name=clip.name, error="no pixels"))
            continue
        if not clip.idt:
            errors.append(ClipWrite(name=clip.name, error="no IDT"))
            continue
        try:
            for rgb in rgb_frames:
                arr = np.asarray(rgb)
                require_write_source_pixels(arr.shape[1], arr.shape[0])
        except ValueError as exc:
            errors.append(ClipWrite(name=clip.name, error=str(exc)))
            continue
        if ycbcr_tags is not None:
            try:
                require_source_ycbcr_tags(ycbcr_tags.get(clip.name))
            except ValueError as exc:
                errors.append(ClipWrite(name=clip.name, error=str(exc)))
                continue
        try:
            if seq_dir.exists():
                shutil.rmtree(seq_dir)
            seq_dir.mkdir(parents=True, exist_ok=True)
            if on_progress:
                on_progress(progress_text(clip_index, clip_total))
            frame_total = len(rgb_frames)
            # Clip-constant CAT / exposure. One IDT+WB pass per write frame.
            # Never graph.apply — that bakes preview ODT (709 / HLG / PQ).
            write_setup = graph.ap0_write_setup()
            for index, rgb in enumerate(rgb_frames):
                if should_cancel and should_cancel():
                    if seq_dir.exists():
                        shutil.rmtree(seq_dir)
                    cancelled = True
                    break
                out = seq_dir / sequence_frame_name(index)
                linear = graph.apply_ap0(rgb, clip.idt, setup=write_setup)
                writer(out, np.asarray(linear, dtype=np.float32))
                if write_fn is None and not out.is_file():
                    raise OSError("write produced no file")
                if on_progress:
                    on_progress(
                        progress_text(
                            clip_index, clip_total, index + 1, frame_total
                        )
                    )
            if cancelled:
                break
            ok, verify_err = verify_locked_proxy_sequence(seq_dir, clip)
            if not ok:
                if seq_dir.exists():
                    shutil.rmtree(seq_dir)
                errors.append(
                    ClipWrite(name=clip.name, error=verify_err or FRAME_MISMATCH_CHIP)
                )
                continue
            written.append(
                ClipWrite(name=clip.name, path=str(seq_dir), frame_count=len(rgb_frames))
            )
        except Exception as exc:  # noqa: BLE001 — per-clip error, keep going
            if seq_dir.exists():
                shutil.rmtree(seq_dir)
            errors.append(ClipWrite(name=clip.name, error=str(exc)))
    return BatchWriteReport(
        written=tuple(written),
        skipped=plan.skipped,
        errors=tuple(errors),
        cancelled=cancelled,
        dest=str(dest),
        locked_count=len(plan.locked),
    )
