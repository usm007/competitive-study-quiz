"""Competitive-Exam Question Quality Engine (Phase 3).

Evaluates questions against 11 deterministic quality dimensions:
1. accuracy (single defensible answer, key consistency, statement logic, blind solve)
2. source_support (KU refs, source block resolution, verbatim excerpts, source-bound compliance)
3. uniqueness (exact/semantic duplicates, same-fact+same-purpose redundancy, diversity preservation)
4. distractor_quality (plausible, same domain, valid purpose/origin/type, no absurd or duplicate distractors)
5. exam_value (academic tone, serious exam value, no frivolous trivia or superficial wording)
6. difficulty_fit (reasoning demand matches difficulty: easy/medium/hard, no fake difficulty or filler)
7. clarity (clear, unambiguous stem, direct exam language, no artificial filler or unstated assumptions)
8. purpose_fit (deterministic purpose mismatch detection: distinction, chronology, statement_evaluation, etc.)
9. leak_prevention (answer length outlier, extreme qualifiers, grammatical clues, stem overlap leak)
10. statement_quality (2+ statements, boolean truth values, valid false alteration types, single answer logic)
11. explanation_quality (pedagogical explanation, clarifies tested distinction, rejects lazy boilerplates)

Assigns rubric grade (A=Excellent, B=Good, C=Needs Improvement, D=Reject) and quality status (accepted/rejected).
"""
import argparse
import collections
import itertools
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, toks, token_set_sim, fail, run_main

VALID_PURPOSES = {
    "direct_recall", "conceptual_understanding", "distinction", "confusable_fact",
    "elimination", "statement_evaluation", "chronology", "classification",
    "cause_effect", "exception", "association", "application", "integrated_concept"
}

VALID_DISTRACTOR_PURPOSES = {
    "confusable_fact", "adjacent_value", "partial_truth", "reversed_relation",
    "wrong_category", "wrong_entity", "wrong_date", "scope_error", "causal_reversal"
}

VALID_CONFUSION_TYPES = {
    "near_synonym", "adjacent_value", "adjacent_date", "reversed_causality", "reversed_relation",
    "wrong_date", "wrong_person", "wrong_place", "wrong_entity", "wrong_article",
    "wrong_category", "partial_truth", "overgeneralization", "scope_error",
    "causal_reversal", "plausible_external"
}

VALID_ALTERATION_TYPES = {
    "date", "date_shift", "entity", "entity_swap", "place", "place_swap",
    "function", "classification", "relationship", "reversed_relation",
    "scope", "scope_change", "causality", "causality_flip", "exception",
    "quantitative_value", "value_swap", "negation", "partial_truth",
    "overgeneralization", "fabrication"
}

ABSURD_INDICATORS = {
    "mars", "jupiter", "pineapple", "chocolate", "pizza", "superman", "batman",
    "99999", "12345", "foo", "bar", "lorem", "ipsum", "test text", "dummy", "random option"
}

ARTIFICIAL_FILLER_PATTERNS = [
    r"in\s+the\s+context\s+of\s+the\s+aforementioned\s+discussion",
    r"as\s+elaborated\s+in\s+the\s+preceding\s+paragraphs?",
    r"which\s+among\s+the\s+following\s+can\s+be\s+considered\s+to\s+be\s+true\s+with\s+regard\s+to",
    r"it\s+may\s+be\s+pertinent\s+to\s+ask\s+whether",
]

LAZY_EXPLANATION_PATTERNS = [
    r"^option\s+[A-D]\s+is\s+correct\s+because\s+it\s+is\s+(given|stated|mentioned)\s+in\s+the\s+document\.?$",
    r"^this\s+is\s+(given|stated|mentioned)\s+in\s+the\s+(document|source|text)\.?$",
    r"^as\s+per\s+the\s+source\.?$",
    r"^correct\s+answer\s+is\s+[A-D]\.?$",
    r"^refer\s+to\s+the\s+text\.?$"
]


def extract_primary_ku(q):
    kus = q.get("knowledge_units") or []
    for e in kus:
        if isinstance(e, dict) and e.get("role") == "primary":
            return e.get("ku_id")
    if q.get("primary_ku"):
        return q.get("primary_ku")
    if kus and isinstance(kus[0], dict):
        return kus[0].get("ku_id")
    if q.get("ku_refs"):
        return q.get("ku_refs")[0]
    return None


