"""Unit tests for StudySynth naming and slug generation utilities."""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from naming import parse_clean_title, generate_slug


class TestNaming(unittest.TestCase):
    def test_parse_clean_title_basic(self):
        self.assertEqual(parse_clean_title("assam_geography_v2.pdf"), "Assam Geography v2")
        self.assertEqual(parse_clean_title("polity_fundamentals_exam.md"), "Polity Fundamentals Exam")
        self.assertEqual(parse_clean_title("modern_history_notes_pack.json"), "Modern History Notes Pack")

    def test_parse_clean_title_path_handling(self):
        self.assertEqual(parse_clean_title("C:/data/docs/assam_geography_v2.pdf"), "Assam Geography v2")
        self.assertEqual(parse_clean_title("/var/study/environment_ecology.docx"), "Environment Ecology")
        self.assertEqual(parse_clean_title(Path("notes/ancient_india.txt")), "Ancient India")

    def test_parse_clean_title_quiz_purging(self):
        self.assertEqual(parse_clean_title("geography_quiz.pdf"), "Geography Study Module")
        self.assertEqual(parse_clean_title("upsc_quiz_module.md"), "Upsc Study Module")
        self.assertEqual(parse_clean_title("history_quizzes.pdf"), "History Study Modules")

    def test_parse_clean_title_fallback(self):
        self.assertEqual(parse_clean_title(""), "StudySynth Module")
        self.assertEqual(parse_clean_title(".pdf"), "StudySynth Module")
        self.assertEqual(parse_clean_title(None), "StudySynth Module")

    def test_generate_slug_basic(self):
        self.assertEqual(generate_slug("assam_geography_v2.pdf"), "assam-geography-module.html")
        self.assertEqual(generate_slug("Polity Fundamentals.docx"), "polity-fundamentals-module.html")

    def test_generate_slug_custom_suffix(self):
        self.assertEqual(generate_slug("assam_geography_v2.pdf", suffix="practice"), "assam-geography-practice.html")
        self.assertEqual(generate_slug("assam_geography_v2.pdf", suffix=""), "assam-geography.html")
        self.assertEqual(generate_slug("assam_geography_v2.pdf", suffix=None), "assam-geography.html")

    def test_generate_slug_quiz_purging(self):
        slug = generate_slug("assam_quiz.pdf")
        self.assertNotIn("quiz", slug)
        self.assertEqual(slug, "assam-module.html")


if __name__ == "__main__":
    unittest.main()
