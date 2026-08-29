"""Chinese settings page. No color numbers. No 精准 / 一键还原 / 全自动校准."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "macos/LogBridge/LogBridge/Views/SettingsView.swift"
APP = ROOT / "macos/LogBridge/LogBridge/Models/AppSettings.swift"
CLIP = ROOT / "macos/LogBridge/LogBridge/Models/Clip.swift"
SIDEBAR = ROOT / "macos/LogBridge/LogBridge/Views/ClipSidebarView.swift"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_settings_copy_is_chinese():
    s = _read(SETTINGS)
    assert "默认预览" in s
    assert "Rec.709 预览·非成片" in s
    assert "Rec.2100 HLG 预览·非成片" in s
    assert "Rec.2100 PQ 预览·非成片" in s
    assert "导入后提示估计白平衡" in s
    assert "未锁 IDT 挡住处理" in s
    assert "不能关" in s
    assert "不猜 5600" in s
    assert "不是校准" in s
    assert "精准" not in s or "不写精准" in s
    assert "一键还原" not in s or "不写" in s
    assert "全自动校准" not in s or "不写" in s
    assert "已实现（未验证）" in s
    assert "implemented (unverified)" not in s.lower()


def test_settings_defaults_locked():
    app = _read(APP)
    clip = _read(CLIP)
    assert "defaultPreviewODT" in app
    assert ".rec709" in app
    assert "promptEstimateWBOnImport" in app
    assert "blockUnlockedIDT: Bool = true" in app
    assert "lastExportDirectoryPath" in app
    assert "logbridge.lastExportDirectory" in app
    assert "rememberExportDirectory" in app
    assert "graph.odt = settings.defaultPreviewODT" in clip
    assert "promptEstimateWBOnImport" in clip
    assert "confirmAutoWB" not in clip.split("promptEstimateWBOnImport")[1].split("refreshPreview")[0]
    assert "5600" in clip
    assert "showSettings" in clip


def test_settings_button_and_block_cannot_disable():
    sidebar = _read(SIDEBAR)
    settings = _read(SETTINGS)
    clip = _read(CLIP)
    assert 'Button("设置")' in sidebar
    assert ".disabled(true)" in settings
    assert "canProcess" in clip
    assert "hasLockedPair" in clip
    assert "先选择 Log 与色域" in clip
