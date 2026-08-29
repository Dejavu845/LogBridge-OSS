"""Detection order: metadata -> filename/model -> user picker.

Never trust QuickTime nclc. Never default S-Log3 to S-Gamut3.Cine.
"""

from color.detect import (
    CLOG2_PAIRS,
    CLOG3_PAIRS,
    SLOG3_PAIRS,
    SLOG3_VENICE_PAIRS,
    can_one_click_process,
    can_one_click_process_all,
    detect_clip,
    detect_from_filename,
    detect_from_metadata,
    picker_labels,
    picker_pairs,
    picker_pairs_for_detection,
)
from color.gamuts import VENICE_IDTS as GAMUT_VENICE


def test_arri_mxf_metadata_wins():
    d = detect_clip(
        "clip.mov",
        metadata={"arri_mxf_color_space": "ARRI LogC4 / AWG4", "nclc": "1-1-1"},
        model="anything",
        user_idt="sony_slog3_sgamut3cine",
    )
    # Metadata wins over filename, model, user, and nclc.
    assert d.idt_id == "arri_logc4_awg4"
    assert d.source == "metadata"


def test_nclc_is_never_used_for_slog3_or_logc4():
    d = detect_clip(
        "unknown.mov",
        metadata={"nclc": "1-1-1", "quicktime_nclc": "S-Log3"},
    )
    assert d.idt_id is None
    assert d.needs_user_picker
    assert d.source == "unresolved"


def test_sony_acquisition_sgamut3_not_cine():
    d = detect_from_metadata(
        {
            "sony_acquisition_gamma": "S-Log3",
            "sony_acquisition_gamut": "S-Gamut3",
        }
    )
    assert d.idt_id == "sony_slog3_sgamut3"
    assert d.gamut == "SGamut3"


def test_sony_slog3_without_gamut_does_not_default_cine():
    d = detect_from_metadata({"sony_acquisition_gamma": "S-Log3"})
    assert d.curve == "slog3"
    assert d.gamut is None
    assert d.needs_user_picker
    assert "Cine" in d.note or "cine" in d.note.lower()


def test_filename_slog3_without_gamut_needs_picker():
    d = detect_from_filename("A001_SLog3_take.mov")
    assert d.curve == "slog3"
    assert d.gamut is None
    assert d.needs_user_picker


def test_filename_sgamut3_cine_is_explicit():
    d = detect_from_filename("A001_SLog3_SGamut3.Cine.mov")
    assert d.idt_id == "sony_slog3_sgamut3cine"


def test_filename_sgamut3_without_cine():
    d = detect_from_filename("A001_SLog3_SGamut3.mov")
    assert d.idt_id == "sony_slog3_sgamut3"


def test_red_rmd():
    d = detect_clip("clip.rmd", metadata={"red_rmd_gamma": "Log3G10", "red_rmd_colorspace": "REDWideGamutRGB"})
    assert d.idt_id == "red_log3g10_rwg"
    assert d.source == "metadata"


def test_user_picker_when_unresolved():
    d = detect_clip("plain.mov", user_idt="fujifilm_flog2_bt2020")
    assert d.idt_id == "fujifilm_flog2_bt2020"
    assert d.source == "user"


def test_model_hint_alexa35():
    d = detect_clip("plain.mxf", model="ARRI ALEXA 35")
    assert d.idt_id == "arri_logc4_awg4"
    assert d.source == "model"




def test_venice_filename_with_sgamut3_is_venice_idt():
    d = detect_from_filename("A001_Venice_SLog3_SGamut3.mov")
    assert d.idt_id == "sony_slog3_sgamut3_venice"
    assert d.needs_user_picker is False


def test_venice_model_alone_does_not_default_gamut():
    d = detect_clip("plain.mov", model="Sony VENICE 2")
    assert d.idt_id is None
    assert d.needs_user_picker
    assert d.curve == "slog3"


def test_slog3_without_venice_is_not_venice():
    d = detect_from_filename("A001_SLog3_SGamut3.mov")
    assert d.idt_id == "sony_slog3_sgamut3"

def test_picker_slog3_without_venice_is_two_paired_idts():
    pairs = picker_pairs(curve="slog3", venice_detected=False, needs_picker=True)
    assert pairs == list(SLOG3_PAIRS)
    assert "sony_slog3_sgamut3cine_venice" not in pairs
    labels = [lab for _, lab in picker_labels(pairs)]
    assert labels == ["S-Log3 + S-Gamut3", "S-Log3 + S-Gamut3.Cine"]
    # Never a silent Cine default: both pairs offered, Cine is not first.
    assert pairs[0] == "sony_slog3_sgamut3"


