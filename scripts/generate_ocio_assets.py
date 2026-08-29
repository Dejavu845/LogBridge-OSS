#!/usr/bin/env python3
"""Generate handwritten LUTs/matrices and ocio/config.ocio.

config.ocio names OCIO BuiltinTransform styles for IDTs that have them.
Only F-Log2, N-Log, C-Log2 (BT.2020 pair), C-Log3 (BT.2020 pair), D-Log,
and the Rec.709 OETF LUT are generated from color/. Do not emit homemade
LogC4 / S-Log3 / V-Log / Log3G10 / Apple Log LUTs or DWG matrices.
C-Log2+Cinema Gamut keeps the full Builtin (no homemade Cinema Gamut LUT).
LogC3 EI800+AWG3 uses Builtin ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1.
Apple Log 2 uses CURVE - APPLE_LOG_to_LINEAR + Apple Wide Gamut matrix.
There is no APPLE_LOG2 Builtin.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from color.curves import (  # noqa: E402
    clog2_to_linear,
    clog3_to_linear,
    dlog_to_linear,
    flog2_to_linear,
    nlog_normalized_to_linear,
)
from color.gamuts import camera_to_aces2065_matrix  # noqa: E402
from color.rec709 import rec709_oetf  # noqa: E402

LUT_DIR = ROOT / "ocio" / "luts"
MTX_DIR = ROOT / "ocio" / "matrices"
CONFIG = ROOT / "ocio" / "config.ocio"
LUT_SIZE = 4096


def write_spi1d(path: Path, values: np.ndarray, from_min=0.0, from_max=1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Version 1",
        f"From {from_min:.10f} {from_max:.10f}",
        f"Length {len(values)}",
        "Components 1",
        "{",
    ]
    for v in values:
        lines.append(f"  {float(v):.10e}")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_spimtx(path: Path, m: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(3):
        rows.append(f"{m[i, 0]:.12f} {m[i, 1]:.12f} {m[i, 2]:.12f} 0")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def ocio_matrix_16(m3: np.ndarray) -> str:
    m = np.eye(4)
    m[:3, :3] = m3
    return ", ".join(f"{v:.10f}" for v in m.reshape(-1))


def generate_luts() -> None:
    x = np.linspace(0.0, 1.0, LUT_SIZE)
    # Handwritten only: F-Log2 / N-Log have no Builtin. Rec.709 OETF for the ODT.
    # Mac OCIO uses BuiltinTransform for LogC4 / S-Log3 / V-Log / Log3G10.
    # Linux pytest uses color/ reference encode/decode for 18% codes only.
    write_spi1d(LUT_DIR / "FLog2_to_lin.spi1d", flog2_to_linear(x))
    write_spi1d(LUT_DIR / "NLog_to_lin.spi1d", nlog_normalized_to_linear(x))
    # C-Log2+BT.2020 / C-Log3+BT.2020 have no full IDT Builtin.
    # C-Log2+CG / C-Log3+CG / Apple Log use Builtins.
    write_spi1d(LUT_DIR / "CLog2_to_lin.spi1d", clog2_to_linear(x))
    write_spi1d(LUT_DIR / "CLog3_to_lin.spi1d", clog3_to_linear(x))
    write_spi1d(LUT_DIR / "DLog_to_lin.spi1d", dlog_to_linear(x))
    write_spi1d(LUT_DIR / "lin_to_Rec709_oetf.spi1d", rec709_oetf(x))


def generate_matrices() -> None:
    write_spimtx(MTX_DIR / "BT2020_to_AP0.spimtx", camera_to_aces2065_matrix("BT2020"))
    write_spimtx(MTX_DIR / "DGamut_to_AP0.spimtx", camera_to_aces2065_matrix("DGamut"))
    write_spimtx(
        MTX_DIR / "AppleWideGamut_to_AP0.spimtx",
        camera_to_aces2065_matrix("AppleWideGamut"),
    )


def builtin_cs(name: str, style: str, description: str) -> str:
    return f"""  - !<ColorSpace>
    name: {name}
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      {description}
      OCIO BuiltinTransform: {style}
      Status: implemented (unverified). Not marked supported.
    isdata: false
    allocation: uniform
    to_scene_reference: !<BuiltinTransform> {{style: {style}}}
