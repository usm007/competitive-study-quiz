"""Deterministic competitive-exam test engine (Phase 3).

Transforms validated question banks into frozen, timestamp-timed exam
papers with exact scoring and Phase 2 revision handoff.

Design rules (see spec PHASE 3):
- Validated questions only; never generate or modify questions live.
- Deterministic assembly: same bank + config + seed => same paper.
- Scoring rules come from configuration (profile values surfaced with
  their verified/unverified status, never hard-coded as official facts).
- Exact arithmetic (Fraction); rounding only at display.
- Unknown question types are rejected, never silently scored.

Sections: seeded RNG, config validation, profile rules, assembly,
pre-test checks, scoring, analysis, sessions, revision handoff, print,
CLI.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main

TEST_ENGINE_VERSION = 1
DEFAULT_SEED = 20261007

SUPPORTED_TYPES = (
    "factual_mcq", "statement_based", "assertion_reason", "match_pairs",
    "elimination_mcq", "one_liner_mcq", "data_interpretation_mcq",
    "reasoning_mcq", "pedagogy_mcq", "sequence_mcq", "true_false",
)

SELECTION_MODES = ("RANDOM", "BALANCED", "CUSTOM_BLUEPRINT")

# Analysis thresholds: observations fire only when data supports them.
HIGH_UNANSWERED_RATE = 0.2
HCE_RATE = 0.1
TIME_CONCENTRATION = 0.5
TIME_PRESSURE_USED = 0.9
MIN_TIME_SAMPLE = 3


# --------------------------------------------------------------------------
# Seeded RNG (xfnv1a + mulberry32). Bit-identical port lives in
# templates/web/test.engine.js; tests/test_test_engine.py checks parity.
# --------------------------------------------------------------------------
def xfnv1a(text):
    """32-bit FNV-1a over UTF-8 bytes (matches the JS port exactly)."""
    h = 2166136261
    for b in str(text).encode("utf-8"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _canon_norm(obj):
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _canon_norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon_norm(v) for v in obj]
    return obj


def canonical_json(obj):
    """Canonical form for hashing: sorted keys, compact separators, raw UTF-8.

    Integral floats normalize to ints so Python float(30) and JS 30 hash alike.
    """
    return json.dumps(_canon_norm(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


class RNG:
    """Mulberry32 over unsigned 32-bit ints (matches JS Math.imul path)."""

    def __init__(self, seed):
        if isinstance(seed, str):
            seed = xfnv1a(seed)
        self.s = int(seed) & 0xFFFFFFFF

    @staticmethod
    def _imul(a, b):
        return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF

    def random(self):
        self.s = (self.s + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.s
        t = self._imul(t ^ (t >> 15), (1 | t)) & 0xFFFFFFFF
        t = (((t + self._imul(t ^ (t >> 7), (61 | t))) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return (((t ^ (t >> 14)) & 0xFFFFFFFF)) / 4294967296.0

    def shuffle(self, items):
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = int(self.random() * (i + 1))
            items[i], items[j] = items[j], items[i]
        return items


# --------------------------------------------------------------------------
# Question accessors (tolerant of older banks missing new fields).
# --------------------------------------------------------------------------
def q_topic(q):
    return q.get("topic") or q.get("knowledge_area") or q.get("subject") or "General"


def q_diff(q):
    return str(q.get("difficulty") or "medium").lower()


def q_type(q):
    return q.get("type") or q.get("question_type") or "factual_mcq"


def q_purpose(q):
    return q.get("purpose") or "unspecified"


def q_section(q):
    src = q.get("source") or q.get("source_ref") or ""
    refs = src if isinstance(src, list) else [src]
    for s in refs:
        if not isinstance(s, dict):
            if isinstance(s, str) and s:
                return s.split(">")[0].strip() or "General"
            continue
        sp = s.get("section_path", "")
        if isinstance(sp, list):
            if sp and str(sp[0]).strip():
                return str(sp[0]).strip()
        elif isinstance(sp, str) and sp.strip():
            return sp.split(">")[0].strip()
    return "General"


def q_correct_key(q, options=None):
    opts = options if options is not None else (q.get("options") or q.get("choices") or [])
    for x in opts:
        if isinstance(x, dict) and x.get("is_correct"):
            return (x.get("key") or "A").strip().upper()
    a = q.get("answer", q.get("key", q.get("correct", None)))
    if isinstance(a, str) and len(a.strip()) == 1:
        return a.strip().upper()
    return None


def scoring_rule_for(qtype):
    """Single-select MCQ scoring applies to every supported type.

    Unknown types are rejected, never silently scored (§16).
    """
    if qtype not in SUPPORTED_TYPES:
        raise ValueError("no defined scoring behavior for question type %r" % (qtype,))
    return "single_select_mcq"


# --------------------------------------------------------------------------
# Test configuration (§2) and profile rules (§3).
# --------------------------------------------------------------------------
def default_config():
    return {
        "title": "Practice Test",
        "exam_profile": "GENERAL_PSC",
        "question_count": 20,
        "duration_minutes": 30,
        "marks_per_correct": 1.0,
        "negative_marking": {"enabled": True, "penalty_fraction": 0.25},
        "max_attempts": 1,
        "topics": [],
        "difficulty": None,
        "qtypes": None,
        "collect_confidence": True,
        "allow_mark": True,
        "allow_navigation": True,
        "selection": "BALANCED",
        "seed": DEFAULT_SEED,
        "blueprint": None,
        "exclude_ids": [],
    }


def validate_config(cfg):
    """Return (resolved_config, errors). Never raises on bad input."""
    errors = []
    base = default_config()
    if not isinstance(cfg, dict):
        return base, ["configuration must be an object"]
    out = dict(base)
    for k, v in cfg.items():
        if k in out or k in ("verified_rules",):
            out[k] = v
        else:
            errors.append("unknown configuration field %r" % (k,))
    try:
        out["question_count"] = int(out["question_count"])
    except (TypeError, ValueError):
        errors.append("question_count must be an integer")
        out["question_count"] = base["question_count"]
    if out["question_count"] < 1:
        errors.append("question_count must be >= 1")
    try:
        out["duration_minutes"] = float(out["duration_minutes"])
    except (TypeError, ValueError):
        errors.append("duration_minutes must be a number")
        out["duration_minutes"] = base["duration_minutes"]
    if not (out["duration_minutes"] > 0):
        errors.append("duration_minutes must be > 0")
    try:
        out["marks_per_correct"] = float(out["marks_per_correct"])
    except (TypeError, ValueError):
        errors.append("marks_per_correct must be a number")
        out["marks_per_correct"] = base["marks_per_correct"]
    if not (out["marks_per_correct"] > 0):
        errors.append("marks_per_correct must be > 0")
    nm = out.get("negative_marking") or {}
    if not isinstance(nm, dict):
        errors.append("negative_marking must be an object")
        nm = {}
    try:
        pen = float(nm.get("penalty_fraction", 0))
    except (TypeError, ValueError):
        errors.append("negative_marking.penalty_fraction must be a number")
        pen = 0.0
    if pen < 0:
        errors.append("negative_marking.penalty_fraction must be >= 0")
    out["negative_marking"] = {"enabled": bool(nm.get("enabled", False)),
                               "penalty_fraction": pen}
    try:
        out["max_attempts"] = int(out.get("max_attempts", 1))
    except (TypeError, ValueError):
        errors.append("max_attempts must be an integer")
        out["max_attempts"] = 1
    if out["max_attempts"] < 1:
        errors.append("max_attempts must be >= 1")
    if not isinstance(out.get("topics"), list):
        errors.append("topics must be a list")
        out["topics"] = []
    for name in ("difficulty", "qtypes"):
        dist = out.get(name)
        if dist is None:
            continue
        if not isinstance(dist, dict) or not dist:
            errors.append("%s must be an object or null" % name)
            out[name] = None
            continue
        try:
            tot = sum(float(v) for v in dist.values())
        except (TypeError, ValueError):
            errors.append("%s values must be numbers" % name)
            out[name] = None
            continue
        if abs(tot - 100.0) > 0.01:
            errors.append("%s must sum to 100 (got %.2f)" % (name, tot))
    for flag in ("collect_confidence", "allow_mark", "allow_navigation"):
        out[flag] = bool(out.get(flag, True))
    if out.get("selection") not in SELECTION_MODES:
        errors.append("selection must be one of %s" % (", ".join(SELECTION_MODES),))
        out["selection"] = "BALANCED"
    if out.get("blueprint") is not None:
        if out["selection"] != "CUSTOM_BLUEPRINT":
            errors.append("blueprint requires selection CUSTOM_BLUEPRINT")
        elif not isinstance(out["blueprint"], list) or not out["blueprint"]:
            errors.append("blueprint must be a non-empty list")
        else:
            for i, row in enumerate(out["blueprint"]):
                if not isinstance(row, dict) or int(row.get("count", 0)) < 1:
                    errors.append("blueprint row %d needs count >= 1" % i)
    if not isinstance(out.get("exclude_ids"), list):
        errors.append("exclude_ids must be a list")
        out["exclude_ids"] = []
    if out.get("seed") is None:
        out["seed"] = DEFAULT_SEED
    return out, errors


def resolve_rules(profile, config):
    """Scoring rules for a test. Profile values are surfaced with their
    verified status; nothing is presented as an official fact (§3, §50)."""
    prof = profile if isinstance(profile, dict) else {}
    nm = prof.get("negative_marking") or {}
    cfg_nm = (config or {}).get("negative_marking") or {}
    enabled = bool(cfg_nm.get("enabled", nm.get("enabled", False)))
    praw = cfg_nm.get("penalty_fraction", nm.get("penalty_fraction", 0))
    try:
        penalty = float(praw)
    except (TypeError, ValueError):
        # exact fractions ("1/3") pass through as strings; scoring parses them
        penalty = praw if isinstance(praw, str) else 0.0
    try:
        marks = float((config or {}).get("marks_per_correct", 1.0))
    except (TypeError, ValueError):
        marks = 1.0
    return {
        "marks_per_correct": marks,
        "penalty_fraction": penalty if enabled else 0.0,
        "negative_marking": enabled,
        "profile_verified": bool(nm.get("verified", False)),
        "profile_name": prof.get("name", (config or {}).get("exam_profile", "CUSTOM")),
    }


# --------------------------------------------------------------------------
# Assembly (§4-5). Deterministic; seed in, frozen paper out.
# --------------------------------------------------------------------------
def _largest_remainder(total, fracs):
    """Allocate integer quotas summing to total. Tie-break by key asc."""
    raw = [(k, total * f) for k, f in sorted(fracs.items())]
    quotas = {k: int(v // 1) for k, v in raw}
    rema = total - sum(quotas.values())
    order = sorted(raw, key=lambda kv: (-(kv[1] - int(kv[1] // 1)), kv[0]))
    i = 0
    while rema > 0 and order:
        quotas[order[i % len(order)][0]] += 1
        rema -= 1
        i += 1
    return quotas


def _norm_dist(dist, keys):
    if not dist:
        return {k: 1.0 / len(keys) for k in keys} if keys else {}
    tot = sum(float(dist.get(k, 0)) for k in keys)
    if tot <= 0:
        return {k: 1.0 / len(keys) for k in keys} if keys else {}
    return {k: float(dist.get(k, 0)) / tot for k in keys}


def assemble(questions, validation, config, inventory=None, profile=None):
    """Build a frozen test paper. Returns (paper, errors).

    questions: full bank list. validation: {qid: True} for validated ids
    (or validation_results object). config: resolved test config.
    Only validated questions are eligible; unknown types rejected.
    """
    errors = []
    if isinstance(validation, dict) and "results" in validation:
        valid = {r["id"] for r in validation.get("results", [])
                 if r.get("status") == "validated"}
    elif isinstance(validation, dict):
        valid = {qid for qid, ok in validation.items() if ok is True}
    else:
        valid = set(validation or [])
    pool = []
    for q in questions or []:
        if not isinstance(q, dict) or not q.get("id"):
            continue
        if q["id"] not in valid:
            continue
        try:
            scoring_rule_for(q_type(q))
        except ValueError as e:
            errors.append("question %s: %s" % (q.get("id"), e))
            continue
        pool.append(q)
    if config.get("topics"):
        want = set(config["topics"])
        pool = [q for q in pool if q_topic(q) in want]
    excluded = set(config.get("exclude_ids") or [])
    fresh = [q for q in pool if q["id"] not in excluded]
    n = config["question_count"]
    if len(fresh) < n:
        if len(pool) < n:
            msg = "insufficient validated questions: need %d, have %d" % (n, len(pool))
            if config.get("topics"):
                msg += " for topics %s" % ", ".join(sorted(config["topics"]))
            return None, [msg]
        # §30: reuse only when alternatives are exhausted, and say so.
        pool = fresh + [q for q in pool if q["id"] in excluded]
        reused_note = sorted(q["id"] for q in pool if q["id"] in excluded)
    else:
        pool = fresh
        reused_note = []
    rng = RNG(config.get("seed", DEFAULT_SEED))
    mode = config.get("selection", "BALANCED")
    if mode == "RANDOM":
        order = rng.shuffle([q["id"] for q in pool])[:n]
    elif mode == "CUSTOM_BLUEPRINT":
        order, berr = _assemble_blueprint(pool, config["blueprint"], rng)
        if berr:
            return None, berr
    else:
        order = _assemble_balanced(pool, n, config, rng)
    if len(order) < n:
        return None, ["assembler shortfall: need %d, selected %d" % (n, len(order))]
    # Final order is itself seeded-shuffled so strata don't leak position.
    order = rng.shuffle(order)
    cfg_hash = "%08x" % xfnv1a(canonical_json(config))
    paper = {
        "test_id": "T-%s-%s" % (config.get("seed", DEFAULT_SEED), cfg_hash),
        "test_version": 1,
        "seed": config.get("seed", DEFAULT_SEED),
        "selection": mode,
        "config": {k: config.get(k) for k in (
            "title", "exam_profile", "question_count", "duration_minutes",
            "marks_per_correct", "negative_marking", "max_attempts", "topics",
            "difficulty", "qtypes", "collect_confidence", "allow_mark",
            "allow_navigation", "blueprint")},
        "rules": resolve_rules(profile, config),
        "question_ids": order,
        "stats": _paper_stats(pool, order),
        "reused_from_excluded": sorted(set(order) & set(reused_note)),
        "created_by": "test_engine",
    }
    return paper, []


def _paper_stats(pool, order):
    by_id = {q["id"]: q for q in pool}
    return {
        "by_topic": dict(collections.Counter(q_topic(by_id[i]) for i in order)),
        "by_difficulty": dict(collections.Counter(q_diff(by_id[i]) for i in order)),
        "by_type": dict(collections.Counter(q_type(by_id[i]) for i in order)),
        "by_purpose": dict(collections.Counter(q_purpose(by_id[i]) for i in order)),
        "by_section": dict(collections.Counter(q_section(by_id[i]) for i in order)),
    }


def _assemble_balanced(pool, n, config, rng):
    topics = sorted({q_topic(q) for q in pool})
    diffs = sorted({q_diff(q) for q in pool})
    types = sorted({q_type(q) for q in pool})
    t_frac = _norm_dist(config.get("difficulty"), diffs)
    y_frac = _norm_dist(config.get("qtypes"), types)
    need_t = _largest_remainder(n, {t: 1.0 / len(topics) for t in topics})
    need_d = _largest_remainder(n, t_frac)
    need_y = _largest_remainder(n, y_frac)
    sec_of = {}
    for q in pool:
        sec_of[q["id"]] = q_section(q)
    # cells keyed (topic, difficulty, type); qids interleaved by section so
    # the section cap can bite deterministically
    cells = collections.defaultdict(list)
    for q in pool:
        cells[(q_topic(q), q_diff(q), q_type(q))].append(q["id"])
    for key in sorted(cells):
        by_sec = collections.defaultdict(list)
        for qid in sorted(cells[key]):
            by_sec[sec_of[qid]].append(qid)
        for s in sorted(by_sec):
            by_sec[s] = rng.shuffle(by_sec[s])
        order, secs, k, more = [], sorted(by_sec), 0, True
        while more:
            more = False
            for s in secs:
                if k < len(by_sec[s]):
                    order.append(by_sec[s][k])
                    more = True
            k += 1
        cells[key] = order
    cap = max(1, int(n * 0.5))
    picked, sec_count, pending = [], collections.Counter(), []
    in_pending = set()
    pos = {k: 0 for k in cells}

    def best_cell():
        best = None
        for k in sorted(cells):
            if pos[k] >= len(cells[k]):
                continue
            t, d, y = k
            s = need_t.get(t, 0) + need_d.get(d, 0) + need_y.get(y, 0)
            if best is None or s > best[0]:
                best = (s, k)
        return best[1] if best else None

    guard = 0
    while len(picked) < n and guard < n * 4 + 10:
        guard += 1
        k = best_cell()
        if k is None:
            break
        t, d, y = k
        qid = None
        while pos[k] < len(cells[k]):
            cand = cells[k][pos[k]]
            pos[k] += 1
            if sec_count[sec_of[cand]] >= cap:
                if cand not in in_pending:
                    pending.append(cand)
                    in_pending.add(cand)
                continue
            qid = cand
            break
        if qid is None:
            continue
        picked.append(qid)
        sec_count[sec_of[qid]] += 1
        need_t[t] = need_t.get(t, 0) - 1
        need_d[d] = need_d.get(d, 0) - 1
        need_y[y] = need_y.get(y, 0) - 1
    used = set(picked)
    for qid in pending:
        if len(picked) >= n or qid in used:
            continue
        if sec_count[sec_of[qid]] < cap:
            picked.append(qid)
            used.add(qid)
            sec_count[sec_of[qid]] += 1
    for qid in pending:
        if len(picked) >= n or qid in used:
            continue
        picked.append(qid)
        used.add(qid)
    if len(picked) < n:
        for q in pool:
            if len(picked) >= n:
                break
            if q["id"] not in used:
                picked.append(q["id"])
                used.add(q["id"])
    return picked[:n]


def _assemble_blueprint(pool, blueprint, rng):
    by_id = {q["id"]: q for q in pool}
    used, order = set(), []
    for ri, row in enumerate(blueprint):
        need = int(row.get("count", 0))
        rt = row.get("qtype") or row.get("type")
        cand = [qid for qid, q in by_id.items() if qid not in used
                and (not row.get("topic") or q_topic(q) == row["topic"])
                and (not row.get("difficulty") or q_diff(q) == str(row["difficulty"]).lower())
                and (not rt or q_type(q) == rt)
                and (not row.get("purpose") or q_purpose(q) == row["purpose"])]
        # section spread inside a row when possible
        cand = rng.shuffle(sorted(cand))
        if len(cand) < need:
            return None, ["blueprint row %d needs %d, only %d match (topic=%s difficulty=%s type=%s purpose=%s)" % (
                ri, need, len(cand), row.get("topic") or "", row.get("difficulty") or "",
                rt or "", row.get("purpose") or "")]
        order.extend(cand[:need])
        used.update(cand[:need])
    return order, []


# --------------------------------------------------------------------------
# Pre-test validation (§34).
# --------------------------------------------------------------------------
def pretest_check(questions, validation, config, profile=None):
    errors = []
    ok_cfg, cerr = validate_config(config)
    errors.extend(cerr)
    if isinstance(validation, dict) and "results" in validation:
        results = validation.get("results", [])
        rej = [r["id"] for r in results if r.get("status") != "validated"]
        if rej:
            errors.append("%d bank questions not validated" % len(rej))
        valid = {r["id"] for r in results if r.get("status") == "validated"}
    elif isinstance(validation, dict):
        valid = {qid for qid, ok in validation.items() if ok is True}
    else:
        valid = set(validation or [])
    seen, dups = set(), set()
    for q in questions or []:
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid:
            errors.append("bank contains a question without id")
            continue
        if qid in seen:
            dups.add(qid)
        seen.add(qid)
        if qid in valid:
            try:
                scoring_rule_for(q_type(q))
            except ValueError as e:
                errors.append("question %s: %s" % (qid, e))
    if dups:
        errors.append("duplicate question ids: %s" % ", ".join(sorted(dups)))
    n = ok_cfg["question_count"]
    pool = [q for q in (questions or [])
            if isinstance(q, dict) and q.get("id") in valid
            and (not ok_cfg["topics"] or q_topic(q) in ok_cfg["topics"])]
    fresh = [q for q in pool if q["id"] not in set(ok_cfg["exclude_ids"])]
    usable = fresh if len(fresh) >= n else pool
    if len(usable) < n:
        errors.append("insufficient validated questions: need %d, have %d" % (n, len(usable)))
    rules = resolve_rules(profile, ok_cfg)
    if rules["marks_per_correct"] <= 0:
        errors.append("marks_per_correct must be > 0")
    return (len(errors) == 0), errors


# --------------------------------------------------------------------------
# Scoring (§15-16). Exact Fraction arithmetic; rounding only at display.
# --------------------------------------------------------------------------
def _sel_of(value):
    """Normalize an answer-map value to a selected key or None.

    Accepts raw keys ("A"), None, or Phase-2-style answer records ({sel,...}).
    """
    if isinstance(value, dict):
        value = value.get("sel")
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _marked_of(value):
    if isinstance(value, dict):
        return bool(value.get("marked"))
    return False


def parse_exact(x, default=0):
    """Exact rational from config values. Strings may name fractions ("1/3");
    floats are taken at face value (documented, never silently reinterpreted).
    """
    if isinstance(x, bool):
        return Fraction(int(x))
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, Fraction):
        return x
    if isinstance(x, str):
        try:
            return Fraction(x.strip())
        except (ValueError, ZeroDivisionError):
            pass
    try:
        return Fraction(str(float(x)))
    except (TypeError, ValueError):
        return Fraction(default)


def score_session(paper_or_rules, answers, questions):
    """answers: {qid: selected_key or None}. questions: {qid: question}.

    Returns exact counts + Fraction-based money math.
    """
    rules = paper_or_rules.get("rules", paper_or_rules) if isinstance(paper_or_rules, dict) else {}
    marks = parse_exact(rules.get("marks_per_correct", 1.0), 1)
    penalty = parse_exact(rules.get("penalty_fraction", 0.0)) \
        if rules.get("negative_marking") else Fraction(0)
    qids = paper_or_rules.get("question_ids", []) if isinstance(paper_or_rules, dict) else list(questions or [])
    correct = incorrect = unanswered = 0
    per_q = {}
    for qid in qids:
        sel = _sel_of((answers or {}).get(qid))
        q = (questions or {}).get(qid)
        if q is None:
            continue
        key = q_correct_key(q)
        if not sel:
            unanswered += 1
            per_q[qid] = {"selected": None, "correct": False, "attempted": False}
        elif key is not None and sel.strip().upper() == key:
            correct += 1
            per_q[qid] = {"selected": sel, "correct": True, "attempted": True}
        else:
            incorrect += 1
            per_q[qid] = {"selected": sel, "correct": False, "attempted": True}
    attempted = correct + incorrect
    positive = marks * correct
    penalty_total = penalty * incorrect
    final = positive - penalty_total
    return {
        "correct": correct, "incorrect": incorrect, "unanswered": unanswered,
        "attempted": attempted, "total": len(qids),
        "positive": positive, "penalty_total": penalty_total, "final": final,
        "accuracy": (Fraction(correct, attempted) if attempted else None),
        "attempt_rate": (Fraction(attempted, len(qids)) if qids else None),
        "per_question": per_q,
    }


def fmt_frac(fr):
    """Display a score with one decimal, integer-exact half-away-from-zero.

    Implemented on numerator/denominator so Python and JS agree bit for bit
    (float round() modes differ across languages on exact quarters).
    """
    if fr is None:
        return "-"
    n, d = (fr["n"], fr["d"]) if isinstance(fr, dict) else (fr.numerator, fr.denominator)
    sign = "-" if (n < 0) != (d < 0) else ""
    m = (20 * abs(n) + abs(d)) // (2 * abs(d))
    whole, tenth = divmod(m, 10)
    if tenth == 0:
        return "%s%d" % (sign, whole)
    return "%s%d.%d" % (sign, whole, tenth)


# --------------------------------------------------------------------------
# Analysis (§21-29). Deterministic, threshold-gated, neutral wording.
# --------------------------------------------------------------------------
def analyze_results(paper, answers, questions, kus=None, now_ms=None):
    """Full result analysis. kus: optional {ku_id: ku} for tier/cluster data."""
    score = score_session(paper, answers, questions)
    qmap = questions or {}
    kmap = kus or {}
    rows = []
    for qid in paper.get("question_ids", []):
        q = qmap.get(qid)
        if q is None:
            continue
        r = score["per_question"].get(qid, {})
        raw = (answers or {}).get(qid)
        a = raw if isinstance(raw, dict) else {}
        prim = None
        secs = []
        for e in q.get("knowledge_units") or []:
            if isinstance(e, dict) and e.get("ku_id"):
                if e.get("role") == "primary" and prim is None:
                    prim = e["ku_id"]
                elif e.get("role") == "secondary":
                    secs.append(e["ku_id"])
        rows.append({
            "qid": qid, "topic": q_topic(q), "difficulty": q_diff(q),
            "type": q_type(q), "purpose": q_purpose(q),
            "primary_ku": prim, "secondary_kus": secs,
            "cluster": q.get("confusion_cluster"),
            "selected": r.get("selected"), "correct": r.get("correct", False),
            "attempted": r.get("attempted", False),
            "confidence": a.get("conf") or a.get("confidence"),
            "marked": bool(a.get("marked")),
            "dt_ms": a.get("dt_ms", a.get("time_taken_ms")),
        })
    by_topic = _slice(rows, lambda r: r["topic"], paper)
    by_diff = _slice(rows, lambda r: r["difficulty"], paper)
    by_purpose = _slice(rows, lambda r: r["purpose"], paper)
    # KU-level: wrong answers grouped to underlying gaps (§24)
    ku_groups, tier1_miss, tier2_miss = {}, set(), set()
    for r in rows:
        if r["correct"] or not r["primary_ku"]:
            continue
        if not r["attempted"]:
            continue
        g = ku_groups.setdefault(r["primary_ku"], {"misses": 0, "question_ids": []})
        g["misses"] += 1
        g["question_ids"].append(r["qid"])
        t = kmap.get(r["primary_ku"], {}).get("tier") if isinstance(kmap.get(r["primary_ku"]), dict) else None
        try:
            t = int(t) if t is not None else None
        except (TypeError, ValueError):
            t = None
        if t == 1:
            tier1_miss.add(r["primary_ku"])
        elif t == 2:
            tier2_miss.add(r["primary_ku"])
    ku_gaps = [{"ku_id": k, "misses": v["misses"], "question_ids": v["question_ids"],
                "tier": (kmap.get(k, {}).get("tier") if isinstance(kmap.get(k), dict) else None)}
               for k, v in sorted(ku_groups.items(), key=lambda kv: (-kv[1]["misses"], kv[0]))]
    # confusion clusters among misses
    clusters = collections.Counter()
    for r in rows:
        if not r["correct"] and r["attempted"] and r["cluster"]:
            clusters[r["cluster"]] += 1
    # high-confidence errors (§26): neutral label, opt-in wording only
    hce = [r for r in rows if r["attempted"] and not r["correct"]
           and (r["confidence"] in ("Certain", "Fairly confident"))]
    # unanswered high-priority KUs (§27: listed, not blamed)
    unans_kus = sorted({r["primary_ku"] for r in rows
                        if not r["attempted"] and r["primary_ku"]})
    # time analysis (§28)
    times = [(r["qid"], r["dt_ms"]) for r in rows
             if isinstance(r["dt_ms"], (int, float)) and r["dt_ms"] >= 0]
    time_rep = {"samples": len(times)}
    if len(times) >= MIN_TIME_SAMPLE:
        vals = sorted(t for _, t in times)
        med = vals[len(vals) // 2]
        by_t = collections.defaultdict(list)
        tc = collections.Counter()
        ti = collections.Counter()
        for r in rows:
            if isinstance(r["dt_ms"], (int, float)) and r["dt_ms"] >= 0:
                by_t[r["topic"]].append(r["dt_ms"])
                tc[r["topic"]] += r["dt_ms"]
                ti[r["topic"]] += 1
        tot_t = sum(tc.values()) or 1
        slow = sorted(times, key=lambda kv: -kv[1])[:3]
        corr_t = [r["dt_ms"] for r in rows if r["attempted"] and r["correct"]
                  and isinstance(r["dt_ms"], (int, float))]
        incorr_t = [r["dt_ms"] for r in rows if r["attempted"] and not r["correct"]
                    and isinstance(r["dt_ms"], (int, float))]
        time_rep.update({
            "average_ms": sum(vals) / len(vals),
            "median_ms": med,
            "slowest": [{"qid": q, "dt_ms": t} for q, t in slow],
            "by_topic_ms": {k: sum(v) / len(v) for k, v in by_t.items()},
            "topic_time_share": {k: tc[k] / tot_t for k in tc},
            "correct_avg_ms": (sum(corr_t) / len(corr_t)) if corr_t else None,
            "incorrect_avg_ms": (sum(incorr_t) / len(incorr_t)) if incorr_t else None,
        })
    else:
        time_rep["note"] = "insufficient timing samples"
    # strategy observations: only when data supports them (§29)
    obs = []
    att = score["attempted"]
    tot = score["total"] or 1
    if score["unanswered"] / tot > HIGH_UNANSWERED_RATE:
        obs.append({"code": "high_unanswered",
                    "text": "Unanswered rate is %d%%." % int(100.0 * score["unanswered"] / tot + 0.5)})
    unresolved = sum(1 for r in rows if r["marked"] and not r["attempted"])
    if unresolved:
        obs.append({"code": "marked_unresolved",
                    "text": "%d marked question(s) left unanswered." % unresolved})
    if att and len(hce) / att > HCE_RATE:
        obs.append({"code": "hce_rate",
                    "text": "High-confidence errors on %d of %d attempted." % (len(hce), att)})
    if len(times) >= MIN_TIME_SAMPLE:
        for topic, share in time_rep.get("topic_time_share", {}).items():
            n = sum(1 for r in rows if r["topic"] == topic and isinstance(r["dt_ms"], (int, float)))
            if share > TIME_CONCENTRATION and n >= MIN_TIME_SAMPLE:
                obs.append({"code": "time_concentration",
                            "text": "%s took %d%% of total time." % (topic, int(100 * share + 0.5))})
                break
    def score_struct(s):
        def pct(fr):
            if fr is None:
                return None
            return fmt_frac({"n": 100 * fr.numerator, "d": fr.denominator}
                            if isinstance(fr, Fraction) else fr)
        return {
            "correct": s["correct"], "incorrect": s["incorrect"],
            "unanswered": s["unanswered"], "attempted": s["attempted"],
            "total": s["total"],
            "positive": frac_dict(s["positive"]),
            "penalty_total": frac_dict(s["penalty_total"]),
            "final": frac_dict(s["final"]),
            "accuracy": frac_dict(s["accuracy"]),
            "attempt_rate": frac_dict(s["attempt_rate"]),
            "display": {
                "final": fmt_frac(s["final"]),
                "accuracy_pct": pct(s["accuracy"]),
                "attempt_pct": pct(s["attempt_rate"]),
            },
        }

    return {
        "score": score_struct(score),
        "per_question": score["per_question"],
        "by_topic": by_topic, "by_difficulty": by_diff, "by_purpose": by_purpose,
        "ku_gaps": ku_gaps, "tier1_misses": sorted(tier1_miss),
        "tier2_misses": sorted(tier2_miss),
        "confusion_clusters": [{"cluster": k, "misses": v}
                               for k, v in clusters.most_common()],
        "high_confidence_errors": [{"qid": r["qid"], "primary_ku": r["primary_ku"],
                                    "confidence": r["confidence"]} for r in hce],
        "unanswered_kus": unans_kus,
        "time": time_rep,
        "observations": obs,
    }


def _slice(rows, keyfn, paper):
    rules = paper.get("rules", {}) if isinstance(paper, dict) else {}
    marks = float(parse_exact(rules.get("marks_per_correct", 1.0), 1))
    penalty = float(parse_exact(rules.get("penalty_fraction", 0.0), 0)) \
        if rules.get("negative_marking") else 0.0
    groups = collections.defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    out = {}
    for k in sorted(groups):
        rs = groups[k]
        att = [r for r in rs if r["attempted"]]
        c = sum(1 for r in att if r["correct"])
        w = len(att) - c
        out[k] = {"attempted": len(att), "correct": c, "incorrect": w,
                  "total": len(rs),
                  "accuracy": (c / len(att)) if att else None,
                  "contribution": c * marks - w * penalty}
    return out


# --------------------------------------------------------------------------
# Sessions (§7-9, §20, §36-38).
# --------------------------------------------------------------------------
def new_test_session(paper, config, now_ms, answers=None):
    cfg = config or {}
    dur = float(paper.get("config", {}).get("duration_minutes",
                                            cfg.get("duration_minutes", 30)))
    return {
        "test_id": paper["test_id"],
        "test_version": paper.get("test_version", 1),
        "profile": paper.get("config", {}).get("exam_profile", "CUSTOM"),
        "config": paper.get("config", {}),
        "rules": paper.get("rules", {}),
        "question_ids": list(paper.get("question_ids", [])),
        "start_time": int(now_ms),
        "expires_at": int(now_ms + dur * 60000),
        "answers": dict(answers or {}),
        "marked": [],
        "submitted": False,
        "submission_time": None,
        "submit_reason": None,
        "result": None,
    }


def confirm_summary(session):
    """Counts for the pre-submission confirmation screen (§14)."""
    answers = session.get("answers", {}) or {}
    qids = list(session.get("question_ids", []))
    marked = set(session.get("marked", []) or [])
    answered = sum(1 for q in qids if (answers.get(q) or {}).get("sel"))
    marked_n = sum(1 for q in qids if q in marked)
    return {"answered": answered, "unanswered": len(qids) - answered,
            "marked": marked_n, "total": len(qids)}


def remaining_ms(session, now_ms):
    try:
        rem = int(session.get("expires_at", 0)) - int(now_ms)
    except (TypeError, ValueError):
        return 0
    return max(0, rem)


def is_expired(session, now_ms):
    try:
        return int(now_ms) >= int(session.get("expires_at", 0))
    except (TypeError, ValueError):
        return True


def finalize_session(session, questions, now_ms, reason="submitted"):
    """Freeze a test: scoring + analysis snapshot. Immutable afterwards.

    questions: bank list [{...}] or {qid: question} map.
    """
    if session.get("submitted"):
        return session.get("result")
    if isinstance(questions, dict):
        qmap = {q.get("id", k): q for k, q in questions.items() if isinstance(q, dict)}
    else:
        qmap = {q["id"]: q for q in (questions or []) if isinstance(q, dict) and q.get("id")}
    paper = {"question_ids": list(session.get("question_ids", [])),
             "rules": dict(session.get("rules", {}))}
    analysis = analyze_results(paper, session.get("answers", {}), qmap)
    result = {
        "test_id": session.get("test_id"),
        "test_version": session.get("test_version", 1),
        "submit_reason": reason,
        "submission_time": int(now_ms),
        "score": analysis["score"],
        "time_used_ms": max(0, int(now_ms) - int(session.get("start_time", now_ms))),
        "duration_minutes": (session.get("config") or {}).get("duration_minutes"),
        "analysis": {k: v for k, v in analysis.items() if k != "score"},
        "answers": json.loads(json.dumps(session.get("answers", {}), default=str)),
        "marked": list(session.get("marked", [])),
        "config": dict(session.get("config", {})),
        "rules": dict(session.get("rules", {})),
        "question_ids": list(session.get("question_ids", [])),
    }
    session["submitted"] = True
    session["submission_time"] = int(now_ms)
    session["submit_reason"] = reason
    session["result"] = result
    return result


def retake_seed(seed):
    if isinstance(seed, bool):
        return ("true" if seed else "false") + "-r2"
    if isinstance(seed, int):
        return seed + 1
    try:
        return int(str(seed)) + 1
    except (TypeError, ValueError):
        return "%s-r2" % seed


def frac_dict(fr):
    if fr is None:
        return None
    return {"n": fr.numerator, "d": fr.denominator}


def retake_paper(paper, questions, validation, seed=None, inventory=None, profile=None):
    """New test version: same blueprint, fresh seed, prior ids excluded (§30-31)."""
    cfg = dict(paper.get("config", {}))
    cfg["seed"] = retake_seed(paper.get("seed")) if seed is None else seed
    prev = list(paper.get("question_ids", []))
    cfg["exclude_ids"] = sorted(set(cfg.get("exclude_ids") or []) | set(prev))
    new_paper, errors = assemble(questions, validation, cfg, inventory, profile)
    if errors:
        return None, errors
    new_paper["test_version"] = int(paper.get("test_version", 1)) + 1
    new_paper["retake_of"] = paper.get("test_id")
    return new_paper, []


# --------------------------------------------------------------------------
# Revision handoff (§25, §43-44): test answers become Phase 2 events.
# --------------------------------------------------------------------------
def events_from_result(result, questions):
    """Structured performance events for the learner model / revision engine."""
    try:
        import revision as revmod
    except Exception:
        revmod = None
    if isinstance(questions, dict):
        qmap = {q.get("id", k): q for k, q in questions.items() if isinstance(q, dict)}
    else:
        qmap = {q["id"]: q for q in (questions or []) if isinstance(q, dict) and q.get("id")}
    out = []
    for qid in result.get("question_ids", []):
        a = (result.get("answers") or {}).get(qid) or {}
        q = qmap.get(qid, {})
        ev = {
            "question_id": qid,
            "primary_ku": a.get("primary_ku") or (revmod.primary_of(q) if revmod else None),
            "result": ("correct" if a.get("correct") else "wrong") if a.get("sel") else None,
            "confidence": a.get("conf"),
            "confusion_type": a.get("distype"),
            "timestamp": a.get("time"),
            "mode": "test",
        }
        if revmod is not None:
            out.append(revmod.normalize_event(ev, q))
        else:
            out.append(ev)
    return [e for e in out if e.get("result")]


# --------------------------------------------------------------------------
# Print consistency (§42): paper-ordered package for the PDF renderer.
# --------------------------------------------------------------------------
def filter_package_to_paper(pkg, paper):
    """Return a package copy containing only paper questions in paper order."""
    want = list(paper.get("question_ids", []))
    by_id = {}
    for q in (pkg.get("questions") or []):
        if isinstance(q, dict) and q.get("id"):
            by_id[q["id"]] = q
    missing = [i for i in want if i not in by_id]
    if missing:
        raise ValueError("paper references %d questions missing from package: %s"
                         % (len(missing), missing[:5]))
    out = json.loads(json.dumps(pkg))
    out["questions"] = [by_id[i] for i in want]
    meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
    meta["title"] = "%s (Test %s v%s)" % (
        meta.get("title", "Quiz"), paper.get("test_id"), paper.get("test_version", 1))
    out["meta"] = meta
    return out


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------
def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_assemble(a):
    pkg = _read(a.package)
    questions = pkg.get("questions", [])
    validation = _read(a.validation) if a.validation else {}
    inventory = _read(a.inventory) if a.inventory else None
    if isinstance(inventory, dict) and "units" in inventory:
        inventory = inventory["units"]
    profile = _read(a.profile) if a.profile else {}
    cfg_in = _read(a.config) if a.config else {}
    ok, errs = pretest_check(questions, validation, cfg_in, profile)
    if not ok:
        print("pre-test check FAILED:")
        for e in errs:
            print("  - %s" % e)
        return 1
    cfg = dict(cfg_in)
    if a.count is not None:
        cfg["question_count"] = a.count
    if a.seed is not None:
        cfg["seed"] = a.seed
    cfg_final, cerr = validate_config(cfg)
    if cerr:
        print("config invalid:")
        for e in cerr:
            print("  - %s" % e)
        return 1
    paper, perrs = assemble(questions, validation, cfg_final, inventory, profile)
    if perrs:
        print("assembly FAILED:")
        for e in perrs:
            print("  - %s" % e)
        return 1
    save_json(a.out, paper)
    print("assembled %s v%s: %d questions (seed %s, %s)" % (
        paper["test_id"], paper["test_version"], len(paper["question_ids"]),
        paper["seed"], paper["selection"]))
    return 0


def cmd_score(a):
    paper = _read(a.paper)
    answers = _read(a.answers)
    if isinstance(answers, dict) and "answers" in answers:
        answers = answers["answers"]
    questions = _read(a.bank)
    if isinstance(questions, dict):
        questions = questions.get("questions", [])
    qmap = {q["id"]: q for q in questions if isinstance(q, dict) and q.get("id")}
    score = score_session(paper, answers, qmap)
    out = {k: (str(v) if isinstance(v, Fraction) else v)
           for k, v in score.items() if k != "per_question"}
    out["final_display"] = fmt_frac(score["final"])
    save_json(a.out, out)
    print("score: correct=%d incorrect=%d unanswered=%d final=%s" % (
        score["correct"], score["incorrect"], score["unanswered"], out["final_display"]))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Deterministic competitive-exam test engine.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("assemble", help="Assemble a frozen test paper.")
    p.add_argument("--package", required=True)
    p.add_argument("--validation", default=None)
    p.add_argument("--inventory", default=None)
    p.add_argument("--profile", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--seed", default=None)
    p.add_argument("--out", required=True)
    s = sub.add_parser("score", help="Score an answer map against a paper.")
    s.add_argument("--paper", required=True)
    s.add_argument("--answers", required=True)
    s.add_argument("--bank", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "assemble":
        return cmd_assemble(a)
    if a.cmd == "score":
        return cmd_score(a)
    return 1


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