def test_picker_slog3_venice_only_if_detected():
    pairs = picker_pairs(curve="slog3", venice_detected=True, needs_picker=True)
    assert pairs == list(SLOG3_VENICE_PAIRS)
    assert set(pairs) <= set(GAMUT_VENICE)
    labels = [lab for _, lab in picker_labels(pairs)]
    assert labels == [
        "S-Log3 + S-Gamut3 (Venice)",
        "S-Log3 + S-Gamut3.Cine (Venice)",
    ]


def test_picker_unresolved_excludes_venice():
    pairs = picker_pairs(curve=None, venice_detected=False, needs_picker=True)
    assert "sony_slog3_sgamut3" in pairs
    assert "sony_slog3_sgamut3cine" in pairs
    assert not (set(pairs) & set(GAMUT_VENICE))
    # Labels are paired, not split curve/gamut.
    for _, lab in picker_labels(pairs):
        assert " + " in lab


def test_picker_unresolved_includes_venice_only_when_detected():
    pairs = picker_pairs(curve=None, venice_detected=True, needs_picker=True)
    assert "sony_slog3_sgamut3_venice" in pairs
    assert "sony_slog3_sgamut3cine_venice" in pairs


def test_one_click_blocked_until_pair_chosen():
    pending = detect_from_filename("A001_SLog3_take.mov")
    assert pending.needs_user_picker
    assert pending.idt_id is None
    assert can_one_click_process(pending) is False
    locked = detect_from_filename("A001_SLog3_SGamut3.mov")
    assert can_one_click_process(locked) is True
    assert can_one_click_process_all([pending, locked]) is False
    assert can_one_click_process_all([locked]) is True


def test_filename_venice_slog3_without_gamut_offers_venice_pairs():
    d = detect_from_filename("A001_Venice_SLog3_take.mov")
    assert d.needs_user_picker
    assert d.venice_detected
    assert d.idt_id is None
    assert can_one_click_process(d) is False
    pairs = picker_pairs_for_detection(d)
    assert pairs == list(SLOG3_VENICE_PAIRS)


def test_filename_slog3_without_venice_does_not_offer_venice_pairs():
    d = detect_from_filename("A001_SLog3_take.mov")
    assert d.venice_detected is False
    pairs = picker_pairs_for_detection(d)
    assert pairs == list(SLOG3_PAIRS)
    assert not (set(pairs) & set(GAMUT_VENICE))


def test_metadata_slog3_venice_body_without_gamut():
    d = detect_from_metadata(
        {
            "sony_acquisition_gamma": "S-Log3",
            "sony_camera_model": "VENICE 2",
        }
    )
    assert d.needs_user_picker
    assert d.venice_detected
    assert d.gamut is None
    assert can_one_click_process(d) is False
    assert picker_pairs_for_detection(d) == list(SLOG3_VENICE_PAIRS)


def test_user_pick_locks_pair_and_unblocks_process():
    pending = detect_clip("A001_SLog3_take.mov")
    assert can_one_click_process(pending) is False
    chosen = detect_clip("A001_SLog3_take.mov", user_idt="sony_slog3_sgamut3")
    assert chosen.idt_id == "sony_slog3_sgamut3"
    assert chosen.source == "user"
    assert can_one_click_process(chosen) is True


def test_canon_clog2_without_gamut_does_not_default_cinema_gamut():
    d = detect_from_metadata({"canon_vendor_gamma": "C-Log2"})
    assert d.curve == "clog2"
    assert d.gamut is None
    assert d.needs_user_picker
    assert d.idt_id is None
    assert "Cinema Gamut" in d.note


def test_canon_clog2_metadata_cinema_gamut_locks():
    d = detect_from_metadata(
        {"canon_vendor_gamma": "C-Log2", "canon_vendor_gamut": "Cinema Gamut"}
    )
    assert d.idt_id == "canon_clog2_cgamut"
    assert d.needs_user_picker is False


def test_canon_clog2_metadata_bt2020_locks():
    d = detect_from_metadata(
        {"canon_vendor_gamma": "C-Log2", "canon_vendor_gamut": "BT.2020"}
    )
    assert d.idt_id == "canon_clog2_bt2020"


def test_canon_clog3_without_gamut_does_not_default_cinema_gamut():
    d = detect_from_metadata({"canon_vendor_gamma": "C-Log3"})
    assert d.curve == "clog3"
    assert d.gamut is None
    assert d.needs_user_picker
    assert d.idt_id is None
    assert "Cinema Gamut" in d.note


def test_canon_clog3_metadata_cinema_gamut_locks():
    d = detect_from_metadata(
        {"canon_vendor_gamma": "C-Log3", "canon_vendor_gamut": "Cinema Gamut"}
    )
    assert d.idt_id == "canon_clog3_cgamut"


def test_canon_clog3_metadata_bt2020_locks():
    d = detect_from_metadata(
        {"canon_vendor_gamma": "C-Log3", "canon_vendor_gamut": "BT.2020"}
    )
    assert d.idt_id == "canon_clog3_bt2020"


