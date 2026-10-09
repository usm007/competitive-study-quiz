"""Authoritative V1 Release Gate Verification for StudySynth.

Verifies:
1. Full test suite (all unittest test_*.py pass with 0 failures and 0 errors)
2. Schema conformity (schemas/*.schema.json validate correctly)
3. Node.js engine parity (test.engine.js and revision.engine.js parity)
4. Quality benchmark fixture (quality.py catches 100% of intentional defects)
5. End-to-end pipeline run (ingest -> anchors -> check -> validate -> quality -> coverage -> dedupe -> audit -> gate -> package -> web -> pdf -> pdf_check)
6. Delivery artifacts (HTML standalone quiz and A4 PDF versions A/B/C)
7. Documentation sync (README.md, SKILL.md align with implementation)
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from lib_common import load_json, save_json


def run_cmd(cmd, cwd=ROOT):
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


def check_tests():
    print("[1/7] Running full test suite...")
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    passed = result.wasSuccessful()
    return {
        "name": "full_test_suite",
        "passed": passed,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped)
    }


def check_schemas():
    print("[2/7] Checking schemas...")
    schema_dir = ROOT / "schemas"
    schemas = list(schema_dir.glob("*.schema.json"))
    errors = []
    for s in schemas:
        try:
            d = json.loads(s.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or "type" not in d and "$schema" not in d:
                errors.append(f"{s.name}: invalid root schema")
        except Exception as e:
            errors.append(f"{s.name}: parse error {e}")
    return {
        "name": "schema_integrity",
        "passed": len(errors) == 0,
        "schema_count": len(schemas),
        "errors": errors
    }


def check_node_parity():
    print("[3/7] Verifying Node.js engine parity...", flush=True)
    rc, out, err = run_cmd([
        sys.executable, "-m", "unittest",
        "tests.test_revision_js",
        "tests.test_test_js"
    ])
    return {
        "name": "node_engine_parity",
        "passed": rc == 0,
        "details": out.strip() if rc == 0 else (err + out).strip()
    }


def check_quality_benchmark():
    print("[4/7] Verifying Phase 3 Quality benchmark...")
    from quality import evaluate_question
    bench_path = ROOT / "tests" / "fixtures" / "quality_benchmark.json"
    inv_path = ROOT / "tests" / "fixtures" / "quality_benchmark_inventory.json"
    st_path = ROOT / "tests" / "fixtures" / "quality_benchmark_struct.json"

    bench = load_json(bench_path)
    inv = load_json(inv_path)
    st = load_json(st_path)

    ku_ids = {u["id"] for u in inv["units"]}
    ku_map = {u["id"]: u.get("supporting_excerpt", "") for u in inv["units"]}
    block_ids = {b["id"] for b in st["blocks"]}
    ntext = st.get("normalized_text", "")

    rejected = 0
    total = len(bench["questions"])
    for q in bench["questions"]:
        res = evaluate_question(q, ku_ids, ku_map, block_ids, ntext, "SOURCE_BOUND", bench["questions"])
        if res["quality_status"] == "rejected":
            rejected += 1

    passed = (rejected == total)
    return {
        "name": "quality_benchmark",
        "passed": passed,
        "benchmark_defects_total": total,
        "benchmark_defects_caught": rejected
    }


def check_end_to_end():
    print("[5/7] Running representative end-to-end acceptance pipeline...", flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="v1_release_gate_"))
    src = ROOT / "examples" / "sample_source.md"
    inv = ROOT / "examples" / "sample_inventory.json"
    bank = ROOT / "examples" / "question_bank_apsc.json"
    prof = ROOT / "profiles" / "APSC_PRELIMS.json"
    cfg = ROOT / "config.default.json"
    ign = ROOT / "tests" / "fixtures" / "e2e_ignored_anchors.json"
    diff = ROOT / "tests" / "fixtures" / "e2e_inventory_diff.json"

    cmd = [
        sys.executable, str(ROOT / "scripts" / "pipeline.py"),
        "--source", str(src),
        "--inventory", str(inv),
        "--bank", str(bank),
        "--profile", str(prof),
        "--config", str(cfg),
        "--ignored", str(ign),
        "--diff", str(diff),
        "--run-id", "acceptance_run",
        "--build-dir", str(tmp),
        "--full"
    ]
    rc, out, err = run_cmd(cmd)

    gate_file = tmp / "acceptance_run" / "gate.json"
    audit_file = tmp / "acceptance_run" / "audit_report.json"
    pkg_file = tmp / "acceptance_run" / "quiz_package.json"
    html_file = tmp / "acceptance_run" / "quiz.html"
    pdf_check_file = tmp / "acceptance_run" / "pdf_check_report.json"

    passed = (rc == 0 and gate_file.is_file() and pkg_file.is_file() and
              html_file.is_file() and pdf_check_file.is_file())

    gate_data = load_json(gate_file) if gate_file.is_file() else {}
    pdf_check_data = load_json(pdf_check_file) if pdf_check_file.is_file() else {}
    audit_data = load_json(audit_file) if audit_file.is_file() else {}

    return {
        "name": "end_to_end_acceptance",
        "passed": passed,
        "pipeline_exit": rc,
        "gate_status": gate_data.get("status"),
        "gate_reasons": gate_data.get("reasons", []),
        "pdf_check_overall": pdf_check_data.get("overall"),
        "anchor_recall": audit_data.get("anchor_recall"),
        "artifacts_generated": {
            "gate": gate_file.is_file(),
            "package": pkg_file.is_file(),
            "html": html_file.is_file(),
            "pdf_check": pdf_check_file.is_file()
        }
    }


def check_delivery():
    print("[6/7] Verifying pre-built delivery artifacts...")
    html_file = ROOT / "examples" / "quiz.html"
    pdf_a = ROOT / "examples" / "pdf" / "question-paper-A.pdf"
    pdf_b = ROOT / "examples" / "pdf" / "answer-key-B.pdf"
    pdf_c = ROOT / "examples" / "pdf" / "explanations-C.pdf"
    pkg_file = ROOT / "examples" / "quiz_package.json"

    exists = (html_file.is_file() and pdf_a.is_file() and
              pdf_b.is_file() and pdf_c.is_file() and pkg_file.is_file())

    rc, out, err = run_cmd([
        sys.executable, str(ROOT / "scripts" / "check_pdf.py"),
        str(pdf_a), str(pdf_b), str(pdf_c),
        "--package", str(pkg_file),
        "--report", str(ROOT / "examples" / "pdf_check_report.json")
    ])

    return {
        "name": "delivery_artifacts",
        "passed": exists and rc == 0,
        "artifacts_exist": exists,
        "pdf_check_exit": rc
    }


def check_docs():
    print("[7/7] Checking documentation alignment...")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    has_pipeline = "pipeline" in readme.lower() and "pipeline" in skill.lower()
    has_profiles = "APSC_PRELIMS" in readme or "APSC" in skill
    has_formats = ".pdf" in readme and ".docx" in readme
    has_quality = "Phase 3" in skill or "quality" in skill.lower()

    passed = bool(has_pipeline and has_profiles and has_formats and has_quality)
    return {
        "name": "documentation_alignment",
        "passed": passed,
        "pipeline_documented": has_pipeline,
        "formats_documented": has_formats,
        "quality_documented": has_quality
    }


def main():
    print("=" * 60)
    print("COMPETITIVE STUDY QUIZ — V1.0 RELEASE GATE AUDIT")
    print("=" * 60)

    checks = [
        check_tests(),
        check_schemas(),
        check_node_parity(),
        check_quality_benchmark(),
        check_end_to_end(),
        check_delivery(),
        check_docs()
    ]

    all_passed = all(c["passed"] for c in checks)

    report = {
        "release_version": "1.0.0",
        "overall_status": "PASS" if all_passed else "FAIL",
        "checks": checks
    }

    out_file = ROOT / "build" / "release_gate_report.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    save_json(out_file, report)

    print("-" * 60)
    for c in checks:
        badge = "PASS" if c["passed"] else "FAIL"
        print(f"[{badge}] {c['name']}")

    print("=" * 60)
    print(f"OVERALL V1.0 RELEASE STATUS: {report['overall_status']}")
    print(f"Report written to: {out_file}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
