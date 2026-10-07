"""Phase 2 tests: deterministic KU-level revision engine.

Covers spec section 30 (18 required behaviours), 31 (compact fixtures),
32 (end-to-end on the sample package), 33 (edge cases) and 37 (acceptance
lifecycle). Node parity tests live in test_revision_js.py.
Runnable via unittest discover.
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import revision as R

NOW = 1700000000.0
DAY = 86400.0


def mk_ku(kid, tier=1, exam_relevance="high", conf_risk="high",
          rev_pri="high", confusable=None, cluster=None, ktype="concept",
          conceptual="high", topic="Polity", subtopic="Basics"):
    return {
        "id": kid, "tier": tier, "type": ktype, "topic": topic,
        "subtopic": subtopic, "statement": "stmt %s" % kid,
        "confusable_with": list(confusable or []),
        "confusion_cluster": cluster, "related_ku": [],
        "dimensions": {"importance": "high", "exam_relevance": exam_relevance,
                       "factual_density": "high", "conceptual_density": conceptual,
                       "confusion_risk": conf_risk, "discrimination_value": "high",
                       "revision_priority": rev_pri},
    }


def mk_q(qid, prim, secondaries=(), purpose="direct_recall", cog="recall",
         qtype="factual_mcq", difficulty="medium", cluster=None, tier=1,
         topic="Polity", origin="source"):
    kus = [{"ku_id": prim, "role": "primary"}]
    kus += [{"ku_id": s, "role": "secondary"} for s in secondaries]
    return {
        "id": qid, "type": qtype, "stem": "stem %s about %s" % (qid, prim),
        "purpose": purpose, "cognitive_level": cog, "difficulty": difficulty,
        "origin": origin, "topic": topic, "tier": tier,
        "confusion_cluster": cluster,
        "knowledge_units": kus,
        "source": [{"page": 1, "section_path": "S", "block_id": "B-1",
                    "char_start": 0, "char_end": 5, "table_ref": None}],
        "options": [
            {"key": "A", "text": "right answer %s" % qid, "is_correct": True,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym",
             "ku_ref": prim, "distractor_purpose": None},
            {"key": "B", "text": "wrong answer %s" % qid, "is_correct": False,
             "distractor_origin": "source_ku", "confusion_type": "near_synonym",
             "ku_ref": prim, "distractor_purpose": "confusable_fact"},
        ],
        "answer": "A", "statements": None,
        "explanation": "exp %s" % qid,
    }


def ev(qid, ku, result, conf="Unsure", days_ago=1, marked=False,
       confusion=None, mode="practice"):
    return {"question_id": qid, "primary_ku": ku, "result": result,
            "confidence": conf, "timestamp": NOW - days_ago * DAY,
            "marked": marked, "confusion_type": confusion, "mode": mode,
            "sel": "A" if result == "correct" else "B"}


def run_events(kus, questions, events):
    qmap = {q["id"]: q for q in questions}
    normed = [R.normalize_event(e, qmap.get(e.get("question_id")), NOW) for e in events]
    return R.aggregate(normed, qmap)


def score_all(kus, questions, events):
    aggs = run_events(kus, questions, events)
    qbyku = R.questions_by_primary(questions)
    out = {}
    for k, a in aggs.items():
        meta = next((u for u in kus if u["id"] == k), None)
        req = R.required_forms_for(k, kus, qbyku)
        out[k] = (R.score_ku(k, a, meta, NOW, None, req), a)
    return out, aggs


def fixture_31():
    """Compact deterministic fixture (§31)."""
    kus = [
        mk_ku("KU-A", tier=1, confusable=["KU-F"], cluster="CL-AF"),
        mk_ku("KU-F", tier=1, confusable=["KU-A"], cluster="CL-AF"),
        mk_ku("KU-B", tier=1),
        mk_ku("KU-C", tier=2, exam_relevance="medium", conf_risk="low",
              rev_pri="medium", ktype="definition", conceptual="low"),
        mk_ku("KU-D", tier=1),
        mk_ku("KU-E", tier=1, cluster="CL-EF"),
    ]
    questions = [
        mk_q("Q-A1", "KU-A"),
        mk_q("Q-A2", "KU-A", purpose="distinction", cog="distinction"),
        mk_q("Q-A2b", "KU-A", purpose="confusable_fact", cog="distinction"),
        mk_q("Q-A3", "KU-A", purpose="statement_evaluation", cog="analysis",
             qtype="statement_based"),
        mk_q("Q-B1", "KU-B"),
        mk_q("Q-C1", "KU-C", tier=2),
        mk_q("Q-D1", "KU-D"),
        mk_q("Q-E1", "KU-E", cluster="CL-EF"),
        mk_q("Q-F1", "KU-F", cluster="CL-AF"),
    ]
    return kus, questions


class TestPriorityBasics(unittest.TestCase):
    def test_single_incorrect_raises_priority(self):
        kus, questions = fixture_31()
        scored, _ = score_all(kus, questions, [ev("Q-B1", "KU-B", "wrong")])
        s = scored["KU-B"][0]
        self.assertGreater(s["score"], 0)
        self.assertIn(s["band"], ("critical", "high", "medium"))
        self.assertIn(R.RECENT_ERROR, s["reasons"])

    def test_no_attempts_no_priority(self):
        kus, questions = fixture_31()
        scored, aggs = score_all(kus, questions, [])
        self.assertEqual(scored, {})
        self.assertEqual(R.build_queue(aggs, kus, questions), [])

    def test_repeated_incorrect_scores_higher(self):
        kus, questions = fixture_31()
        one, _ = score_all(kus, questions, [ev("Q-B1", "KU-B", "wrong", days_ago=1)])
        three, _ = score_all(kus, questions, [ev("Q-B1", "KU-B", "wrong", days_ago=3),
                                             ev("Q-B1", "KU-B", "wrong", days_ago=2),
                                             ev("Q-B1", "KU-B", "wrong", days_ago=1)])
        self.assertGreater(three["KU-B"][0]["score"], one["KU-B"][0]["score"])
        self.assertIn(R.REPEATED_ERROR, three["KU-B"][0]["reasons"])
        self.assertNotIn(R.REPEATED_ERROR, one["KU-B"][0]["reasons"])

    def test_high_confidence_error_elevated(self):
        kus, questions = fixture_31()
        certain, _ = score_all(kus, questions,
                               [ev("Q-D1", "KU-D", "wrong", conf="Certain")])
        unsure, _ = score_all(kus, questions,
                              [ev("Q-D1", "KU-D", "wrong", conf="Unsure")])
        self.assertGreater(certain["KU-D"][0]["score"], unsure["KU-D"][0]["score"])
        self.assertIn(R.HIGH_CONF_ERROR, certain["KU-D"][0]["reasons"])
        self.assertNotIn(R.HIGH_CONF_ERROR, unsure["KU-D"][0]["reasons"])

    def test_correct_reduces_priority(self):
        kus, questions = fixture_31()
        before, _ = score_all(kus, questions, [ev("Q-B1", "KU-B", "wrong", days_ago=2)])
        after, _ = score_all(kus, questions, [ev("Q-B1", "KU-B", "wrong", days_ago=2),
                                              ev("Q-B1", "KU-B", "correct", conf="Certain", days_ago=0.01)])
        self.assertLess(after["KU-B"][0]["score"], before["KU-B"][0]["score"])

    def test_tier1_outranks_tier2_on_identical_miss(self):
        kus = [mk_ku("KU-T1", tier=1), mk_ku("KU-T2", tier=2, exam_relevance="medium",
                                             conf_risk="low", rev_pri="medium",
                                             ktype="definition", conceptual="low")]
        questions = [mk_q("Q-T1", "KU-T1"), mk_q("Q-T2", "KU-T2", tier=2)]
        scored, _ = score_all(kus, questions, [ev("Q-T1", "KU-T1", "wrong"),
                                              ev("Q-T2", "KU-T2", "wrong")])
        self.assertGreater(scored["KU-T1"][0]["score"], scored["KU-T2"][0]["score"])


class TestMastery(unittest.TestCase):
    def test_single_correct_not_stable(self):
        kus, questions = fixture_31()
        scored, aggs = score_all(kus, questions,
                                 [ev("Q-C1", "KU-C", "correct", conf="Certain", days_ago=1)])
        self.assertNotEqual(R.mastery_of("KU-C", aggs["KU-C"]), R.STABLE)
        self.assertEqual(R.mastery_of("KU-C", aggs["KU-C"]), R.LEARNING)

    def test_repeated_success_stable(self):
        ku = mk_ku("KU-S", tier=3, exam_relevance="low", conf_risk="low",
                   rev_pri="low", ktype="definition", conceptual="low")
        q = mk_q("Q-S1", "KU-S", tier=3, topic="Geo")
        events = [ev("Q-S1", "KU-S", "correct", conf="Certain", days_ago=d)
                  for d in (5, 4, 3, 2, 1)]
        aggs = run_events([ku], [q], events)
        req = R.required_forms_for("KU-S", [ku], R.questions_by_primary([q]))
        self.assertEqual(R.mastery_of("KU-S", aggs["KU-S"], ku, NOW, None, req), R.STABLE)

    def test_hce_blocks_stable_allows_improving(self):
        ku = mk_ku("KU-H", tier=3, exam_relevance="low", conf_risk="low",
                   rev_pri="low", ktype="definition", conceptual="low")
        q = mk_q("Q-H1", "KU-H", tier=3, topic="Geo")
        events = [ev("Q-H1", "KU-H", "wrong", conf="Certain", days_ago=10),
                  ev("Q-H1", "KU-H", "correct", conf="Unsure", days_ago=2),
                  ev("Q-H1", "KU-H", "correct", conf="Unsure", days_ago=1)]
        aggs = run_events([ku], [q], events)
        req = R.required_forms_for("KU-H", [ku], R.questions_by_primary([q]))
        m = R.mastery_of("KU-H", aggs["KU-H"], ku, NOW, None, req)
        self.assertEqual(m, R.IMPROVING)

    def test_per_form_mastery(self):
        kus, questions = fixture_31()
        aggs = run_events(kus, questions, [
            ev("Q-A1", "KU-A", "correct", days_ago=3),
            ev("Q-A1", "KU-A", "correct", days_ago=2),
            ev("Q-A2", "KU-A", "wrong", days_ago=1)])
        self.assertEqual(R.form_mastery(aggs["KU-A"], "recall"), R.STABLE)
        self.assertEqual(R.form_mastery(aggs["KU-A"], "distinction"), R.WEAK)
        self.assertEqual(R.form_mastery(aggs["KU-A"], "statement"), R.NEW)

    def test_zero_attempts_new(self):
        self.assertEqual(R.mastery_of("KU-X", None), R.NEW)
        self.assertEqual(R.form_mastery(None, "recall"), R.NEW)


class TestCognitiveRevision(unittest.TestCase):
    def test_recall_strong_distinction_weak_targets_distinction(self):
        kus, questions = fixture_31()
        aggs = run_events(kus, questions, [
            ev("Q-A1", "KU-A", "correct", days_ago=3),
            ev("Q-A1", "KU-A", "correct", days_ago=2),
            ev("Q-A2", "KU-A", "wrong", days_ago=1)])
        qbyku = R.questions_by_primary(questions)
        req = R.required_forms_for("KU-A", kus, qbyku)
        s = R.score_ku("KU-A", aggs["KU-A"], kus[0], NOW, None, req)
        self.assertEqual(s["weak_forms"][0], "distinction")
        pick = R.select_question("KU-A", "distinction", questions,
                                 answered_ids={"Q-A2"})
        self.assertIsNotNone(pick["question_id"])
        chosen = next(q for q in questions if q["id"] == pick["question_id"])
        self.assertNotEqual(chosen["id"], "Q-A2")
        self.assertIn("distinction", R.question_forms(chosen))

    def test_weak_distinction_never_triggers_recall_item(self):
        kus, questions = fixture_31()
        pick = R.select_question("KU-A", "distinction", questions, answered_ids=set())
        chosen = next(q for q in questions if q["id"] == pick["question_id"])
        self.assertIn("distinction", R.question_forms(chosen))
        self.assertNotEqual(R.question_forms(chosen), {"recall"})


class TestConfusionClusters(unittest.TestCase):
    def test_repeated_cluster_errors_create_revision(self):
        kus, questions = fixture_31()
        aggs = run_events(kus, questions, [
            ev("Q-E1", "KU-E", "wrong", confusion="wrong_article", days_ago=2),
            ev("Q-E1", "KU-E", "wrong", confusion="wrong_article", days_ago=1)])
        qbyku = R.questions_by_primary(questions)
        queue = R.build_queue(aggs, kus, questions, NOW)
        entry = next(e for e in queue if e["ku_id"] == "KU-E")
        self.assertIn(R.CONFUSION_CLUSTER, entry["reasons"])
        summary = R.analytics_revision(aggs, queue)
        self.assertTrue(any(c["cluster"] == "CL-EF" for c in summary["confusion_clusters"]))

    def test_confusion_mode_selects_cluster_items(self):
        kus, questions = fixture_31()
        aggs = run_events(kus, questions, [
            ev("Q-E1", "KU-E", "wrong", confusion="wrong_article", days_ago=2),
            ev("Q-E1", "KU-E", "wrong", confusion="wrong_article", days_ago=1),
            ev("Q-B1", "KU-B", "wrong", days_ago=1)])
        queue = R.build_queue(aggs, kus, questions, NOW)
        picked = R.select_session(queue, "confusion")
        self.assertTrue(picked)
        self.assertTrue(all(R.CONFUSION_CLUSTER in e["reasons"] for e in picked))


class TestSelector(unittest.TestCase):
    def test_avoids_exact_previous_question(self):
        kus, questions = fixture_31()
        pick = R.select_question("KU-A", "recall", questions,
                                 answered_ids={"Q-A1"})
        # only recall item answered -> must generate, never repeat Q-A1
        self.assertNotEqual(pick.get("question_id"), "Q-A1")
        self.assertEqual(pick["strategy"], "generate")
        self.assertIn("ku_id", pick["request"])
        self.assertEqual(pick["request"]["ku_id"], "KU-A")
        self.assertIn("Q-A1", pick["request"]["excluded_question_ids"])

    def test_prefers_unanswered_different_purpose(self):
        kus, questions = fixture_31()
        pick = R.select_question("KU-A", "distinction", questions,
                                 answered_ids={"Q-A2"}, last_purpose="distinction")
        self.assertEqual(pick["strategy"], "new_form")

    def test_source_bound_excludes_external(self):
        kus, questions = fixture_31()
        ext = mk_q("Q-X1", "KU-B", topic="Polity")
        ext["origin"] = "external"
        pick = R.select_question("KU-B", "recall", questions + [ext],
                                 answered_ids={"Q-B1"})
        self.assertNotEqual(pick.get("question_id"), "Q-X1")

    def test_semantic_duplicate_excluded(self):
        kus, questions = fixture_31()
        twin = copy.deepcopy(next(q for q in questions if q["id"] == "Q-A2"))
        twin["id"] = "Q-A2B"
        answered_blobs = [R.question_blob(next(q for q in questions if q["id"] == "Q-A2"))]
        pick = R.select_question("KU-A", "distinction", questions + [twin],
                                 answered_ids=set(), answered_blobs=answered_blobs)
        self.assertNotEqual(pick.get("question_id"), "Q-A2B")

    def test_empty_bank_returns_generate_request(self):
        pick = R.select_question("KU-Z", "recall", [], answered_ids=set())
        self.assertIsNone(pick["question_id"])
        self.assertEqual(pick["strategy"], "generate")


class TestMarkedDistinct(unittest.TestCase):
    def test_marked_only_is_low_never_dominant(self):
        kus = [mk_ku("KU-M", tier=1), mk_ku("KU-W", tier=1)]
        questions = [mk_q("Q-M1", "KU-M"), mk_q("Q-W1", "KU-W")]
        aggs = run_events(kus, questions, [
            ev("Q-M1", "KU-M", "correct", days_ago=1, marked=True),
            ev("Q-W1", "KU-W", "wrong", days_ago=1)])
        qbyku = R.questions_by_primary(questions)
        queue = R.build_queue(aggs, kus, questions, NOW)
        by_id = {e["ku_id"]: e for e in queue}
        self.assertEqual(by_id["KU-M"]["priority"], "low")
        self.assertIn(R.MARKED, by_id["KU-M"]["reasons"])
        self.assertGreater(by_id["KU-W"]["score"], by_id["KU-M"]["score"])

    def test_mark_without_attempts(self):
        kus = [mk_ku("KU-M", tier=2, exam_relevance="medium", conf_risk="low",
                     rev_pri="medium", ktype="definition", conceptual="low")]
        aggs = {"KU-M": dict(R.empty_agg(), marked=True)}
        queue = R.build_queue(aggs, kus, [], NOW)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["reasons"], [R.MARKED])
        self.assertEqual(queue[0]["priority"], "low")


class TestQueueOrdering(unittest.TestCase):
    def test_deterministic_order_with_tiebreak(self):
        kus = [mk_ku("KU-B", tier=1), mk_ku("KU-A", tier=1)]
        questions = [mk_q("Q-B1", "KU-B"), mk_q("Q-A1", "KU-A")]
        events = [ev("Q-B1", "KU-B", "wrong", days_ago=1),
                  ev("Q-A1", "KU-A", "wrong", days_ago=1)]
        q1 = R.build_queue(run_events(kus, questions, events), kus, questions, NOW)
        q2 = R.build_queue(run_events(kus, questions, list(reversed(events))), kus, questions, NOW)
        self.assertEqual([e["ku_id"] for e in q1], [e["ku_id"] for e in q2])
        self.assertEqual([e["ku_id"] for e in q1], ["KU-A", "KU-B"])  # tie -> ku_id asc

    def test_score_descending(self):
        kus, questions = fixture_31()
        aggs = run_events(kus, questions, [
            ev("Q-B1", "KU-B", "wrong", days_ago=1),
            ev("Q-D1", "KU-D", "wrong", conf="Certain", days_ago=1),
            ev("Q-C1", "KU-C", "correct", days_ago=1)])
        queue = R.build_queue(aggs, kus, questions, NOW)
        scores = [e["score"] for e in queue]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestTopicBalancing(unittest.TestCase):
    def test_cap_applies_when_pool_allows(self):
        kus = [mk_ku("KU-%02d" % i, topic="Only") for i in range(8)]
        questions = [mk_q("Q-%02d" % i, "KU-%02d" % i, topic="Only") for i in range(8)]
        events = [ev("Q-%02d" % i, "KU-%02d" % i, "wrong", days_ago=1) for i in range(8)]
        queue = R.build_queue(run_events(kus, questions, events), kus, questions, NOW)
        sess = R.build_session(queue, size=6)
        self.assertEqual(len(sess), 6)
        # concentrated weakness still fills the session (cap relaxes)
        import collections
        self.assertLessEqual(max(collections.Counter(e["topic"] for e in sess).values()), 6)

    def test_mixed_topics_capped(self):
        kus, questions, events = [], [], []
        for t in ("Alpha", "Beta"):
            for i in range(6):
                kid = "KU-%s%d" % (t[0], i)
                kus.append(mk_ku(kid, topic=t))
                questions.append(mk_q("Q-%s%d" % (t[0], i), kid, topic=t))
                events.append(ev("Q-%s%d" % (t[0], i), kid, "wrong", days_ago=1))
        queue = R.build_queue(run_events(kus, questions, events), kus, questions, NOW)
        sess = R.build_session(queue, size=6)
        import collections
        counts = collections.Counter(e["topic"] for e in sess)
        self.assertLessEqual(max(counts.values()), 3)


class TestSessionModes(unittest.TestCase):
    def setUp(self):
        self.kus, self.questions = fixture_31()
        self.aggs = run_events(self.kus, self.questions, [
            ev("Q-A2", "KU-A", "wrong", confusion="near_synonym", days_ago=1),
            ev("Q-B1", "KU-B", "wrong", days_ago=3),
            ev("Q-B1", "KU-B", "wrong", days_ago=1),
            ev("Q-D1", "KU-D", "wrong", conf="Certain", days_ago=1),
            ev("Q-C1", "KU-C", "correct", days_ago=1)])
        self.queue = R.build_queue(self.aggs, self.kus, self.questions, NOW)

    def test_all_modes_return_ordered_lists(self):
        for mode in R.REVISION_MODES:
            with self.subTest(mode=mode):
                out = R.select_session(self.queue, mode)
                self.assertIsInstance(out, list)

    def test_quick_is_small(self):
        out = R.select_session(self.queue, "quick")
        self.assertLessEqual(len(out), R.DEFAULT_CONFIG["quick_size"])
        self.assertGreater(len(out), 0)

    def test_hce_mode(self):
        out = R.select_session(self.queue, "hce")
        self.assertEqual([e["ku_id"] for e in out], ["KU-D"])

    def test_cognitive_mode_weak_form_filter(self):
        out = R.select_session(self.queue, "cognitive", weak_form="distinction")
        self.assertTrue(out)
        self.assertTrue(all("distinction" in e["weak_forms"] for e in out))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            R.select_session(self.queue, "nope")

    def test_empty_queue(self):
        self.assertEqual(R.select_session([], "targeted"), [])
        self.assertEqual(R.build_session([], size=10), [])


class TestMigration(unittest.TestCase):
    def test_legacy_web_session_migrates(self):
        raw = {"answers": {
            "Q-0001": {"sel": "B", "conf": "Certain", "correct": False,
                       "distype": "wrong_date", "primary_ku": "KU-0001",
                       "marked": False, "time": "2026-01-01T00:00:00Z"},
            "Q-0002": {"sel": "A", "conf": "Guessing", "correct": True,
                       "primary_ku": "KU-0002", "time": "2026-01-02T00:00:00Z"}},
            "mode": "practice"}
        s, migrated, notes = R.migrate_session(raw)
        self.assertTrue(migrated)
        self.assertEqual(s["study_session_version"], 2)
        self.assertEqual(len(s["events"]), 2)
        self.assertEqual(s["events"][0]["confidence"], "Certain")
        self.assertEqual(s["events"][0]["result"], "wrong")
        # answers preserved, defaults filled without overwriting
        self.assertEqual(s["answers"]["Q-0001"]["sel"], "B")
        self.assertFalse(s["answers"]["Q-0001"]["marked"])

    def test_v2_passthrough(self):
        raw = {"study_session_version": 2, "answers": {}, "events": [],
               "mode": "practice", "revision_state": {"queue": [], "sessions": []}}
        s, migrated, _ = R.migrate_session(raw)
        self.assertFalse(migrated)
        self.assertEqual(s["study_session_version"], 2)

    def test_garbage_and_old_schema_shape(self):
        s, migrated, _ = R.migrate_session(None)
        self.assertTrue(migrated)
        self.assertEqual(s["answers"], {})
        s2, _, _ = R.migrate_session({"not": "a session"})
        self.assertEqual(s2["answers"], {})
        schema_like = {"session_id": "s", "run_id": "r", "profile": "p",
                       "question_ids": ["Q-1"],
                       "responses": [{"question_id": "Q-1", "result": "wrong",
                                      "confidence": "Certain",
                                      "confusion_type": "wrong_date",
                                      "timestamp": "2026-01-01T00:00:00Z",
                                      "primary_ku": "KU-0001"}],
                       "score": 0, "started_at": "2026-01-01T00:00:00Z",
                       "completed_at": None}
        s3, _, _ = R.migrate_session(schema_like)
        self.assertEqual(len(s3["events"]), 1)
        self.assertEqual(s3["events"][0]["confidence"], "Certain")


class TestSourceGrounding(unittest.TestCase):
    def test_selector_excludes_unvalidated_shape(self):
        kus, questions = fixture_31()
        bad = mk_q("Q-BAD", "KU-B")
        del bad["options"]  # structurally broken: never selectable
        pick = R.select_question("KU-B", "recall", questions + [bad],
                                 answered_ids={"Q-B1"})
        self.assertNotEqual(pick.get("question_id"), "Q-BAD")
        bad2 = mk_q("Q-BAD2", "KU-B")
        bad2["answer"] = None
        pick2 = R.select_question("KU-B", "recall", [bad2], answered_ids=set())
        self.assertIsNone(pick2["question_id"])

    def test_validate_revision_question_accepts_good(self):
        kus, questions = fixture_31()
        st = {"blocks": [{"id": "B-1", "page": 1}], "normalized_text": "stub"}
        ku_ids = {u["id"] for u in kus}
        ku_map = {u["id"]: "stub supporting excerpt" for u in kus}
        q = mk_q("Q-NEW", "KU-B", purpose="distinction", cog="distinction")
        q["knowledge_units"] = [{"ku_id": "KU-B", "role": "primary"}]
        ctx = {"ku_ids": ku_ids, "ku_map": ku_map, "block_ids": {"B-1"},
               "ntext": "stub supporting excerpt", "n_opts": 2, "mode": "SOURCE_BOUND",
               "threshold": 0.85, "target_ku": "KU-B", "weak_form": "distinction",
               "excluded_ids": ["Q-B1"]}
        ok, notes = R.validate_revision_question(q, ctx)
        self.assertTrue(ok, notes)

    def test_validate_revision_question_rejects(self):
        kus, questions = fixture_31()
        ctx = {"ku_ids": {u["id"] for u in kus}, "ku_map": {},
               "block_ids": {"B-1"}, "ntext": "nothing here", "n_opts": 2,
               "mode": "SOURCE_BOUND", "threshold": 0.85,
               "target_ku": "KU-B", "weak_form": "distinction",
               "excluded_ids": ["Q-B1"]}
        q = mk_q("Q-B1", "KU-C")  # wrong primary + excluded id + wrong form
        ok, notes = R.validate_revision_question(q, ctx)
        self.assertFalse(ok)
        self.assertTrue(notes)
        ext = mk_q("Q-EXT", "KU-B")
        ext["origin"] = "external"
        ok2, _ = R.validate_revision_question(ext, ctx)
        self.assertFalse(ok2)


class TestEdgeCases(unittest.TestCase):
    def test_multi_ku_question_attribution(self):
        kus = [mk_ku("KU-P", tier=1), mk_ku("KU-S", tier=2, exam_relevance="medium",
                                           conf_risk="low", rev_pri="medium",
                                           ktype="definition", conceptual="low")]
        q = mk_q("Q-PS", "KU-P", topic="Polity")
        q["knowledge_units"] = [{"ku_id": "KU-P", "role": "primary"},
                                {"ku_id": "KU-S", "role": "secondary"},
                                {"ku_id": "KU-D", "role": "distractor_basis"}]
        aggs = R.aggregate([R.normalize_event(
            ev("Q-PS", "KU-P", "wrong"), q, NOW)], {"Q-PS": q})
        self.assertEqual(aggs["KU-P"]["incorrect"], 1)
        self.assertEqual(aggs["KU-S"].get("secondary_exposure"), 1)
        self.assertEqual(aggs["KU-S"].get("attempts", 0), 0)
        self.assertNotIn("KU-D", aggs)

    def test_all_correct_all_incorrect(self):
        kus = [mk_ku("KU-X", tier=2, exam_relevance="medium", conf_risk="low",
                     rev_pri="low", ktype="definition", conceptual="low")]
        q = mk_q("Q-X", "KU-X", tier=2)
        good = run_events(kus, [q], [ev("Q-X", "KU-X", "correct", days_ago=d) for d in (3, 2, 1)])
        self.assertEqual(good["KU-X"]["accuracy"], 1.0)
        self.assertEqual(good["KU-X"]["recent_accuracy"], 1.0)
        bad = run_events(kus, [q], [ev("Q-X", "KU-X", "wrong", days_ago=d) for d in (3, 2, 1)])
        self.assertEqual(bad["KU-X"]["accuracy"], 0.0)

    def test_minimal_raw_event_never_crashes(self):
        e = R.normalize_event({}, None, NOW)
        self.assertIsNone(e["primary_ku"])
        aggs = R.aggregate([e], {})
        self.assertEqual(aggs, {})
        e2 = R.normalize_event({"question_id": "Q", "correct": True}, None, NOW)
        self.assertEqual(e2["result"], "correct")

    def test_no_marks_no_weak_areas(self):
        self.assertEqual(R.build_queue({}, [], [], NOW), [])
        self.assertEqual(R.analytics_revision({}, [])["queue_size"], 0)


class TestAcceptanceLifecycle(unittest.TestCase):
    """§37: Certain+wrong -> priority rises -> queued with reason ->
    new question -> correct lowers but keeps priority -> STABLE."""

    def test_certain_wrong_to_stable(self):
        ku = mk_ku("KU-DT", tier=1, ktype="definition", conceptual="low",
                   conf_risk="low")
        # required forms for tier3-like? tier1 definition low-concept:
        # recall + statement (no confusable, low risk)
        q1 = mk_q("Q-DT1", "KU-DT", qtype="factual_mcq")
        q2 = mk_q("Q-DT2", "KU-DT", qtype="factual_mcq")
        q2["stem"] = "stem Q-DT2 about KU-DT with different wording"
        q2["options"][0]["text"] = "right answer Q-DT2"
        q2["options"][1]["text"] = "wrong answer Q-DT2"
        q3 = mk_q("Q-DT3", "KU-DT", qtype="factual_mcq")
        q3["stem"] = "stem Q-DT3 about KU-DT third wording"
        q4 = mk_q("Q-DT4", "KU-DT", qtype="factual_mcq")
        q4["stem"] = "stem Q-DT4 about KU-DT fourth wording"
        questions = [q1, q2, q3, q4]
        kus = [ku]

        def state_after(events):
            aggs = run_events(kus, questions, events)
            req = R.required_forms_for("KU-DT", kus, R.questions_by_primary(questions))
            s = R.score_ku("KU-DT", aggs["KU-DT"], ku, NOW, None, req)
            m = R.mastery_of("KU-DT", aggs["KU-DT"], ku, NOW, None, req)
            return aggs, s, m

        # old high-confidence error (40d): recency respected, HCE still counts
        aggs, s1, m1 = state_after(
            [ev("Q-DT1", "KU-DT", "wrong", conf="Certain", days_ago=40)])
        self.assertIn(s1["band"], ("critical", "high"))
        self.assertIn(R.HIGH_CONF_ERROR, s1["reasons"])
        queue = R.build_queue(aggs, kus, questions, NOW)
        entry = next(e for e in queue if e["ku_id"] == "KU-DT")
        self.assertIn(R.HIGH_CONF_ERROR, entry["reasons"])
        pick = R.select_question("KU-DT", "recall", questions, answered_ids={"Q-DT1"})
        self.assertIsNotNone(pick["question_id"])
        self.assertNotEqual(pick["question_id"], "Q-DT1")

        aggs, s2, m2 = state_after([
            ev("Q-DT1", "KU-DT", "wrong", conf="Certain", days_ago=40),
            ev(pick["question_id"], "KU-DT", "correct", conf="Unsure", days_ago=2)])
        self.assertLess(s2["score"], s1["score"])
        self.assertNotEqual(m2, R.STABLE)

        aggs, s3, m3 = state_after([
            ev("Q-DT1", "KU-DT", "wrong", conf="Certain", days_ago=40),
            ev("Q-DT2", "KU-DT", "correct", conf="Unsure", days_ago=3),
            ev("Q-DT3", "KU-DT", "correct", conf="Unsure", days_ago=2),
            ev("Q-DT4", "KU-DT", "correct", conf="Certain", days_ago=1)])
        _ = (aggs, s3)
        self.assertEqual(m3, R.STABLE)


class TestSamplePackageE2E(unittest.TestCase):
    """§32: realistic scripted session over the real sample package."""

    @classmethod
    def setUpClass(cls):
        import json
        with open(ROOT / "examples" / "sample_package.json", encoding="utf-8") as fh:
            cls.pkg = json.load(fh)
        with open(ROOT / "examples" / "sample_inventory.json", encoding="utf-8") as fh:
            cls.inv = json.load(fh)
        cls.questions = cls.pkg["questions"]
        cls.kus = cls.inv["units"] if isinstance(cls.inv, dict) else cls.inv
        cls.qmap = {q["id"]: q for q in cls.questions}
        by_ku = {}
        for q in cls.questions:
            for e in q.get("knowledge_units") or []:
                if isinstance(e, dict) and e.get("role") == "primary":
                    by_ku.setdefault(e["ku_id"], []).append(q["id"])
        # sample bank: one primary question per KU (verified below)
        for v in by_ku.values():
            assert len(v) == 1
        kids = sorted(by_ku)
        cls.ku_a = kids[0]
        cls.qa1 = by_ku[cls.ku_a][0]
        cls.ku_b = kids[1]
        cls.qb1 = by_ku[cls.ku_b][0]

    def test_lifecycle_on_real_bank(self):
        qmap = self.qmap
        script = [
            {"question_id": self.qa1, "primary_ku": self.ku_a, "result": "wrong",
             "confidence": "Certain", "confusion_type": "near_synonym",
             "timestamp": NOW - 2 * DAY, "marked": False, "mode": "practice"},
            {"question_id": self.qb1, "primary_ku": self.ku_b, "result": "correct",
             "confidence": "Unsure", "timestamp": NOW - 2 * DAY, "mode": "practice"},
            {"question_id": self.qa1, "primary_ku": self.ku_a, "result": "wrong",
             "confidence": "Fairly confident", "timestamp": NOW - 1 * DAY,
             "marked": True, "mode": "practice"},
        ]
        normed = [R.normalize_event(e, qmap.get(e["question_id"]), NOW) for e in script]
        aggs = R.aggregate(normed, qmap)
        self.assertIn(self.ku_a, aggs)
        queue = R.build_queue(aggs, self.kus, self.questions, NOW)
        entry_a = next(e for e in queue if e["ku_id"] == self.ku_a)
        self.assertIn(R.HIGH_CONF_ERROR, entry_a["reasons"])
        self.assertIn(R.REPEATED_ERROR, entry_a["reasons"])
        self.assertIn(R.MARKED, entry_a["reasons"])
        # priority of repeatedly-missed KU-A beats once-correct KU-B (if queued)
        scores = {e["ku_id"]: e["score"] for e in queue}
        if self.ku_b in scores:
            self.assertGreater(scores[self.ku_a], scores[self.ku_b])
        # bank has one primary question per KU, so the exhausted KU must
        # yield a generation request, never a silent repeat (§9, §26)
        answered = {self.qa1}
        weak = entry_a["weak_forms"][0] if entry_a["weak_forms"] else None
        pick = R.select_question(self.ku_a, weak, self.questions, answered_ids=answered)
        self.assertIsNone(pick["question_id"])
        req = pick["request"]
        self.assertEqual(req["ku_id"], self.ku_a)
        self.assertIn(self.qa1, req["excluded_question_ids"])
        self.assertTrue(req["preferred_purpose"])
        self.assertTrue(req["preferred_type"])
        self.assertEqual(req["fidelity"], "SOURCE_BOUND")
        # a generated revision question must validate before reaching learners
        self.assertIn("rules", req)


class TestRevisionCLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "revision.py")] + list(args),
            capture_output=True, text=True, cwd=str(ROOT), timeout=120)

    def test_queue_select_migrate_commands(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            evf = Path(tmp) / "events.json"
            evf.write_text(json.dumps([
                {"question_id": "Q-B1", "primary_ku": "KU-B", "result": "wrong",
                 "confidence": "Certain", "timestamp": NOW - DAY}]), encoding="utf-8")
            kumb = {"units": [mk_ku("KU-B")]}
            kuf = Path(tmp) / "kus.json"
            kuf.write_text(json.dumps(kumb), encoding="utf-8")
            bankf = Path(tmp) / "bank.json"
            bankf.write_text(json.dumps({"questions": [
                mk_q("Q-B1", "KU-B"), mk_q("Q-B2", "KU-B", purpose="distinction",
                                           cog="distinction")]}), encoding="utf-8")
            qout = Path(tmp) / "queue.json"
            r = self.run_cli("queue", "--events", str(evf), "--kus", str(kuf),
                             "--questions", str(bankf), "--out", str(qout))
            self.assertEqual(r.returncode, 0, r.stderr)
            queue = json.loads(qout.read_text(encoding="utf-8"))["queue"]
            self.assertEqual([e["ku_id"] for e in queue], ["KU-B"])
            ansf = Path(tmp) / "answered.json"
            ansf.write_text(json.dumps({"Q-B1": {"sel": "B"}}), encoding="utf-8")
            sout = Path(tmp) / "sess.json"
            r = self.run_cli("select", "--queue", str(qout), "--bank", str(bankf),
                             "--mode", "targeted", "--size", "5",
                             "--answered", str(ansf), "--out", str(sout))
            self.assertEqual(r.returncode, 0, r.stderr)
            picks = json.loads(sout.read_text(encoding="utf-8"))["picks"]
            self.assertEqual(picks[0]["ku_id"], "KU-B")
            # recall already answered -> falls through to the weak distinction form
            self.assertEqual(picks[0]["weak_used"], "distinction")
            self.assertEqual(picks[0]["question_id"], "Q-B2")
            mout = Path(tmp) / "sess2.json"
            oldf = Path(tmp) / "old.json"
            oldf.write_text(json.dumps({"answers": {}, "mode": "practice"}),
                            encoding="utf-8")
            r = self.run_cli("migrate", "--session", str(oldf), "--out", str(mout))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(mout.read_text(encoding="utf-8"))
                             ["study_session_version"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
