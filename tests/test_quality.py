"""Question Quality Regression Tests (Phase 3).

Tests the 15 required quality checks:
1. ambiguous question rejection
2. double-correct rejection
3. no-correct rejection
4. unsupported-fact rejection
5. poor-distractor detection
6. answer-length clue detection
7. semantic duplicate detection
8. purpose mismatch detection
9. weak statement detection
10. false-statement alteration validation
11. explanation quality requirements
12. source provenance requirements
13. cognitive-level mismatch
14. trivial-question warning
15. competitive-exam quality review (full benchmark fixture evaluation)
"""
import copy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import quality as qmod
import dedupe as dmod
from lib_common import norm


def make_valid_q(qid="Q-TEST", ku_id="KU-0003", purpose="direct_recall", qtype="factual_mcq", diff="easy"):
    return {
        "id": qid,
        "type": qtype,
        "purpose": purpose,
        "stem": "Which body is included in the definition of State under Article 12?",
        "options": [
            {
                "key": "A",
                "text": "Government and Parliament of India",
                "is_correct": True,
                "distractor_origin": "source_ku",
                "confusion_type": "near_synonym",
                "ku_ref": ku_id,
                "distractor_purpose": None
            },
            {
                "key": "B",
                "text": "Private commercial companies without state share",
                "is_correct": False,
                "distractor_origin": "source_ku",
                "confusion_type": "wrong_category",
                "ku_ref": ku_id,
                "distractor_purpose": "wrong_category"
            },
            {
                "key": "C",
                "text": "Foreign diplomatic missions in India",
                "is_correct": False,
                "distractor_origin": "source_ku",
                "confusion_type": "wrong_entity",
                "ku_ref": ku_id,
                "distractor_purpose": "wrong_entity"
            },
            {
                "key": "D",
                "text": "International non-governmental organizations",
                "is_correct": False,
                "distractor_origin": "source_ku",
                "confusion_type": "scope_error",
                "ku_ref": ku_id,
                "distractor_purpose": "scope_error"
            }
        ],
        "answer": "A",
        "difficulty": diff,
        "cognitive_level": "recall",
        "origin": "source",
        "statements": None,
        "knowledge_units": [{"ku_id": ku_id, "role": "primary"}],
        "source": [{
            "page": 1,
            "section_path": "Polity",
            "block_id": "B-0001",
            "char_start": 0,
            "char_end": 50,
            "table_ref": None
        }],
        "explanation": "Article 12 provides that State includes the Government and Parliament of India and local authorities.",
        "memory_aid": None,
        "hint": None,
        "topic": "Polity",
        "exam_profile": "APSC_PRELIMS",
        "language": "en"
    }


class TestQualityEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fix_dir = HERE / "fixtures"
        with open(cls.fix_dir / "quality_benchmark_inventory.json", encoding="utf-8") as fh:
            cls.inv = json.load(fh)
        with open(cls.fix_dir / "quality_benchmark_struct.json", encoding="utf-8") as fh:
            cls.st = json.load(fh)
        cls.ku_ids = {u["id"] for u in cls.inv["units"]}
        cls.ku_map = {u["id"]: u.get("supporting_excerpt", "") for u in cls.inv["units"]}
        cls.block_ids = {b["id"] for b in cls.st["blocks"]}
        cls.ntext = norm(cls.st["normalized_text"])

    def eval_q(self, q, seen=None):
        return qmod.evaluate_question(
            q, self.ku_ids, self.ku_map, self.block_ids, self.ntext,
            mode="SOURCE_BOUND", seen_bank=seen or []
        )

    # 1. Ambiguous question rejection
    def test_01_ambiguous_question_rejection(self):
        q = make_valid_q()
        q["stem"] = "Which is true?"
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["clarity"]["status"], "FAIL")
        self.assertTrue(any("vague" in r or "ambiguous" in r for r in res["rejection_reasons"]))

    # 2. Double-correct rejection
    def test_02_double_correct_rejection(self):
        q = make_valid_q()
        q["options"][1]["is_correct"] = True  # Both A and B are True
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["accuracy"]["status"], "FAIL")
        self.assertTrue(any("single_select" in r for r in res["rejection_reasons"]))

    # 3. No-correct rejection
    def test_03_no_correct_rejection(self):
        q = make_valid_q()
        for o in q["options"]:
            o["is_correct"] = False
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["accuracy"]["status"], "FAIL")
        self.assertTrue(any("single_select" in r for r in res["rejection_reasons"]))

    # 4. Unsupported-fact rejection
    def test_04_unsupported_fact_rejection(self):
        q = make_valid_q()
        q["knowledge_units"] = [{"ku_id": "KU-NONEXISTENT", "role": "primary"}]
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["source_support"]["status"], "FAIL")
        self.assertTrue(any("missing or unknown" in r for r in res["rejection_reasons"]))

    # 5. Poor-distractor detection
    def test_05_poor_distractor_detection(self):
        q = make_valid_q()
        q["options"][1]["text"] = "Mars rover launched into space"
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["distractor_quality"]["status"], "FAIL")
        self.assertTrue(any("absurd distractor indicator" in r for r in res["rejection_reasons"]))

    # 6. Answer-length clue detection
    def test_06_answer_length_clue_detection(self):
        q = make_valid_q()
        # Make key option overwhelmingly longer
        q["options"][0]["text"] = "The Government and Parliament of India, together with each State Legislature and all statutory authorities constituted under central or state enactments across India"
        q["options"][1]["text"] = "Courts"
        q["options"][2]["text"] = "Police"
        q["options"][3]["text"] = "Banks"
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["leak_prevention"]["status"], "FAIL")
        self.assertTrue(any("answer leak: key option is substantially longer" in r for r in res["rejection_reasons"]))

    # 7. Semantic duplicate detection
    def test_07_semantic_duplicate_detection(self):
        q1 = make_valid_q("Q-1")
        q2 = make_valid_q("Q-2")
        # Identical question text with minor spacing
        q2["stem"] = "Which body is included in the definition of State under Article 12 ?"
        res = self.eval_q(q2, seen=[q1])
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["uniqueness"]["status"], "FAIL")
        self.assertTrue(any("exact stem duplicate" in r or "duplicate" in r for r in res["rejection_reasons"]))

    # 8. Purpose mismatch detection
    def test_08_purpose_mismatch_detection(self):
        q = make_valid_q()
        # Marked distinction, but asking single date without comparison
        q["purpose"] = "distinction"
        q["stem"] = "In which year was Article 21A enacted?"
        q["options"] = [
            {"key": "A", "text": "2002", "is_correct": True, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0005"},
            {"key": "B", "text": "2000", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "wrong_date", "ku_ref": "KU-0005"},
            {"key": "C", "text": "2004", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "wrong_date", "ku_ref": "KU-0005"},
            {"key": "D", "text": "2006", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "wrong_date", "ku_ref": "KU-0005"}
        ]
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["purpose_fit"]["status"], "FAIL")
        self.assertTrue(any("purpose mismatch" in r for r in res["rejection_reasons"]))

    # 9. Weak statement detection
    def test_09_weak_statement_detection(self):
        q = make_valid_q(qtype="statement_based", purpose="statement_evaluation")
        q["statements"] = [{"text": "Only one statement here without truth mark"}]
        q["options"] = [
            {"key": "A", "text": "1 only", "is_correct": True, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": [1]},
            {"key": "B", "text": "Neither 1 nor 2", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": []}
        ]
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["statement_quality"]["status"], "FAIL")
        self.assertTrue(any(">= 2 statements" in r for r in res["rejection_reasons"]))

    # 10. False-statement alteration validation
    def test_10_false_statement_alteration_validation(self):
        q = make_valid_q(qtype="statement_based", purpose="statement_evaluation")
        q["statements"] = [
            {"text": "State includes Parliament of India.", "truth_value": True, "ku_basis": "KU-0003"},
            {"text": "State excludes local authorities.", "truth_value": False, "ku_basis": "KU-0003"}  # missing alteration_type
        ]
        q["options"] = [
            {"key": "A", "text": "1 only", "is_correct": True, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": [1]},
            {"key": "B", "text": "2 only", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": [2]},
            {"key": "C", "text": "Both 1 and 2", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": [1, 2]},
            {"key": "D", "text": "Neither 1 nor 2", "is_correct": False, "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": "KU-0003", "covers": []}
        ]
        res = self.eval_q(q)
        # Warning about missing alteration_type
        self.assertTrue(any("alteration_type" in w for w in res["warnings"]))

    # 11. Explanation quality requirements
    def test_11_explanation_quality_requirements(self):
        q = make_valid_q()
        q["explanation"] = "Option A is correct because it is given in the document."
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["explanation_quality"]["status"], "FAIL")
        self.assertTrue(any("lazy boilerplate explanation" in r for r in res["rejection_reasons"]))

    # 12. Source provenance requirements
    def test_12_source_provenance_requirements(self):
        q = make_valid_q()
        q["source"] = [{"page": 1, "section_path": "Polity", "block_id": "B-UNRESOLVED", "char_start": 0, "char_end": 50, "table_ref": None}]
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["source_support"]["status"], "FAIL")
        self.assertTrue(any("unresolved source blocks" in r for r in res["rejection_reasons"]))

    # 13. Cognitive-level / difficulty mismatch
    def test_13_cognitive_difficulty_mismatch(self):
        q = make_valid_q(diff="hard")
        # Hard difficulty on a simple factual MCQ with no statements or complex distinction
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["difficulty_fit"]["status"], "FAIL")
        self.assertTrue(any("fake difficulty" in r for r in res["rejection_reasons"]))

    # 14. Trivial-question warning / rejection
    def test_14_trivial_question_warning(self):
        q = make_valid_q()
        q["stem"] = "What color was the ink used to sign the constitutional notes?"
        res = self.eval_q(q)
        self.assertEqual(res["quality_status"], "rejected")
        self.assertEqual(res["grade"], "D")
        self.assertEqual(res["checks"]["exam_value"]["status"], "FAIL")
        self.assertTrue(any("trivial non-examinable" in r for r in res["rejection_reasons"]))

    # 15. Competitive-exam quality review (benchmark fixture evaluation)
    def test_15_competitive_exam_quality_benchmark(self):
        bench_path = self.fix_dir / "quality_benchmark.json"
        with open(bench_path, encoding="utf-8") as fh:
            bank = json.load(fh)
        rep = qmod.evaluate_bank(bank, self.inv, self.st)
        s = rep["summary"]

        # Exactly the 1 good question passes; all 13 bad questions are rejected
        self.assertEqual(s["quality_accepted"], 1)
        self.assertEqual(s["quality_rejected"], 13)
        self.assertEqual(s["grades"]["A"], 1)
        self.assertGreaterEqual(s["grades"].get("D", 0), 11)

        # Confirm each bad question got caught
        by_id = {r["id"]: r for r in rep["results"]}
        self.assertEqual(by_id["GOOD-01"]["quality_status"], "accepted")
        self.assertEqual(by_id["GOOD-01"]["grade"], "A")

        self.assertEqual(by_id["BAD-01-TWO-CORRECT"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-02-NO-CORRECT"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-03-ABSURD-DISTRACTOR"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-04-ANSWER-LENGTH-CLUE"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-05-TRIVIAL-QUESTION"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-06-AMBIGUOUS-STEM"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-07-UNSUPPORTED-FACT"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-08-MISLEADING-STATEMENT"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-09-DUPLICATE-B"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-10-FAKE-DIFFICULTY"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-11-WEAK-EXPLANATION"]["quality_status"], "rejected")
        self.assertEqual(by_id["BAD-12-PURPOSE-MISMATCH"]["quality_status"], "rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
