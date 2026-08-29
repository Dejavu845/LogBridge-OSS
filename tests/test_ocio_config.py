"""OCIO config presence, BuiltinTransform names, and handwritten-only LUTs."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "ocio" / "config.ocio"


def test_config_exists():
    assert CONFIG.is_file()
    text = CONFIG.read_text(encoding="utf-8")
    assert "ocio_profile_version" in text


def test_roles_aces_not_dwg():
    text = CONFIG.read_text(encoding="utf-8")
    assert "scene_linear: ACES2065-1" in text
    assert "color_timing: ACEScct" in text
    assert "reference: ACES2065-1" in text
    assert "Linear DWG" not in text
    assert "DaVinci Intermediate" not in text
    assert "rec709:" in text or "color_picking:" in text


def test_six_idts_declared():
    text = CONFIG.read_text(encoding="utf-8")
    for name in (
        "ARRI LogC4 AWG4",
        "Sony S-Log3 S-Gamut3",
        "Sony S-Log3 S-Gamut3.Cine",
        "Panasonic V-Log V-Gamut",
        "Fujifilm F-Log2 BT.2020",
        "Nikon N-Log BT.2020",
        "RED Log3G10 REDWideGamutRGB",
        "Canon C-Log2 Cinema Gamut",
        "Canon C-Log2 BT.2020",
        "Canon C-Log3 Cinema Gamut",
        "Canon C-Log3 BT.2020",
        "Apple Log BT.2020",
        "Apple Log 2 Apple Wide Gamut",
        "ARRI LogC3 EI800 AWG3",
        "DJI D-Log D-Gamut",
    ):
        assert name in text


def test_builtin_styles_named():
    text = CONFIG.read_text(encoding="utf-8")
    for style in (
        "ARRI_LOGC4_to_ACES2065-1",
        "SONY_SLOG3-SGAMUT3_to_ACES2065-1",
        "SONY_SLOG3-SGAMUT3.CINE_to_ACES2065-1",
        "SONY_SLOG3-SGAMUT3-VENICE_to_ACES2065-1",
        "SONY_SLOG3-SGAMUT3.CINE-VENICE_to_ACES2065-1",
        "PANASONIC_VLOG-VGAMUT_to_ACES2065-1",
        "RED_LOG3G10-RWG_to_ACES2065-1",
        "CANON_CLOG2-CGAMUT_to_ACES2065-1",
        "CANON_CLOG3-CGAMUT_to_ACES2065-1",
        "APPLE_LOG_to_ACES2065-1",
        "ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1",
        "ACEScct_to_ACES2065-1",
        "ACEScg_to_ACES2065-1",
    ):
        assert f"style: {style}" in text


def test_sony_does_not_default_cine():
    text = CONFIG.read_text(encoding="utf-8")
    assert "Sony S-Log3 S-Gamut3.Cine" in text
    assert "Sony S-Log3 S-Gamut3" in text
    assert "name: Sony S-Log3 S-Gamut3\n" in text or 'name: "Sony S-Log3 S-Gamut3"' in text
    assert "Never a silent" in text or "never the implicit" in text.lower() or "Never a silent S-Log3 default" in text


def test_nlog_comment_about_10bit():
    text = CONFIG.read_text(encoding="utf-8")
    assert "1023" in text
    assert "N-Log" in text
    assert "452" in text


def test_canon_uses_ocio_builtin_not_invented_toe():
    text = CONFIG.read_text(encoding="utf-8")
    assert "CURVE - CANON_CLOG2_to_LINEAR" in text
    assert "CANON_CLOG2-CGAMUT_to_ACES2065-1" in text
    assert "CANON_CLOG3-CGAMUT_to_ACES2065-1" in text
    assert "Do not invent a mirrored toe" in text
    assert "name: Canon C-Log2 (stub)" not in text


def test_unsupported_idts_named():
    text = CONFIG.read_text(encoding="utf-8")
    assert "DJI D-Log M (unsupported)" in text
    assert "Apple Log 2 (unsupported)" not in text
    assert "ARRI LogC3 (unsupported)" not in text
    assert "style: APPLE_LOG2" not in text
    assert "Apple Wide Gamut" in text
    assert "EI800" in text
    logc3 = text.split("name: ARRI LogC3 EI800 AWG3")[1].split("name:")[0]
    assert "EI800" in logc3
    apple2 = text.split("name: Apple Log 2 Apple Wide Gamut")[1].split("name:")[0]
    assert "Apple Wide Gamut" in apple2
    assert "style: APPLE_LOG2" not in apple2
    assert "Apple Log 2 BT.2020" not in text
    assert "not BT.2020" in apple2.lower() or "Not BT.2020" in apple2


def test_handwritten_luts_only_for_no_builtin():
    luts = ROOT / "ocio" / "luts"
    assert (luts / "FLog2_to_lin.spi1d").is_file()
    assert (luts / "NLog_to_lin.spi1d").is_file()
    assert (luts / "CLog2_to_lin.spi1d").is_file()
    assert (luts / "CLog3_to_lin.spi1d").is_file()
    assert (luts / "DLog_to_lin.spi1d").is_file()
    # Builtin-replaced homemade LUTs must not remain.
    for name in (
        "LogC4_to_lin.spi1d",
        "SLog3_to_lin.spi1d",
        "VLog_to_lin.spi1d",
        "Log3G10_to_lin.spi1d",
        "AppleLog_to_lin.spi1d",
    ):
        assert not (luts / name).is_file(), name
