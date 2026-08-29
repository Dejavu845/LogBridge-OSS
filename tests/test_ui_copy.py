"""Review locks: pending process/export, preview badge, paired IDT picker."""

from pathlib import Path

from color.batch import (
    ADVANCED_DISCLOSURE_HELP,
    ADVANCED_EXPORT_HELP,
    HONEST_PROXY_NOTE,
    PREVIEW_STATUS_DECODE_FAIL,
    PREVIEW_STATUS_DECODING,
    PREVIEW_STATUS_EMPTY,
    PREVIEW_STATUS_NOT_DELIVERABLE,
    PREVIEW_STATUS_ODT_CACHE_HIT,
    PREVIEW_STATUS_ODT_OFF,
    PREVIEW_STATUS_HDR_BUILD_FAIL,
    PREVIEW_STATUS_HDR_NO_EDR,
    PREVIEW_STATUS_PROXY,
    PROCESS_BUTTON,
    PROCESS_BUTTON_HELP,
    REASON_PICK_LOG_GAMUT,
    REASON_PICK_PAIRED_IDT,
    SKIPPED_BUCKET,
)

ROOT = Path(__file__).resolve().parents[1]
SWIFT_ROOT = ROOT / "macos"
INSPECTOR = SWIFT_ROOT / "LogBridge/LogBridge/Views/InspectorView.swift"
CONTENT = SWIFT_ROOT / "LogBridge/LogBridge/ContentView.swift"
PREVIEW = SWIFT_ROOT / "LogBridge/LogBridge/Color/Rec709PreviewView.swift"
CLIP = SWIFT_ROOT / "LogBridge/LogBridge/Models/Clip.swift"
ENGINE = SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _all_swift() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SWIFT_ROOT.rglob("*.swift"))


def test_primary_button_is_locked_chinese():
    content = _read(CONTENT)
    assert "处理已锁定片段" in content
    assert "先选择 Log 与色域" in content
    assert "导出 ACEScct / EXR" in content
    assert "预览·非成片" in _all_swift()
    assert 'Button("一键还原")' not in content
    assert 'Button("一键还原")' not in _all_swift()
    assert "一键精准" not in _all_swift() or "Not 一键精准" in _all_swift()
    swift = _all_swift()
    assert "处理已锁定片段" in swift
    assert "先选择 Log 与色域" in swift
    assert "导出 ACEScct / EXR" in swift
    assert "先选择成对 IDT" in swift
    assert "处理已锁定片段" in content
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "cancelLockedDeliverables" in bar


def test_preview_overlay_badge_feichengpian():
    preview = _read(PREVIEW)
    assert "预览·非成片" in preview
    assert "8-bit thumbnail is not a deliverable" in preview
    assert "PreviewNotDeliverableBadge" in preview
    badge = preview.split("struct PreviewNotDeliverableBadge")[1].split("struct Rec709TaggedHost")[0]
    assert 'Text("预览·非成片")' in badge
    assert 'Text("8-bit thumbnail is not a deliverable")' not in badge


def test_paired_idt_picker_not_two_dropdowns():
    inspector = _read(INSPECTOR)
    assert "Paired IDT" in inspector
    assert 'Picker("Paired IDT"' in inspector
    assert 'Picker("Curve"' not in inspector
    assert 'Picker("Gamut"' not in inspector
    assert "S-Log3 + S-Gamut3" in inspector
    assert "S-Log3 + S-Gamut3.Cine" in inspector
    assert "Venice pair only if detected" in inspector


def test_pending_clips_block_process_and_export():
    clip = _read(CLIP)
    assert "isPending" in clip
    assert "canProcess" in clip
    assert "canProcessSelected" in clip
    assert "func processSelected()" in clip
    assert "func applyGraph()" in clip
    assert "func processLockedClips()" in clip
    assert "pending" in clip
    content = _read(CONTENT)
    assert "showsProcessLockedButton" in content
    assert ".disabled(!session.canProcess)" in content
    assert "lockedClipCount" in clip
    assert "processSkipReason" in clip
    can = clip.split("var canProcess")[1].split("var canProcessSelected")[0]
    assert "pendingPickerCount == 0" not in can
    assert "lockedClipCount" in can
    assert "writeACES2065EXR" in clip
    assert "条已写出代理" in clip
    assert "待选跳过" in clip
    assert "失败原因" in clip
    assert "writeLockedDeliverables" in clip
    assert "整段代理，不是全精度成片" in clip
    assert "已写出代理" in clip
    assert "exportChip" in clip
    assert "revealClipExportInFinder" in clip
    assert "clipSequenceRevealURL" in clip
    assert "_proxy" in _read(
        SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift"
    )
    assert "_ACES2065-1_proxy" in _read(
        SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift"
    )
    assert "frame_%06d.exr" in _read(
        SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift"
    )


def test_docs_name_the_review_locks():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    blob = readme + "\n" + acceptance
    assert "预览·非成片" in blob
    assert "8-bit thumbnail is not a deliverable" in blob
    assert "处理已锁定片段" in blob
    assert "先选择 Log 与色域" in blob
    assert "导出 ACEScct / EXR" in blob
    assert "Apply graph" in blob
    assert "一键还原" in blob  # forbidden label is named so reviewers can grep
    assert "pending" in blob.lower()
    assert "paired IDT" in blob or "paired IDT" in blob
    assert "Rec.2100 HLG" in blob
    assert "Rec.2100 PQ" in blob
    assert "高级" in blob
    assert "条已锁定" in blob
    assert "待选" in blob and "已锁定" in blob
    assert "先选择成对 IDT" in blob
    assert "整段代理，不是全精度成片" in blob
    assert "已写出代理" in blob
    assert "待选跳过" in blob
    assert "失败原因" in blob
    assert "帧数对不上" in blob
    assert "读不到帧率，未核对" in blob
    assert "_proxy" in blob
    assert "ACEScct 成片" not in blob
    assert "_ACES2065-1_proxy/frame_000000.exr" in blob
    assert "709 预览" in blob
    assert "先选择成对 IDT" in blob


def test_exposure_inspector_and_preview_not_finished_picture():
    inspector = _read(INSPECTOR)
    assert "ExposureInspector" in inspector
    assert "Stops" in inspector
    assert "2^stops" in inspector or "2 ** stops" in inspector or "rgb × (2^stops)" in inspector
    assert "Do not add/subtract Log code values" in inspector
    swift = _all_swift()
    assert "case exposure" in swift or "case .exposure" in swift
    assert "applyExposure" in swift
    assert "02_Exposure" in swift
    assert "not a finished" in (inspector + swift).lower() or "not a finished picture" in inspector
    assert "预览·非成片" in inspector