def extract_all_kus(q):
    out = []
    for e in q.get("knowledge_units") or []:
        if isinstance(e, dict) and e.get("ku_id"):
            out.append(e["ku_id"])
        elif isinstance(e, str):
            out.append(e)
    for k in (q.get("ku_refs") or q.get("ku_ids") or []):
        if k not in out:
            out.append(k)
    return out


def opt_covers(o, n):
    if isinstance(o.get("covers"), list):
        try:
            return sorted(int(x) for x in o["covers"])
        except (TypeError, ValueError):
            return None
    t = o.get("text", "")
    if re.search(r"none\s+of\s+the\s+above|none\s+of\s+these|neither.+nor", t, re.I):
        return []
    if re.search(r"all\s+of\s+the\s+above|all\s+of\s+these|both\s+\d+\s+and\s+\d+.*all", t, re.I):
        return list(range(1, n + 1))
    nums = sorted({int(x) for x in re.findall(r"\d+", t) if 1 <= int(x) <= max(n, 1)})
    return nums if nums or not t.strip() else None


def truth_of(s):
    for k in ("truth_value", "truth", "is_true", "correct"):
        if isinstance(s.get(k), bool):
            return s[k]
    return None


def blind_solve_stmt(q):
    """Blindly solve a statement-based question using statement truths."""
    sts = q.get("statements") or []
    truths = [truth_of(s) for s in sts if isinstance(s, dict)]
    if not sts or not all(isinstance(t, bool) for t in truths):
        return None, "no complete statement truths"
    expected = sorted(i + 1 for i, t in enumerate(truths) if t)
    opts = q.get("options") or []
    matches = [o for o in opts if opt_covers(o, len(truths)) == expected]
    if len(matches) == 1:
        return str(matches[0].get("key")), "exact match for pattern %s" % expected
    if len(matches) > 1:
        return None, "multiple options match pattern %s" % expected
    return None, "no option matches expected pattern %s" % expected


def evaluate_accuracy(q, st_text, ku_map):
    notes = []
    status = "PASS"
    opts = q.get("options") or []
    correct_opts = [o for o in opts if o.get("is_correct") is True]
    key = str(q.get("answer_key", q.get("answer", "")))

    if len(correct_opts) != 1:
        status = "FAIL"
        notes.append("single_select violated: %d options marked correct" % len(correct_opts))

    if correct_opts and str(correct_opts[0].get("key", "")) != key:
        status = "FAIL"
        notes.append("key_consistent violated: answer key '%s' != correct option '%s'" %
                     (key, correct_opts[0].get("key")))

    # Statement logic
    if q.get("statements"):
        bkey, bmsg = blind_solve_stmt(q)
        if bkey is None:
            status = "FAIL"
            notes.append("statement blind solve failed: %s" % bmsg)
        elif bkey != key:
            status = "FAIL"
            notes.append("statement blind solve mismatch: derived %s != key %s (%s)" % (bkey, key, bmsg))

    return {"status": status, "notes": notes}


