"""Unit tests for StudySynth master dashboard index.html generator."""
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

from dashboard import generate_dashboard_html, update_dashboard, read_dashboard_entries


class TestDashboard(unittest.TestCase):
    def test_generate_dashboard_html_structure(self):
        modules = [
            {
                "title": "Assam Geography v2",
                "rel_path": "assam-geography-module.html",
                "question_count": 64,
                "status": "Comprehensive",
                "updated_at": "2026-10-09 10:00:00",
                "profile": "GENERAL_PSC"
            }
        ]
        html = generate_dashboard_html(modules)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("StudySynth", html)
        self.assertIn("Assam Geography v2", html)
        self.assertIn("assam-geography-module.html", html)
        self.assertIn("Launch Module", html)
        self.assertIn("64 questions", html)
        # Verify quiz purging in UI
        self.assertNotIn(">Quiz<", html)

    def test_update_dashboard_creates_and_upserts(self):
        with tempfile.TemporaryDirectory() as tmp:
            dash_path = Path(tmp) / "index.html"
            mod_path = Path(tmp) / "modules" / "assam-geography-module.html"
            mod_path.parent.mkdir(parents=True, exist_ok=True)
            mod_path.write_text("<html>Module</html>", encoding="utf-8")

            # First insertion
            update_dashboard(
                dashboard_path=str(dash_path),
                module_path=str(mod_path),
                title="Assam Geography v2",
                metadata={"question_count": 64, "status": "Comprehensive"}
            )
            self.assertTrue(dash_path.exists())
            entries = read_dashboard_entries(str(dash_path))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["title"], "Assam Geography v2")

            # Second insertion (upsert same module path)
            update_dashboard(
                dashboard_path=str(dash_path),
                module_path=str(mod_path),
                title="Assam Geography v2 Updated",
                metadata={"question_count": 70, "status": "Comprehensive"}
            )
            entries_after = read_dashboard_entries(str(dash_path))
            self.assertEqual(len(entries_after), 1)
            self.assertEqual(entries_after[0]["title"], "Assam Geography v2 Updated")
            self.assertEqual(entries_after[0]["question_count"], 70)

            # Insert second distinct module
            mod_path_2 = Path(tmp) / "modules" / "polity-module.html"
            mod_path_2.write_text("<html>Polity</html>", encoding="utf-8")
            update_dashboard(
                dashboard_path=str(dash_path),
                module_path=str(mod_path_2),
                title="Polity Governance",
                metadata={"question_count": 45}
            )
            entries_multi = read_dashboard_entries(str(dash_path))
            self.assertEqual(len(entries_multi), 2)
            titles = {e["title"] for e in entries_multi}
            self.assertIn("Assam Geography v2 Updated", titles)
            self.assertIn("Polity Governance", titles)


if __name__ == "__main__":
    unittest.main()