def test_no_bundled_manufacturer_demos():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    blob = readme + "\n" + acceptance
    assert "No bundled camera manufacturer demo" in blob or "does **not** bundle camera manufacturer demo" in blob
    assert "drop your own" in blob.lower() or "drops their own" in blob.lower()
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    assert "no bundled manufacturer demos" in sidebar.lower()
    assert "把混源文件夹拖进来" in sidebar


def test_as_shot_wb_copy_and_no_5600_guess():
    inspector = _read(INSPECTOR)
    assert "as-shot" in inspector.lower() or "As-shot" in inspector
    assert "Pick neutral" in inspector
    assert "5600" in inspector  # named so we can say we do not guess it
    assert "6504" in inspector
    assert "不猜 5600" in inspector
    assert "ACES2065-1 (AP0)" in inspector
    assert "after IDT" in inspector
    assert "已实现（未验证）" in inspector
    assert "CAT(user→D65)·inv(CAT(as→D65))" in inspector
    assert "单位阵" in inspector
    assert "3200→5600 变暖" in inspector
    swift = _all_swift()
    assert "pickNeutral" in swift or "Pick neutral" in swift
    assert "asShotUnknown" in swift or "as-shot unknown" in swift
    assert "WBSource" in swift
    assert "handlePreviewPick" in swift
    assert "sampleLinearRGB" in swift
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    blob = readme + "\n" + acceptance
    assert "as-shot" in blob.lower()
    assert "do not guess 5600 or 6504" in blob.lower()
    assert "after IDT" in blob and "ACES2065-1 (AP0)" in blob
    assert "Grey-card" in blob or "grey-card" in blob
    assert "nclc" in blob.lower()
    assert "pending / identity" in blob.lower()


def test_user_visible_english_leftovers_are_chinese():
    """P2 leftovers: user-visible English must not return; Chinese copy is required."""
    preview = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")
    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    settings = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/SettingsView.swift")
    clip = _read(CLIP)

    assert f'"{PREVIEW_STATUS_EMPTY}"' in preview
    assert f'"{PREVIEW_STATUS_DECODING}"' in preview
    assert f'"{PREVIEW_STATUS_DECODE_FAIL}"' in preview
    assert f'"{REASON_PICK_PAIRED_IDT}"' in preview
    assert f'"{PREVIEW_STATUS_PROXY}"' in preview
    assert '"先选择成对 Log 与色域"' not in preview
    assert '"No clip"' not in preview
    assert "Decoding preview" not in preview
    assert "Could not decode a preview frame" not in preview
    assert "Pick a paired IDT" not in preview
    assert "Preview proxy" not in preview
    assert "Stub IDT" not in preview
    assert "ODT only —" not in preview
    assert "graded linear cache hit" not in preview

    status = content.split("struct StatusBar")[1]
    assert "已实现（未验证）" in status
    assert "serial graph" not in status
    assert "implemented (unverified)" not in status.lower()

    assert 'Text("已实现（未验证）")' in sidebar
    assert 'Text("implemented (unverified)")' not in sidebar

    wb = inspector.split("struct WBInspector")[1].split("struct ODTInspector")[0]
    assert 'Text("绿品")' in wb
    assert 'Text("Tint")' not in wb
    assert "机内色温只填旋钮，默认 CAT 是单位阵。" in wb
    assert "用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。" in wb
    assert "灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。" in wb
    assert "As-shot CCT/tint fills these knobs" not in wb
    assert "do not guess 5600 or 6504" not in wb.lower()
    assert "implemented (unverified)" not in wb.lower()

    assert "已实现（未验证）" in settings
    assert "implemented (unverified)" not in settings.lower()

    export_fn = clip.split("func exportResolve()")[1]
    assert 'panel.prompt = "导出"' in export_fn
    assert 'panel.prompt = "Export"' not in export_fn


def _help_literals(src: str) -> list[str]:
    """Quoted strings passed to SwiftUI `.help(...)` (hover / tooltip)."""
    import re

    lits: list[str] = []
    for line in src.splitlines():
        code = line.split("//", 1)[0]
        if ".help(" not in code:
            continue
        lits.extend(re.findall(r'\.help\("([^"]*)"\)', code))
    return lits


def _chengpian_only_honesty(text: str) -> None:
    stripped = (
        text.replace("不是全精度成片", "")
        .replace("预览·非成片", "")
        .replace("不是成片", "")
    )
    assert "成片" not in stripped
    assert "精准" not in text


def test_process_bar_and_advanced_help_are_chinese():
    """Process bar + 高级 hover/help stay locked Chinese. No new button/path."""
    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    strip = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/NodeStripView.swift")
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    advanced = content.split("struct AdvancedPanel")[1].split("struct SplitPreview")[0]

    assert PROCESS_BUTTON == "处理已锁定片段"
    assert HONEST_PROXY_NOTE == "整段代理，不是全精度成片"
    assert SKIPPED_BUCKET == "待选跳过"
    assert REASON_PICK_LOG_GAMUT == "先选择 Log 与色域"
    assert REASON_PICK_PAIRED_IDT == "先选择成对 IDT"
    assert PROCESS_BUTTON_HELP == (
        "整段代理，不是全精度成片。ACES2065-1 AP0 线性，不是 ACEScct。"
        "待选跳过（先选择 Log 与色域 / 先选择成对 IDT）。"
    )
    assert ADVANCED_EXPORT_HELP == (
        "只处理已锁定片段。待选跳过。709 预览。预览·非成片。不必全部锁定。"
    )
    assert ADVANCED_DISCLOSURE_HELP == "节点与导出 ACEScct / EXR。默认收起。预览·非成片。"

    assert f'.help("{PROCESS_BUTTON_HELP}")' in bar
    assert f'.help("{ADVANCED_EXPORT_HELP}")' in advanced
    assert f'.help("{ADVANCED_DISCLOSURE_HELP}")' in advanced
    assert 'DisclosureGroup("高级"' in advanced
    assert PROCESS_BUTTON in bar
    assert HONEST_PROXY_NOTE in bar
    assert SKIPPED_BUCKET in bar
    assert REASON_PICK_LOG_GAMUT in bar
    assert REASON_PICK_PAIRED_IDT in bar
    assert PROCESS_BUTTON in ADVANCED_EXPORT_HELP
    assert SKIPPED_BUCKET in ADVANCED_EXPORT_HELP
    assert "709 预览" in ADVANCED_EXPORT_HELP
    assert "预览·非成片" in ADVANCED_EXPORT_HELP
    assert "预览·非成片" in ADVANCED_DISCLOSURE_HELP

    english_leftovers = (
        "Unlocked stay listed",
        "Locked clips only",
        "Pending stay listed",
        "Does not require the whole bin",
    )
    for chunk in (bar, advanced, inspector, strip):
        for en in english_leftovers:
            assert en not in chunk
    for help_text in _help_literals(bar) + _help_literals(advanced):
        for en in english_leftovers:
            assert en not in help_text
        assert "Unlocked" not in help_text
        assert "Locked clips" not in help_text
        assert "Pending stay" not in help_text
        assert "whole bin" not in help_text
        _chengpian_only_honesty(help_text)

    assert _help_literals(bar) == [PROCESS_BUTTON_HELP]
    assert ADVANCED_EXPORT_HELP in _help_literals(advanced)
    assert ADVANCED_DISCLOSURE_HELP in _help_literals(advanced)
    assert _help_literals(strip) == []

    assert bar.count("Button(") == 1
    assert advanced.count("Button(") == 1
    assert 'Button("导出 ACEScct / EXR")' in advanced
    assert 'Button("处理已锁定片段")' not in advanced
    assert "processLockedClips" not in advanced
    assert strip.count("Button(") == 0
    assert "精准" not in PROCESS_BUTTON_HELP
    assert "精准" not in ADVANCED_EXPORT_HELP
    assert "精准" not in ADVANCED_DISCLOSURE_HELP


