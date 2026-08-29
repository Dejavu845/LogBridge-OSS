"""Review lock: root LICENSE is MIT; copyright is LogBridge contributors."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"
COPYRIGHT = "Copyright (c) 2026 LogBridge contributors"

# Personal-name / identifier copyright is forbidden on LICENSE.
BANNED_IN_LICENSE = (
    "Dejavu",
    "Dejavu845",
    "Phillip",
    "Hopkins",
    "@",
    "微信",
    "WeChat",
    "weixin",
    "/Users/",
    "/home/",
)


def test_license_is_mit_contributors_not_personal():
    assert LICENSE.is_file()
    text = LICENSE.read_text(encoding="utf-8")
    assert "MIT License" in text
    assert COPYRIGHT in text
    copyright_lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith("Copyright (c)")
    ]
    assert copyright_lines == [COPYRIGHT]
    for token in BANNED_IN_LICENSE:
        assert token not in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "MIT" in readme