def evaluate_source_support(q, ku_ids, ku_map, block_ids, ntext, mode):
    notes = []
    status = "PASS"
    roles = extract_all_kus(q)
    prim = extract_primary_ku(q)

    if not prim or prim not in ku_ids:
        status = "FAIL"
        notes.append("primary KU '%s' missing or unknown" % prim)

    missing_kus = [k for k in roles if k not in ku_ids]
    if missing_kus:
        status = "FAIL"
        notes.append("unresolved KUs: %s" % missing_kus)

    # Source block IDs
    srcs = []
    for s in q.get("source") or []:
        if isinstance(s, dict) and s.get("block_id"):
            srcs.append(s["block_id"])
        elif isinstance(s, str):
            srcs.append(s)
    if not srcs:
        status = "FAIL"
        notes.append("no source block IDs provided")
    else:
        unresolved_blocks = [b for b in srcs if b not in block_ids]
        if unresolved_blocks:
            status = "FAIL"
            notes.append("unresolved source blocks: %s" % unresolved_blocks)

    # Excerpt check
    exc = q.get("supporting_excerpt", q.get("source_excerpt", q.get("excerpt", ""))) or ""
    if exc:
        if norm(exc) not in ntext:
            status = "FAIL"
            notes.append("supporting excerpt not found verbatim in source")
    else:
        # Check primary KU supporting excerpt
        prim_exc = ku_map.get(prim, "")
        if prim_exc and norm(prim_exc) not in ntext:
            status = "FAIL"
            notes.append("primary KU excerpt '%s' not verbatim in source" % prim)

    # Source bound discipline
    if mode == "SOURCE_BOUND":
        if q.get("origin") == "external":
            status = "FAIL"
            notes.append("external question origin forbidden in SOURCE_BOUND")
        for s in q.get("statements") or []:
            if isinstance(s, dict) and not s.get("ku_basis"):
                status = "FAIL"
                notes.append("statement lacks ku_basis in SOURCE_BOUND")
        # Check for unsupported dates and statistics in stem and correct answer
        stem_txt = q.get("stem", "")
        corr_txt = " ".join((o.get("text") or "") for o in (q.get("options") or []) if o.get("is_correct") is True)
        tested_claim = stem_txt + " " + corr_txt
        # 4-digit years
        for yr in re.findall(r"\b(?:1[789]\d\d|20\d\d)\b", tested_claim):
            if yr not in ntext:
                status = "FAIL"
                notes.append("unsupported date '%s' absent from source document" % yr)
                break
        # Percentages
        for pct in re.findall(r"\b\d+(?:\.\d+)?\s*%", tested_claim):
            p_clean = re.sub(r"\s+", "", pct)
            num_part = re.search(r"\b\d+(?:\.\d+)?", pct).group(0)
            in_source = (
                p_clean in ntext or
                norm(pct) in norm(ntext) or
                norm(pct.replace("%", "percent")) in norm(ntext) or
                bool(re.search(r"\b" + re.escape(num_part) + r"\s+(?:percent|pct|per\s+cent)\b", ntext, re.I)) or
                bool(re.search(r"\b" + re.escape(num_part) + r"\s*%", ntext))
            )
            if not in_source:
                status = "FAIL"
                notes.append("unsupported statistic '%s' absent from source document" % pct.strip())
                break

    return {"status": status, "notes": notes}


def evaluate_uniqueness(q, seen_bank, threshold=0.85):
    notes = []
    status = "PASS"
    qid = q.get("id")
    stem = q.get("stem", "")
    purp = q.get("purpose")
    prim = extract_primary_ku(q)
    opts = [(o.get("text") or "") for o in (q.get("options") or [])]
    blob = norm(stem + " " + " ".join(opts))

    fail_notes = []
    warn_notes = []

    for oq in seen_bank:
        if oq.get("id") == qid:
            continue
        ostem = oq.get("stem", "")
        oprim = extract_primary_ku(oq)
        opurp = oq.get("purpose")
        oopts = [(o.get("text") or "") for o in (oq.get("options") or [])]
        oblob = norm(ostem + " " + " ".join(oopts))

        # 1. Exact duplicate
        if norm(stem) and norm(stem) == norm(ostem):
            status = "FAIL"
            fail_notes.append("exact stem duplicate with %s" % oq.get("id"))
            break

        # 2. Semantic duplicate
        sim = token_set_sim(blob, oblob)
        if sim >= threshold:
            status = "FAIL"
            fail_notes.append("semantic duplicate of %s (similarity %.2f)" % (oq.get("id"), sim))
            break

        # 3. Same fact + Same purpose redundancy
        if prim and oprim and prim == oprim and purp and opurp and purp == opurp:
            stem_sim = token_set_sim(stem, ostem)
            if stem_sim >= 0.65:
                status = "FAIL"
                fail_notes.append("redundant: same primary KU %s and same purpose '%s' as %s (stem sim %.2f)" %
                                  (prim, purp, oq.get("id"), stem_sim))
                break
            else:
                warn_notes.append("potential redundancy: same KU %s and purpose '%s' as %s" %
                                 (prim, purp, oq.get("id")))

        # 4. Statement permutation redundancy
        sts1 = [norm(s.get("text", "")) for s in (q.get("statements") or []) if isinstance(s, dict)]
        sts2 = [norm(s.get("text", "")) for s in (oq.get("statements") or []) if isinstance(s, dict)]
        if sts1 and sts2 and len(sts1) == len(sts2):
            matches = sum(1 for s in sts1 if any(token_set_sim(s, s2) >= 0.85 for s2 in sts2))
            if matches == len(sts1):
                status = "FAIL"
                fail_notes.append("statement set duplicate of %s" % oq.get("id"))
                break

    if status != "FAIL" and warn_notes:
        status = "WARNING"

    return {"status": status, "notes": fail_notes + warn_notes}