def _preview_status_literals(src: str) -> list[str]:
    """Quoted strings assigned to preview.status / the note that feeds it."""
    import re

    lits: list[str] = []
    for line in src.splitlines():
        code = line.split("//", 1)[0]
        if "status" not in code and "note =" not in code:
            continue
        lits.extend(re.findall(r'"([^"]*)"', code))
    return lits


def test_preview_status_is_locked_chinese():
    """preview.status (and Swift/Python strings that feed it) stay locked Chinese."""
    engine = _read(ENGINE)
    content = _read(CONTENT)
    clip = _read(CLIP)

    assert PREVIEW_STATUS_ODT_CACHE_HIT == "只重跑 ODT"
    assert PREVIEW_STATUS_PROXY == "预览代理，不是成片"
    assert PREVIEW_STATUS_NOT_DELIVERABLE == "预览·非成片"
    assert PREVIEW_STATUS_ODT_OFF == "709 预览关"
    assert PREVIEW_STATUS_HDR_BUILD_FAIL == "HDR 预览建不出"
    assert PREVIEW_STATUS_HDR_NO_EDR == "屏幕无 EDR，预览被压到 SDR"
    assert REASON_PICK_PAIRED_IDT == "先选择成对 IDT"
    assert REASON_PICK_LOG_GAMUT == "先选择 Log 与色域"
    assert "成片" not in PREVIEW_STATUS_ODT_OFF
    assert "成片" not in PREVIEW_STATUS_ODT_CACHE_HIT
    assert "精准" not in PREVIEW_STATUS_ODT_OFF

    odt = engine.split("func renderODTFromGraded")[1].split("func publishODTOnly")[0]
    assert f'"{PREVIEW_STATUS_ODT_CACHE_HIT}"' in odt
    assert "cacheHit" in odt
    assert f'"{PREVIEW_STATUS_PROXY}"' in odt
    assert f'"{PREVIEW_STATUS_NOT_DELIVERABLE}"' in odt
    assert f'"{PREVIEW_STATUS_ODT_OFF}"' in odt
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in odt
    assert "HDRPreviewColor.encodeFromGradedAP0" in odt
    assert "applyODT" in odt  # 709 branch only
    assert "acesOTNote" not in odt
    assert "ODT only —" not in odt
    assert "graded linear cache hit" not in odt
    assert "homemade HDR curve" not in odt
    assert "ODT off —" not in odt
    assert "ACEScct deliverable" not in odt
    assert "Rec.709 pane is not tagged" not in odt
    assert "成片预览关" not in odt
    assert "精准" not in odt

    build = engine.split("private func build(")[1].split("private static func gradeKey")[0]
    assert "processSkipReason" in build
    assert f'?? "{REASON_PICK_PAIRED_IDT}"' in build
    assert "Stub IDT" not in build
    assert "no preview process" not in build
    assert '"先选择成对 Log 与色域"' not in build
    assert f'"{REASON_PICK_LOG_GAMUT}"' not in build
    assert "精准" not in build

    refresh = engine.split("func refresh(")[1].split("func refreshODT(")[0]
    assert f'"{PREVIEW_STATUS_EMPTY}"' in refresh
    assert f'"{PREVIEW_STATUS_DECODING}"' in refresh
    refresh_odt = engine.split("func refreshODT(")[1].split(
        "private func applyODTFromGradedOrRebuild"
    )[0]
    assert f'"{PREVIEW_STATUS_EMPTY}"' in refresh_odt

    status_bar = content.split("struct StatusBar")[1]
    assert "preview.status" in status_bar
    assert "session.preview.status" in status_bar

    skip = clip.split("var processSkipReason")[1].split("var verificationBadge")[0]
    assert REASON_PICK_PAIRED_IDT in skip
    assert REASON_PICK_LOG_GAMUT in skip

    banned = (
        "ODT only",
        "cache hit",
        "Stub IDT",
        "no preview process",
        "homemade HDR",
        "does not apply",
        "ODT off —",
        "deliverable",
        "pane is not tagged",
        "No clip",
        "Decoding preview",
        "Could not decode",
        "Pick a paired",
        "Preview proxy",
        "先选择成对 Log 与色域",
        "成片预览关",
    )
    for lit in _preview_status_literals(engine):
        for token in banned:
            assert token not in lit, (token, lit)
        assert "精准" not in lit
        cleaned = (
            lit.replace("预览·非成片", "")
            .replace("不是全精度成片", "")
            .replace("不是成片", "")
        )
        assert "成片" not in cleaned, lit

    assert "Button(" not in odt
    assert "Button(" not in build


