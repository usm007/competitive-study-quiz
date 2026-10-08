"""JS parity tests: templates/web/test.engine.js must agree with
scripts/test_engine.py on identical inputs (RNG, assembly, scoring,
analysis, sessions, formatting).

Runs node tests/parity_test_engine.js; skipped only if node is unavailable.
"""
import json
import shutil
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
NODE = shutil.which("node")

import test_engine as T


def approx(a, b, path="$"):
    if isinstance(a, bool) or isinstance(b, bool):
        assert a == b, "%s: %r != %r" % (path, a, b)
    elif isinstance(a, (int, float)) or isinstance(b, (int, float)):
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


def frac_dict(fr):
    if fr is None:
        return None
    return {"n": fr.numerator, "d": fr.denominator}


def mkq(qid, topic="Polity", diff="easy", qtype="factual_mcq", sec="S1",
        purpose="direct_recall", answer="A"):
    return {
        "id": qid, "type": qtype, "stem": "Stem %s." % qid, "topic": topic,
        "difficulty": diff, "purpose": purpose, "origin": "source", "answer": answer,
        "knowledge_units": [{"ku_id": "KU-%s" % qid, "role": "primary"}],
        "source": [{"page": 1, "section_path": [sec], "block_id": "B",
                    "char_start": 0, "char_end": 1, "table_ref": None}],
        "options": [{"key": "A", "is_correct": True}, {"key": "B", "is_correct": False}],
    }


def payload():
    qs = []
    for i, t in enumerate(["Polity", "Polity", "Geography", "Geography",
                           "Polity-Union", "Geography"]):
        d = ["easy", "medium", "hard"][i % 3]
        y = "statement_based" if i % 2 else "factual_mcq"
        qs.append(mkq("Q%02d" % (i + 1), topic=t, diff=d, qtype=y,
                      sec="S%d" % (1 + (i % 2)),
                      purpose="statement_evaluation" if y == "statement_based" else "direct_recall"))
    qs.append(mkq("QX", topic="Polité", diff="hard", qtype="elimination_mcq", sec="S3"))
    valid = {q["id"]: True for q in qs}
    cfg_bal, _ = T.validate_config({"title": "P", "question_count": 4,
                                    "duration_minutes": 20, "selection": "BALANCED",
                                    "seed": 20261007})
    cfg_rand, _ = T.validate_config({"title": "P", "question_count": 4,
                                     "duration_minutes": 20, "selection": "RANDOM",
                                     "seed": "seed-9"})
    cfg_bp, _ = T.validate_config({"title": "P", "question_count": 3,
                                   "duration_minutes": 20, "selection": "CUSTOM_BLUEPRINT",
                                   "seed": 3,
                                   "blueprint": [{"topic": "Polity", "count": 2},
                                                 {"difficulty": "hard", "count": 1}]})
    prof = {"name": "APSC_PRELIMS",
            "negative_marking": {"enabled": True, "penalty_fraction": "1/3", "verified": False}}
    answers = {"Q01": "A", "Q02": "B", "Q03": None,
               "Q04": {"sel": "A", "conf": "Certain", "marked": True, "dt_ms": 4500},
               "Q05": {"sel": "B", "conf": "Guessing", "marked": False, "dt_ms": 12000}}
    paper_cfg, _ = T.validate_config({"title": "P", "question_count": 5,
                                      "duration_minutes": 30, "selection": "BALANCED",
                                      "seed": 11,
                                      "negative_marking": {"enabled": True,
                                                           "penalty_fraction": "1/3"}})
    paper, errs = T.assemble(qs, valid, paper_cfg, None, prof)
    assert not errs
    sess = T.new_test_session(paper, paper_cfg, 1_700_000_000)
    sess["answers"] = dict(answers)
    sess["marked"] = ["Q04"]
    return {
        "rng_cases": [{"seed": 1}, {"seed": 20261007}, {"seed": "seed-9"},
                      {"seed": 0xFFFFFFFF}],
        "hash_cases": ["abc", "APSC Full Test", "Polité OK", ""],
        "assemble_cases": [
            {"questions": qs, "validation": valid, "config": cfg_bal,
             "inventory": None, "profile": prof},
            {"questions": qs, "validation": valid, "config": cfg_rand,
             "inventory": None, "profile": prof},
            {"questions": qs, "validation": valid, "config": cfg_bp,
             "inventory": None, "profile": prof},
            {"questions": qs, "validation": valid,
             "config": dict(cfg_bal, question_count=200), "inventory": None,
             "profile": prof},
        ],
        "config_cases": [
            {"question_count": 10, "duration_minutes": 20},
            {"question_count": 0, "duration_minutes": -1, "selection": "X",
             "difficulty": {"easy": 10}, "blueprint": [{"count": 0}]},
            {"title": "T", "question_count": 5, "duration_minutes": 45.5,
             "marks_per_correct": 2, "selection": "RANDOM", "seed": "s",
             "topics": ["Polity"], "exclude_ids": ["Q01"]},
        ],
        "rule_cases": [
            {"profile": prof, "config": {"marks_per_correct": 2.0,
                                         "negative_marking": {"enabled": True,
                                                              "penalty_fraction": "1/3"}}},
            {"profile": {"name": "T"}, "config": {}},
        ],
        "score_cases": [
            {"paper_or_rules": {"question_ids": ["Q01", "Q02", "Q03"],
                                "rules": {"marks_per_correct": 1.0,
                                          "penalty_fraction": "1/3",
                                          "negative_marking": True}},
             "answers": answers, "questions": qs},
            {"paper_or_rules": {"question_ids": ["Q04"],
                                "rules": {"marks_per_correct": 2.0,
                                          "penalty_fraction": 0.25,
                                          "negative_marking": False}},
             "answers": {"Q04": "B"}, "questions": qs},
        ],
        "analyze_cases": [
            {"paper": {"question_ids": ["Q01", "Q02", "Q03", "Q04", "Q05"],
                       "rules": {"marks_per_correct": 1.0, "penalty_fraction": "1/3",
                                 "negative_marking": True}},
             "answers": answers, "questions": qs,
             "kus": {"KU-Q01": {"id": "KU-Q01", "tier": 1},
                     "KU-Q02": {"id": "KU-Q02", "tier": 1}},
             "now_ms": None},
        ],
        "session_cases": [
            {"paper": {"test_id": "T-1", "test_version": 1,
                       "config": {"duration_minutes": 30, "exam_profile": "X"},
                       "rules": {}, "question_ids": ["Q01", "Q02"]},
             "config": None, "now_ms": 1_000_000, "at": 1_060_000},
            {"paper": {"test_id": "T-1", "test_version": 1,
                       "config": {"duration_minutes": 30},
                       "rules": {}, "question_ids": ["Q01"]},
             "config": None, "now_ms": 1_000_000, "at": 1_000_000 + 30 * 60000},
        ],
        "finalize_cases": [
            {"session": sess, "questions": qs, "now_ms": 1_700_100_000,
             "reason": "submitted"},
        ],
        "fmt_cases": [{"n": 59, "d": 1}, {"n": 117, "d": 2}, {"n": -3, "d": 4},
                      {"n": 5, "d": 3}, {"n": 0, "d": 5}, None],
        "retake_cases": [7, "7", "abc", True],
        "_paper": paper, "_sess": sess,
    }


