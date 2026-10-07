"""JS parity tests: templates/web/revision.engine.js must agree with
scripts/revision.py on identical inputs (scores, bands, reasons, weak
forms, queue order, mastery, sessions, picks, migration).

Runs node tests/parity_revision.js; skipped only if node is unavailable.
"""
import json
import shutil
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
NODE = shutil.which("node")
ENGINE = ROOT / "templates" / "web" / "revision.engine.js"
HARNESS = HERE / "parity_revision.js"


def mk_ku(kid, tier=1, topic="Polity"):
    return {"id": kid, "tier": tier, "type": "concept", "topic": topic,
            "subtopic": "Basics", "statement": "stmt %s" % kid,
            "confusable_with": [], "confusion_cluster": None, "related_ku": [],
            "source": {"block_id": "B-1", "page": 1, "section_path": ["S"],
                       "char_start": 0, "char_end": 5, "table_ref": None},
            "dimensions": {"importance": "high", "exam_relevance": "high",
                           "factual_density": "high", "conceptual_density": "high",
                           "confusion_risk": "high", "discrimination_value": "high",
                           "revision_priority": "high"}}


def mk_q(qid, prim, purpose="direct_recall", cog="recall", qtype="factual_mcq",
         topic="Polity"):
    return {"id": qid, "type": qtype, "stem": "stem %s about %s" % (qid, prim),
            "purpose": purpose, "cognitive_level": cog, "difficulty": "medium",
            "origin": "source", "topic": topic,
            "knowledge_units": [{"ku_id": prim, "role": "primary"}],
            "source": [{"page": 1, "section_path": "S", "block_id": "B-1",
                        "char_start": 0, "char_end": 5, "table_ref": None}],
            "options": [
                {"key": "A", "text": "right %s" % qid, "is_correct": True,
                 "distractor_origin": "source_ku", "confusion_type": "near_synonym",
                 "ku_ref": prim, "distractor_purpose": None},
                {"key": "B", "text": "wrong %s" % qid, "is_correct": False,
                 "distractor_origin": "source_ku", "confusion_type": "wrong_date",
                 "ku_ref": prim, "distractor_purpose": "wrong_date"}],
            "answer": "A", "statements": None, "explanation": "exp"}


def approx(a, b, path="$"):
    if isinstance(a, float) or isinstance(b, float):
        assert abs(float(a) - float(b)) < 1e-9, "%s: %r != %r" % (path, a, b)
    elif isinstance(a, dict):
        assert set(a) == set(b), "%s keys %s != %s" % (path, set(a), set(b))
        for k in a:
            approx(a[k], b[k], "%s.%s" % (path, k))
    elif isinstance(a, list):
        assert len(a) == len(b), "%s len %d != %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            approx(x, y, "%s[%d]" % (path, i))
    else:
        assert a == b, "%s: %r != %r" % (path, a, b)


def python_side(payload):
    kus = payload["kus"]
    questions = payload["questions"]
    events = payload["events"]
    now = payload["now"]
    qmap = {q["id"]: q for q in questions}
    qbyku = R.questions_by_primary(questions)
    normed = [R.normalize_event(e, qmap.get(e.get("question_id")), now) for e in events]
    aggs = R.aggregate(normed, qmap)
    queue = R.build_queue(aggs, kus if kus else None, questions, now, None)
    mastery = {}
    for k, a in aggs.items():
        meta = next((u for u in (kus or []) if u["id"] == k), None)
        mastery[k] = R.mastery_of(k, a, meta, now, None,
                                  R.required_forms_for(k, kus if kus else None, qbyku))
    sessions = {}
    for m in payload.get("queue_modes", []):
        sessions[m["mode"] if "weak_form" not in m or not m.get("weak_form") else
                 m["mode"] + "+" + (m.get("weak_form") or "")] = [
            e["ku_id"] for e in R.select_session(
                queue, m["mode"], m.get("limit"), m.get("weak_form"), None)]
    for s in payload.get("session_sizes", []):
        sessions["build_%d" % s] = [e["ku_id"] for e in R.build_session(queue, s, None)]
    picks = []
    for c in payload.get("select_cases", []):
        picks.append(R.select_question(
            c["ku_id"], c["weak_form"], questions,
            answered_ids=set(c.get("answered", [])),
            exclude_ids=set(c.get("exclude", [])),
            answered_blobs=c.get("answered_blobs", []),
            last_purpose=c.get("last_purpose"),
            fidelity=c.get("fidelity", "SOURCE_BOUND")))
    migrated = None
    if payload.get("migrate") is not None:
        s, mflag, notes = R.migrate_session(payload["migrate"])
        migrated = [s, mflag, notes]
    return {"queue": queue, "mastery": mastery, "sessions": sessions,
            "picks": picks, "migrated": migrated}