def test_preview_pane_title_odt_off_is_709():
    """Preview pane title (ODT off) is 709 预览关, matching #43 preview.status."""
    clip = _read(CLIP)
    content = _read(CONTENT)
    preview = _read(PREVIEW)
    swift = _all_swift()

    assert PREVIEW_STATUS_ODT_OFF == "709 预览关"
    title = clip.split("var odtPreviewTitle")[1].split("var odtPreviewCaption")[0]
    assert "case .off:" in title
    assert f'return "{PREVIEW_STATUS_ODT_OFF}"' in title
    assert "成片预览关" not in title
    assert "ACEScct" not in title
    assert "精准" not in title
    _chengpian_only_honesty(title)

    caption = clip.split("var odtPreviewCaption")[1].split("func setIDT")[0]
    assert "成片预览关" not in caption
    assert "精准" not in caption
    _chengpian_only_honesty(caption)

    split = content.split("struct SplitPreview")[1].split("struct WriteProgressLine")[0]
    assert "odtPreviewTitle" in split
    assert "odtPreviewCaption" in split
    assert "Rec709PreviewView" in split
    assert "Button(" not in split
    assert "成片预览关" not in split
    assert "精准" not in split

    pane = preview.split("struct Rec709PreviewView")[1].split("struct PreviewNotDeliverableBadge")[0]
    assert "PreviewPaneTitle(title: title)" in pane
    chrome = preview.split("private struct PreviewPaneTitle")[1].split("struct SourceUntaggedHost")[0]
    assert "Text(title)" in chrome
    assert "成片预览关" not in pane
    assert "成片预览关" not in chrome
    assert "精准" not in pane
    assert "精准" not in chrome

    assert "成片预览关" not in content
    assert "成片预览关" not in swift
    assert f'"{PREVIEW_STATUS_ODT_OFF}"' in clip
    assert f'"{PREVIEW_STATUS_ODT_OFF}"' in _read(ENGINE)


def _odt_preview_caption_literals(src: str) -> list[str]:
    """Quoted strings returned by odtPreviewCaption (and locals that feed it)."""
    import re

    lits: list[str] = []
    for line in src.splitlines():
        code = line.split("//", 1)[0]
        if "return" not in code and "badge" not in code and "=" not in code:
            continue
        lits.extend(re.findall(r'"([^"]*)"', code))
    return lits


def test_odt_preview_caption_is_locked_chinese():
    """odtPreviewCaption (and strings that feed it) reuse 预览·非成片 / 709 预览关."""
    import re

    clip = _read(CLIP)
    content = _read(CONTENT)
    preview = _read(PREVIEW)
    engine = _read(ENGINE)

    assert PREVIEW_STATUS_NOT_DELIVERABLE == "预览·非成片"
    assert PREVIEW_STATUS_ODT_OFF == "709 预览关"
    assert "成片" not in PREVIEW_STATUS_ODT_OFF
    assert "精准" not in PREVIEW_STATUS_ODT_OFF
    assert "精准" not in PREVIEW_STATUS_NOT_DELIVERABLE

    title = clip.split("var odtPreviewTitle")[1].split("var odtPreviewCaption")[0]
    assert f'return "{PREVIEW_STATUS_ODT_OFF}"' in title
    assert "成片预览关" not in title

    caption = clip.split("var odtPreviewCaption")[1].split("func setIDT")[0]
    assert "case .off:" in caption
    assert f'return "{PREVIEW_STATUS_ODT_OFF}"' in caption
    assert f'return "{PREVIEW_STATUS_NOT_DELIVERABLE}"' in caption
    assert "acesOTNote" not in caption
    assert "badge" not in caption
    assert "成片预览关" not in caption
    assert "精准" not in caption
    _chengpian_only_honesty(caption)

    allowed = {PREVIEW_STATUS_ODT_OFF, PREVIEW_STATUS_NOT_DELIVERABLE}
    leftover_english = (
        "Node 4 off",
        "ACEScct deliverable",
        "This pane is not tagged",
        "Not a finished picture",
        "Tagged CGColorSpace",
        "Preview only",
        "finished grade",
        "Golden grey-card",
        "accuracy claim",
        "homemade HLG",
        "does not invent",
        "8-bit thumbnail is not a deliverable",
        "deliverable",
        "finished picture",
        "itur_709",
    )
    for lit in _odt_preview_caption_literals(caption):
        assert lit in allowed, lit
        for token in leftover_english:
            assert token not in lit, (token, lit)
        assert "成片预览关" not in lit
        assert "精准" not in lit
        assert not re.search(r"[A-Za-z]", lit), lit
        _chengpian_only_honesty(lit)

    for token in leftover_english:
        assert token not in caption, token

    split = content.split("struct SplitPreview")[1].split("struct WriteProgressLine")[0]
    assert "odtPreviewCaption" in split
    assert "odtPreviewTitle" in split
    assert "Rec709PreviewView" in split
    assert "Button(" not in split
    assert "成片预览关" not in split
    assert "精准" not in split

    pane = preview.split("struct Rec709PreviewView")[1].split("struct PreviewNotDeliverableBadge")[0]
    assert ".help(caption)" in pane
    assert "Button(" not in pane
    assert "成片预览关" not in pane
    assert "精准" not in pane

    odt = engine.split("func renderODTFromGraded")[1].split("func publishODTOnly")[0]
    assert f'"{PREVIEW_STATUS_ODT_CACHE_HIT}"' in odt
    assert f'"{PREVIEW_STATUS_PROXY}"' in odt
    assert f'"{PREVIEW_STATUS_NOT_DELIVERABLE}"' in odt
    assert f'"{PREVIEW_STATUS_ODT_OFF}"' in odt
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in odt
    assert "acesOTNote" not in odt