"""


def write_config() -> None:
    m_2020 = ocio_matrix_16(camera_to_aces2065_matrix("BT2020"))
    m_dgamut = ocio_matrix_16(camera_to_aces2065_matrix("DGamut"))
    m_apple_wg = ocio_matrix_16(camera_to_aces2065_matrix("AppleWideGamut"))
    text = f"""ocio_profile_version: 2.2

# LogBridge M1 + M2-start OCIO config.
# scene_linear / reference: ACES2065-1 (AP0).
# color_timing: ACEScct (Academy grading). WB / preview sit here.
# Do NOT use DaVinci Wide Gamut Intermediate as the internal reference.
#
# IDTs with a standard Builtin use BuiltinTransform (Mac OCIO).
# F-Log2, N-Log, C-Log2+BT.2020, C-Log3+BT.2020, D-Log have no full IDT Builtin.
# C-Log2+Cinema Gamut / C-Log3+Cinema Gamut / Apple Log 1 / LogC3 EI800+AWG3
# use BuiltinTransform. Apple Log 2: CURVE - APPLE_LOG_to_LINEAR + AWG matrix.
# No APPLE_LOG2 Builtin.
# Rec.2100 HLG / PQ use ACES Output Transform / BT.2100 BuiltinTransform
# (no homemade HLG/PQ curve). Rec.709 stays preview-only DIY OETF.
# Python color/ calls Builtins when PyOpenColorIO is importable; otherwise
# it uses matching white-paper reference implementations for IDT 18% tests.
# HDR apply requires OCIO. All paths: implemented (unverified). Not supported.

environment: {{}}

search_path: luts:matrices

roles:
  scene_linear: ACES2065-1
  color_timing: ACEScct
  compositing_log: ACEScct
  default: ACES2065-1
  data: Raw
  reference: ACES2065-1
  rendering: ACES2065-1
  color_picking: Rec.709
  rec709: Rec.709
  matte_paint: ACEScct
  texture_paint: ACES2065-1
  aces_interchange: ACES2065-1
  cie_xyz_d65_interchange: CIE-XYZ-D65

file_rules:
  - !<Rule> {{name: Default, colorspace: default}}

displays:
  Rec.709:
    - !<View> {{name: Rec.709, colorspace: Rec.709}}
  Rec.2100-HLG:
    - !<View> {{name: Rec.2100-HLG, colorspace: Rec.2100-HLG}}
  Rec.2100-PQ:
    - !<View> {{name: Rec.2100-PQ, colorspace: Rec.2100-PQ}}
  ACEScct:
    - !<View> {{name: ACEScct, colorspace: ACEScct}}

active_displays: [Rec.709]
active_views: [Rec.709]

