"""Scanline OpenEXR container (RGB float32). No color math.

Writes / reads uncompressed single-part scanline EXR so Linux tests can
assert files on disk without OpenEXR/ImageIO. Pixel values are stored as
given — this module does not apply an IDT, CAT, exposure, or ODT.

The header writes OpenEXR ``chromaticities`` for SMPTE ST 2065-1 / ACES
AP0 primaries and ACES white. It does not write ``acesImageContainerFlag``.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

EXR_MAGIC = 20000630
EXR_VERSION_SCANLINE = 2  # single-part scanline; not tiled / multipart
PIXEL_FLOAT = 2

# SMPTE ST 2065-1 / ACES AP0 primaries + ACES white (not D65, not AP1).
# OpenEXR chromaticities: red.xy, green.xy, blue.xy, white.xy
ACES2065_1_CHROMATICITIES = (
    0.73470,
    0.26530,
    0.00000,
    1.00000,
    0.00010,
    -0.07700,
    0.32168,
    0.33767,
)


def _attr(name: str, typ: str, payload: bytes) -> bytes:
    return name.encode("ascii") + b"\x00" + typ.encode("ascii") + b"\x00" + struct.pack(
        "<i", len(payload)
    ) + payload


def _chlist_channel(name: str) -> bytes:
    # name, pixelType FLOAT, pLinear, reserved[3], xSampling, ySampling
    return (
        name.encode("ascii")
        + b"\x00"
        + struct.pack("<i", PIXEL_FLOAT)
        + bytes([0, 0, 0, 0])
        + struct.pack("<ii", 1, 1)
    )


def as_rgb_image(rgb) -> np.ndarray:
    """Normalize RGB to (H, W, 3) float32. Vectors become 1×1."""
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim == 1 and arr.shape[0] == 3:
        return arr.reshape(1, 1, 3)
    if arr.ndim == 2 and arr.shape[-1] == 3:
        return arr.reshape(1, arr.shape[0], 3)
    if arr.ndim == 3 and arr.shape[-1] == 3:
        return np.ascontiguousarray(arr)
    raise ValueError(f"RGB must be (..., 3), got {arr.shape}")


def write_rgb_exr_sequence(directory, frames, name_prefix: str = "frame") -> list[Path]:
    """Write ``frame_000000.exr`` … per RGB array. Container only — no color."""
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, rgb in enumerate(frames):
        written.append(write_rgb_exr(dest / f"{name_prefix}_{index:06d}.exr", rgb))
    return written


def _chromaticities_payload(
    values: tuple[float, ...] = ACES2065_1_CHROMATICITIES,
) -> bytes:
    return struct.pack("<8f", *values)


def write_rgb_exr(path, rgb) -> Path:
    """Write uncompressed RGB float32 scanline EXR. Container only."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = as_rgb_image(rgb)
    height, width, _ = img.shape
    if width < 1 or height < 1:
        raise ValueError("EXR image must have positive width and height")

    channels = _chlist_channel("B") + _chlist_channel("G") + _chlist_channel("R") + b"\x00"
    box = struct.pack("<iiii", 0, 0, width - 1, height - 1)
    header = b"".join(
        [
            _attr("channels", "chlist", channels),
            _attr(
                "chromaticities",
                "chromaticities",
                _chromaticities_payload(),
            ),
            _attr("compression", "compression", struct.pack("<B", 0)),
            _attr("dataWindow", "box2i", box),
            _attr("displayWindow", "box2i", box),
            _attr("lineOrder", "lineOrder", struct.pack("<B", 0)),
            _attr("pixelAspectRatio", "float", struct.pack("<f", 1.0)),
            _attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0)),
            _attr("screenWindowWidth", "float", struct.pack("<f", 1.0)),
            b"\x00",
        ]
    )

    scanlines: list[bytes] = []
    for y in range(height):
        row = img[y]
        planar = (
            np.ascontiguousarray(row[:, 2]).tobytes()
            + np.ascontiguousarray(row[:, 1]).tobytes()
            + np.ascontiguousarray(row[:, 0]).tobytes()
        )
        scanlines.append(struct.pack("<iI", y, len(planar)) + planar)

    offset_table_size = height * 8
    data_start = 8 + len(header) + offset_table_size
    offsets = []
    pos = data_start
    for payload in scanlines:
        offsets.append(pos)
        pos += len(payload)

    with dest.open("wb") as fh:
        fh.write(struct.pack("<I", EXR_MAGIC))
        fh.write(struct.pack("<I", EXR_VERSION_SCANLINE))
        fh.write(header)
        for off in offsets:
            fh.write(struct.pack("<Q", off))
        for payload in scanlines:
            fh.write(payload)
    return dest


def _parse_exr_header(data: bytes) -> tuple[dict[str, tuple[str, bytes]], int]:
    magic, version = struct.unpack_from("<II", data, 0)
    if magic != EXR_MAGIC:
        raise ValueError(f"Not an OpenEXR file (magic={magic})")
    if version & 0x200 or version & 0x2000:
        raise ValueError("Tiled / multipart EXR is not read here")
    pos = 8
    attrs: dict[str, tuple[str, bytes]] = {}
    while pos < len(data):
        if data[pos] == 0:
            pos += 1
            break
        name_end = data.index(b"\x00", pos)
        name = data[pos:name_end].decode("ascii")
        pos = name_end + 1
        type_end = data.index(b"\x00", pos)
        typ = data[pos:type_end].decode("ascii")
        pos = type_end + 1
        (size,) = struct.unpack_from("<i", data, pos)
        pos += 4
        attrs[name] = (typ, data[pos : pos + size])
        pos += size
    return attrs, pos


def read_exr_attributes(path) -> dict[str, tuple[str, bytes]]:
    """OpenEXR header attributes as ``name -> (type, payload)``."""
    return _parse_exr_header(Path(path).read_bytes())[0]


def read_exr_chromaticities(path) -> tuple[float, ...]:
    """Read OpenEXR ``chromaticities`` (8 little-endian floats)."""
    attrs = read_exr_attributes(path)
    entry = attrs.get("chromaticities")
    if not entry:
        raise ValueError("EXR missing chromaticities")
    typ, payload = entry
    if typ != "chromaticities" or len(payload) != 32:
        raise ValueError(f"Bad chromaticities attribute ({typ!r}, {len(payload)} bytes)")
    return struct.unpack("<8f", payload)


def read_rgb_exr(path) -> np.ndarray:
    """Read an uncompressed RGB float32 EXR written by ``write_rgb_exr``."""
    data = Path(path).read_bytes()
    attrs, pos = _parse_exr_header(data)

    box = attrs.get("dataWindow", (None, None))[1]
    if not box or len(box) < 16:
        raise ValueError("EXR missing dataWindow")
    xmin, ymin, xmax, ymax = struct.unpack("<iiii", box[:16])
    width = xmax - xmin + 1
    height = ymax - ymin + 1
    pos += height * 8  # skip offset table
    img = np.empty((height, width, 3), dtype=np.float32)
    row_bytes = width * 4
    for _ in range(height):
        y, nbytes = struct.unpack_from("<iI", data, pos)
        pos += 8
        planar = data[pos : pos + nbytes]
        pos += nbytes
        b = np.frombuffer(planar[0:row_bytes], dtype=np.float32)
        g = np.frombuffer(planar[row_bytes : 2 * row_bytes], dtype=np.float32)
        r = np.frombuffer(planar[2 * row_bytes : 3 * row_bytes], dtype=np.float32)
        yi = y - ymin
        img[yi, :, 0] = r
        img[yi, :, 1] = g
        img[yi, :, 2] = b
    return img