def test_hdr_preview_colorsync_fail_closed_no_709_fallback():
    """HLG/PQ: ColorSync itur_2100. 709 applyODT / u8 / OETF untouched. Fail closed."""
    engine = _read(ENGINE)
    content = _read(CONTENT)
    preview_709 = _read(PREVIEW)
    hdr = _read(SWIFT_ROOT / "LogBridge/LogBridge/Color/HDRPreview.swift")
    clip = _read(CLIP)
    exporter = _read(SWIFT_ROOT / "LogBridge/LogBridge/Export/ResolveExporter.swift")

    assert PREVIEW_STATUS_HDR_BUILD_FAIL == "HDR 预览建不出"
    assert PREVIEW_STATUS_HDR_NO_EDR == "屏幕无 EDR，预览被压到 SDR"
    assert PREVIEW_STATUS_NOT_DELIVERABLE == "预览·非成片"
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in engine
    assert f'"{PREVIEW_STATUS_HDR_NO_EDR}"' in engine
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in hdr
    assert f'"{PREVIEW_STATUS_HDR_NO_EDR}"' in hdr

    odt = engine.split("func renderODTFromGraded")[1].split("func publishODTOnly")[0]
    hdr_branch = odt.split("} else if graph.odt.isHDR")[1].split('note = "709 预览关"')[0]
    assert "HDRPreviewColor.encodeFromGradedAP0" in hdr_branch
    assert "graded.rgb" in hdr_branch
    assert "PreviewColor.applyODT" not in hdr_branch
    assert "makeCGImage" not in hdr_branch
    assert "u8(" not in hdr_branch
    assert "rec709OETF" not in hdr_branch
    assert "itur_709" not in hdr_branch
    assert "applyODT" not in hdr_branch
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in hdr_branch
    rec709_branch = odt.split("graph.odt == .rec709")[1].split("} else if graph.odt.isHDR")[0]
    assert "PreviewColor.applyODT" in rec709_branch
    assert "itur_709" in rec709_branch
    assert "makeCGImage" in rec709_branch

    apply = engine.split("static func applyODT(rgb: inout [Float])")[1].split(
        "private static let ap0ToXYZ"
    )[0]
    assert "ap0ToRec709" in apply
    assert "rec709OETF: true" in apply
    assert "PreviewMetal.applyMatrix" in apply
    metal = engine.split("enum PreviewMetal")[1]
    assert "0.018053968510807" in metal
    assert "1.09929682680944" in metal
    assert "rec709OETF" in metal

    assert "itur_2100_HLG" in hdr
    assert "itur_2100_PQ" in hdr
    assert "ColorSync" in hdr
    assert "extendedLinearITUR_2020" in hdr
    assert "wantsExtendedDynamicRangeContent" in hdr
    assert "RGBA16Float" in hdr
    assert 'setValue(true, forKey: "wantsExtendedDynamicRangeContent")' in hdr
    assert 'setValue("RGBA16Float", forKey: "contentsFormat")' in hdr
    assert "bt2020ToAP0.inverse" in hdr
    assert "0.679085634707" in hdr
    assert "0.679085634707" in engine
    assert "PreviewColor.applyODT" not in hdr
    assert "func applyODT" not in hdr
    assert "rec709OETF" not in hdr
    assert "func u8" not in hdr
    assert "CGColorSpace.itur_709" not in hdr
    assert "import OpenColorIO" not in hdr
    assert "ACES-OUTPUT" not in hdr
    assert "No OCIO" in hdr
    assert "0.17883277" not in hdr
    assert "78.84375" not in hdr
    assert "完善" not in hdr
    assert "精准" not in hdr or "Not 一键精准" in hdr
    _chengpian_only_honesty(hdr)

    assert "itur_2100" not in preview_709
    assert "CGColorSpace.itur_709" in preview_709
    assert "bitsPerComponent: 8" in engine
    assert "func u8(_ x: Float)" in engine

    split = content.split("struct SplitPreview")[1].split("struct WriteProgressLine")[0]
    assert "HDRPreviewView" in split
    assert "Rec709PreviewView" in split
    assert "graph.odt.isHDR" in split
    assert "failClosedHDRPreviewLayer" in split
    assert "Button(" not in split

    assert "func failClosedHDRPreviewLayer" in clip
    assert "graph.odt.isHDR" in clip.split("func failClosedHDRPreviewLayer")[1].split("var pendingPickerCount")[0]
    assert "encodeFromGradedAP0" not in exporter
    assert "itur_2100" not in exporter
    assert "applyODT" not in exporter

    resolved = engine.split("func resolvedPreviewStatus")[1].split("private func build(")[0]
    assert f'"{PREVIEW_STATUS_HDR_NO_EDR}"' in resolved
    assert f'"{PREVIEW_STATUS_HDR_BUILD_FAIL}"' in resolved
    assert "displayHasEDR" in resolved
    assert "applyODT" not in resolved

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    blob = readme + "\n" + acceptance
    assert "HDR 预览建不出" in blob
    assert "屏幕无 EDR，预览被压到 SDR" in blob
    assert "ColorSync" in blob
    assert "itur_2100" in blob
    assert "预览·非成片" in blob


def test_inspector_cat_three_sentences_review_lock():
    """As-shot default is 单位阵. Relative CAT only on user move. No 机内白转到 D65."""
    inspector = _read(INSPECTOR)
    wb = inspector.split("struct WBInspector")[1].split("struct ODTInspector")[0]
    assert "机内色温只填旋钮，默认 CAT 是单位阵。" in wb
    assert "用户改色温才做相对变换 CAT(user→D65)·inv(CAT(as→D65))，3200→5600 变暖。" in wb
    assert "灰卡是绝对 CAT；读不到就保持单位阵，不猜 5600。" in wb
    assert "单位阵" in wb
    assert "CAT(user→D65)·inv(CAT(as→D65))" in wb
    assert "3200→5600 变暖" in wb
    stripped = wb.replace("CAT(user→D65)·inv(CAT(as→D65))", "")
    assert "CAT(as→D65)" not in stripped
    assert "机内白转到 D65" not in wb
    clip = _read(CLIP)
    assert "已写出代理" in clip
    assert "待选跳过" in clip
    assert "失败原因" in clip


def test_idt_bar_always_visible_no_hidden_picker():
    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    strip = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/NodeStripView.swift")
    assert "PairedIDTBar" in content
    assert "成对 IDT" in inspector
    assert 'Button("Apply graph")' not in strip
    assert "确认估计" in inspector
    assert "估计白平衡" in inspector
    assert "高级" in content
    # Main path: preview → paired IDT → process. Not inside 高级.
    center = content.split("VStack(spacing: 0)")[1].split(".frame(minWidth: 520)")[0]
    assert "SplitPreview" in center
    assert center.index("PairedIDTBar") < center.index("AdvancedPanel")
    assert "PairedIDTBar" not in content.split("struct AdvancedPanel")[1].split("struct SplitPreview")[0]
    advanced = content.split("struct AdvancedPanel")[1].split("struct SplitPreview")[0]
    assert "NodeStripView" in advanced
    assert "导出 ACEScct / EXR" in advanced
    assert "ODTInspector" not in advanced
    assert 'Picker("Paired IDT"' not in advanced
    assert "成对 IDT" not in advanced
    assert "layoutPriority(1)" in center
    inspector_frame = content.split("InspectorView(session: session)")[1].split("}")[0]
    assert "maxWidth: 260" in inspector_frame
    assert "maxWidth: 380" not in inspector_frame
    sidebar_frame = content.split("ClipSidebarView(session: session)")[1].split("VStack")[0]
    assert "maxWidth: 280" in sidebar_frame
    assert "处理已锁定片段" not in inspector.split("struct InspectorView")[1].split("struct WBInspector")[0]


def test_sidebar_pending_and_locked_are_glanceable():
    """待选 / 已锁定 are two visual states. No extra lock button."""
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    row = sidebar.split("struct ClipRow")[1]
    assert "clip.isPending" in row
    assert '"待选"' in row
    assert '"已锁定"' in row
    assert "weight(.semibold)" in row
    assert "frame(width: 3)" in row
    assert 'Button("锁 IDT")' not in sidebar
    assert 'Button("锁定")' not in sidebar
    assert 'Button("锁定 IDT")' not in sidebar
    assert "处理已锁定片段" not in row
    assert "精准" not in sidebar


