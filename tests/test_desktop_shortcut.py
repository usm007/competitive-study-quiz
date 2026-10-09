"""Unit tests for StudySynth cross-platform desktop shortcut generator."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from desktop_shortcut import (
    get_desktop_dir,
    _create_windows_url_fallback,
    _create_macos_shortcut,
    _create_linux_shortcut,
    create_desktop_shortcut
)


class TestDesktopShortcut(unittest.TestCase):
    def test_get_desktop_dir(self):
        desktop = get_desktop_dir()
        self.assertIsNotNone(desktop)
        self.assertTrue(isinstance(desktop, Path))

    def test_create_windows_url_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index.html"
            target.write_text("<html>Dashboard</html>", encoding="utf-8")
            shortcut = Path(tmp) / "StudySynth.url"
            res = _create_windows_url_fallback(target, shortcut)
            self.assertEqual(res, shortcut)
            self.assertTrue(shortcut.exists())
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("[InternetShortcut]", content)
            self.assertIn(target.as_uri(), content)

    def test_create_macos_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index.html"
            target.write_text("<html>Dashboard</html>", encoding="utf-8")
            shortcut = Path(tmp) / "StudySynth.webloc"
            res = _create_macos_shortcut(target, shortcut)
            self.assertEqual(res, shortcut)
            self.assertTrue(shortcut.exists())
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("<plist", content)
            self.assertIn(target.as_uri(), content)

    def test_create_linux_shortcut(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index.html"
            target.write_text("<html>Dashboard</html>", encoding="utf-8")
            shortcut = Path(tmp) / "StudySynth.desktop"
            res = _create_linux_shortcut(target, shortcut, "StudySynth Library")
            self.assertEqual(res, shortcut)
            self.assertTrue(shortcut.exists())
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("[Desktop Entry]", content)
            self.assertIn("Type=Link", content)
            self.assertIn(target.as_uri(), content)

    def test_create_desktop_shortcut_in_custom_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "index.html"
            target.write_text("<html>Dashboard</html>", encoding="utf-8")
            custom_dir = Path(tmp) / "Desktop"
            custom_dir.mkdir()
            created = create_desktop_shortcut(str(target), name="TestStudySynth", desktop_dir=str(custom_dir))
            self.assertIsNotNone(created)
            self.assertTrue(Path(created).exists())


if __name__ == "__main__":
    unittest.main()
