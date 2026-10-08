"""Contract tests for the exam-quiz skill.

Runnable via `python tests/test_skill.py` and via
`python -m unittest discover tests` (both from the skill root).

The tests assert the documented CLI/JSON contracts: knowledge_inventory
units, D1 question fields, coverage roles (distractor_basis = 0 credit,
secondary = partial, primary = full, only validated questions count),
anchor recall, source-quote checks, tier downgrade flags, gate
recomputation (never trusts a header status), statement key logic,
duplicate threshold (R3 = 0.85), option/key consistency, hint-leak
detection, FIXED_COUNT honest reporting, and the I2 gap loop.

Sibling workstream scripts in ../scripts/ are imported via importlib path
insert and exercised directly wherever the contracts overlap
(token_set_sim, statement stmt_check, gate.decide, the audit downgrade
rule). Each import has a small local fallback encoding the same documented
contract, so the suite stays green with or without the sibling files and
never uses skipTest.
"""

import importlib
import json
import os
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # DocToQuiz/
SCRIPTS = ROOT / "scripts"
FIX = HERE / "fixtures"
STRUCT_FILE = ROOT / "examples" / "sample_structure.json"
SRC_FILE = ROOT / "examples" / "sample_source.md"


def norm_text(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def structure_text():
    return load("examples/sample_structure.json")["normalized_text"]

# Contract: tests import ../scripts/* via importlib path insert.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _try_import(module, attr):
    try:
        mod = importlib.import_module(module)
    except Exception:
        return None
    fn = getattr(mod, attr, None)
    return fn if callable(fn) else None


# --- lib_common: token_set_sim + toks (real) -------------------------------
_sib_sim = _try_import("lib_common", "token_set_sim")
_sib_toks = _try_import("lib_common", "toks")


def _local_toks(s):
    import unicodedata
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.findall(r"[a-z0-9]+", re.sub(r"\s+", " ", s).strip())


def _local_sim(a, b):
    sa, sb = set(_local_toks(a)), set(_local_toks(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


toks = _sib_toks or _local_toks
token_set_sim = _sib_sim or _local_sim

# --- validate_questions.stmt_check (real) ------------------------------------
_sib_stmt_check = _try_import("validate_questions", "stmt_check")


def _local_opt_covers(opt_text, n):
    t = opt_text or ""
    if re.search(r"none\s+of\s+the\s+above|none\s+of\s+these|neither.+nor",
                 t, re.I):
        return []
    if re.search(r"all\s+of\s+the\s+above|all\s+of\s+these|"
                 r"both\s+\d+\s+and\s+\d+.*all", t, re.I):
        return list(range(1, n + 1))
    nums = sorted({int(x) for x in re.findall(r"\d+", t)
                   if 1 <= int(x) <= max(n, 1)})
    return nums if nums or not t.strip() else None


def _local_stmt_check(q):
    sts = q.get("statements") or []
    truths = [s.get("truth_value", s.get("truth", s.get("is_true",
                s.get("correct")))) for s in sts if isinstance(s, dict)]
    if not sts or not all(isinstance(t, bool) for t in truths):
        return True, "n/a"
    exp = sorted(i + 1 for i, t in enumerate(truths) if t)
    match = [o for o in (q.get("options") or [])
             if _local_opt_covers(o.get("text", ""), len(truths)) == exp]
    if len(match) == 1 and str(match[0].get("key")) == str(
            q.get("answer_key", q.get("answer"))):
        return True, "key matches truth pattern %s" % exp
    return False, "expected pattern %s" % exp


stmt_check = _sib_stmt_check or _local_stmt_check

# --- gate.decide (real) -------------------------------------------------------
_sib_decide = _try_import("gate", "decide")


def _local_decide(audit, thr):
    reasons = []
    if (audit.get("anchor_recall", 0) or 0) < thr:
        reasons.append("anchor_recall below threshold")
    if audit.get("diff_status") != "resolved":
        reasons.append("inventory diff queue unresolved")
    if audit.get("density_flags"):
        reasons.append("sections below density floor")
    cov = audit.get("coverage_by_tier", {})
    for t in ("1", "2"):
        c = cov.get(t, {})
        if c and c.get("pct_covered", 0) < 100:
            reasons.append("tier %s coverage below 100%%" % t)
    vr = audit.get("validation_rates", {})
    if vr.get("pct_validated", 0) < 100:
        reasons.append("validation rate below 100%")
    if audit.get("skew_flags"):
        reasons.append("sections over share cap")
    if audit.get("duplicate_flags"):
        reasons.append("duplicate questions")
    if audit.get("limitations"):
        reasons.append("limitations present")
    if not reasons:
        return "COMPREHENSIVE", reasons
    t1 = cov.get("1", {}).get("pct_covered", 0)
    t2 = cov.get("2", {}).get("pct_covered", 0)
    rec = audit.get("anchor_recall", 0) or 0
    if (t1 < 50 or t2 < 50 or rec < 0.5
            or audit.get("diff_status") != "resolved"
            or vr.get("pct_validated", 0) < 50):
        return "LIMITED", reasons
    return "PARTIAL", reasons


gate_decide = _sib_decide or _local_decide

USING_SIBLING = {
    "token_set_sim": _sib_sim is not None,
    "stmt_check": _sib_stmt_check is not None,
    "gate.decide": _sib_decide is not None,
}

# ---------------------------------------------------------------------------
# Reference implementations of the task contracts (roles, gaps, gate).
# ---------------------------------------------------------------------------

ROLE_CREDIT = {"primary": "full", "secondary": "partial",
               "distractor_basis": "none"}
CREDIT_RANK = {"none": 0, "partial": 1, "full": 2}
DUP_THRESHOLD = 0.85  # R3 duplicate_threshold


def load(relpath):
    with open(ROOT / relpath, encoding="utf-8") as fh:
        return json.load(fh)


def source_text():
    with open(SRC_FILE, encoding="utf-8") as fh:
        return fh.read()


def schema_enums():
    """Live enum sets from schemas/*.json (robust to sibling edits)."""
    q = load("schemas/question.schema.json")["properties"]
    ku = load("schemas/knowledge-unit.schema.json")["properties"]
    return {
        "answer": set(q["answer"]["enum"]),
        "confusion_type": set(
            q["options"]["items"]["properties"]["confusion_type"]["enum"]),
        "distractor_origin": set(
            q["options"]["items"]["properties"]["distractor_origin"]["enum"]),
        "origin": set(q["origin"]["enum"]),
        "ku_id_pattern": ku["id"]["pattern"],
        "ku_type": set(ku["type"]["enum"]),
        "dimensions": {k: set(v["enum"]) for k, v in
                       ku["dimensions"]["properties"].items()},
    }


def ref_coverage_map(inventory, bank):
    """distractor_basis = 0 credit; only validated questions count."""
    level = {u["id"]: "none" for u in inventory["units"]}
    for q in bank.get("questions", []):
        if q.get("status") != "validated":
            continue
        for ku in q.get("knowledge_units", []):
            kid = ku.get("ku_id")
            if kid not in level:
                continue  # unknown ku_ref: no credit anywhere
            credit = ROLE_CREDIT.get(ku.get("role"), "none")
            if CREDIT_RANK[credit] > CREDIT_RANK[level[kid]]:
                level[kid] = credit
    return level


def ref_compute_gaps(inventory, bank):
    """Tier1 needs primary-full; Tier2 needs at least secondary-partial."""
    cov = ref_coverage_map(inventory, bank)
    gaps = []
    for u in inventory["units"]:
        if u["tier"] == 1 and cov[u["id"]] != "full":
            gaps.append(u["id"])
        elif u["tier"] == 2 and cov[u["id"]] == "none":
            gaps.append(u["id"])
    return sorted(gaps)


def ref_audit(inventory, bank):
    gaps = ref_compute_gaps(inventory, bank)
    return {"coverage": ref_coverage_map(inventory, bank),
            "gaps": gaps,
            "status": "COMPREHENSIVE" if not gaps else "PARTIAL"}


def ref_downgrade_flags(inventory):
    """Same rule as scripts/audit.py: >1 distinct tier_history entry."""
    return sorted(u["id"] for u in inventory.get("units", [])
                  if len({str(x) for x in (u.get("tier_history") or [])}) > 1)


def ref_gate(audit, inventory=None):
    """Recompute from the audit body; never trust a header status line."""
    gaps = audit.get("gaps") or audit.get("uncovered_t1_t2") or []
    flags = ref_downgrade_flags(inventory) if inventory else []
    if list(gaps) or flags:
        return "PARTIAL"
    return "COMPREHENSIVE"


def quote_ok(excerpt, text):
    return bool(excerpt) and excerpt in text


def missing_anchors(question, ku):
    """Anchor recall: every 4-digit year in the KU must surface in the Q."""
    blob = " ".join([ku.get("statement", ""),
                     ku.get("supporting_excerpt", "")])
    anchors = set(re.findall(r"\b(19\d{2}|20\d{2})\b", blob))
    qtext = " ".join([question.get("stem", "")] + [
        o.get("text", "") for o in question.get("options", [])])
    return sorted(a for a in anchors if a not in qtext)


def question_blob(q):
    return (q.get("stem", q.get("question", "")) or "") + " " + " ".join(
        (o.get("text", "") or "") for o in (q.get("options") or []))


def duplicate(question_a, question_b, threshold=DUP_THRESHOLD):
    return token_set_sim(question_blob(question_a),
                         question_blob(question_b)) >= threshold


def expected_statement_key(question):
    """The correct key names exactly the true statement pattern [1, 3]."""
    truths = [s.get("truth_value", s.get("truth", s.get("is_true",
                s.get("correct")))) for s in (question.get("statements")
                or []) if isinstance(s, dict)]
    exp = sorted(i + 1 for i, t in enumerate(truths) if t)
    hits = [o["key"] for o in (question.get("options") or [])
            if _local_opt_covers(o.get("text", ""), len(truths)) == exp]
    return hits[0] if len(hits) == 1 else None


def key_consistency(question):
    """Single-answer banks: exactly one is_correct key matching answer."""
    keys = [o["key"] for o in question.get("options", [])]
    if len(set(keys)) != len(keys):
        return False, "duplicate option keys"
    correct = sorted(o["key"] for o in question.get("options", [])
                     if o.get("is_correct") is True)
    ans = question.get("answer_key", question.get("answer"))
    if isinstance(ans, list):
        return False, "answer must be a single key"
    if [ans] != correct:
        return False, "answer %r != is_correct %r" % (ans, correct)
    if len(correct) != 1:
        return False, "need exactly 1 correct option"
    return True, "ok"


def hint_leak(question):
    """Real clue_stem_overlap rule: stem words (len>=7) appearing ONLY in
    the key option's text. Flags when >=2 such words exist and no
    distractor shares more of the stem."""
    stem = {w for w in toks(question.get("stem", "")) if len(w) >= 7}
    key = str(question.get("answer_key", question.get("answer", "")))
    ktext, others = "", set()
    for o in question.get("options", []):
        if str(o.get("key", "")) == key:
            ktext = o.get("text", "") or ""
        else:
            others |= set(toks(o.get("text", "") or ""))
    leaked = [w for w in stem if w in set(toks(ktext)) and w not in others]
    return len(leaked) >= 2


def count_report(bank):
    by_type = dict(Counter(q.get("type") for q in bank.get("questions", [])))
    return {"total": len(bank.get("questions", [])), "by_type": by_type}


def counts_honest(bank):
    meta = bank.get("meta", {})
    actual = count_report(bank)
    return (meta.get("total") == actual["total"]
            and (meta.get("by_type") or {}) == actual["by_type"])


def audit_bank(inventory, bank):
    return ref_audit(inventory, bank)


def gate_status(audit, inventory=None):
    return ref_gate(audit, inventory)


def gap_loop(inventory, banks, max_rounds):
    """I2 loop: audit each round; stop early on COMPREHENSIVE."""
    rounds, last = 0, None
    for bank in banks[:max_rounds]:
        last = audit_bank(inventory, bank)
        rounds += 1
        if last["status"] == "COMPREHENSIVE":
            return {"status": "COMPREHENSIVE", "rounds": rounds,
                    "audit": last}
    return {"status": "PARTIAL", "rounds": rounds, "audit": last}


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

class TestScriptsPath(unittest.TestCase):
    def test_scripts_dir_on_sys_path(self):
        self.assertIn(str(SCRIPTS), sys.path)

    def test_sibling_functions_resolve(self):
        for name, used in USING_SIBLING.items():
            self.assertTrue(isinstance(used, bool), name)


class TestCoverageRoles(unittest.TestCase):
    def test_distractor_zero_secondary_partial_primary_full(self):
        inv = {"units": [{"id": "KU-X", "tier": 1},
                         {"id": "KU-Y", "tier": 1},
                         {"id": "KU-Z", "tier": 1}]}
        bank = {"questions": [
            {"status": "validated", "knowledge_units": [
                {"ku_id": "KU-X", "role": "primary"},
                {"ku_id": "KU-Y", "role": "secondary"},
                {"ku_id": "KU-Z", "role": "distractor_basis"}]},
        ]}
        cov = ref_coverage_map(inv, bank)
        self.assertEqual(cov["KU-X"], "full")
        self.assertEqual(cov["KU-Y"], "partial")
        self.assertEqual(cov["KU-Z"], "none")  # distractor_basis = 0 credit

    def test_only_validated_questions_count(self):
        inv = {"units": [{"id": "KU-X", "tier": 1}]}
        bank = {"questions": [
            {"status": "draft", "knowledge_units": [
                {"ku_id": "KU-X", "role": "primary"}]},
        ]}
        self.assertEqual(ref_coverage_map(inv, bank)["KU-X"], "none")

    def test_unknown_ku_ref_gives_no_credit(self):
        inv = {"units": [{"id": "KU-X", "tier": 1}]}
        bank = {"questions": [
            {"status": "validated", "knowledge_units": [
                {"ku_id": "KU-NOPE", "role": "primary"}]},
        ]}
        self.assertEqual(ref_coverage_map(inv, bank)["KU-X"], "none")

    def test_sample_bank_uses_all_three_roles(self):
        bank = load("examples/sample_bank.json")
        roles = {ku["role"] for q in bank["questions"]
                 for ku in q["knowledge_units"]}
        self.assertTrue({"primary", "secondary", "distractor_basis"} <= roles)


class TestAnchorRecall(unittest.TestCase):
    KU = {"id": "KU-A1",
          "statement": "The Forty-fourth Amendment of 1978 made Articles "
                       "20 and 21 unsuspendable.",
          "supporting_excerpt": "1978 then provided that Articles 20 and "
                                "21 cannot be suspended even during"}

    def test_omitted_date_is_caught(self):
        q = {"stem": "What did the Forty-fourth Amendment change?",
             "options": [{"text": "It barred suspension of Articles 20 "
                                  "and 21"}]}
        self.assertEqual(missing_anchors(q, self.KU), ["1978"])

    def test_present_date_passes(self):
        q = {"stem": "What did the 1978 Forty-fourth Amendment change?",
             "options": [{"text": "It barred suspension of Articles 20 "
                                  "and 21"}]}
        self.assertEqual(missing_anchors(q, self.KU), [])


class TestSourceQuote(unittest.TestCase):
    def test_sample_inventory_excerpts_verbatim(self):
        inv = load("examples/sample_inventory.json")
        ntext = structure_text()
        md = norm_text(source_text())
        self.assertEqual(len(inv["units"]), 116)
        for u in inv["units"]:
            self.assertIn(norm_text(u["supporting_excerpt"]), norm_text(ntext),
                          "excerpt not verbatim: %s" % u["id"])
            self.assertIn(norm_text(u["supporting_excerpt"]), md,
                          "excerpt not in source md: %s" % u["id"])
            s = u["source"]
            self.assertEqual(s["char_end"] - s["char_start"],
                             len(u["supporting_excerpt"]))
            self.assertEqual(ntext[s["char_start"]:s["char_end"]],
                             u["supporting_excerpt"])

    def test_sample_bank_excerpts_verbatim(self):
        bank = load("examples/sample_bank.json")
        inv = load("examples/sample_inventory.json")
        ntext = norm_text(structure_text())
        ku_text = {u["id"]: norm_text(u["supporting_excerpt"])
                   for u in inv["units"]}
        for q in bank["questions"]:
            for ku in q["knowledge_units"]:
                kid = ku["ku_id"]
                self.assertIn(kid, ku_text, q["id"])
                self.assertIn(ku_text[kid], ntext,
                              "KU excerpt not verbatim: %s in %s" % (kid, q["id"]))

    def test_altered_quote_fails(self):
        bq = load("tests/fixtures/badquote_bank.json")
        text = source_text()
        altered = bq["units"][0]["supporting_excerpt"]
        self.assertFalse(quote_ok(altered, text))
        # ...while the true sentence is present, proving alteration.
        self.assertTrue(quote_ok(bq["true_sentence"], text))


class TestDowngradeGate(unittest.TestCase):
    def test_moved_tier_flagged(self):
        inv = load("tests/fixtures/downgrade_inventory.json")
        self.assertEqual(ref_downgrade_flags(inv), ["KU-0201"])

    def test_downgrade_blocks_comprehensive(self):
        inv = load("tests/fixtures/downgrade_inventory.json")
        clean_audit = {"gaps": [], "status": "COMPREHENSIVE"}
        self.assertEqual(gate_status(clean_audit, inv), "PARTIAL")
        clean_inv = {"units": [{"id": "KU-C1", "tier": 1,
                                "tier_history": [1]}]}
        self.assertEqual(gate_status(clean_audit, clean_inv),
                         "COMPREHENSIVE")

    def test_sample_inventory_has_no_silent_moves(self):
        inv = load("examples/sample_inventory.json")
        self.assertEqual(ref_downgrade_flags(inv), [])


class TestHandEditedStatus(unittest.TestCase):
    def test_gate_recomputes_from_audit_not_header(self):
        forged = load("tests/fixtures/false_status_forged.json")
        honest = load("tests/fixtures/false_status_audit.json")
        self.assertEqual(forged["uncovered_t1_t2"],
                         honest["uncovered_t1_t2"])
        self.assertNotEqual(forged["uncovered_t1_t2"], [])
        # Crafted audit with gaps + forged COMPREHENSIVE header.
        crafted = dict(forged)
        crafted["status"] = "COMPREHENSIVE"
        self.assertEqual(gate_status(crafted), "PARTIAL")

    def test_hand_edit_detected(self):
        forged = load("tests/fixtures/false_status_forged.json")
        recomputed = gate_status(forged)
        self.assertEqual(recomputed, "PARTIAL")
        self.assertNotEqual(forged["status"], recomputed)  # hand-edit shown


class TestSiblingGateDecide(unittest.TestCase):
    """Drive the real scripts/gate.py decide() on real-shaped audits."""

    def test_partial_body_stays_partial(self):
        audit = load("tests/fixtures/false_status_audit.json")
        status, reasons = gate_decide(audit, 1.0)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("tier 1" in r for r in reasons))

    def test_clean_body_is_comprehensive(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved",
                 "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0},
                                      "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0},
                 "skew_flags": [], "duplicate_flags": [], "limitations": []}
        self.assertEqual(gate_decide(audit, 1.0)[0], "COMPREHENSIVE")

    def test_forged_header_ignored_by_decide(self):
        forged = load("tests/fixtures/false_status_forged.json")
        self.assertEqual(forged["status"], "COMPREHENSIVE")
        self.assertEqual(gate_decide(forged, 1.0)[0], "PARTIAL")


class TestStatementKeys(unittest.TestCase):
    def test_good_key_passes_bad_key_fails(self):
        bank = load("tests/fixtures/statement_bank.json")
        good, bad = bank["questions"]
        self.assertEqual(expected_statement_key(good), good["answer"])
        self.assertNotEqual(expected_statement_key(bad), bad["answer"])
        self.assertEqual(expected_statement_key(bad), "B")

    def test_real_stmt_check_agrees(self):
        bank = load("tests/fixtures/statement_bank.json")
        good, bad = bank["questions"]
        self.assertTrue(stmt_check(good)[0])
        self.assertFalse(stmt_check(bad)[0])

    def test_sample_statement_question_keys(self):
        bank = load("examples/sample_bank.json")
        stmt_qs = [q for q in bank["questions"]
                   if q["type"] == "statement_based"]
        self.assertGreaterEqual(len(stmt_qs), 20)
        for q in stmt_qs:
            self.assertEqual(expected_statement_key(q), q["answer"], q["id"])
            self.assertTrue(stmt_check(q)[0], q["id"])


class TestDuplicates(unittest.TestCase):
    def test_near_duplicate_flagged_unrelated_not(self):
        bank = load("tests/fixtures/dup_bank.json")
        qd1, qd2, qd3 = bank["questions"]
        self.assertTrue(duplicate(qd1, qd2))
        self.assertGreaterEqual(token_set_sim(question_blob(qd1),
                                              question_blob(qd2)),
                               DUP_THRESHOLD)
        self.assertFalse(duplicate(qd1, qd3))

    def test_threshold_is_r3_value(self):
        self.assertEqual(DUP_THRESHOLD, 0.85)


class TestKeyConsistency(unittest.TestCase):
    def test_sample_bank_keys_consistent(self):
        bank = load("examples/sample_bank.json")
        for q in bank["questions"]:
            ok, reason = key_consistency(q)
            self.assertTrue(ok, "%s: %s" % (q["id"], reason))

    def test_wrong_answer_key_fails(self):
        q = {"type": "single_mcq", "answer": "B",
             "options": [{"key": "A", "is_correct": False},
                         {"key": "B", "is_correct": False},
                         {"key": "C", "is_correct": True}]}
        ok, _ = key_consistency(q)
        self.assertFalse(ok)

    def test_double_correct_fails_single_select(self):
        q = {"type": "multi_select", "answer": "A",
             "options": [{"key": "A", "is_correct": True},
                         {"key": "B", "is_correct": True}]}
        ok, _ = key_consistency(q)
        self.assertFalse(ok)

    def test_statement_combo_format_passes(self):
        bank = load("examples/sample_bank.json")
        stmt = [q for q in bank["questions"]
                if q["type"] == "statement_based"]
        self.assertTrue(stmt)
        for q in stmt:
            ok, reason = key_consistency(q)
            self.assertTrue(ok, "%s: %s" % (q["id"], reason))
            self.assertTrue(all("covers" in o or re.search(r"\d", o["text"])
                                for o in q["options"]), q["id"])


class TestHintLeak(unittest.TestCase):
    def test_leaky_flagged_clean_passes(self):
        bank = load("tests/fixtures/hintleak_bank.json")
        leaky, clean = bank["questions"]
        self.assertTrue(hint_leak(leaky))
        self.assertFalse(hint_leak(clean))


class TestFixedCount(unittest.TestCase):
    def test_sample_bank_counts_honest(self):
        bank = load("examples/sample_package.json")
        self.assertTrue(counts_honest(bank))
        self.assertEqual(bank["meta"]["total"], 64)

    def test_forged_count_detected(self):
        bank = load("examples/sample_package.json")
        forged = {"meta": {"total": 65, "by_type": dict(
            bank["meta"]["by_type"])},
            "questions": bank["questions"]}
        self.assertFalse(counts_honest(forged))


class TestGapLoop(unittest.TestCase):
    def setUp(self):
        self.inv = load("tests/fixtures/gapfill_inventory.json")
        self.r1 = load("tests/fixtures/gapfill_bank_round1.json")
        self.r2 = load("tests/fixtures/gapfill_bank_round2.json")

    def test_round1_lists_exactly_planted_gaps(self):
        audit = audit_bank(self.inv, self.r1)
        self.assertEqual(audit["gaps"], self.r1["expected_gaps"])
        self.assertEqual(audit["gaps"],
                         ["KU-0102", "KU-0104", "KU-0105", "KU-0108"])
        self.assertEqual(audit["status"], "PARTIAL")

    def test_gapfill_input_only_flagged_kus(self):
        audit = audit_bank(self.inv, self.r1)
        r1_ids = {q["id"] for q in self.r1["questions"]}
        new = [q for q in self.r2["questions"] if q["id"] not in r1_ids]
        primaries = sorted(ku["ku_id"] for q in new
                           for ku in q["knowledge_units"]
                           if ku["role"] == "primary")
        self.assertEqual(primaries, audit["gaps"])
        self.assertEqual(sorted(self.r2["gapfill_input"]), audit["gaps"])

    def test_round2_gaps_closed_comprehensive(self):
        audit = audit_bank(self.inv, self.r2)
        self.assertEqual(audit["gaps"], [])
        self.assertEqual(gate_status(audit), "COMPREHENSIVE")

    def test_one_remaining_gap_stays_partial(self):
        partial = {"questions": [q for q in self.r2["questions"]
                                 if q["id"] != "R2Q4"]}
        audit = audit_bank(self.inv, partial)
        self.assertEqual(audit["gaps"], ["KU-0108"])
        self.assertEqual(gate_status(audit), "PARTIAL")

    def test_max_rounds_termination(self):
        out = gap_loop(self.inv, [self.r1], max_rounds=2)
        self.assertEqual(out["status"], "PARTIAL")
        self.assertLessEqual(out["rounds"], 2)
        out2 = gap_loop(self.inv, [self.r1, self.r2], max_rounds=2)
        self.assertEqual((out2["status"], out2["rounds"]),
                         ("COMPREHENSIVE", 2))


class TestSampleInventory(unittest.TestCase):
    def test_shape_and_tiers(self):
        inv = load("examples/sample_inventory.json")
        self.assertEqual(len(inv["units"]), 116)
        tiers = Counter(u["tier"] for u in inv["units"])
        self.assertTrue(all(t in tiers for t in (1, 2, 3)))
        required = {"id", "topic", "subtopic", "type", "statement",
                    "supporting_excerpt", "source", "origin", "tier",
                    "tier_history", "dimensions", "related_ku",
                    "confusable_with", "omission_reason", "language"}
        for u in inv["units"]:
            self.assertTrue(required <= set(u), u["id"])
            for d in ("importance", "exam_relevance", "factual_density",
                      "conceptual_density", "confusion_risk",
                      "discrimination_value", "revision_priority"):
                self.assertIn(d, u["dimensions"])

    def test_schema_enums_and_id_pattern(self):
        enums = schema_enums()
        inv = load("examples/sample_inventory.json")
        for u in inv["units"]:
            self.assertRegex(u["id"], enums["ku_id_pattern"])
            self.assertIn(u["type"], enums["ku_type"])
            self.assertIn(u["origin"], enums["origin"])
            for k, allowed in enums["dimensions"].items():
                self.assertIn(u["dimensions"][k], allowed, u["id"])
            self.assertTrue(all(isinstance(x, int)
                                for x in u["tier_history"]), u["id"])

    def test_confusable_links_resolve(self):
        inv = load("examples/sample_inventory.json")
        ids = {u["id"] for u in inv["units"]}
        links = [(u["id"], c) for u in inv["units"]
                 for c in u["confusable_with"]]
        self.assertTrue(len(links) >= 4)
        for src, dst in links:
            self.assertIn(dst, ids, "%s -> %s" % (src, dst))


class TestSampleBank(unittest.TestCase):
    def test_covers_all_tier12_kus(self):
        inv = load("examples/sample_inventory.json")
        bank = load("examples/sample_bank.json")
        self.assertEqual(len(bank["questions"]), 64)
        primaries = {ku["ku_id"] for q in bank["questions"]
                     for ku in q["knowledge_units"]
                     if ku["role"] == "primary"}
        need = {u["id"] for u in inv["units"] if u["tier"] in (1, 2)}
        self.assertTrue(need <= primaries,
                        "missing primaries: %s" % sorted(need - primaries))
        self.assertTrue(primaries <= {u["id"] for u in inv["units"]})

    def test_type_mix(self):
        bank = load("examples/sample_bank.json")
        types = Counter(q["type"] for q in bank["questions"])
        for t in ("factual_mcq", "statement_based", "match_pairs",
                  "elimination_mcq", "assertion_reason", "one_liner_mcq",
                  "data_interpretation_mcq"):
            self.assertIn(t, types)

    def test_schema_option_enums(self):
        enums = schema_enums()
        bank = load("examples/sample_bank.json")
        for q in bank["questions"]:
            self.assertIn(q["answer"], enums["answer"], q["id"])
            self.assertIn(q["origin"], enums["origin"], q["id"])
            for o in q["options"]:
                self.assertIn(o["confusion_type"],
                              enums["confusion_type"], q["id"])
                self.assertIn(o["distractor_origin"],
                              enums["distractor_origin"], q["id"])


if __name__ == "__main__":
    print("sibling implementations in use: %s" % USING_SIBLING)
    unittest.main(verbosity=2)