def test_write_progress_on_preview_inspector_locks():
    """While writing: one progress line on preview; inspector/IDT locked; one cancel."""
    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    clip = _read(CLIP)

    assert "var isExporting" in clip
    assert "isWritingDeliverables" in clip
    assert "isExporting: Bool { isWritingDeliverables }" in clip

    preview = content.split("struct SplitPreview")[1].split("struct StatusBar")[0]
    assert "WriteProgressLine" in preview
    assert "isExporting" in preview
    assert "lastExportNote" in preview
    assert "ProgressView" not in preview
    assert 'Button(' not in preview
    assert "取消" not in preview
    assert "处理已锁定片段" not in preview
    assert "精准" not in preview
    line = content.split("struct WriteProgressLine")[1].split("struct StatusBar")[0]
    assert line.count("Button(") == 0
    assert "ProgressView" not in line
    assert "Text(text)" in line

    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "cancelLockedDeliverables" in bar
    assert bar.count("lastExportNote") == 1
    assert "showsBatchSummary" in bar
    assert "WriteProgressLine" not in bar

    status = content.split("struct StatusBar")[1]
    assert 'Button("处理已锁定片段")' not in status
    assert "取消" not in status
    assert "WriteProgressLine" not in status
    assert "isWritingDeliverables" not in status
    assert "isExporting" in status
    assert "preview.isWorking" in status
    working = status.split("if session.preview.isWorking")[1].split("{")[0]
    assert "isWritingDeliverables" not in working
    assert "isExporting" not in working

    insp = inspector.split("struct InspectorView")[1].split("struct WBInspector")[0]
    assert "ExposureInspector" in insp
    assert "WBInspector" in insp
    assert "isExporting" in insp
    assert ".disabled(" in insp
    assert 'Button("处理已锁定片段")' not in insp
    assert "精准" not in insp

    idt = inspector.split("struct PairedIDTBar")[1].split("struct InspectorView")[0]
    assert "成对 IDT" in idt
    assert 'Picker("Paired IDT"' in idt
    assert ".disabled(" in idt
    assert "isExporting" in idt
    assert "if session.isExporting" not in idt
    assert "处理已锁定片段" not in idt

    center = content.split("VStack(spacing: 0)")[1].split(".frame(minWidth: 520)")[0]
    assert "PairedIDTBar" in center
    assert center.index("SplitPreview") < center.index("PairedIDTBar")
    assert "整段代理，不是全精度成片" in content
    assert "预览·非成片" in _all_swift()


def test_lock_lands_on_next_pending():
    """Lock selected pending IDT selects next pending (wrap). Mid-write stays. No auto-lock."""
    clip = _read(CLIP)
    set_fn = clip.split("func setIDT")[1].split("func selectNextPendingAfterLock")[0]
    assert "wasPending" in set_fn
    assert "isWritingDeliverables" in set_fn
    assert "selectNextPendingAfterLock" in set_fn
    assert "processLockedClips" not in set_fn
    assert "processSelected" not in set_fn
    assert "exportResolve" not in set_fn
    assert "精准" not in set_fn

    advance = clip.split("func selectNextPendingAfterLock")[1].split("func selectAdjacentClip")[0]
    assert "selectedID == lockedID" in advance
    assert "dropFirst" in advance
    assert "!$0.hasLockedPair" in advance
    assert "id != lockedID" in advance
    assert "selectedID" in advance
    assert "setIDT" not in advance
    assert "processLockedClips" not in advance
    assert "processSelected" not in advance
    assert "exportResolve" not in advance
    assert "精准" not in advance

    import_fn = clip.split("func importURL")[1].split("private static let clipExtensions")[0]
    assert "built.first(where:" in import_fn
    assert "!$0.hasLockedPair" in import_fn
    assert "selectedID" in import_fn

    assert "func selectAdjacentClip" in clip

    cap = clip.split("var previewCaption")[1].split("var displayCurve")[0]
    assert "processSkipReason ?? exportChip" in cap
    assert 'return "先选择 Log 与色域"' not in cap
    assert 'return "先选择成对 IDT"' not in cap

    content = _read(CONTENT)
    inspector = _read(INSPECTOR)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "PairedIDTBar" in content
    assert "session.setIDT" in inspector
    assert 'Button("锁 IDT")' not in sidebar
    assert 'Button("锁定")' not in sidebar
    assert "isExporting" in clip
    assert "isWritingDeliverables" in clip


def test_arrow_keys_select_adjacent_clip():
    """Up/Down moves sidebar selection. Mid-write stays. No new button. Preview chrome #33."""
    clip = _read(CLIP)
    content = _read(CONTENT)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    inspector = _read(INSPECTOR)

    fn = clip.split("func selectAdjacentClip")[1].split("func removeSelectedClipFromSession")[0]
    assert "isWritingDeliverables" in fn
    assert "isArrowConsumedByTextInput" in fn
    assert "selectedID" in fn
    assert "clips.indices.contains" in fn
    assert "setIDT" not in fn
    assert "processLockedClips" not in fn
    assert "processSelected" not in fn
    assert "exportResolve" not in fn
    assert "精准" not in fn

    steal = clip.split("func isArrowConsumedByTextInput")[1].split("func setExposureEnabled")[0]
    assert "NSTextView" in steal
    assert "NSTextField" in steal
    assert "NSSlider" in steal
    assert "NSSearchField" in steal
    assert "精准" not in steal

    cap = clip.split("var previewCaption")[1].split("var displayCurve")[0]
    assert "processSkipReason ?? exportChip" in cap
    assert 'return "先选择 Log 与色域"' not in cap
    assert 'return "先选择成对 IDT"' not in cap
    assert "exportChip" in cap
    assert "已写出代理" in clip

    assert "ClipListArrowMonitor" in content
    assert "onMoveCommand" in content
    assert "selectAdjacentClip" in content
    assert "keyCode" in content
    assert "case 126" in content
    assert "case 125" in content
    assert "case 38" not in content
    assert "case 40" not in content
    monitor = content.split("struct ClipListArrowMonitor")[1].split("struct ProcessLockedBar")[0]
    assert monitor.count("Button(") == 0
    assert "帮助" not in monitor
    assert "overlay" not in monitor.lower() or "No help overlay" in monitor
    assert "精准" not in monitor

    preview = content.split("struct SplitPreview")[1].split("struct StatusBar")[0]
    assert "previewCaption" in preview
    assert "WriteProgressLine" in preview
    assert preview.index("isExporting") < preview.index("previewCaption")
    assert "Button(" not in preview
    assert "帮助" not in preview

    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "PairedIDTBar" in content
    assert "session.setIDT" in inspector
    assert 'Button("锁 IDT")' not in sidebar
    assert 'Button("锁定")' not in sidebar
    assert "ScrollViewReader" in sidebar
    assert "精准" not in sidebar

    set_fn = clip.split("func setIDT")[1].split("func selectNextPendingAfterLock")[0]
    assert "selectNextPendingAfterLock" in set_fn
    assert "isWritingDeliverables" in set_fn
    import_fn = clip.split("func importURL")[1].split("private static let clipExtensions")[0]
    assert "built.first(where:" in import_fn
    assert "!$0.hasLockedPair" in import_fn
    assert "isExporting" in clip
    assert "isWritingDeliverables" in clip