colorspaces:
  - !<ColorSpace>
    name: Raw
    family: Data
    isdata: true
    allocation: uniform

  - !<ColorSpace>
    name: ACES2065-1
    family: ACES
    equalitygroup: ""
    bitdepth: 32f
    aliases: [Linear AP0]
    isdata: false
    allocation: lg2
    allocationvars: [-8, 8, 0.00390625]
    description: |
      ACES2065-1 (AP0 scene-linear). LogBridge M1 interchange / scene_linear.
      Every IDT lands here. WB CAT runs in this AP0 linear space.

  - !<ColorSpace>
    name: ACEScg
    family: ACES
    bitdepth: 32f
    isdata: false
    description: Linear AP1 (ACEScg). Scene-linear form of ACEScct.
    to_scene_reference: !<BuiltinTransform> {{style: ACEScg_to_ACES2065-1}}

  - !<ColorSpace>
    name: ACEScct
    family: ACES
    bitdepth: 32f
    isdata: false
    description: |
      ACEScct (AP1 log). Timeline / grading encode. Rec.709 is preview only.
      Implemented (unverified). White balance is ACES2065-1 (AP0) scene-linear, never log.
    to_scene_reference: !<BuiltinTransform> {{style: ACEScct_to_ACES2065-1}}

  - !<ColorSpace>
    name: CIE-XYZ-D65
    family: Working
    bitdepth: 32f
    isdata: false
    allocation: uniform
    from_scene_reference: !<BuiltinTransform> {{style: UTILITY - ACES-AP0_to_CIE-XYZ-D65_BFD}}

  - !<ColorSpace>
    name: Rec.709
    family: Output
    bitdepth: 32f
    isdata: false
    description: |
      Rec.709 primaries + BT.709 OETF. Preview framebuffers MUST be tagged
      Rec.709 (CGColorSpace.itur_709 / Metal layer.colorspace). Never blit
      Rec.709 pixels into an untagged Display P3 surface.
      Simple ODT, no RRT/DRT. Implemented (unverified).
    from_scene_reference: !<GroupTransform>
      children:
        - !<BuiltinTransform> {{style: ACEScg_to_ACES2065-1, direction: inverse}}
        - !<BuiltinTransform> {{style: UTILITY - ACES-AP1_to_LINEAR-REC709_BFD}}
        - !<FileTransform> {{src: lin_to_Rec709_oetf.spi1d, interpolation: linear}}
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: lin_to_Rec709_oetf.spi1d, interpolation: linear, inverse: true}}
        - !<BuiltinTransform> {{style: UTILITY - ACES-AP1_to_LINEAR-REC709_BFD, direction: inverse}}
        - !<BuiltinTransform> {{style: ACEScg_to_ACES2065-1}}

  - !<ColorSpace>
    name: Rec.2100-HLG
    family: Output
    bitdepth: 32f
    isdata: false
    aliases: ["Output - Rec.2100-HLG - 1000 nit", "BT.2100 HLG"]
    description: |
      Rec.2100 HLG via ACES Output Transform / BT.2100 (BuiltinTransform).
      ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1
      then DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG
      config-aces: Output - Rec.2100-HLG - 1000 nit
      ACES 2.0 alias (if registry has it):
      ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-HLG-1000nit_2.0
      Implemented (unverified). Not supported. Not 一键精准.
      No homemade HLG curve.
    from_scene_reference: !<GroupTransform>
      children:
        - !<BuiltinTransform> {{style: ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1}}
        - !<BuiltinTransform> {{style: DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG}}

  - !<ColorSpace>
    name: Rec.2100-PQ
    family: Output
    bitdepth: 32f
    isdata: false
    aliases: ["Output - Rec.2100-Rec.2020-ST2084 - 1000 nit", "BT.2100 PQ"]
    description: |
      Rec.2100 PQ via ACES Output Transform / BT.2100 (BuiltinTransform).
      ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-ST2084_1.1
      then DISPLAY - CIE-XYZ-D65_to_REC.2100-REC2020-ST2084
      config-aces: Output - Rec.2100-Rec.2020-ST2084 - 1000 nit
      ACES 2.0 alias (if registry has it):
      ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - Rec.2100-Rec.2020-ST2084-1000nit_2.0
      Implemented (unverified). Not supported. Not 一键精准.
      No homemade PQ / ST.2084 curve.
    from_scene_reference: !<GroupTransform>
      children:
        - !<BuiltinTransform> {{style: ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-ST2084_1.1}}
        - !<BuiltinTransform> {{style: DISPLAY - CIE-XYZ-D65_to_REC.2100-REC2020-ST2084}}