def evaluate_distractor_quality(q):
    notes = []
    status = "PASS"
    opts = q.get("options") or []
    key = str(q.get("answer_key", q.get("answer", "")))
    key_opt = next((o for o in opts if str(o.get("key")) == key), None)
    key_text = norm(key_opt.get("text", "")) if key_opt else ""

    # Unique option texts
    texts = [norm(o.get("text", "")) for o in opts]
    if len(set(texts)) != len(texts):
        status = "FAIL"
        notes.append("duplicate option text within question")

    # Evaluate each distractor
    for o in opts:
        if str(o.get("key")) == key:
            continue
        otext = o.get("text", "")
        norm_otext = norm(otext)

        # Accidental duplicate of key
        if norm_otext == key_text:
            status = "FAIL"
            notes.append("distractor %s is identical to correct answer" % o.get("key"))

        # Absurd distractor check
        for w in ABSURD_INDICATORS:
            if re.search(r"\b" + re.escape(w) + r"\b", otext, re.I):
                status = "FAIL"
                notes.append("absurd distractor indicator '%s' in option %s" % (w, o.get("key")))

        # Meaningful distractor purpose
        dp = o.get("distractor_purpose")
        if dp and dp not in VALID_DISTRACTOR_PURPOSES:
            if status != "FAIL":
                status = "WARNING"
            notes.append("unknown distractor_purpose '%s' in %s" % (dp, o.get("key")))

        # Confusion type
        ct = o.get("confusion_type")
        if ct and ct not in VALID_CONFUSION_TYPES:
            if status != "FAIL":
                status = "WARNING"
            notes.append("unknown confusion_type '%s' in %s" % (ct, o.get("key")))

        # Check trivial single-letter or empty option
        if len(norm_otext) < 2 and norm_otext not in ("a", "b", "c", "d"):
            status = "FAIL"
            notes.append("distractor %s is trivial or empty" % o.get("key"))

    return {"status": status, "notes": notes}


def evaluate_exam_value(q):
    notes = []
    status = "PASS"
    stem = q.get("stem", "")

    # Trivia / informal tone
    if re.search(r"\b(guess|trick|joke|quizzer|fun\s+fact|trivia|entertaining)\b", stem, re.I):
        status = "FAIL"
        notes.append("informal/trivia tone in stem")

    # Superficial or non-examinable question
    if re.search(r"what\s+color\s+(is|was)\s+the|font\s+size|how\s+many\s+words\s+are|how\s+many\s+pages", stem, re.I):
        status = "FAIL"
        notes.append("trivial non-examinable subject matter")

    return {"status": status, "notes": notes}


def evaluate_difficulty_fit(q):
    notes = []
    status = "PASS"
    diff = (q.get("difficulty") or "medium").lower()
    qtype = q.get("type", "factual_mcq")
    purp = q.get("purpose") or ""
    has_stmts = bool(q.get("statements"))
    num_stmts = len(q.get("statements") or [])

    # EASY: direct recall with low ambiguity
    if diff == "easy":
        if has_stmts and num_stmts >= 3:
            status = "WARNING"
            notes.append("easy difficulty assigned to 3+ statement question")
        if purp in ("integrated_concept", "elimination") and num_stmts >= 3:
            status = "WARNING"
            notes.append("complex reasoning labeled easy")

    # HARD: should require multiple statements, subtle distinction, elimination, or integrated reasoning
    elif diff == "hard":
        if qtype in ("factual_mcq", "one_liner_mcq", "true_false") and not has_stmts:
            if purp not in ("distinction", "integrated_concept", "cause_effect", "elimination"):
                status = "FAIL"
                notes.append("fake difficulty: hard difficulty on simple 1-fact recall form without statements/distinction")

    # Check for artificial complexity pretending to be hard
    stem = q.get("stem", "")
    for pat in ARTIFICIAL_FILLER_PATTERNS:
        if re.search(pat, stem, re.I):
            status = "FAIL"
            notes.append("fake difficulty: convoluted filler phrasing in stem ('%s')" % pat)
            break

    return {"status": status, "notes": notes}