def test_delete_removes_clip_from_session_not_disk():
    """Delete/Backspace drops the selected clip from the session only.

    Source file and any already-written `_proxy` stay on disk. Mid-write
    ignores Delete. Text fields keep Delete. No new button. No confirm sheet.
    Preview chrome stays #33. #40 evicts the removed clip's preview cache.
    """
    clip = _read(CLIP)
    content = _read(CONTENT)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    inspector = _read(INSPECTOR)
    engine = _read(SWIFT_ROOT / "LogBridge/LogBridge/Preview/PreviewEngine.swift")

    fn = clip.split("func removeSelectedClipFromSession")[1].split(
        "func isArrowConsumedByTextInput"
    )[0]
    body = "\n".join(
        line.split("//", 1)[0]
        for line in fn.splitlines()
        if not line.lstrip().startswith("//")
    )
    assert "isWritingDeliverables" in fn
    assert "isArrowConsumedByTextInput" in fn
    assert "showSettings" in fn
    assert "showImporter" in fn
    assert "clips.remove(at:" in fn
    assert "preview.evict(clipID:" in fn
    assert "clips.indices.contains(idx)" in fn
    assert "idx - 1" in fn
    assert "selectedID = nil" in fn
    assert "applyClipWBToGraph" in fn
    assert "cancelLockedDeliverables" not in fn
    assert "cancelWritingFromEscape" not in fn
    assert "writeCancel" not in fn
    assert "processLockedClips" not in fn
    assert "processSelected" not in fn
    assert "exportResolve" not in fn
    assert "setIDT" not in fn
    assert "FileManager" not in body
    assert "removeItem" not in body
    assert "trash" not in body.lower()
    assert "recycle" not in body.lower()
    assert "unlink" not in body
    assert "NSWorkspace" not in body
    assert "confirmationDialog" not in body
    assert "NSAlert" not in body
    assert "showImporter" in body
    assert "精准" not in fn
    assert "_proxy" in fn
    assert "source" in fn.lower() or "源" in fn

    steal = clip.split("func isArrowConsumedByTextInput")[1].split("func setExposureEnabled")[0]
    assert "NSTextView" in steal
    assert "NSTextField" in steal
    assert "NSSlider" in steal
    assert "NSSearchField" in steal
    assert "精准" not in steal

    cap = clip.split("var previewCaption")[1].split("var displayCurve")[0]
    assert "processSkipReason ?? exportChip" in cap
    assert 'return "先选择 Log 与色域"' not in cap
    assert 'return "先选择成对 IDT"' not in cap
    assert "exportChip" in cap
    assert "已写出代理" in clip

    assert "func evict(clipID:" in engine
    assert "func retainPreviewCaches" in engine
    refresh = engine.split("func refresh(")[1].split("func refreshODT(")[0]
    assert "retainPreviewCaches(keeping: clip?.id)" in refresh

    assert "case 51" in content
    assert "case 117" in content
    assert "removeSelectedClipFromSession" in content
    assert "onDeleteCommand" in content
    assert "onDelete" in content
    assert "isArrowConsumedByTextInput" in content
    assert "keyboardShortcut" not in content
    assert "case 126" in content
    assert "case 125" in content
    assert "case 53" in content
    assert "selectAdjacentClip" in content
    assert "cancelWritingFromEscape" in content

    monitor = content.split("struct ClipListArrowMonitor")[1].split("struct ProcessLockedBar")[0]
    assert monitor.count("Button(") == 0
    assert "case 51" in monitor
    assert "case 117" in monitor
    assert "onDelete" in monitor
    assert "isArrowConsumedByTextInput" in monitor
    assert "isEscapeReservedByPresentedUI" in monitor
    assert "帮助" not in monitor
    assert "overlay" not in monitor.lower() or "No help overlay" in monitor
    assert "精准" not in monitor
    assert "removeItem" not in monitor
    assert "FileManager" not in monitor
    assert "trash" not in monitor.lower()

    preview = content.split("struct SplitPreview")[1].split("struct StatusBar")[0]
    assert "previewCaption" in preview
    assert "WriteProgressLine" in preview
    assert preview.index("isExporting") < preview.index("previewCaption")
    assert "Button(" not in preview
    assert "删除" not in preview
    assert "移出" not in preview
    assert "帮助" not in preview

    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "处理已锁定片段" in bar
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "cancelLockedDeliverables" in bar
    assert 'Button("删除")' not in bar
    assert 'Button("移出")' not in bar

    assert "PairedIDTBar" in content
    assert "session.setIDT" in inspector
    assert 'Button("锁 IDT")' not in sidebar
    assert 'Button("锁定")' not in sidebar
    assert 'Button("删除")' not in sidebar
    assert 'Button("移出")' not in sidebar
    assert "把混源文件夹拖进来" in sidebar
    assert "精准" not in sidebar
    drop = sidebar.split("struct DropZone")[1].split("struct ClipRow")[0]
    assert "把混源文件夹拖进来" in drop
    assert "把文件夹拖进来" in drop

    assert "isWritingDeliverables" in clip
    assert "isExporting" in clip
    assert "没有素材" in engine

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "Delete/Backspace removes the selected clip from the session only" in readme
    assert "does not delete the source file" in readme
    assert "_proxy" in readme
    assert "Delete/Backspace removes the selected clip from the session only" in acceptance
    assert "does not delete, trash, or move the source file" in acceptance
    assert "already-written `_proxy`" in acceptance
    assert "select next, else previous" in acceptance
    assert "把混源文件夹拖进来" in acceptance
    assert "整段代理，不是全精度成片" in readme
    assert "整段代理，不是全精度成片" in acceptance
    assert "精准" not in fn
    assert "Escape while writing" in readme
    assert "idle Escape does nothing" in readme