{builtin_cs(
    "ARRI LogC4 AWG4",
    "ARRI_LOGC4_to_ACES2065-1",
    "ARRI LogC4 + AWG4. EI-independent. Do not keep handwritten a/b/c + homemade AWG4 matrix.",
)}
{builtin_cs(
    "ARRI LogC3 EI800 AWG3",
    "ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1",
    "ARRI LogC3 EI800 + ALEXA Wide Gamut 3 only. Not a generic LogC3. EI>1600 has no closed form. 18% grey encodes to 0.391. ACES CSC / ARRI 2017-03.",
)}
{builtin_cs(
    "Sony S-Log3 S-Gamut3",
    "SONY_SLOG3-SGAMUT3_to_ACES2065-1",
    "Sony S-Log3 + S-Gamut3. Do NOT default S-Log3 to S-Gamut3.Cine. User/metadata picks the gamut.",
)}
{builtin_cs(
    "Sony S-Log3 S-Gamut3.Cine",
    "SONY_SLOG3-SGAMUT3.CINE_to_ACES2065-1",
    "Sony S-Log3 + S-Gamut3.Cine. Separate IDT; never the implicit S-Log3 default.",
)}
{builtin_cs(
    "Sony S-Log3 S-Gamut3 Venice",
    "SONY_SLOG3-SGAMUT3-VENICE_to_ACES2065-1",
    "Venice body only. Never a silent S-Log3 default.",
)}
{builtin_cs(
    "Sony S-Log3 S-Gamut3.Cine Venice",
    "SONY_SLOG3-SGAMUT3.CINE-VENICE_to_ACES2065-1",
    "Venice body + S-Gamut3.Cine only. Never a silent default.",
)}
{builtin_cs(
    "Panasonic V-Log V-Gamut",
    "PANASONIC_VLOG-VGAMUT_to_ACES2065-1",
    "Panasonic V-Log + V-Gamut. Do not keep handwritten cut2/b/c/d as the OCIO IDT.",
)}
{builtin_cs(
    "RED Log3G10 REDWideGamutRGB",
    "RED_LOG3G10-RWG_to_ACES2065-1",
    "RED Log3G10 + REDWideGamutRGB. 18% grey maps to 1/3. Do not keep handwritten a/b/c/g as the OCIO IDT.",
)}
  - !<ColorSpace>
    name: Fujifilm F-Log2 BT.2020
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      Fujifilm F-Log2 (Data Sheet Ver.1.0, a=5.555556) + BT.2020 / D65.
      No standard OCIO Builtin (do not use F-Log1 spi1d). 18% grey is 400/1023.
      Status: implemented (unverified). Not marked supported.
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: FLog2_to_lin.spi1d, interpolation: linear}}
        - !<MatrixTransform> {{matrix: [{m_2020}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_2020}], inverse: true}}
        - !<FileTransform> {{src: FLog2_to_lin.spi1d, interpolation: linear, inverse: true}}

  - !<ColorSpace>
    name: Nikon N-Log BT.2020
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      Nikon N-Log + BT.2020 / D65. White-paper x is 10-bit code 0-1023.
      This LUT is sampled on 0-1 = code/1023 so OCIO buffers stay normalized;
      the curve itself is evaluated at x*1023. Do not divide by 1023 in the Python API.
      Decode: x<452 -> (x/650)^3-0.0075; else exp((x-619)/150) (natural exp).
      452 is the breakpoint, NOT 18% grey (~372).
      Status: implemented (unverified). Not marked supported.
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: NLog_to_lin.spi1d, interpolation: linear}}
        - !<MatrixTransform> {{matrix: [{m_2020}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_2020}], inverse: true}}
        - !<FileTransform> {{src: NLog_to_lin.spi1d, interpolation: linear, inverse: true}}

{builtin_cs(
    "Canon C-Log2 Cinema Gamut",
    "CANON_CLOG2-CGAMUT_to_ACES2065-1",
    "Canon C-Log2 + Cinema Gamut / D65. Never the silent C-Log2 default. Negative toe: OCIO CURVE - CANON_CLOG2_to_LINEAR / ACES CTL. Do not invent a mirrored toe.",
)}
  - !<ColorSpace>
    name: Canon C-Log2 BT.2020
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      Canon C-Log2 + BT.2020 / D65. No full IDT Builtin (C-Log2+Cinema Gamut has one).
      Handwritten C-Log2 curve + BT.2020→AP0 if no Builtin (prefer CURVE - CANON_CLOG2_to_LINEAR).
      Never the silent C-Log2 default. Status: implemented (unverified).
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: CLog2_to_lin.spi1d, interpolation: linear}}
        - !<MatrixTransform> {{matrix: [{m_2020}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_2020}], inverse: true}}
        - !<FileTransform> {{src: CLog2_to_lin.spi1d, interpolation: linear, inverse: true}}

