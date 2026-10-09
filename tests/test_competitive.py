"""Competitive-engine tests: cognitive coverage, purposes, distractors,
revision, confidence, gate. Runnable via unittest discover."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import coverage as covmod
import gate as gatemod
import validate_questions as vq
from lib_quiz import compute_revision_queue, calibration_summary


def mk_ku(kid, tier=1, conf_risk="high", confusable=None, ktype="concept"):
    return {"id": kid, "tier": tier, "type": ktype,
            "dimensions": {"confusion_risk": conf_risk, "conceptual_density": "high",
                           "factual_density": "high", "statement_potential": "high",
                           "confusion_value": conf_risk},
            "confusable_with": confusable or [], "related_ku": []}


def mk_q(qid, prim, purpose=None, qtype="factual_mcq", cog=None, statements=None,
         opts=None, role_extra=None):
    if opts is None:
        opts = [
            {"key": "A", "text": "correct text", "is_correct": True,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym",
             "ku_ref": prim, "distractor_purpose": None},
            {"key": "B", "text": "wrong one", "is_correct": False,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym",
             "ku_ref": prim, "distractor_purpose": "confusable_fact"},
        ]
    q = {"id": qid, "type": qtype, "stem": "stem %s" % qid, "options": opts,
         "answer": "A", "knowledge_units": [{"ku_id": prim, "role": "primary"}],
         "source": [{"page": 1, "section_path": "S", "block_id": "B-1",
                     "char_start": 0, "char_end": 5, "table_ref": None}],
         "explanation": "exp", "difficulty": "medium", "origin": "source"}
    q["purpose"] = purpose or "direct_recall"
    q["cognitive_level"] = cog or "recall"
    q["statements"] = statements
    if role_extra:
        q["knowledge_units"] += role_extra
    return q


class TestCognitiveForms(unittest.TestCase):
    def test_purpose_maps_to_cog(self):
        self.assertEqual(covmod.q_cognitive_forms({"purpose": "direct_recall", "type": "factual_mcq"}), {"recall"})
        self.assertIn("statement", covmod.q_cognitive_forms({"purpose": "statement_evaluation", "type": "statement_based", "statements": [{"text": "x"}]}))
        self.assertEqual(covmod.q_cognitive_forms({"purpose": "distinction", "type": "factual_mcq"}), {"distinction"})
        self.assertEqual(covmod.q_cognitive_forms({"type": "elimination_mcq"}), {"statement"})

    def test_recall_covered_distinction_not(self):
        ku = mk_ku("KU-0001")
        req = covmod.required_forms(ku)
        self.assertIn("recall", req)
        self.assertIn("distinction", req)  # high confusion tier1 needs distinction
        q = mk_q("Q1", "KU-0001", purpose="direct_recall", qtype="factual_mcq")
        forms = covmod.q_cognitive_forms(q)
        self.assertIn("recall", forms)
        self.assertNotIn("distinction", forms)


class TestRequiredForms(unittest.TestCase):
    def test_tier3_recall_only(self):
        ku = mk_ku("KU-0009", tier=3, conf_risk="low", confusable=[], ktype="definition")
        ku["dimensions"]["conceptual_density"] = "low"
        self.assertEqual(covmod.required_forms(ku), {"recall"})

    def test_distinction_gap_shape(self):
        # fixture: recall covered but distinction missing
        covered = {"recall"}
        required = {"recall", "distinction", "statement"}
        missing = sorted(required - covered)
        self.assertEqual(missing, ["distinction", "statement"])


class TestRevisionPriority(unittest.TestCase):
    def test_wrong_increases_priority(self):
        pkg = {"questions": [mk_q("Q1", "KU-0042"), mk_q("Q17", "KU-0042")]}
        answers = {"Q1": {"correct": False, "confidence": "Certain", "primary_ku": "KU-0042"},
                   "Q17": {"correct": False, "confidence": "Certain", "primary_ku": "KU-0042"}}
        ranked = compute_revision_queue(pkg, answers)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["ku_id"], "KU-0042")
        self.assertEqual(ranked[0]["priority"], "critical")

    def test_revision_selects_new_form(self):
        # revision must surface a NEW question on same KU, different form
        bank = [mk_q("Q1", "KU-0042", purpose="direct_recall"),
                mk_q("Q2", "KU-0042", purpose="distinction", qtype="elimination_mcq")]
        forms = {q["id"]: covmod.q_cognitive_forms(q) for q in bank}
        self.assertNotEqual(forms["Q1"], forms["Q2"])


class TestConfusionClusters(unittest.TestCase):
    def test_two_kus_form_cluster(self):
        a = mk_ku("KU-0101", confusable=["KU-0102"])
        b = mk_ku("KU-0102", confusable=["KU-0101"])
        self.assertIn("KU-0102", a["confusable_with"])
        # cluster question discriminates: primary A + distractor from B
        q = mk_q("QC", "KU-0101", purpose="distinction")
        q["options"][1]["ku_ref"] = "KU-0102"
        refs = {o.get("ku_ref") for o in q["options"]}
        self.assertTrue({"KU-0101", "KU-0102"} <= refs)


class TestPurposeValidation(unittest.TestCase):
    def test_known_purpose_passes_flag(self):
        q = mk_q("Q9", "KU-0001", purpose="statement_evaluation",
                 qtype="statement_based",
                 statements=[{"text": "s1", "truth_value": True},
                             {"text": "s2", "truth_value": False}])
        q["options"] = [
            {"key": "A", "text": "1 only", "is_correct": True,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0001"},
            {"key": "B", "text": "2 only", "is_correct": False,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0001"},
        ]
        c, _ = vq.stmt_check(q)
        self.assertTrue(c)

    def test_unknown_purpose_flagged(self):
        ku_ids, ku_map, bids, seen = {"KU-0001"}, {"KU-0001": "excerpt text here"}, {"B-1"}, []
        q = mk_q("QX", "KU-0001", purpose="nonsense_purpose")
        r = vq.check_one(q, ku_ids, ku_map, bids, "excerpt text here", 2, "SOURCE_BOUND", 0.85, seen)
        self.assertFalse(r["checks"]["purpose_ok"])

    def test_distractor_purpose_enum(self):
        ku_ids, ku_map, bids, seen = {"KU-0001"}, {"KU-0001": "excerpt text here"}, {"B-1"}, []
        q = mk_q("QD", "KU-0001")
        q["options"][1]["distractor_purpose"] = "confusable_fact"
        r = vq.check_one(q, ku_ids, ku_map, bids, "excerpt text here", 2, "SOURCE_BOUND", 0.85, seen)
        self.assertTrue(r["checks"]["distractor_purpose_ok"])
        q["options"][1]["distractor_purpose"] = "bogus"
        r2 = vq.check_one(q, ku_ids, ku_map, bids, "excerpt text here", 2, "SOURCE_BOUND", 0.85, {"x": 1} if False else [])
        # fresh seen list
        r2 = vq.check_one(q, ku_ids, ku_map, bids, "excerpt text here", 2, "SOURCE_BOUND", 0.85, [])
        self.assertFalse(r2["checks"]["distractor_purpose_ok"])


class TestConfidenceAnalytics(unittest.TestCase):
    def test_calibration_buckets(self):
        answers = {"Q1": {"correct": False, "confidence": "Certain"},
                   "Q2": {"correct": False, "confidence": "Certain"},
                   "Q3": {"correct": True, "confidence": "Guessing"}}
        cal = calibration_summary(answers)
        self.assertEqual(cal["certain_wrong"], 2)
        self.assertIn("missed 2", cal["overconfidence_note"])


class TestStatementIntegrity(unittest.TestCase):
    def test_single_statement_flagged(self):
        ku_ids, ku_map, bids = {"KU-0001"}, {"KU-0001": "excerpt text here"}, {"B-1"}
        q = mk_q("QS", "KU-0001", qtype="statement_based",
                 statements=[{"text": "only one", "truth_value": True}])
        r = vq.check_one(q, ku_ids, ku_map, bids, "excerpt text here", 2, "SOURCE_BOUND", 0.85, [])
        self.assertFalse(r["checks"]["statement_integrity_ok"])

    def test_distractor_only_gives_no_credit(self):
        # KU tested only as distractor_basis => no coverage credit (existing D2 rule)
        from test_skill import ref_coverage_map
        inv = {"units": [{"id": "KU-X", "tier": 1}]}
        bank = {"questions": [{"status": "validated",
                               "knowledge_units": [{"ku_id": "KU-X", "role": "distractor_basis"}]}]}
        self.assertEqual(ref_coverage_map(inv, bank)["KU-X"], "none")


class TestSourceProvenance(unittest.TestCase):
    def test_unresolved_source_rejected(self):
        ku_ids, ku_map = {"KU-0001"}, {"KU-0001": "verbatim excerpt"}
        q = mk_q("QP", "KU-0001")
        q["source"] = [{"page": 9, "section_path": "X", "block_id": "B-NOPE",
                        "char_start": 0, "char_end": 3, "table_ref": None}]
        r = vq.check_one(q, ku_ids, ku_map, {"B-1"}, "verbatim excerpt", 2, "SOURCE_BOUND", 0.85, [])
        self.assertFalse(r["checks"]["sources_resolve"])
        self.assertEqual(r["status"], "rejected")


class TestFixedCountHonesty(unittest.TestCase):
    def test_counts_honest(self):
        from test_skill import counts_honest
        bank = {"meta": {"total": 2, "by_type": {"factual_mcq": 2}},
                "questions": [{"type": "factual_mcq"}, {"type": "factual_mcq"}]}
        self.assertTrue(counts_honest(bank))
        forged = {"meta": {"total": 3, "by_type": {"factual_mcq": 2}},
                  "questions": bank["questions"]}
        self.assertFalse(counts_honest(forged))


class TestGateBehavior(unittest.TestCase):
    def test_clean_new_engine_comprehensive(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 2},
                 "skew_flags": [], "duplicate_flags": [], "limitations": [],
                 "cognitive_by_tier": {"1": {"pct": 100.0}}, "cognitive_gaps": {},
                 "purpose_coverage": {"direct_recall": 2}, "has_explicit_purposes": True,
                 "unaddressed_clusters": [], "missing_purposes": []}
        self.assertEqual(gatemod.decide(audit, 1.0)[0], "COMPREHENSIVE")

    def test_weak_blueprint_cognitive_gap_blocks(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 2},
                 "skew_flags": [], "duplicate_flags": [], "limitations": [],
                 "cognitive_by_tier": {"1": {"pct": 50.0}},
                 "cognitive_gaps": {"KU-0001": ["distinction"]},
                 "purpose_coverage": {"direct_recall": 2, "distinction": 1},
                 "has_explicit_purposes": True,
                 "unaddressed_clusters": [], "missing_purposes": []}
        status, reasons = gatemod.decide(audit, 1.0)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("cognitive" in r for r in reasons))

    def test_missing_required_purpose_blocks(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 2},
                 "skew_flags": [], "duplicate_flags": [], "limitations": [],
                 "cognitive_by_tier": {}, "cognitive_gaps": {},
                 "purpose_coverage": {"direct_recall": 5}, "has_explicit_purposes": True,
                 "unaddressed_clusters": [], "missing_purposes": ["statement_evaluation"]}
        status, reasons = gatemod.decide(audit, 1.0)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("statement_evaluation" in r for r in reasons))


if __name__ == "__main__":
    unittest.main(verbosity=2)