def evaluate_clarity(q):
    notes = []
    status = "PASS"
    stem = (q.get("stem") or "").strip()

    if len(stem) < 10:
        status = "FAIL"
        notes.append("stem too short / truncated (< 10 chars)")

    # Extremely vague or incomplete stems
    if stem.lower() in ("which is true?", "which is false?", "choose the correct:", "consider:"):
        status = "FAIL"
        notes.append("stem is too vague / ambiguous")

    # Unnecessary introductory padding
    for pat in ARTIFICIAL_FILLER_PATTERNS:
        if re.search(pat, stem, re.I):
            if status != "FAIL":
                status = "WARNING"
            notes.append("artificial introductory filler in stem")

    return {"status": status, "notes": notes}


def evaluate_purpose_fit(q):
    notes = []
    status = "PASS"
    purp = q.get("purpose")
    if not purp:
        return {"status": "FAIL", "notes": ["missing explicit purpose"]}

    if purp not in VALID_PURPOSES:
        return {"status": "FAIL", "notes": ["unknown purpose '%s'" % purp]}

    stem = q.get("stem", "")
    qtype = q.get("type", "")
    stmts = q.get("statements") or []
    opts = q.get("options") or []
    all_kus = extract_all_kus(q)

    # 1. distinction: must compare or contrast
    if purp == "distinction":
        dist_cues = r"\b(distinguish|difference|whereas|while|unlike|contrast|opposed|compare|differentia)\b"
        has_cue = re.search(dist_cues, stem, re.I)
        has_opts_comp = any(re.search(dist_cues, o.get("text", ""), re.I) for o in opts)
        has_two_kus = len(all_kus) >= 2
        # If it simply asks for a single date or single definition without comparison
        is_single_date = bool(re.search(r"^(in\s+which\s+year|on\s+which\s+date|when\s+was)\b", stem.strip(), re.I))
        if is_single_date and not (has_cue or has_opts_comp):
            status = "FAIL"
            notes.append("purpose mismatch: 'distinction' question merely asks for a single date")
        elif not (has_cue or has_opts_comp or has_two_kus):
            status = "WARNING"
            notes.append("distinction question lacks explicit comparative cues or multiple KUs")

    # 2. chronology: must involve sequence or ordering
    elif purp == "chronology":
        chrono_cues = r"\b(chronolog|order|sequence|earliest|latest|timeline|arranged|preceded|succeeded)\b"
        if not re.search(chrono_cues, stem, re.I):
            # Check if options are sequences like "1-2-3" or "A -> B"
            has_seq_opts = any(re.search(r"\d\s*[-–>,]\s*\d", o.get("text", "")) for o in opts)
            if not has_seq_opts and qtype != "sequence_mcq":
                status = "FAIL"
                notes.append("purpose mismatch: 'chronology' question lacks temporal ordering cues")

    # 3. statement_evaluation: must have 2+ statements
    elif purp == "statement_evaluation":
        if len(stmts) < 2 and not re.search(r"consider\s+the\s+following\s+statements", stem, re.I):
            status = "FAIL"
            notes.append("purpose mismatch: 'statement_evaluation' requires >= 2 statements")

    # 4. elimination: must involve elimination mechanics
    elif purp == "elimination":
        # Options should be combinations (e.g. 1 only, 1 and 2, etc.) or statement-based
        is_combo = any(re.search(r"\bonly\b|\bboth\b|\bneither\b|\ball\s+of\b|\bnone\s+of\b", o.get("text", ""), re.I)
                       for o in opts)
        if not (len(stmts) >= 2 or is_combo or qtype == "elimination_mcq"):
            status = "FAIL"
            notes.append("purpose mismatch: plain recall MCQ labeled as 'elimination' without elimination options")

    # 5. exception: must ask for an exception
    elif purp == "exception":
        exc_cues = r"\b(not|except|incorrect|false|does\s+not|never)\b"
        if not re.search(exc_cues, stem, re.I):
            status = "FAIL"
            notes.append("purpose mismatch: 'exception' question lacks negative/exception indicator in stem")

    # 6. classification: must test categories or grouping
    elif purp == "classification":
        class_cues = r"\b(classif|category|group|type\s+of|belongs\s+to|classified|falls\s+under|kind\s+of)\b"
        if not (re.search(class_cues, stem, re.I) or any(re.search(class_cues, o.get("text", ""), re.I) for o in opts)):
            if status != "FAIL":
                status = "WARNING"
            notes.append("classification question lacks explicit classification cues")

    # 7. association: must test pairs or matching
    elif purp == "association":
        assoc_cues = r"\b(correctly\s+matched|pair|match|associat|corresponds?\s+to)\b"
        if not (re.search(assoc_cues, stem, re.I) or qtype == "match_pairs" or
                any(":" in o.get("text", "") or "—" in o.get("text", "") or "-" in o.get("text", "") for o in opts)):
            if status != "FAIL":
                status = "WARNING"
            notes.append("association question lacks pair/matching format or cues")

    # 8. cause_effect: must test causality
    elif purp == "cause_effect":
        cause_cues = r"\b(cause|effect|result\s+of|consequence|lead\s+to|leads\s+to|due\s+to|because|reason)\b"
        if not re.search(cause_cues, stem, re.I) and qtype != "assertion_reason":
            if status != "FAIL":
                status = "WARNING"
            notes.append("cause_effect question lacks explicit causal wording")

    # 9. integrated_concept: must link multiple KUs
    elif purp == "integrated_concept":
        if len(all_kus) < 2:
            status = "FAIL"
            notes.append("purpose mismatch: 'integrated_concept' requires >= 2 distinct KUs")

    return {"status": status, "notes": notes}


