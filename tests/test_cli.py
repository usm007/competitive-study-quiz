"""CLI/integration tests: full pipeline, web build, OCR path, non-Latin.

Runnable via `python tests/test_cli.py` and `python -m unittest discover tests`.
Uses only examples/ + temp dirs; stdlib unittest + subprocess.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable


def run(*args):
    p = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=300)
    return p


class TestPipelineCLI(unittest.TestCase):
    def test_full_chain_comprehensive(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("scripts/pipeline.py", "--source", "examples/sample_source.md",
                    "--run-id", "t1", "--profile", "profiles/GENERAL_PSC.json",
                    "--config", "config.default.json", "--build-dir", tmp,
                    "--inventory", str(ROOT / "examples/sample_inventory.json"),
                    "--bank", str(ROOT / "examples/sample_bank.json"),
                    "--ignored", str(ROOT / "tests/fixtures/e2e_ignored_anchors.json"),
                    "--diff", str(ROOT / "tests/fixtures/e2e_inventory_diff.json"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            gate = json.loads(Path(tmp, "t1", "gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["status"], "COMPREHENSIVE", gate)
            audit = json.loads(Path(tmp, "t1", "audit_report.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["coverage_by_tier"]["1"]["pct_covered"], 100.0)

    def test_pipeline_resume_skips_done_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            a1 = run("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", "t2", "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", tmp)
            self.assertEqual(a1.returncode, 0, a1.stdout + a1.stderr)
            a2 = run("scripts/pipeline.py", "--source", "examples/sample_source.md",
                     "--run-id", "t2", "--profile", "profiles/GENERAL_PSC.json",
                     "--config", "config.default.json", "--build-dir", tmp)
            self.assertEqual(a2.returncode, 0, a2.stdout + a2.stderr)
            state = json.loads(Path(tmp, "t2", "pipeline_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stages"]["ingest"]["status"], "skipped")
            self.assertEqual(state["stages"]["anchors"]["status"], "skipped")


class TestWebBuild(unittest.TestCase):
    def test_web_standalone_parses_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, "quiz.html"))
            r = run("scripts/build_web.py", "examples/sample_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = Path(out).read_text(encoding="utf-8")
            i = html.find("__PACKAGE__")
            self.assertNotEqual(i, -1, "embedded package block missing")
            j = html.find("{", i)
            depth, k = 0, j
            while k < len(html):
                if html[k] == "{":
                    depth += 1
                elif html[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            pkg = json.loads(html[j:k + 1])
            self.assertEqual(len(pkg["questions"]), 64)
            ext = re.findall(r"https?://[^\s\"'<>]+", html)
            ext = [u for u in ext if "w3.org" not in u]
            self.assertEqual(ext, [], "external network dependency found")

    def test_web_session_export_shape(self):
        pkg = json.loads((ROOT / "examples/sample_package.json").read_text(encoding="utf-8"))
        q = pkg["questions"][0]
        for f in ("id", "type", "stem", "options", "answer", "knowledge_units",
                  "source", "explanation", "attempt_count", "correct_count",
                  "last_attempted", "last_result", "confidence"):
            self.assertIn(f, q, f)


class TestIngestLimits(unittest.TestCase):
    def test_image_input_yields_unreliable(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            img = str(Path(tmp, "scan.png"))
            Image.new("RGB", (200, 100), "white").save(img)
            r = run("scripts/ingest.py", img, "--out", tmp, "--run-id", "ocr")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            st = json.loads(Path(tmp, "ocr", "document_structure.json").read_text(encoding="utf-8"))
            self.assertEqual(st["extraction_status"], "unreliable")
            self.assertTrue(st["limitations"])

    def test_non_latin_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "ne.md")
            src.write_text("# \u09ac\u09cd\u09b0\u09b9\u09cd\u09ae\u09aa\u09c1\u09a4\u09cd\u09b0\n\n"
                           "\u09ac\u09cd\u09b0\u09b9\u09cd\u09ae\u09aa\u09c1\u09a4\u09cd\u09b0\u09f0 \u09a6\u09c8\u09f0\u09cd\u0998\u09cd\u09af \u09e8\u09ef\u09e6\u09e6 \u0995\u09bf\u09ae\u09bf\u0964\n",
                           encoding="utf-8")
            r = run("scripts/ingest.py", str(src), "--out", tmp, "--run-id", "ne")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            st = json.loads(Path(tmp, "ne", "document_structure.json").read_text(encoding="utf-8"))
            langs = {b["language"] for b in st["blocks"] if b["text"].strip()}
            self.assertIn("bn", langs, langs)

    def test_gate_limited_on_unreliable(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 1},
                 "skew_flags": [], "duplicate_flags": [],
                 "limitations": ["page 3 image-only table could not be extracted"]}
        with tempfile.TemporaryDirectory() as tmp:
            ap = Path(tmp, "audit.json")
            ap.write_text(json.dumps(audit), encoding="utf-8")
            r = run("scripts/gate.py", str(ap), "--out", tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            gate = json.loads(Path(tmp, "gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["status"], "LIMITED", gate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