def test_escape_cancels_write_only():
    """While writing, Escape is the existing 取消. Idle Escape does nothing. No new button."""
    clip = _read(CLIP)
    content = _read(CONTENT)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")
    inspector = _read(INSPECTOR)

    fn = clip.split("func cancelWritingFromEscape")[1].split("static func exportProgressText")[0]
    assert "isWritingDeliverables" in fn
    assert "cancelLockedDeliverables" in fn
    assert "showSettings" in fn
    assert "showImporter" in fn
    assert "selectedID" not in fn
    assert "terminate" not in fn
    assert "processLockedClips" not in fn
    assert "processSelected" not in fn
    assert "exportResolve" not in fn
    assert "setIDT" not in fn
    assert "精准" not in fn

    cancel = clip.split("func cancelLockedDeliverables")[1].split("func cancelWritingFromEscape")[0]
    assert "writeCancel.request()" in cancel
    assert "Button(" not in cancel
    assert "精准" not in cancel

    note = clip.split("func cancelledExportNote")[1].split("static let bytesPerEXRPixel")[0]
    assert "已取消" in note
    assert "整段代理，不是全精度成片" in note

    reserved = clip.split("func isEscapeReservedByPresentedUI")[1].split("func setExposureEnabled")[0]
    assert "attachedSheet" in reserved
    assert "modalWindow" in reserved
    assert "keyWindow" in reserved
    assert "精准" not in reserved

    assert "case 53" in content
    assert "cancelWritingFromEscape" in content
    assert "isEscapeReservedByPresentedUI" in content
    assert "cancelLockedDeliverables" in content
    assert "keyboardShortcut" not in content
    assert "onExitCommand" not in content

    assert "case 126" in content
    assert "case 125" in content
    assert "selectAdjacentClip" in content
    assert "ClipListArrowMonitor" in content
    assert "onMoveCommand" in content

    monitor = content.split("struct ClipListArrowMonitor")[1].split("struct ProcessLockedBar")[0]
    assert monitor.count("Button(") == 0
    assert "case 53" in monitor
    assert "onEscape" in monitor
    assert "isEscapeReservedByPresentedUI" in monitor
    assert "帮助" not in monitor
    assert "overlay" not in monitor.lower() or "No help overlay" in monitor
    assert "精准" not in monitor

    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "取消" in bar
    assert "isWritingDeliverables" in bar
    assert "cancelLockedDeliverables" in bar
    assert "keyboardShortcut" not in bar
    assert "处理已锁定片段" in bar

    preview = content.split("struct SplitPreview")[1].split("struct StatusBar")[0]
    assert 'Button(' not in preview
    assert "取消" not in preview

    assert "PairedIDTBar" in content
    assert "session.setIDT" in inspector
    assert 'Button("锁 IDT")' not in sidebar
    assert 'Button("锁定")' not in sidebar
    assert "isWritingDeliverables" in clip
    assert "isExporting" in clip

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "ACCEPTANCE.md").read_text(encoding="utf-8")
    assert "Escape while writing" in readme
    assert "idle Escape does nothing" in readme
    assert "Escape while writing" in acceptance
    assert "idle Escape does nothing" in acceptance or "Idle Escape does nothing" in acceptance
    assert "已取消" in readme and "整段代理，不是全精度成片" in readme
    assert "已取消" in acceptance and "整段代理，不是全精度成片" in acceptance


def test_import_lands_on_first_pending():
    """Mixed drop selects first pending/unlocked. All-locked keeps first/existing. No new button."""
    clip = _read(CLIP)
    import_fn = clip.split("func importURL")[1].split("private static let clipExtensions")[0]
    assert "built.first(where:" in import_fn
    assert "!$0.hasLockedPair" in import_fn
    assert "selectedID" in import_fn
    assert "selectedID == nil" in import_fn
    assert "setIDT" not in import_fn
    assert "processLockedClips" not in import_fn
    assert "processSelected" not in import_fn
    assert "exportResolve" not in import_fn
    assert "精准" not in import_fn
    cap = clip.split("var previewCaption")[1].split("var displayCurve")[0]
    assert "processSkipReason ?? exportChip" in cap
    assert 'return "先选择 Log 与色域"' not in cap
    assert 'return "先选择成对 IDT"' not in cap
    content = _read(CONTENT)
    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "PairedIDTBar" in content
    assert "isExporting" in clip
    assert "isWritingDeliverables" in clip


def test_selected_clip_glanceable_on_preview():
    """Selected clip 待选 / 失败 / 已写出代理 on preview chrome. No new buttons."""
    content = _read(CONTENT)
    clip = _read(CLIP)
    sidebar = _read(SWIFT_ROOT / "LogBridge/LogBridge/Views/ClipSidebarView.swift")

    cap = clip.split("var previewCaption")[1].split("var displayCurve")[0]
    assert "processSkipReason ?? exportChip" in cap
    assert 'return "先选择 Log 与色域"' not in cap
    assert 'return "先选择成对 IDT"' not in cap
    assert '"先选择 Log 与色域"' not in cap
    assert '"先选择成对 IDT"' not in cap
    skip = clip.split("var processSkipReason")[1].split("var verificationBadge")[0]
    assert "先选择成对 IDT" in skip
    assert "先选择 Log 与色域" in skip
    assert "exportChip" in cap
    assert "已写出代理" in clip
    assert "重试" not in cap
    assert "精准" not in cap

    preview = content.split("struct SplitPreview")[1].split("struct StatusBar")[0]
    assert "previewCaption" in preview
    assert "WriteProgressLine" in preview
    assert "isExporting" in preview
    assert "lastExportNote" in preview
    assert preview.index("isExporting") < preview.index("previewCaption")
    assert 'Button(' not in preview
    assert "重试" not in preview
    assert "取消" not in preview
    assert "处理已锁定片段" not in preview
    assert "精准" not in preview
    line = content.split("struct WriteProgressLine")[1].split("struct StatusBar")[0]
    assert line.count("Button(") == 0
    assert "重试" not in line
    assert "ProgressView" not in line
    assert "Text(text)" in line

    bar = content.split("struct ProcessLockedBar")[1].split("struct AdvancedPanel")[0]
    assert bar.count("Button(") == 1
    assert "showsProcessLockedButton" in bar
    assert "lockedClipCount" in clip
    assert "重试" not in bar

    row = sidebar.split("struct ClipRow")[1]
    assert "exportChip" in row
    assert "已写出代理" in row
    assert 'Button("重试")' not in sidebar
    assert "精准" not in sidebar

    assert "整段代理，不是全精度成片" in content
    assert "预览·非成片" in _all_swift()
    assert PREVIEW_STATUS_ODT_OFF in clip
    assert "成片预览关" not in clip


def test_forbidden_marketing_copy_stays_forbidden():
    swift = _all_swift()
    docs = (ROOT / "README.md").read_text(encoding="utf-8") + (ROOT / "ACCEPTANCE.md").read_text(
        encoding="utf-8"
    )
    tests = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("*.py"))
    for token in ("一键还原", "一键校准", "全自动校准", "全格式已支持"):
        assert token in tests  # prohibition named in tests
        if token in swift:
            assert "不写" in swift or "never" in swift.lower() or "Never" in swift
    assert "精准" in tests
    assert "全格式已支持" in docs  # named as out of scope / do not write
