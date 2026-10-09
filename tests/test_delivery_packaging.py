"""Tests for final user delivery packaging and deterministic validation.

Verifies:
1. Strict 2-file delivery contract (exactly 1 PDF, exactly 1 HTML, 0 extra files or JSONs).
2. Sanitization of human-readable document titles.
3. Unified mode cross-document unification (deduplication, provenance, merged excerpts).
4. Individual mode numbering (01_, 02_) when multiple documents are provided.
5. Both mode directory tree layout (Individual/ and Unified/).
6. Standalone HTML anti-dependency validation (no external scripts, styles, CDNs, fetch).
7. Single combined PDF integrity (readable pages, valid header).
8. CLI executables for package_delivery.py and validate_package_delivery.py.
9. Pipeline integration (--deliver flag).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from package_delivery import sanitize_name, unify_packages, execute_packaging
from validate_package_delivery import validate_package, validate_delivery_dir, validate_html_standalone, validate_pdf


def run(*args):
    return subprocess.run(
        [PY] + [str(a) for a in args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=300,
    )


class TestDeliverySanitization(unittest.TestCase):
    def test_sanitize_name_cleanups(self):
        self.assertEqual(sanitize_name("sample_source.pdf"), "Sample_Source_Quiz")
        self.assertEqual(sanitize_name("Indian Polity-Notes.docx"), "Indian_Polity_Notes_Quiz")
        self.assertEqual(sanitize_name("Modern History Quiz"), "Modern_History_Quiz")
        self.assertEqual(sanitize_name("custom_master", default_suffix="Master"), "Custom_Master")
        self.assertEqual(sanitize_name(""), "Study_Quiz")


class TestDeliveryUnification(unittest.TestCase):
    def setUp(self):
        self.pkg1 = {
            "meta": {"title": "Doc 1", "source": "doc1.md", "profile": "GENERAL_PSC"},
            "questions": [
                {
                    "id": "Q001",
                    "stem": "What is the capital of Assam?",
                    "options": ["Dispur", "Guwahati", "Silchar", "Tezpur"],
                    "correct_idx": 0,
                    "explanation": "Dispur is the capital.",
                    "anchor_text": "Dispur is the capital of Assam.",
                },
                {
                    "id": "Q002",
                    "stem": "Which river flows through Assam?",
                    "options": ["Brahmaputra", "Ganga", "Yamuna", "Godavari"],
                    "correct_idx": 0,
                    "explanation": "Brahmaputra flows through Assam.",
                    "anchor_text": "The Brahmaputra river flows through Assam.",
                },
            ],
            "ku_excerpts": {"KU1": "Excerpt 1"},
        }
        self.pkg2 = {
            "meta": {"title": "Doc 2", "source": "doc2.md", "profile": "GENERAL_PSC"},
            "questions": [
                {
                    "id": "Q101",
                    "stem": "What is the capital of Assam?",  # duplicate question
                    "options": ["Dispur", "Guwahati", "Silchar", "Tezpur"],
                    "correct_idx": 0,
                    "explanation": "Dispur is the capital.",
                    "anchor_text": "Dispur is the capital of Assam.",
                },
                {
                    "id": "Q102",
                    "stem": "Kaziranga National Park is famous for what animal?",
                    "options": ["One-horned rhino", "Bengal tiger", "Asian elephant", "Snow leopard"],
                    "correct_idx": 0,
                    "explanation": "Kaziranga is famous for the great Indian one-horned rhinoceros.",
                    "anchor_text": "Kaziranga is famous for one-horned rhinos.",
                },
            ],
            "ku_excerpts": {"KU2": "Excerpt 2"},
        }

    def test_unify_dedupes_and_tracks_provenance(self):
        unified = unify_packages([self.pkg1, self.pkg2], master_title="Combined Exam Quiz")
        meta = unified["meta"]
        self.assertEqual(meta["title"], "Combined Exam Quiz")
        self.assertEqual(meta["sources"], ["Doc 1", "Doc 2"])

        # There were 4 questions total, 1 exact duplicate -> should have 3 questions left
        questions = unified["questions"]
        self.assertEqual(len(questions), 3)
        self.assertEqual(meta["deduped_count"], 1)

        # Check provenance stamping
        for q in questions:
            self.assertIn("source_document", q)
            self.assertIn("original_id", q)
            self.assertTrue(q["id"].startswith("Q"))

        # Check merged excerpts
        self.assertIn("KU1", unified["ku_excerpts"])
        self.assertIn("KU2", unified["ku_excerpts"])


class TestDeliveryValidation(unittest.TestCase):
    def test_package_validator_clean_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            # Create a mock valid HTML with inlined tokens
            sample_pkg = ROOT / "examples/sample_package.json"
            pkg_data = sample_pkg.read_text(encoding="utf-8")
            html_content = (
                "<!DOCTYPE html><html><head><style>:root { --bg: #fff; --ink: #000; --accent: #f60; --line: #ccc; }</style></head>"
                "<body><div id='app'></div><script>/*__PACKAGE__*/" + pkg_data + "\n"
                "class RevisionEngine{}; function normOptions(){}; function render(){};</script></body></html>"
            )
            html_file = p / "Test_Quiz.html"
            html_file.write_text(html_content, encoding="utf-8")

            # Create a mock valid PDF file using pypdf
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
            pdf_file = p / "Test_Quiz.pdf"
            c = canvas.Canvas(str(pdf_file), pagesize=letter)
            c.drawString(100, 700, "Mock Test PDF")
            c.showPage()
            c.save()

            ok, errors = validate_package(p)
            self.assertTrue(ok, f"Validation failed unexpectedly: {errors}")

    def test_package_validator_detects_forbidden_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "Test.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
            (p / "Test.pdf").write_text("%PDF-1.4\n...", encoding="utf-8")
            (p / "quiz_package.json").write_text("{}", encoding="utf-8")  # forbidden json
            (p / "assets").mkdir()  # forbidden subdirectory

            ok, errors = validate_package(p)
            self.assertFalse(ok)
            error_str = " ".join(errors)
            self.assertIn("Forbidden file in final delivery package: quiz_package.json", error_str)
            self.assertIn("Forbidden subdirectory in final delivery package: assets", error_str)

    def test_html_standalone_detects_external_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_html = Path(tmp) / "bad.html"
            bad_html.write_text(
                "<!DOCTYPE html><html><head>"
                "<link rel='stylesheet' href='https://cdn.example.com/style.css'>"
                "<script src='app.js'></script>"
                "</head><body><img src='logo.png'><script>fetch('/data.json');</script></body></html>",
                encoding="utf-8"
            )
            errors = validate_html_standalone(bad_html)
            err_text = " ".join(errors)
            self.assertIn("External stylesheet link", err_text)
            self.assertIn("External script src", err_text)
            self.assertIn("Unbundled image src", err_text)
            self.assertIn("Runtime fetch()", err_text)


class TestPackagingExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample_pkg = ROOT / "examples/sample_package.json"
        cls.quiz_pkg = ROOT / "examples/quiz_package.json"

    def test_individual_mode_single_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "delivery_individual_single"
            res = execute_packaging(
                package_inputs=[self.sample_pkg],
                out_dir=out_root,
                mode="individual",
            )
            self.assertEqual(len(res["individual"]), 1)
            pkg_folder = Path(res["individual"][0]["folder"])
            self.assertTrue(pkg_folder.is_dir())

            # Verify strictly 2 files
            files = list(pkg_folder.iterdir())
            self.assertEqual(len(files), 2)
            names = {f.suffix for f in files}
            self.assertEqual(names, {".html", ".pdf"})

            # Validate directory tree
            ok, errors = validate_delivery_dir(out_root, mode="individual")
            self.assertTrue(ok, f"Validation failed: {errors}")

    def test_individual_mode_multiple_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "delivery_individual_multi"
            res = execute_packaging(
                package_inputs=[self.quiz_pkg, self.sample_pkg],
                out_dir=out_root,
                mode="individual",
            )
            self.assertEqual(len(res["individual"]), 2)

            # Folders must be numbered 01_ and 02_
            f1 = Path(res["individual"][0]["folder"])
            f2 = Path(res["individual"][1]["folder"])
            self.assertTrue(f1.name.startswith("01_"))
            self.assertTrue(f2.name.startswith("02_"))

            for folder in (f1, f2):
                files = list(folder.iterdir())
                self.assertEqual(len(files), 2)
                self.assertEqual({f.suffix for f in files}, {".html", ".pdf"})

            ok, errors = validate_delivery_dir(out_root, mode="individual")
            self.assertTrue(ok, f"Validation failed: {errors}")

    def test_unified_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "delivery_unified"
            res = execute_packaging(
                package_inputs=[self.quiz_pkg, self.sample_pkg],
                out_dir=out_root,
                mode="unified",
                master_title="Consolidated Exam Master",
            )
            self.assertEqual(len(res["unified"]), 1)
            master_folder = Path(res["unified"][0]["folder"])
            self.assertTrue(master_folder.is_dir())

            # Check 2 files
            files = list(master_folder.iterdir())
            self.assertEqual(len(files), 2)
            self.assertEqual({f.suffix for f in files}, {".html", ".pdf"})

            # Verify PDF opens and has pages
            pdf_path = Path(res["unified"][0]["pdf"])
            reader = PdfReader(str(pdf_path))
            self.assertGreater(len(reader.pages), 0)

            # Validate delivery
            ok, errors = validate_delivery_dir(out_root, mode="unified")
            self.assertTrue(ok, f"Validation failed: {errors}")

    def test_both_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "delivery_both"
            res = execute_packaging(
                package_inputs=[self.quiz_pkg, self.sample_pkg],
                out_dir=out_root,
                mode="both",
                master_title="Combined Master Quiz",
            )
            self.assertTrue((out_root / "Individual").is_dir())
            self.assertTrue((out_root / "Unified").is_dir())

            # Individual tree has 2 packages
            indiv_dirs = [d for d in (out_root / "Individual").iterdir() if d.is_dir()]
            self.assertEqual(len(indiv_dirs), 2)

            # Unified tree has 1 master package
            unified_dirs = [d for d in (out_root / "Unified").iterdir() if d.is_dir()]
            self.assertEqual(len(unified_dirs), 1)

            ok, errors = validate_delivery_dir(out_root, mode="both")
            self.assertTrue(ok, f"Validation failed: {errors}")


class TestDeliveryCLI(unittest.TestCase):
    def test_package_delivery_cli_and_validator_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            r = run(
                "scripts/package_delivery.py",
                "examples/quiz_package.json",
                "--mode", "individual",
                "--out-dir", str(out_dir),
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            # Run validator CLI on generated output
            v = run("scripts/validate_package_delivery.py", str(out_dir))
            self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
            self.assertIn("PASS:", v.stdout)


class TestPipelineDeliverIntegration(unittest.TestCase):
    def test_pipeline_deliver_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "test_deliv"
            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "examples/sample_package.json", run_dir / "quiz_package.json")
            delivery_dir = Path(tmp) / "delivery"
            r = run(
                "scripts/pipeline.py",
                "--source", "examples/sample_source.md",
                "--run-id", "test_deliv",
                "--profile", "profiles/GENERAL_PSC.json",
                "--config", "config.default.json",
                "--build-dir", tmp,
                "--deliver",
                "--delivery-dir", str(delivery_dir),
                "--delivery-mode", "individual",
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            # Check that final delivery dir is valid and contains only PDF and HTML
            ok, errors = validate_delivery_dir(delivery_dir, mode="individual")
            self.assertTrue(ok, f"Pipeline delivery validation failed: {errors}")


if __name__ == "__main__":
    unittest.main()