def evaluate_clue_leak(q):
    notes = []
    status = "PASS"
    opts = q.get("options") or []
    key = str(q.get("answer_key", q.get("answer", "")))
    key_opt = next((o for o in opts if str(o.get("key")) == key), None)
    if not key_opt:
        return {"status": "FAIL", "notes": ["missing key option"]}

    ktext = key_opt.get("text", "") or ""
    klen = len(ktext)
    others = [o.get("text", "") or "" for o in opts if str(o.get("key")) != key]
    other_lens = [len(t) for t in others]

    # 1. Answer length outlier: correct answer substantially longer
    if other_lens:
        avg_other = sum(other_lens) / len(other_lens)
        if avg_other > 0 and klen > 1.35 * avg_other and (klen - avg_other) >= 20:
            status = "FAIL"
            notes.append("answer leak: key option is substantially longer (len=%d vs avg=%0.1f)" % (klen, avg_other))
        elif avg_other > 0 and klen > 1.20 * avg_other and (klen - avg_other) >= 15:
            if status != "FAIL":
                status = "WARNING"
            notes.append("answer leak warning: key option is noticeably longer (len=%d vs avg=%0.1f)" % (klen, avg_other))

    # 2. Extreme qualifier pattern: absolute words only in distractors
    absolutes = {r"\balways\b", r"\bnever\b", r"\bsolely\b", r"\bexclusively\b"}
    abs_in_dist = []
    for d in others:
        for pat in absolutes:
            if re.search(pat, d, re.I):
                abs_in_dist.append(pat)
    abs_in_key = any(re.search(pat, ktext, re.I) for pat in absolutes)
    if abs_in_dist and not abs_in_key and len(abs_in_dist) >= 2:
        if status != "FAIL":
            status = "WARNING"
        notes.append("qualifier clue: absolute words used in multiple distractors")

    # 3. Stem word overlap: rare words in stem appear only in key
    stem = q.get("stem", "")
    swords = {w.lower() for w in toks(stem) if len(w) >= 7}
    if swords and ktext:
        ko = {w.lower() for w in toks(ktext)}
        oo = set()
        for d in others:
            oo |= {w.lower() for w in toks(d)}
        leaked = [w for w in swords if w in ko and w not in oo]
        # Ignore common legal/structural words
        benign = {"fundamental", "constitution", "article", "following", "statement", "amendment", "schedule"}
        real_leaks = [w for w in leaked if w not in benign]
        if len(real_leaks) >= 2:
            status = "FAIL"
            notes.append("stem word leak: words '%s' appear in stem and only in correct option" % real_leaks[:3])
        elif len(real_leaks) == 1:
            if status != "FAIL":
                status = "WARNING"
            notes.append("potential word overlap leak: '%s' only in correct option" % real_leaks[0])

    # 4. Grammatical giveaway (e.g. stem ends in 'an' but only key starts with vowel)
    stem_stripped = stem.strip()
    if re.search(r"\ban\s*$", stem_stripped, re.I):
        key_vowel = bool(re.match(r"^[aeiou]", ktext.strip(), re.I))
        dist_vowels = [bool(re.match(r"^[aeiou]", d.strip(), re.I)) for d in others]
        if key_vowel and not any(dist_vowels):
            status = "FAIL"
            notes.append("grammatical leak: stem ends in 'an' and only correct option begins with a vowel")

    return {"status": status, "notes": notes}