def test_filename_clog3_without_gamut_needs_picker():
    d = detect_from_filename("A001_CLog3_take.mov")
    assert d.curve == "clog3"
    assert d.idt_id is None
    assert d.needs_user_picker


def test_filename_clog3_cinema_gamut():
    d = detect_from_filename("A001_CLog3_CinemaGamut.mov")
    assert d.idt_id == "canon_clog3_cgamut"


def test_filename_clog2_without_gamut_needs_picker():
    d = detect_from_filename("A001_CLog2_take.mov")
    assert d.curve == "clog2"
    assert d.idt_id is None
    assert d.needs_user_picker


def test_filename_clog2_cinema_gamut():
    d = detect_from_filename("A001_CLog2_CinemaGamut.mov")
    assert d.idt_id == "canon_clog2_cgamut"


def test_filename_clog2_bt2020():
    d = detect_from_filename("A001_CLog2_BT2020.mov")
    assert d.idt_id == "canon_clog2_bt2020"


def test_filename_apple_log():
    d = detect_from_filename("IMG_AppleLog.mov")
    assert d.idt_id == "apple_log_bt2020"


def test_filename_dlog():
    d = detect_from_filename("DJI_DLog_clip.mov")
    assert d.idt_id == "dji_dlog_dgamut"


def test_filename_dlog_m_unsupported():
    d = detect_from_filename("Osmo_DLogM_clip.mov")
    assert d.idt_id is None
    assert d.needs_user_picker
    assert "D-Log M" in d.note
    from color.gamuts import IDT_PAIRS
    from color.stubs import STUB_IDTS

    assert "dji_dlog_m" not in IDT_PAIRS
    assert any(s["id"] == "dji_dlog_m" for s in STUB_IDTS)


def test_filename_apple_log2_locks_awg_not_bt2020():
    d = detect_from_filename("IMG_AppleLog2.mov")
    assert d.idt_id == "apple_log2_awg"
    assert d.gamut == "AppleWideGamut"
    assert d.gamut != "BT2020"
    assert "Apple Wide Gamut" in picker_labels([d.idt_id])[0][1]
    assert "BT.2020" not in picker_labels([d.idt_id])[0][1]


def test_filename_logc3_locks_ei800_awg3_not_bare_logc3():
    d = detect_from_filename("A001_LogC3_take.mxf")
    assert d.idt_id == "arri_logc3_ei800_awg3"
    assert d.curve == "logc3_ei800"
    assert d.gamut == "AWG3"
    label = picker_labels([d.idt_id])[0][1]
    assert "EI800" in label
    assert "AWG3" in label
    assert label != "LogC3"


def test_picker_clog2_is_two_paired_idts():
    pairs = picker_pairs(curve="clog2", venice_detected=False, needs_picker=True)
    assert pairs == list(CLOG2_PAIRS)
    labels = [lab for _, lab in picker_labels(pairs)]
    assert labels == ["C-Log2 + Cinema Gamut", "C-Log2 + BT.2020"]
    assert set(pairs) == {"canon_clog2_cgamut", "canon_clog2_bt2020"}
    # Never a silent Cinema Gamut default: both pairs offered.
    assert pairs[0] == "canon_clog2_cgamut"
    assert "canon_clog2_bt2020" in pairs


def test_picker_clog3_is_two_paired_idts():
    pairs = picker_pairs(curve="clog3", venice_detected=False, needs_picker=True)
    assert pairs == list(CLOG3_PAIRS)
    labels = [lab for _, lab in picker_labels(pairs)]
    assert labels == ["C-Log3 + Cinema Gamut", "C-Log3 + BT.2020"]
    assert set(pairs) == {"canon_clog3_cgamut", "canon_clog3_bt2020"}


def test_swift_ui_names_logc3_ei800_awg3_and_apple_log2_awg():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    idt = (root / "macos/LogBridge/LogBridge/Models/IDT.swift").read_text(encoding="utf-8")
    detector = (
        root / "macos/LogBridge/LogBridge/Detection/ClipDetector.swift"
    ).read_text(encoding="utf-8")
    assert 'case arriLogC3EI800AWG3 = "arri_logc3_ei800_awg3"' in idt
    assert 'return "LogC3 EI800"' in idt
    assert 'return "AWG3"' in idt
    assert 'return "Apple Wide Gamut"' in idt
    assert 'case appleLog2AWG = "apple_log2_awg"' in idt
    assert "appleLog2Stub" not in idt
    assert "arriLogC3Stub" not in idt
    assert "filename LogC3 EI800 + AWG3" in detector
    assert "filename Apple Log 2 + Apple Wide Gamut" in detector
    assert "ARRI LogC3 is unsupported" not in detector
    assert "Apple Log 2 is unsupported" not in detector
    assert "D-Log M is unsupported" in detector