def payload(with_metas):
    kus = [mk_ku("KU-A", topic="Polity"), mk_ku("KU-B", topic="Polity"),
           mk_ku("KU-C", tier=2, topic="History")]
    questions = [
        mk_q("Q-A1", "KU-A"), mk_q("Q-A2", "KU-A", purpose="distinction", cog="distinction"),
        mk_q("Q-A3", "KU-A", purpose="statement_evaluation", cog="analysis", qtype="statement_based"),
        mk_q("Q-B1", "KU-B"), mk_q("Q-B2", "KU-B"),
        mk_q("Q-C1", "KU-C", topic="History"),
    ]
    events = [
        {"question_id": "Q-A1", "primary_ku": "KU-A", "result": "correct",
         "confidence": "Certain", "timestamp": NOW - 10 * DAY},
        {"question_id": "Q-A1", "primary_ku": "KU-A", "result": "correct",
         "confidence": "Unsure", "timestamp": NOW - 9 * DAY},
        {"question_id": "Q-A2", "primary_ku": "KU-A", "result": "wrong",
         "confidence": "Fairly confident", "confusion_type": "near_synonym",
         "timestamp": NOW - 2 * DAY},
        {"question_id": "Q-A2", "primary_ku": "KU-A", "result": "wrong",
         "confidence": "Guessing", "confusion_type": "near_synonym",
         "timestamp": NOW - 1 * DAY, "marked": True},
        {"question_id": "Q-B1", "primary_ku": "KU-B", "result": "wrong",
         "confidence": "Certain", "confusion_type": "wrong_date",
         "timestamp": "2023-11-14T22:13:20Z"},
        {"question_id": "Q-B1", "primary_ku": "KU-B", "result": "wrong",
         "confidence": "Unsure", "timestamp": NOW - 1 * DAY},
        {"question_id": "Q-C1", "primary_ku": "KU-C", "result": "correct",
         "confidence": "Certain", "timestamp": NOW - 20 * DAY},
    ]
    blobs = {}
    for q in questions:
        blobs[q["id"]] = R.question_blob(q)
    return {
        "kus": kus if with_metas else [],
        "questions": questions, "events": events, "now": NOW,
        "queue_modes": [{"mode": m} for m in R.REVISION_MODES] + [
            {"mode": "cognitive", "weak_form": "distinction"},
            {"mode": "targeted", "limit": 2}],
        "session_sizes": [5, 10],
        "select_cases": [
            {"ku_id": "KU-A", "weak_form": "distinction", "answered": ["Q-A2"],
             "answered_blobs": [blobs["Q-A2"]], "last_purpose": "distinction"},
            {"ku_id": "KU-B", "weak_form": "recall", "answered": ["Q-B1"],
             "answered_blobs": [blobs["Q-B1"]]},
            {"ku_id": "KU-C", "weak_form": "recall", "answered": []},
        ],
        "migrate": {"answers": {
            "Q-A1": {"sel": "B", "conf": "Certain", "correct": False,
                     "distype": "near_synonym", "primary_ku": "KU-A",
                     "marked": False, "time": NOW - 1 * DAY}},
            "mode": "practice"},
    }


class TestJsParity(unittest.TestCase):
    def run_parity(self, with_metas):
        if NODE is None:
            self.skipTest("node not available")
        p = payload(with_metas)
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.json"
            inp.write_text(json.dumps(p), encoding="utf-8")
            r = subprocess.run([NODE, str(HARNESS), str(inp)], capture_output=True,
                               text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        py = python_side(p)
        approx(py["mastery"], js["mastery"], "mastery")
        approx(py["sessions"], js["sessions"], "sessions")
        approx(py["picks"], js["picks"], "picks")
        approx(py["migrated"], js["migrated"], "migrated")
        approx(py["queue"], js["queue"], "queue")

    def test_parity_with_metas(self):
        self.run_parity(True)

    def test_parity_without_metas(self):
        self.run_parity(False)

    def test_engine_is_self_contained(self):
        t = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("require(", t)
        self.assertIn("RevisionEngine", t)
        self.assertIn("study_session_version", t)

    def test_template_js_parses(self):
        if NODE is None:
            self.skipTest("node not available")
        import re
        t = (ROOT / "templates" / "web" / "app.template.html").read_text(encoding="utf-8")
        i = t.find("<script>")
        j = t.find("</script>", i)
        self.assertGreater(i, -1)
        # strip the package/status placeholders so node parses structure only
        js = t[i + 8:j].replace("/*__PACKAGE__*/{}", "{}").replace('/*__STATUS__*/""', '""')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "app.js"
            p.write_text(js, encoding="utf-8")
            r = subprocess.run([NODE, "--check", str(p)], capture_output=True,
                               text=True, cwd=str(ROOT), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_required_forms_parity(self):
        if NODE is None:
            self.skipTest("node not available")
        import coverage as covmod
        metas = [
            {"id": "KU-1", "tier": 1, "type": "concept",
             "dimensions": {"confusion_risk": "high", "conceptual_density": "high"}},
            {"id": "KU-2", "tier": 1, "type": "definition",
             "dimensions": {"confusion_risk": "low", "conceptual_density": "low"}},
            {"id": "KU-3", "tier": 2, "type": "date",
             "dimensions": {"confusion_risk": "low", "conceptual_density": "low"},
             "confusable_with": ["KU-4"]},
            {"id": "KU-4", "tier": 3, "type": "formula",
             "dimensions": {"confusion_risk": "low", "conceptual_density": "high"}},
            {"id": "KU-5", "tier": 2, "type": "cause_effect",
             "dimensions": {"confusion_risk": "low", "conceptual_density": "medium"}},
            {"id": "KU-6"},
        ]
        expected = {m["id"]: sorted(covmod.required_forms(m)) for m in metas}
        js_src = "const RE = require(%s);\n" % json.dumps(str(ENGINE)) + \
            "const metas = %s;\n" % json.dumps(metas) + \
            "const out = {};\n" + \
            "metas.forEach(m => { out[m.id] = RE.requiredForms(m).slice().sort(); });\n" + \
            "console.log(JSON.stringify(out));"
        with tempfile.TemporaryDirectory() as tmp:
            drv = Path(tmp) / "req.js"
            drv.write_text(js_src, encoding="utf-8")
            r = subprocess.run([NODE, str(drv)], capture_output=True,
                               text=True, cwd=str(ROOT), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