def evaluate_statement_quality(q):
    stmts = q.get("statements")
    if not stmts:
        return {"status": "PASS", "notes": ["no statements (n/a)"]}

    notes = []
    status = "PASS"

    if len(stmts) < 2:
        status = "FAIL"
        notes.append("statement question must carry >= 2 statements")

    truths = []
    for i, s in enumerate(stmts):
        if not isinstance(s, dict):
            status = "FAIL"
            notes.append("statement %d is malformed" % (i + 1))
            continue
        tv = truth_of(s)
        if not isinstance(tv, bool):
            status = "FAIL"
            notes.append("statement %d lacks clear boolean truth_value" % (i + 1))
        else:
            truths.append(tv)

        # Check false statement alteration
        if tv is False:
            alt_t = s.get("alteration_type")
            alt = s.get("alteration")
            if not alt_t:
                if status != "FAIL":
                    status = "WARNING"
                notes.append("false statement %d lacks alteration_type" % (i + 1))
            elif alt_t not in VALID_ALTERATION_TYPES:
                if status != "FAIL":
                    status = "WARNING"
                notes.append("false statement %d has non-standard alteration_type '%s'" % (i + 1, alt_t))

    # All-true or all-false pattern check
    if len(truths) >= 3 and (all(truths) or not any(truths)):
        if status != "FAIL":
            status = "WARNING"
        notes.append("warning: all statements are %s" % ("true" if all(truths) else "false"))

    return {"status": status, "notes": notes}


def evaluate_explanation_quality(q):
    notes = []
    status = "PASS"
    exp = (q.get("explanation") or "").strip()

    if not exp or len(exp) < 15:
        status = "FAIL"
        notes.append("explanation missing or too brief (< 15 chars)")
        return {"status": status, "notes": notes}

    # Lazy explanation checks
    for pat in LAZY_EXPLANATION_PATTERNS:
        if re.search(pat, exp, re.I):
            status = "FAIL"
            notes.append("lazy boilerplate explanation: does not teach ('%s')" % exp)
            break

    # Explanation should ideally mention the subject matter
    prim = extract_primary_ku(q)
    if len(exp) < 30 and status != "FAIL":
        status = "WARNING"
        notes.append("explanation is very brief (< 30 chars)")

    return {"status": status, "notes": notes}


def evaluate_question(q, ku_ids, ku_map, block_ids, ntext, mode, seen_bank):
    """Run full 11-dimension quality evaluation on a single question."""
    qid = q.get("id", "?")
    checks = {}

    checks["accuracy"] = evaluate_accuracy(q, ntext, ku_map)
    checks["source_support"] = evaluate_source_support(q, ku_ids, ku_map, block_ids, ntext, mode)
    checks["uniqueness"] = evaluate_uniqueness(q, seen_bank)
    checks["distractor_quality"] = evaluate_distractor_quality(q)
    checks["exam_value"] = evaluate_exam_value(q)
    checks["difficulty_fit"] = evaluate_difficulty_fit(q)
    checks["clarity"] = evaluate_clarity(q)
    checks["purpose_fit"] = evaluate_purpose_fit(q)
    checks["leak_prevention"] = evaluate_clue_leak(q)
    checks["statement_quality"] = evaluate_statement_quality(q)
    checks["explanation_quality"] = evaluate_explanation_quality(q)

    # Collect notes and fails
    all_fails = []
    all_warnings = []
    for dim, res in checks.items():
        if res["status"] == "FAIL":
            all_fails.extend(["[%s] %s" % (dim, n) for n in res["notes"]])
        elif res["status"] == "WARNING":
            all_warnings.extend(["[%s] %s" % (dim, n) for n in res["notes"]])

    # Grade determination (A, B, C, D)
    if all_fails:
        grade = "D"
        quality_status = "rejected"
    elif len(all_warnings) >= 3:
        grade = "C"
        quality_status = "rejected"
    elif len(all_warnings) >= 1:
        grade = "B"
        quality_status = "accepted"
    else:
        grade = "A"
        quality_status = "accepted"

    rejection_reasons = list(all_fails)
    if grade == "C":
        rejection_reasons.extend(all_warnings)

    return {
        "id": qid,
        "quality_status": quality_status,
        "grade": grade,
        "checks": checks,
        "rejection_reasons": rejection_reasons,
        "warnings": all_warnings
    }