def python_side(p):
    out = {}
    out["rng"] = []
    for c in p["rng_cases"]:
        r = T.RNG(c["seed"])
        out["rng"].append({"seed": c["seed"],
                           "seq": [r.random() for _ in range(5)],
                           "shuffle": T.RNG(c["seed"]).shuffle(list(range(10)))})
    out["hashes"] = [T.xfnv1a(s) for s in p["hash_cases"]]
    out["assembled"] = []
    for c in p["assemble_cases"]:
        paper, errs = T.assemble(c["questions"], c["validation"], c["config"],
                                 c["inventory"], c["profile"])
        out["assembled"].append({"paper": paper, "errors": errs})
    out["validated"] = []
    for c in p["config_cases"]:
        cfg, errs = T.validate_config(c)
        out["validated"].append({"config": cfg, "errors": errs})
    out["rules"] = [T.resolve_rules(c["profile"], c["config"]) for c in p["rule_cases"]]
    out["scored"] = []
    for c in p["score_cases"]:
        qmap = {q["id"]: q for q in c["questions"]}
        s = T.score_session(c["paper_or_rules"], c["answers"], qmap)
        out["scored"].append({k: (frac_dict(v) if isinstance(v, Fraction) else v)
                              if k in ("positive", "penalty_total", "final",
                                       "accuracy", "attempt_rate") else v
                              for k, v in s.items()})
    out["analyzed"] = []
    for c in p["analyze_cases"]:
        qmap = {q["id"]: q for q in c["questions"]}
        a = T.analyze_results(c["paper"], c["answers"], qmap, c["kus"], c["now_ms"])
        a["score"] = {k: (frac_dict(v) if isinstance(v, Fraction) else v)
                      for k, v in a["score"].items()}
        out["analyzed"].append(a)
    out["sessions"] = []
    for c in p["session_cases"]:
        s = T.new_test_session(c["paper"], c["config"], c["now_ms"])
        out["sessions"].append({
            "session": {"test_id": s["test_id"], "expires_at": s["expires_at"],
                        "question_ids": s["question_ids"]},
            "remaining": T.remaining_ms(s, c["at"]),
            "expired": T.is_expired(s, c["at"])})
    out["finalized"] = []
    for c in p["finalize_cases"]:
        import copy
        s = copy.deepcopy(c["session"])
        res = T.finalize_session(s, c["questions"], c["now_ms"], c["reason"])
        res2 = T.finalize_session(s, c["questions"], c["now_ms"] + 99999, "submitted")
        res = json.loads(json.dumps(res, default=str))
        out["finalized"].append({"result": res, "frozen": res == res2,
                                 "submitted": s["submitted"]})
    out["fmt"] = [T.fmt_frac(f and __import__("fractions").Fraction(f["n"], f["d"])) for f in p["fmt_cases"]]
    out["retake_seeds"] = [T.retake_seed(s) for s in p["retake_cases"]]
    return out


class TestEngineParity(unittest.TestCase):
    def test_parity(self):
        if NODE is None:
            self.skipTest("node not available")
        p = payload()
        py = python_side(p)
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.json"
            inp.write_text(json.dumps(p), encoding="utf-8")
            r = subprocess.run([NODE, str(HERE / "parity_test_engine.js"), str(inp)],
                               capture_output=True, text=True, encoding="utf-8",
                               cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        approx(py["rng"], js["rng"], "rng")
        approx(py["hashes"], js["hashes"], "hashes")
        approx(py["assembled"], js["assembled"], "assembled")
        approx(py["validated"], js["validated"], "validated")
        approx(py["rules"], js["rules"], "rules")
        approx(py["scored"], js["scored"], "scored")
        approx(py["analyzed"], js["analyzed"], "analyzed")
        approx(py["sessions"], js["sessions"], "sessions")
        approx(py["finalized"], js["finalized"], "finalized")
        approx(py["fmt"], js["fmt"], "fmt")
        approx(py["retake_seeds"], js["retake_seeds"], "retake_seeds")


if __name__ == "__main__":
    unittest.main(verbosity=2)
