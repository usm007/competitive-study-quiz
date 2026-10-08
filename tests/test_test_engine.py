"""Phase 3 tests: deterministic test engine (scripts/test_engine.py).

Covers spec section 45 items 1-8, 12-18, 20-28, 30 (browser-covered items
9-11, 19, 29 live in tests/test_test_browser.py; parity in the JS section
below via tests/parity_test_engine.js).
Runnable via `python tests/test_test_engine.py` and `python -m unittest discover tests`.
Uses only examples/ + temp dirs; stdlib unittest + subprocess.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
PY = sys.executable

import test_engine as T


def run(*args):
    p = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=300)
    return p


def sample_bank():
    pkg = json.loads((ROOT / "examples" / "sample_package.json").read_text(encoding="utf-8"))
    return pkg["questions"]


def sample_valid_ids():
    return {q["id"] for q in sample_bank()}


def sample_kus():
    inv = json.loads((ROOT / "examples" / "sample_inventory.json").read_text(encoding="utf-8"))
    units = inv.get("units") if isinstance(inv, dict) else inv
    return {u["id"]: u for u in units}


def tiny_bank():
    """12 questions: 2 topics x 3 difficulties x 2 types, deterministic ids."""
    qs = []
    topics = ["Polity", "Geography"]
    diffs = ["easy", "medium", "hard"]
    types = ["factual_mcq", "statement_based"]
    n = 0
    for t in topics:
        for d in diffs:
            for y in types:
                n += 1
                qid = "Q-T%02d" % n
                qs.append({
                    "id": qid, "type": y, "stem": "Stem %s about %s/%s." % (qid, t, d),
                    "topic": t, "difficulty": d, "purpose": "direct_recall",
                    "origin": "source", "answer": "A",
                    "knowledge_units": [{"ku_id": "KU-%04d" % n, "role": "primary"}],
                    "source": [{"page": 1, "section_path": "S%d>sub" % (1 if t == "Polity" else 2),
                                "block_id": "B-%04d" % n, "char_start": 0, "char_end": 5,
                                "table_ref": None}],
                    "options": [
                        {"key": "A", "text": "right %s" % qid, "is_correct": True,
                         "distractor_origin": "source_ku", "confusion_type": "near_synonym",
                         "ku_ref": "KU-%04d" % n},
                        {"key": "B", "text": "wrong %s" % qid, "is_correct": False,
                         "distractor_origin": "source_ku", "confusion_type": "wrong_date",
                         "ku_ref": "KU-%04d" % n},
                        {"key": "C", "text": "other %s" % qid, "is_correct": False,
                         "distractor_origin": "source_ku", "confusion_type": "partial_truth",
                         "ku_ref": None},
                        {"key": "D", "text": "another %s" % qid, "is_correct": False,
                         "distractor_origin": "source_ku", "confusion_type": "overgeneralization",
                         "ku_ref": None},
                    ],
                    "statements": None, "explanation": "exp %s" % qid,
                })
    return qs


def tiny_valid(qs=None):
    return {q["id"]: True for q in (qs or tiny_bank())}


def base_config(**over):
    cfg, errs = T.validate_config({
        "title": "T", "exam_profile": "GENERAL_PSC", "question_count": 6,
        "duration_minutes": 12, "marks_per_correct": 1.0,
        "negative_marking": {"enabled": True, "penalty_fraction": 0.25},
        "selection": "BALANCED", "seed": 20261007,
    })
    assert not errs, errs
    cfg.update(over)
    return cfg


class TestRNG(unittest.TestCase):
    def test_hash_stable(self):
        self.assertEqual(T.xfnv1a("abc"), T.xfnv1a("abc"))
        self.assertNotEqual(T.xfnv1a("abc"), T.xfnv1a("abd"))
        self.assertTrue(0 <= T.xfnv1a("abc") <= 0xFFFFFFFF)

    def test_shuffle_deterministic(self):
        a = T.RNG(7).shuffle(list(range(20)))
        b = T.RNG(7).shuffle(list(range(20)))
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), list(range(20)))
        c = T.RNG(8).shuffle(list(range(20)))
        self.assertNotEqual(a, c)

    def test_string_seed(self):
        self.assertEqual(T.RNG("s").shuffle([1, 2, 3]), T.RNG("s").shuffle([1, 2, 3]))


class TestConfig(unittest.TestCase):
    def test_valid_config(self):
        cfg, errs = T.validate_config({"question_count": 10, "duration_minutes": 20})
        self.assertEqual(errs, [])
        self.assertEqual(cfg["question_count"], 10)
        self.assertEqual(cfg["seed"], T.DEFAULT_SEED)

    def test_invalid_fields(self):
        cfg, errs = T.validate_config({
            "question_count": 0, "duration_minutes": -5, "marks_per_correct": 0,
            "negative_marking": {"enabled": True, "penalty_fraction": -1},
            "max_attempts": 0, "topics": "Polity",
            "difficulty": {"easy": 50, "medium": 60}, "qtypes": {},
            "selection": "MAYBE", "exclude_ids": "Q-1", "bogus": 1,
            "blueprint": [{"count": 0}],
        })
        for needle in ["question_count", "duration_minutes", "marks_per_correct",
                       "penalty_fraction", "max_attempts", "topics must be a list",
                       "difficulty must sum", "qtypes must be", "selection must be",
                       "exclude_ids", "unknown configuration"]:
            self.assertTrue(any(needle in e for e in errs), (needle, errs))

    def test_blueprint_requires_mode(self):
        _, errs = T.validate_config({"selection": "BALANCED",
                                     "blueprint": [{"count": 2}]})
        self.assertTrue(any("CUSTOM_BLUEPRINT" in e for e in errs))
        _, errs2 = T.validate_config({"selection": "CUSTOM_BLUEPRINT",
                                      "blueprint": [{"count": 0}]})
        self.assertTrue(any("needs count" in e for e in errs2))

    def test_profile_rules_surface_verified(self):
        prof = {"name": "X", "negative_marking": {"enabled": True, "penalty_fraction": 0.5, "verified": True}}
        r = T.resolve_rules(prof, {"marks_per_correct": 2.0,
                                   "negative_marking": {"enabled": True, "penalty_fraction": 0.5}})
        self.assertEqual(r["marks_per_correct"], 2.0)
        self.assertEqual(r["penalty_fraction"], 0.5)
        self.assertTrue(r["profile_verified"])
        r2 = T.resolve_rules({"negative_marking": {"enabled": False, "penalty_fraction": 0.25}}, {})
        self.assertEqual(r2["penalty_fraction"], 0)
        self.assertFalse(r2["negative_marking"])


class TestAssembly(unittest.TestCase):
    def test_deterministic_paper(self):
        qs = tiny_bank()
        cfg = base_config(question_count=6)
        p1, e1 = T.assemble(qs, tiny_valid(qs), cfg)
        p2, e2 = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertEqual(e1, [])
        self.assertEqual(p1["question_ids"], p2["question_ids"])
        self.assertEqual(p1["test_id"], p2["test_id"])
        self.assertEqual(p1["test_version"], 1)

    def test_seed_changes_order(self):
        qs = tiny_bank()
        a, _ = T.assemble(qs, tiny_valid(qs), base_config(question_count=6, seed=1))
        b, _ = T.assemble(qs, tiny_valid(qs), base_config(question_count=6, seed=2))
        self.assertNotEqual(a["question_ids"], b["question_ids"])

    def test_exact_count_and_validated_only(self):
        qs = tiny_bank()
        valid = tiny_valid(qs)
        valid.pop("Q-T01")
        cfg = base_config(question_count=6)
        p, errs = T.assemble(qs, valid, cfg)
        self.assertEqual(errs, [])
        self.assertEqual(len(p["question_ids"]), 6)
        self.assertNotIn("Q-T01", p["question_ids"])
        self.assertEqual(len(set(p["question_ids"])), 6)

    def test_balanced_topics(self):
        qs = tiny_bank()
        p, _ = T.assemble(qs, tiny_valid(qs), base_config(question_count=6))
        by = p["stats"]["by_topic"]
        self.assertEqual(by, {"Geography": 3, "Polity": 3})

    def test_difficulty_mix(self):
        qs = tiny_bank()
        cfg = base_config(question_count=6, difficulty={"easy": 50, "medium": 50, "hard": 0})
        p, _ = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertEqual(p["stats"]["by_difficulty"], {"easy": 3, "medium": 3})

    def test_type_mix(self):
        qs = tiny_bank()
        cfg = base_config(question_count=6, qtypes={"factual_mcq": 100, "statement_based": 0})
        p, _ = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertEqual(p["stats"]["by_type"], {"factual_mcq": 6})

    def test_random_mode(self):
        qs = tiny_bank()
        p, _ = T.assemble(qs, tiny_valid(qs), base_config(question_count=6, selection="RANDOM", seed=5))
        self.assertEqual(len(p["question_ids"]), 6)

    def test_custom_blueprint(self):
        qs = tiny_bank()
        cfg = base_config(question_count=4, selection="CUSTOM_BLUEPRINT",
                          blueprint=[{"topic": "Polity", "difficulty": "easy", "count": 2},
                                     {"topic": "Geography", "difficulty": "hard", "count": 2}])
        p, errs = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertEqual(errs, [])
        self.assertEqual(len(p["question_ids"]), 4)
        by_id = {q["id"]: q for q in qs}
        topics = sorted(by_id[i]["topic"] for i in p["question_ids"])
        diffs = sorted(by_id[i]["difficulty"] for i in p["question_ids"])
        self.assertEqual(topics, ["Geography", "Geography", "Polity", "Polity"])
        self.assertEqual(diffs, ["easy", "easy", "hard", "hard"])

    def test_blueprint_shortfall_explains(self):
        qs = tiny_bank()
        cfg = base_config(question_count=4, selection="CUSTOM_BLUEPRINT",
                          blueprint=[{"topic": "Nope", "count": 2}])
        p, errs = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertIsNone(p)
        self.assertTrue(any("blueprint row 0" in e for e in errs))

    def test_insufficient_never_silent(self):
        qs = tiny_bank()[:4]
        cfg = base_config(question_count=6)
        p, errs = T.assemble(qs, tiny_valid(qs), cfg)
        self.assertIsNone(p)
        self.assertTrue(any("insufficient" in e for e in errs))

    def test_exclude_reuse_honest(self):
        qs = tiny_bank()
        valid = tiny_valid(qs)
        cfg = base_config(question_count=10,
                          exclude_ids=["Q-T%02d" % i for i in range(1, 7)])
        p, errs = T.assemble(qs, valid, cfg)
        self.assertEqual(errs, [])
        self.assertEqual(len(p["question_ids"]), 10)
        self.assertTrue(p["reused_from_excluded"])

    def test_section_cap(self):
        qs = []
        for i in range(8):
            q = dict(tiny_bank()[0])
            q = {**q, "id": "Q-S%02d" % i,
                 "source": [{"page": 1, "section_path": ["Big" if i < 4 else "Small"],
                             "block_id": "B", "char_start": 0, "char_end": 1, "table_ref": None}]}
            qs.append(q)
        valid = {q["id"]: True for q in qs}
        p, errs = T.assemble(qs, valid, base_config(question_count=6))
        self.assertEqual(errs, [])
        self.assertLessEqual(p["stats"]["by_section"]["Big"], 3)


class TestPretest(unittest.TestCase):
    def test_rejects_unvalidated_dup_unknown(self):
        qs = tiny_bank()
        dupe = dict(qs[0])
        bad = dict(qs[1])
        bad["type"] = "future_hologram"
        vals = [{"id": q["id"], "status": "validated"} for q in qs] + \
               [{"id": qs[0]["id"], "status": "rejected"}]
        ok, errs = T.pretest_check(qs + [dupe, bad], {"results": vals},
                                   base_config(question_count=4))
        self.assertFalse(ok)
        self.assertTrue(any("not validated" in e for e in errs))
        self.assertTrue(any("duplicate" in e for e in errs))
        self.assertTrue(any("future_hologram" in e for e in errs))

    def test_ok_path(self):
        qs = tiny_bank()
        ok, errs = T.pretest_check(qs, tiny_valid(qs), base_config(question_count=4))
        self.assertTrue(ok, errs)


class TestScoring(unittest.TestCase):
    def rules(self, penalty=0.25, marks=1.0, enabled=True):
        return {"marks_per_correct": marks, "penalty_fraction": penalty,
                "negative_marking": enabled}

    def test_third_penalty_exact(self):
        # exact thirds require exact configuration ("1/3", not float 1/3)
        paper = {"question_ids": ["Q1", "Q2", "Q3", "Q4"],
                 "rules": self.rules(penalty="1/3")}
        qs = {qid: {"id": qid, "type": "factual_mcq",
                    "options": [{"key": "A", "is_correct": True},
                                {"key": "B", "is_correct": False}],
                    "answer": "A"} for qid in ["Q1", "Q2", "Q3", "Q4"]}
        s = T.score_session(paper, {"Q1": "A", "Q2": "A", "Q3": "B", "Q4": "B"}, qs)
        self.assertEqual(s["correct"], 2)
        self.assertEqual(s["incorrect"], 2)
        self.assertEqual(s["positive"], Fraction(2, 1))
        self.assertEqual(s["penalty_total"], Fraction(2, 3))
        self.assertEqual(s["final"], Fraction(4, 3))
        self.assertEqual(T.fmt_frac(s["final"]), "1.3")

    def test_no_negative_when_disabled(self):
        paper = {"question_ids": ["Q1"], "rules": self.rules(enabled=False)}
        qs = {"Q1": {"id": "Q1", "type": "true_false",
                     "options": [{"key": "A", "is_correct": False},
                                 {"key": "B", "is_correct": True}],
                     "answer": "B"}}
        s = T.score_session(paper, {"Q1": "A"}, qs)
        self.assertEqual(s["penalty_total"], Fraction(0, 1))
        self.assertEqual(s["final"], Fraction(0, 1))

    def test_unanswered_neutral(self):
        paper = {"question_ids": ["Q1", "Q2"], "rules": self.rules()}
        qs = {"Q1": {"id": "Q1", "type": "match_pairs",
                     "options": [{"key": "A", "is_correct": True}], "answer": "A"},
              "Q2": {"id": "Q2", "type": "match_pairs",
                     "options": [{"key": "A", "is_correct": True}], "answer": "A"}}
        s = T.score_session(paper, {"Q1": None}, qs)
        self.assertEqual((s["correct"], s["incorrect"], s["unanswered"]), (0, 0, 2))
        self.assertIsNone(s["accuracy"])
        s2 = T.score_session(paper, {"Q1": "A", "Q2": "B"}, qs)
        self.assertEqual(s2["accuracy"], Fraction(1, 2))

    def test_all_supported_types_score(self):
        for i, t in enumerate(T.SUPPORTED_TYPES):
            qid = "Q%d" % i
            paper = {"question_ids": [qid], "rules": self.rules()}
            qs = {qid: {"id": qid, "type": t,
                        "options": [{"key": "A", "is_correct": True},
                                    {"key": "B", "is_correct": False}],
                        "answer": "A"}}
            s = T.score_session(paper, {qid: "A"}, qs)
            self.assertEqual(s["correct"], 1, t)

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            T.scoring_rule_for("future_hologram")

    def test_fmt_cases(self):
        self.assertEqual(T.fmt_frac(Fraction(59, 1)), "59")
        self.assertEqual(T.fmt_frac(Fraction(117, 2)), "58.5")
        self.assertEqual(T.fmt_frac(Fraction(-3, 4)), "-0.8")
        self.assertEqual(T.fmt_frac(None), "-")


class TestSessions(unittest.TestCase):
    def paper(self):
        return {"test_id": "T-1-abc", "test_version": 1, "seed": 1,
                "config": {"duration_minutes": 30, "exam_profile": "X"},
                "rules": {"marks_per_correct": 1.0, "penalty_fraction": 0.25,
                          "negative_marking": True},
                "question_ids": ["Q1", "Q2"]}

    def test_timer_math(self):
        s = T.new_test_session(self.paper(), {}, 1_000_000)
        self.assertEqual(s["expires_at"], 1_000_000 + 30 * 60000)
        self.assertEqual(T.remaining_ms(s, 1_000_000 + 60_000), 29 * 60000)
        self.assertFalse(T.is_expired(s, 1_000_000))
        self.assertTrue(T.is_expired(s, 1_000_000 + 30 * 60000))
        self.assertEqual(T.remaining_ms(s, 1_000_000 + 99 * 60000), 0)

    def test_invalid_timestamps_safe(self):
        s = {"expires_at": "junk"}
        self.assertEqual(T.remaining_ms(s, 1_000_000), 0)
        self.assertTrue(T.is_expired(s, 1_000_000))

    def test_finalize_freezes(self):
        s = T.new_test_session(self.paper(), {}, 1_000_000)
        s["answers"] = {"Q1": {"sel": "A"}}
        s["marked"] = ["Q2"]
        qs = {"Q1": {"id": "Q1", "type": "factual_mcq",
                     "options": [{"key": "A", "is_correct": True}], "answer": "A",
                     "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}],
                     "topic": "Polity"},
              "Q2": {"id": "Q2", "type": "factual_mcq",
                     "options": [{"key": "A", "is_correct": True}], "answer": "A",
                     "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}],
                     "topic": "Polity"}}
        r1 = T.finalize_session(s, qs, 1_600_000, "submitted")
        self.assertTrue(s["submitted"])
        self.assertEqual(r1["submit_reason"], "submitted")
        self.assertEqual(r1["score"]["correct"], 1)
        s["answers"]["Q2"] = {"sel": "A"}
        r2 = T.finalize_session(s, qs, 1_700_000, "submitted")
        self.assertIs(r2, r1)

    def test_confirm_summary(self):
        s = T.new_test_session(self.paper(), {}, 1_000_000)
        s["answers"] = {"Q1": {"sel": "A"}, "Q2": {}}
        s["marked"] = ["Q2"]
        c = T.confirm_summary(s)
        self.assertEqual(c, {"answered": 1, "unanswered": 1, "marked": 1, "total": 2})


class TestAnalysis(unittest.TestCase):
    def setUp(self):
        self.qs = {
            "Q1": {"id": "Q1", "type": "factual_mcq", "topic": "Polity",
                   "difficulty": "easy", "purpose": "direct_recall",
                   "confusion_cluster": "CL-A",
                   "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}],
                   "options": [{"key": "A", "is_correct": True}], "answer": "A"},
            "Q2": {"id": "Q2", "type": "factual_mcq", "topic": "Polity",
                   "difficulty": "easy", "purpose": "direct_recall",
                   "confusion_cluster": "CL-A",
                   "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}],
                   "options": [{"key": "A", "is_correct": True}], "answer": "A"},
            "Q3": {"id": "Q3", "type": "statement_based", "topic": "Geo",
                   "difficulty": "hard", "purpose": "statement_evaluation",
                   "knowledge_units": [{"ku_id": "KU-2", "role": "primary"}],
                   "options": [{"key": "A", "is_correct": True}], "answer": "A"},
        }
        self.paper = {"question_ids": ["Q1", "Q2", "Q3"],
                      "rules": {"marks_per_correct": 1.0, "penalty_fraction": 0.25,
                                "negative_marking": True}}
        self.answers = {
            "Q1": {"sel": "B", "conf": "Certain", "marked": False, "dt_ms": 5000},
            "Q2": {"sel": "B", "conf": "Certain", "marked": False, "dt_ms": 9000},
            "Q3": {"sel": None, "marked": True, "dt_ms": 7000},
        }
        self.kus = {"KU-1": {"id": "KU-1", "tier": 1}, "KU-2": {"id": "KU-2", "tier": 2}}

    def test_ku_grouping_four_to_one(self):
        a = T.analyze_results(self.paper, self.answers, self.qs, self.kus)
        gaps = {g["ku_id"]: g for g in a["ku_gaps"]}
        self.assertEqual(gaps["KU-1"]["misses"], 2)
        self.assertEqual(sorted(gaps["KU-1"]["question_ids"]), ["Q1", "Q2"])
        self.assertEqual(a["tier1_misses"], ["KU-1"])
        self.assertNotIn("KU-2", [g["ku_id"] for g in a["ku_gaps"]])

    def test_hce_neutral(self):
        a = T.analyze_results(self.paper, self.answers, self.qs, self.kus)
        self.assertEqual(len(a["high_confidence_errors"]), 2)
        texts = json.dumps(a)
        self.assertNotIn("careless", texts.lower())

    def test_unanswered_listed_not_blamed(self):
        a = T.analyze_results(self.paper, self.answers, self.qs, self.kus)
        self.assertEqual(a["unanswered_kus"], ["KU-2"])
        self.assertNotIn("KU-2", [g["ku_id"] for g in a["ku_gaps"]])

    def test_time_analysis(self):
        a = T.analyze_results(self.paper, self.answers, self.qs, self.kus)
        self.assertEqual(a["time"]["samples"], 3)
        self.assertIn("slowest", a["time"])
        a2 = T.analyze_results(self.paper, {}, self.qs, self.kus)
        self.assertEqual(a2["time"]["note"], "insufficient timing samples")

    def test_observations_gated(self):
        a = T.analyze_results(self.paper, self.answers, self.qs, self.kus)
        codes = [o["code"] for o in a["observations"]]
        self.assertEqual(sorted(codes), ["hce_rate", "high_unanswered", "marked_unresolved"])
        a2 = T.analyze_results(
            {"question_ids": ["Q1"], "rules": self.paper["rules"]},
            {"Q1": {"sel": "A", "conf": "Guessing", "marked": False, "dt_ms": 1000}},
            {"Q1": self.qs["Q1"]}, self.kus)
        self.assertEqual(a2["observations"], [])


class TestRetake(unittest.TestCase):
    def test_new_version_disjoint(self):
        qs = tiny_bank()
        cfg = base_config(question_count=6)
        p1, _ = T.assemble(qs, tiny_valid(qs), cfg)
        p2, errs = T.retake_paper(p1, qs, tiny_valid(qs), None)
        self.assertEqual(errs, [])
        self.assertEqual(p2["test_version"], 2)
        self.assertEqual(p2["retake_of"], p1["test_id"])
        self.assertNotEqual(p2["seed"], p1["seed"])
        self.assertEqual(set(p2["question_ids"]).intersection(p1["question_ids"]), set())
        self.assertEqual(p2["stats"]["by_topic"], p1["stats"]["by_topic"])

    def test_retake_seed_helper(self):
        self.assertEqual(T.retake_seed(7), 8)
        self.assertEqual(T.retake_seed("7"), 8)
        self.assertEqual(T.retake_seed("abc"), "abc-r2")


class TestRevisionHandoff(unittest.TestCase):
    def test_events_feed_phase2(self):
        import revision as R
        result = {
            "question_ids": ["Q1", "Q2"],
            "answers": {
                "Q1": {"sel": "B", "conf": "Certain", "correct": False,
                       "distype": "wrong_date", "primary_ku": "KU-1",
                       "marked": False, "time": 1700000000},
                "Q2": {"sel": "A", "conf": "Unsure", "correct": True,
                       "primary_ku": "KU-2", "time": 1700000060},
            },
        }
        qs = [{"id": "Q1", "type": "factual_mcq", "purpose": "direct_recall",
               "knowledge_units": [{"ku_id": "KU-1", "role": "primary"}]},
              {"id": "Q2", "type": "factual_mcq", "purpose": "direct_recall",
               "knowledge_units": [{"ku_id": "KU-2", "role": "primary"}]}]
        evs = T.events_from_result(result, qs)
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["primary_ku"], "KU-1")
        self.assertEqual(evs[0]["mode"], "test")
        qmap = {q["id"]: q for q in qs}
        aggs = R.aggregate(evs, qmap)
        queue = R.build_queue(aggs, [], qs)
        self.assertEqual(queue[0]["ku_id"], "KU-1")
        self.assertIn("high_confidence_error", queue[0]["reasons"])


class TestPrintConsistency(unittest.TestCase):
    def test_paper_order_survives_pdf(self):
        import subprocess
        pkg = json.loads((ROOT / "examples" / "sample_package.json").read_text(encoding="utf-8"))
        valid = {q["id"]: True for q in pkg["questions"]}
        cfg, errs = T.validate_config({"title": "Print check", "question_count": 12,
                                       "duration_minutes": 20, "selection": "BALANCED",
                                       "seed": 99})
        self.assertEqual(errs, [])
        paper, perrs = T.assemble(pkg["questions"], valid, cfg)
        self.assertEqual(perrs, [])
        sub = T.filter_package_to_paper(pkg, paper)
        self.assertEqual([q["id"] for q in sub["questions"]], paper["question_ids"])
        with tempfile.TemporaryDirectory() as tmp:
            subp = Path(tmp) / "paper_pkg.json"
            subp.write_text(json.dumps(sub), encoding="utf-8")
            r = run("scripts/build_pdf.py", str(subp), "--out", tmp,
                    "--profile", "profiles/GENERAL_PSC.json")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = run("scripts/check_pdf.py",
                    str(Path(tmp) / "question-paper-A.pdf"),
                    str(Path(tmp) / "answer-key-B.pdf"),
                    str(Path(tmp) / "explanations-C.pdf"),
                    "--package", str(subp),
                    "--report", str(Path(tmp) / "check.json"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            # answer key follows the exact paper order
            from pypdf import PdfReader
            btext = "\n".join(p.extract_text() or ""
                              for p in PdfReader(str(Path(tmp) / "answer-key-B.pdf")).pages)
            import re
            rows = re.findall(r"Q(\d+)\s+\S+\s+([A-F])\b", btext)
            self.assertEqual(len(rows), 12)
            for (num, key), qid in zip(rows, paper["question_ids"]):
                q = next(q for q in sub["questions"] if q["id"] == qid)
                self.assertEqual(key, T.q_correct_key(q))


if __name__ == "__main__":
    unittest.main(verbosity=2)