{builtin_cs(
    "Canon C-Log3 Cinema Gamut",
    "CANON_CLOG3-CGAMUT_to_ACES2065-1",
    "Canon C-Log3 + Cinema Gamut / D65. Never the silent C-Log3 default. User/metadata picks the gamut.",
)}
{builtin_cs(
    "Apple Log BT.2020",
    "APPLE_LOG_to_ACES2065-1",
    "Apple Log 1 + BT.2020 / D65. Apple Log 2 is a separate AWG pair.",
)}
  - !<ColorSpace>
    name: Apple Log 2 Apple Wide Gamut
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      Apple Log 2 + Apple Wide Gamut (ACES CSC.Apple.AppleLog2_to_ACES.ctl).
      Curve is the same as Apple Log 1. No APPLE_LOG2 Builtin — do not claim one.
      Prefer CURVE - APPLE_LOG_to_LINEAR + AWG→AP0. Not BT.2020.
      Status: implemented (unverified). Not marked supported.
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<BuiltinTransform> {{style: CURVE - APPLE_LOG_to_LINEAR}}
        - !<MatrixTransform> {{matrix: [{m_apple_wg}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_apple_wg}], inverse: true}}
        - !<BuiltinTransform> {{style: CURVE - APPLE_LOG_to_LINEAR, direction: inverse}}

  - !<ColorSpace>
    name: Canon C-Log3 BT.2020
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      Canon C-Log3 + BT.2020 / D65. No full IDT Builtin (C-Log3+Cinema Gamut has one).
      Curve is ACES / Canon v1.2 three-segment (prefer CURVE - CANON_CLOG3_to_LINEAR when applying via OCIO).
      Never the silent C-Log3 default. Status: implemented (unverified).
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: CLog3_to_lin.spi1d, interpolation: linear}}
        - !<MatrixTransform> {{matrix: [{m_2020}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_2020}], inverse: true}}
        - !<FileTransform> {{src: CLog3_to_lin.spi1d, interpolation: linear, inverse: true}}

  - !<ColorSpace>
    name: DJI D-Log D-Gamut
    family: Input/LogBridge
    equalitygroup: ""
    bitdepth: 32f
    description: |
      DJI D-Log + D-Gamut (2017-10-10 white paper). No standard OCIO Builtin.
      D-Log M is unsupported. Status: implemented (unverified). Not marked supported.
    isdata: false
    allocation: uniform
    to_scene_reference: !<GroupTransform>
      children:
        - !<FileTransform> {{src: DLog_to_lin.spi1d, interpolation: linear}}
        - !<MatrixTransform> {{matrix: [{m_dgamut}]}}
    from_scene_reference: !<GroupTransform>
      children:
        - !<MatrixTransform> {{matrix: [{m_dgamut}], inverse: true}}
        - !<FileTransform> {{src: DLog_to_lin.spi1d, interpolation: linear, inverse: true}}

  # --- Explicitly unsupported (not implemented) ---
  - !<ColorSpace>
    name: DJI D-Log M (unsupported)
    family: Input/Stub
    bitdepth: 32f
    isdata: false
    description: UNSUPPORTED. D-Log M is not the 2017 D-Log + D-Gamut IDT.
"""
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(text, encoding="utf-8")


def main() -> None:
    generate_luts()
    generate_matrices()
    write_config()
    print(f"Wrote LUTs in {LUT_DIR}")
    print(f"Wrote matrices in {MTX_DIR}")
    print(f"Wrote {CONFIG}")


if __name__ == "__main__":
    main()