def evaluate_bank(bank, inventory, struct, profile=None, mode="SOURCE_BOUND", threshold=0.85):
    """Evaluate an entire question bank and produce a comprehensive quality report."""
    qs = bank.get("questions") if isinstance(bank, dict) else bank
    units = inventory.get("units") if isinstance(inventory, dict) else inventory
    ku_ids = {u.get("id") for u in units}
    ku_map = {u.get("id"): u.get("supporting_excerpt", "") or "" for u in units}
    block_ids = {x.get("id") for x in struct.get("blocks", [])}
    ntext = norm(struct.get("normalized_text", ""))

    seen_bank = []
    results = []

    for q in qs:
        res = evaluate_question(q, ku_ids, ku_map, block_ids, ntext, mode, seen_bank)
        results.append(res)
        seen_bank.append(q)

    # Summary statistics
    total = len(results)
    accepted = sum(1 for r in results if r["quality_status"] == "accepted")
    rejected = total - accepted
    grades = dict(collections.Counter(r["grade"] for r in results))

    qmap = {q.get("id"): q for q in qs}
    by_purpose = collections.defaultdict(lambda: {"accepted": 0, "rejected": 0})
    by_diff = collections.defaultdict(lambda: {"accepted": 0, "rejected": 0})
    by_type = collections.defaultdict(lambda: {"accepted": 0, "rejected": 0})

    for r in results:
        q = qmap.get(r["id"], {})
        p = q.get("purpose") or "unspecified"
        d = q.get("difficulty") or "unspecified"
        t = q.get("type") or "unspecified"
        st = r["quality_status"]
        by_purpose[p][st] += 1
        by_diff[d][st] += 1
        by_type[t][st] += 1

    all_rej = [note for r in results for note in r["rejection_reasons"]]
    top_reasons = [item[0] for item in collections.Counter(all_rej).most_common(10)]

    report = {
        "summary": {
            "total": total,
            "quality_accepted": accepted,
            "quality_rejected": rejected,
            "grades": grades,
            "by_purpose": dict(by_purpose),
            "by_difficulty": dict(by_diff),
            "by_type": dict(by_type),
            "top_rejection_reasons": top_reasons
        },
        "results": results
    }

    return report


def main(argv):
    ap = argparse.ArgumentParser(description="Evaluate competitive exam question quality")
    ap.add_argument("bank", help="Path to question_bank.json")
    ap.add_argument("inventory", help="Path to knowledge_inventory.json")
    ap.add_argument("struct", help="Path to document_structure.json")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--mode", default="SOURCE_BOUND")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=float, default=0.85)
    a = ap.parse_args(argv)

    for p in (a.bank, a.inventory, a.struct):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)

    bank = load_json(a.bank)
    inv = load_json(a.inventory)
    st = load_json(a.struct)

    rep = evaluate_bank(bank, inv, st, profile=a.profile, mode=a.mode, threshold=a.threshold)

    dest = a.out
    if not dest:
        dest = os.path.join(os.path.dirname(os.path.abspath(a.bank)), "quality_report.json")
    save_json(dest, rep)

    s = rep["summary"]
    print("quality: %d/%d accepted (grades=%s) -> %s" %
          (s["quality_accepted"], s["total"], s["grades"], dest))
    if s["quality_rejected"] > 0:
        print("  REJECTIONS (%d):" % s["quality_rejected"])
        for r in rep["results"]:
            if r["quality_status"] == "rejected":
                print("    %s (Grade %s): %s" % (r["id"], r["grade"], "; ".join(r["rejection_reasons"][:2])))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
