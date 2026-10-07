"""Deterministic KU-level revision engine (Phase 2).

Turns observable question attempts into knowledge-unit priorities,
mastery states, revision queues and targeted retest selection.

Design rules (see also prompts/revision.md):
- KU-level, never question-level: repeated weakness on one concept outranks
  scattered single misses.
- Deterministic: same inputs always give the same outputs. Every ordering has
  an explicit tie-break (score desc, ku_id asc). No randomness, no hidden
  AI judgment; every queue entry carries explicit reasons.
- Observable data only: attempts store what happened (result, confidence,
  confusion type, timestamps). No psychological inference.
- Primary KU gets full attribution; secondary KUs get exposure-only tracking;
  distractor_basis KUs are ignored.
- Correct answers reduce priority gradually (relief is arithmetic); history is
  never reset by a single correct answer.

Sections: config, events, aggregation, scoring, mastery, queue, sessions,
selector, generation hook, migration, analytics, CLI.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main, token_set_sim

try:
    import coverage as covmod
except Exception:  # pragma: no cover - engine still works without bank forms
    covmod = None

SESSION_VERSION = 2

# --------------------------------------------------------------------------
# Config. Every number lives here so behaviour is explainable and tunable.
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    # importance: Tier 1 vs Tier 2 (§4, §29)
    "tier_weight": {"1": 30, "2": 15, "3": 5},
    "exam_relevance_weight": {"very_high": 12, "high": 8, "medium": 4, "low": 0},
    "ku_priority_weight": {"critical": 8, "high": 5, "medium": 2, "low": 0},
    # error signals (§4)
    "w_recent_wrong": 20,          # last recorded result is wrong
    "w_repeat_wrong": 8,           # per extra miss beyond the first
    "repeat_cap": 3,               # max extra misses counted
    "w_hce_certain": 12,           # per Certain+wrong
    "hce_certain_cap": 2,
    "w_hce_fairly": 6,             # per Fairly-confident+wrong
    "hce_fairly_cap": 2,
    "w_confusion_repeat": 10,      # >=2 misses share a confusion signal
    "w_cognitive_gap": 10,         # per weak required form
    "cog_gap_cap": 2,
    "w_stale": 8,                  # last success older than stale_days
    "w_never_correct": 6,          # attempts exist but no success yet
    "w_marked": 4,                 # manual mark: modest, never dominant (§28)
    "relief_per_recent_correct": 6,
    "relief_cap": 18,
    # recency (§5): explicit, configurable decay on error signals
    "recent_days": 7,
    "mid_days": 30,
    "recent_mult": 1.0,
    "mid_mult": 0.7,
    "old_mult": 0.4,
    "recent_window_n": 5,
    "stale_days": 14,
    # priority bands
    "band_critical": 60,
    "band_high": 35,
    "band_medium": 15,
    # mastery (§15-16)
    "stable_min_attempts": 4,
    "stable_window": 3,            # last N all correct
    "stable_no_hce_days": 30,
    "form_stable_min_correct": 2,
    # sessions (§12-14)
    "quick_size": 5,
    "session_recipe": [["priority", 4], ["confusion", 3],
                       ["cognitive", 2], ["stale", 1]],
    "topic_cap": 3,
    # selector (§9, §25, §27)
    "dup_threshold": 0.85,
    "retest_after_new": 3,         # new attempts before a repeat is allowed
    # confidence vocabulary (observed labels only, §6)
    "conf_certain": "Certain",
    "conf_fairly": "Fairly confident",
    "conf_unsure": "Unsure",
    "conf_guessing": "Guessing",
}

# Reason vocabulary for queue entries (§11). Never free text.
RECENT_ERROR = "recent_error"
REPEATED_ERROR = "repeated_error"
HIGH_CONF_ERROR = "high_confidence_error"
CONFUSION_CLUSTER = "confusion_cluster"
COGNITIVE_GAP = "cognitive_gap"
STALE_RECALL = "stale_recall"
MARKED = "marked_for_revision"
LOW_RECENT_ACC = "low_recent_accuracy"
INCOMPLETE_MASTERY = "incomplete_mastery"

REASON_LABELS = {
    RECENT_ERROR: "Recent incorrect answer",
    REPEATED_ERROR: "Repeated errors detected",
    HIGH_CONF_ERROR: "Recent high-confidence error",
    CONFUSION_CLUSTER: "Repeated confusion in one cluster",
    COGNITIVE_GAP: "Weak cognitive form",
    STALE_RECALL: "No recent successful recall",
    MARKED: "Marked for revisit",
    LOW_RECENT_ACC: "Recent accuracy is below target",
    INCOMPLETE_MASTERY: "Required forms not yet demonstrated",
}

# Mastery states (§15). Deterministic; see mastery_of().
NEW, LEARNING, WEAK, IMPROVING, STABLE = (
    "NEW", "LEARNING", "WEAK", "IMPROVING", "STABLE")

# Weak cognitive form -> recommended question type (§7).
FORM_TO_QTYPE = {
    "recall": "factual_mcq",
    "distinction": "elimination_mcq",
    "statement": "statement_based",
    "application": "reasoning_mcq",
}
FORM_TO_PURPOSE = {
    "recall": "direct_recall",
    "distinction": "distinction",
    "statement": "statement_evaluation",
    "application": "application",
}
COG_ORDER = ("recall", "distinction", "statement", "application")


def cfg_get(config, key):
    c = DEFAULT_CONFIG if config is None else config
    return c.get(key, DEFAULT_CONFIG[key])


# --------------------------------------------------------------------------
# Time helpers. Timestamps are ISO-8601 strings (web: toISOString) or epoch
# seconds. Tests pass fixed values, so nothing depends on wall clock.
# --------------------------------------------------------------------------
def to_epoch(ts):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    try:  # numeric strings are epoch seconds, like JS Number()
        return float(s)
    except ValueError:
        pass
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def days_since(ts, now):
    t = to_epoch(ts)
    n = to_epoch(now)
    if t is None or n is None:
        return None
    return max(0.0, (n - t) / 86400.0)


# --------------------------------------------------------------------------
# 1. Performance events (§2). Canonical observable record per attempt.
# --------------------------------------------------------------------------
EVENT_FIELDS = (
    "timestamp", "question_id", "primary_ku", "secondary_kus", "result",
    "selected_answer", "correct_answer", "confidence", "confusion_type",
    "question_purpose", "cognitive_level", "difficulty", "mode",
    "time_taken_ms", "marked", "revision_priority_at_attempt",
)


def normalize_event(raw, question=None, now=None):
    """Build a canonical event from a raw attempt (+ optional question).

    Never invents: unknown fields become None. `question` (bank object) fills
    purpose/cognitive/difficulty/secondary KUs/correct answer when the raw
    attempt lacks them.
    """
    raw = raw if isinstance(raw, dict) else {}
    q = question if isinstance(question, dict) else {}
    kus = q.get("knowledge_units") or []
    prim = None
    secs = []
    for e in kus:
        if isinstance(e, dict) and e.get("ku_id"):
            if e.get("role") == "primary" and prim is None:
                prim = e["ku_id"]
            elif e.get("role") == "secondary":
                secs.append(e["ku_id"])
    res = raw.get("result")
    if res is None:
        c = raw.get("correct")
        res = "correct" if c is True else ("wrong" if c is False else None)
    if res not in ("correct", "wrong", "skipped"):
        res = None
    conf = raw.get("confidence") or raw.get("conf")
    ev = {
        "timestamp": raw.get("timestamp", raw.get("time")),
        "question_id": raw.get("question_id", raw.get("qid")),
        "primary_ku": raw.get("primary_ku", raw.get("primaryKu")) or prim,
        "secondary_kus": raw.get("secondary_kus") or secs,
        "result": res,
        "selected_answer": raw.get("selected_answer", raw.get("sel")),
        "correct_answer": raw.get("correct_answer", raw.get("key")),
        "confidence": conf,
        "confusion_type": raw.get("confusion_type", raw.get("distype")),
        "question_purpose": raw.get("question_purpose", raw.get("purpose")) or q.get("purpose"),
        "cognitive_level": raw.get("cognitive_level") or q.get("cognitive_level"),
        "difficulty": raw.get("difficulty") or q.get("difficulty"),
        "mode": raw.get("mode"),
        "time_taken_ms": raw.get("time_taken_ms", raw.get("dt_ms")),
        "marked": bool(raw.get("marked", False)),
        "revision_priority_at_attempt": raw.get("revision_priority_at_attempt"),
    }
    if ev["timestamp"] is None and now is not None:
        ev["timestamp"] = now
    return ev


# --------------------------------------------------------------------------
# 2. KU aggregation (§3). Primary gets full attribution; secondaries get
# exposure-only tracking; distractor_basis KUs are ignored.
# --------------------------------------------------------------------------
def empty_agg():
    return {
        "attempts": 0, "correct": 0, "incorrect": 0, "skipped": 0,
        "accuracy": None, "recent": [], "recent_accuracy": None,
        "certain_wrong": 0, "fairly_wrong": 0,
        "unsure_correct": 0, "guessing_correct": 0,
        "high_confidence_errors": 0, "low_confidence_correct": 0,
        "last_attempted": None, "last_correct": None, "last_result": None,
        "last_confidence": None,
        "consecutive_correct": 0, "consecutive_incorrect": 0,
        "forms": {}, "types": {}, "purposes": {},
        "confusion_wrong": {}, "confusion_all": {},
        "clusters_wrong": {}, "marked": False,
        "secondary_exposure": 0,
    }


def _bump_counter(d, key):
    if key:
        d[key] = d.get(key, 0) + 1


def aggregate(events, questions_by_id=None, config=None):
    """Aggregate canonical events per primary KU. Returns {ku_id: metrics}."""
    qmap = questions_by_id or {}
    aggs = {}
    ordered = sorted(
        [e for e in (events or []) if isinstance(e, dict) and e.get("primary_ku")],
        key=lambda e: (to_epoch(e.get("timestamp")) or 0.0,
                       str(e.get("question_id") or "")),
    )
    for e in ordered:
        ku = e["primary_ku"]
        a = aggs.setdefault(ku, empty_agg())
        res = e.get("result")
        conf = e.get("confidence")
        ccfg = cfg_get(config, "conf_certain")
        fcfg = cfg_get(config, "conf_fairly")
        ucfg = cfg_get(config, "conf_unsure")
        gcfg = cfg_get(config, "conf_guessing")
        a["attempts"] += 1
        a["last_attempted"] = e.get("timestamp")
        a["last_result"] = res
        a["last_confidence"] = conf
        if e.get("marked"):
            a["marked"] = True
        if res == "skipped":
            a["skipped"] += 1
        elif res == "correct":
            a["correct"] += 1
            a["last_correct"] = e.get("timestamp")
            a["consecutive_correct"] += 1
            a["consecutive_incorrect"] = 0
            if conf == ucfg or conf == gcfg:
                a["low_confidence_correct"] += 1
            if conf == ucfg:
                a["unsure_correct"] += 1
            if conf == gcfg:
                a["guessing_correct"] += 1
        elif res == "wrong":
            a["incorrect"] += 1
            a["consecutive_incorrect"] += 1
            a["consecutive_correct"] = 0
            if conf == ccfg:
                a["certain_wrong"] += 1
                a["high_confidence_errors"] += 1
            if conf == fcfg:
                a["fairly_wrong"] += 1
        # cognitive + confusion attribution comes from the question record
        q = qmap.get(e.get("question_id")) or {}
        forms = set()
        if covmod is not None:
            try:
                forms = set(covmod.q_cognitive_forms({
                    "purpose": e.get("question_purpose") or q.get("purpose"),
                    "cognitive_level": e.get("cognitive_level") or q.get("cognitive_level"),
                    "type": q.get("type"),
                    "statements": q.get("statements") if q else None,
                }))
            except Exception:
                forms = set()
        for f in forms:
            st = a["forms"].setdefault(f, {"attempts": 0, "correct": 0})
            if res in ("correct", "wrong"):
                st["attempts"] += 1
                if res == "correct":
                    st["correct"] += 1
        if q.get("type"):
            _bump_counter(a["types"], q.get("type"))
        purp = e.get("question_purpose") or q.get("purpose")
        if purp:
            _bump_counter(a["purposes"], purp)
        ct = e.get("confusion_type")
        if ct:
            _bump_counter(a["confusion_all"], ct)
            if res == "wrong":
                _bump_counter(a["confusion_wrong"], ct)
        clu = q.get("confusion_cluster")
        if clu and res == "wrong":
            _bump_counter(a["clusters_wrong"], clu)
        if res in ("correct", "wrong"):
            a["recent"].append({"result": res, "confidence": conf,
                                "timestamp": e.get("timestamp"), "forms": sorted(forms)})
    # secondary exposure (no result attribution)
    for e in ordered:
        for sk in e.get("secondary_kus") or []:
            if isinstance(sk, str) and sk:
                aggs.setdefault(sk, empty_agg())["secondary_exposure"] += 1
    for a in aggs.values():
        n = a["correct"] + a["incorrect"]
        a["accuracy"] = (a["correct"] / n) if n else None
        w = cfg_get(config, "recent_window_n")
        tail = [r for r in a["recent"][-w:] if r["result"] in ("correct", "wrong")]
        a["recent_accuracy"] = (sum(1 for r in tail if r["result"] == "correct") / len(tail)) if tail else None
    return aggs


# --------------------------------------------------------------------------
# Required forms, with a bank-derived fallback when KU metadata is absent
# (browser has questions but no inventory objects).
# --------------------------------------------------------------------------
def required_forms_for(ku_id, ku_metas=None, questions_by_ku=None):
    if ku_metas:
        for ku in ku_metas:
            if isinstance(ku, dict) and ku.get("id") == ku_id and covmod is not None:
                try:
                    return set(covmod.required_forms(ku))
                except Exception:
                    break
    forms = set()
    for q in (questions_by_ku or {}).get(ku_id, []):
        if covmod is not None:
            try:
                forms |= set(covmod.q_cognitive_forms(q))
            except Exception:
                pass
    return forms or {"recall"}


def questions_by_primary(questions):
    out = {}
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        for e in q.get("knowledge_units") or []:
            if isinstance(e, dict) and e.get("role") == "primary" and e.get("ku_id"):
                out.setdefault(e["ku_id"], []).append(q)
    return out


# --------------------------------------------------------------------------
# 3-4. Priority scoring (§4, §5, §29). Weighted, recency-scaled, explainable.
# --------------------------------------------------------------------------
def recency_mult(days_ago, config=None):
    if days_ago is None:
        return cfg_get(config, "mid_mult")
    if days_ago <= cfg_get(config, "recent_days"):
        return cfg_get(config, "recent_mult")
    if days_ago <= cfg_get(config, "mid_days"):
        return cfg_get(config, "mid_mult")
    return cfg_get(config, "old_mult")


def ku_importance(ku_meta, config=None):
    if not isinstance(ku_meta, dict):
        return 0, {}
    tw = cfg_get(config, "tier_weight")
    erw = cfg_get(config, "exam_relevance_weight")
    kpw = cfg_get(config, "ku_priority_weight")
    dims = ku_meta.get("dimensions") or {}
    parts = {
        "tier": tw.get(str(ku_meta.get("tier", "")), 0),
        "exam_relevance": erw.get(dims.get("exam_relevance"), 0),
        "ku_priority": kpw.get(dims.get("revision_priority"), 0),
    }
    return sum(parts.values()), parts


def score_ku(ku_id, agg, ku_meta=None, now=None, config=None, required_forms=None):
    """Return {score, band, reasons, weak_forms, breakdown}.

    KUs with no attempts score from marks only (§28): importance weights
    amplify observed weakness, they do not create priority alone.
    """
    reasons = []
    weak_forms = []
    breakdown = {"base": 0, "error": 0, "relief": 0, "marked": 0, "mult": 1.0}
    if agg is None or agg.get("attempts", 0) == 0:
        if agg is not None and agg.get("marked"):
            reasons.append(MARKED)
            breakdown["marked"] = cfg_get(config, "w_marked")
        score = breakdown["marked"]
        return {"score": round(score, 1), "band": band_of(score, config),
                "reasons": reasons, "weak_forms": weak_forms, "breakdown": breakdown}
    base, _ = ku_importance(ku_meta, config)
    # Importance amplifies observed weakness; without any incorrect attempt
    # only a quarter applies (recognition, not revision). Stale recall and
    # marks can still surface the KU. See §28.
    evidence = agg.get("incorrect", 0) > 0
    breakdown["base"] = round(base if evidence else base * 0.25, 1)
    err = 0.0
    if agg.get("last_result") == "wrong":
        err += cfg_get(config, "w_recent_wrong")
        reasons.append(RECENT_ERROR)
    extra = max(0, agg.get("incorrect", 0) - 1)
    if extra:
        err += min(extra, cfg_get(config, "repeat_cap")) * cfg_get(config, "w_repeat_wrong")
        reasons.append(REPEATED_ERROR)
    hce = min(agg.get("certain_wrong", 0), cfg_get(config, "hce_certain_cap"))
    if hce:
        err += hce * cfg_get(config, "w_hce_certain")
        reasons.append(HIGH_CONF_ERROR)
    hcf = min(agg.get("fairly_wrong", 0), cfg_get(config, "hce_fairly_cap"))
    if hcf:
        err += hcf * cfg_get(config, "w_hce_fairly")
    # repeated confusion: same confusion_type or same cluster, >=2 misses
    if any(v >= 2 for v in (agg.get("confusion_wrong") or {}).values()) or \
       any(v >= 2 for v in (agg.get("clusters_wrong") or {}).values()):
        err += cfg_get(config, "w_confusion_repeat")
        reasons.append(CONFUSION_CLUSTER)
    # cognitive gaps among required forms
    req = set(required_forms) if required_forms is not None else set()
    failed, untried = [], []
    for f in COG_ORDER:
        if f not in req:
            continue
        st = (agg.get("forms") or {}).get(f, {"attempts": 0, "correct": 0})
        if st["attempts"] > 0 and st["correct"] == 0:
            failed.append(f)
        elif st["correct"] == 0:
            untried.append(f)
    weak_forms = failed + untried
    if failed:
        err += min(len(failed), cfg_get(config, "cog_gap_cap")) * cfg_get(config, "w_cognitive_gap")
        reasons.append(COGNITIVE_GAP)
    elif weak_forms:
        reasons.append(INCOMPLETE_MASTERY)
    # staleness: no recent successful recall
    d_correct = days_since(agg.get("last_correct"), now)
    d_last = days_since(agg.get("last_attempted"), now)
    stale_days = cfg_get(config, "stale_days")
    if agg.get("last_correct") is None and agg.get("attempts", 0) > 0 and \
            (d_last is None or d_last >= stale_days):
        err += cfg_get(config, "w_never_correct")
        reasons.append(STALE_RECALL)
    elif d_correct is not None and d_correct >= stale_days:
        err += cfg_get(config, "w_stale")
        reasons.append(STALE_RECALL)
    if agg.get("marked"):
        breakdown["marked"] = cfg_get(config, "w_marked")
        if MARKED not in reasons:
            reasons.append(MARKED)
    mult = recency_mult(d_last, config)
    breakdown["mult"] = mult
    breakdown["error"] = round(err * mult, 1)
    # relief: recent correct answers lower priority gradually (§17)
    w = cfg_get(config, "recent_window_n")
    recent_correct = sum(1 for r in (agg.get("recent") or [])[-w:]
                         if r.get("result") == "correct")
    breakdown["relief"] = -min(recent_correct * cfg_get(config, "relief_per_recent_correct"),
                               cfg_get(config, "relief_cap"))
    score = max(0.0, breakdown["base"] + breakdown["error"] + breakdown["relief"] + breakdown["marked"])
    # low recent accuracy is descriptive; scoring already reflects misses
    ra = agg.get("recent_accuracy")
    if agg.get("last_result") == "wrong" or (
            ra is not None and ra < 0.5 and agg.get("attempts", 0) >= 2):
        if LOW_RECENT_ACC not in reasons:
            reasons.append(LOW_RECENT_ACC)
    return {"score": round(score, 1), "band": band_of(score, config),
            "reasons": reasons, "weak_forms": weak_forms, "breakdown": breakdown}


def band_of(score, config=None):
    if score >= cfg_get(config, "band_critical"):
        return "critical"
    if score >= cfg_get(config, "band_high"):
        return "high"
    if score >= cfg_get(config, "band_medium"):
        return "medium"
    return "low"


# --------------------------------------------------------------------------
# 4. Mastery (§15-16): overall + per cognitive form. Deterministic rules.
# --------------------------------------------------------------------------
def mastery_of(ku_id, agg, ku_meta=None, now=None, config=None, required_forms=None):
    """Overall mastery state for one KU."""
    if agg is None or agg.get("attempts", 0) == 0:
        return NEW
    n = cfg_get(config, "stable_min_attempts")
    w = cfg_get(config, "stable_window")
    tail = [r["result"] for r in (agg.get("recent") or [])[-w:]
            if r.get("result") in ("correct", "wrong")]
    hce_days = cfg_get(config, "stable_no_hce_days")
    recent_hce = False
    for r in agg.get("recent") or []:
        if r.get("result") == "wrong" and r.get("confidence") == cfg_get(config, "conf_certain"):
            d = days_since(r.get("timestamp"), now)
            if d is None or d <= hce_days:
                recent_hce = True
    req = set(required_forms) if required_forms is not None else set()
    forms_ok = all((agg.get("forms") or {}).get(f, {"correct": 0})["correct"] > 0
                   for f in req if (agg.get("forms") or {}).get(f, {"attempts": 0})["attempts"] > 0)
    if agg.get("attempts", 0) >= n and len(tail) >= min(w, 3) and all(r == "correct" for r in tail) \
            and not recent_hce and forms_ok:
        return STABLE
    if agg.get("incorrect", 0) >= 1:
        last2 = [r["result"] for r in (agg.get("recent") or [])[-2:]
                 if r.get("result") in ("correct", "wrong")]
        if len(last2) == 2 and all(r == "correct" for r in last2):
            return IMPROVING
    ra = agg.get("recent_accuracy")
    if agg.get("last_result") == "wrong" or (
            ra is not None and ra < 0.5 and agg.get("attempts", 0) >= 2):
        return WEAK
    return LEARNING


def form_mastery(agg, form, now=None, config=None):
    """Mastery of one cognitive form: NEW / LEARNING / WEAK / IMPROVING / STABLE."""
    st = (agg.get("forms") or {}).get(form, {"attempts": 0, "correct": 0}) if agg else {"attempts": 0, "correct": 0}
    if not agg or st["attempts"] == 0:
        return NEW
    if st["correct"] >= cfg_get(config, "form_stable_min_correct"):
        return STABLE
    if st["correct"] > 0:
        return IMPROVING
    return WEAK


# --------------------------------------------------------------------------
# 5. Revision queue (§10-11) and session selection (§12-14).
# --------------------------------------------------------------------------
def ku_source_ref(ku_meta, questions_by_ku=None):
    if isinstance(ku_meta, dict):
        src = ku_meta.get("source") or {}
        if src.get("block_id"):
            sec = src.get("section_path")
            sec = " > ".join(sec) if isinstance(sec, list) else (sec or "")
            return {"block_id": src.get("block_id"), "page": src.get("page"),
                    "section": sec, "table_ref": src.get("table_ref")}
    for q in (questions_by_ku or {}).values():
        for qq in q:
            for s in qq.get("source") or []:
                if isinstance(s, dict) and s.get("block_id"):
                    sec = s.get("section_path")
                    sec = " > ".join(sec) if isinstance(sec, list) else (sec or "")
                    return {"block_id": s.get("block_id"), "page": s.get("page"),
                            "section": sec, "table_ref": s.get("table_ref")}
    return {}


def build_queue(aggregates, ku_metas=None, questions=None, now=None, config=None):
    """Ordered revision queue. Every entry explains itself (§10-11)."""
    metas = {k["id"]: k for k in (ku_metas or []) if isinstance(k, dict) and k.get("id")}
    qbyku = questions_by_primary(questions or [])
    entries = []
    for ku_id, agg in (aggregates or {}).items():
        meta = metas.get(ku_id)
        req = required_forms_for(ku_id, ku_metas, qbyku)
        s = score_ku(ku_id, agg, meta, now, config, req)
        if s["score"] <= 0 and not s["reasons"]:
            continue
        topic = (meta or {}).get("topic") or ""
        if not topic and qbyku.get(ku_id):
            topic = qbyku[ku_id][0].get("topic", "")
        entries.append({
            "ku_id": ku_id,
            "topic": topic,
            "subtopic": (meta or {}).get("subtopic", ""),
            "priority": s["band"],
            "score": s["score"],
            "reasons": s["reasons"],
            "weak_forms": s["weak_forms"],
            "source": ku_source_ref(meta, {ku_id: qbyku.get(ku_id, [])}),
            "recommended_type": FORM_TO_QTYPE.get((s["weak_forms"] or ["recall"])[0], "factual_mcq"),
            "last_result": agg.get("last_result"),
            "confidence_signal": agg.get("last_confidence"),
            "mastery": mastery_of(ku_id, agg, meta, now, config, req),
            "next_action": "Practise %s items" % (
                (s["weak_forms"] or ["recall"])[0]),
        })
    entries.sort(key=lambda e: (-e["score"], e["ku_id"]))
    return entries


REVISION_MODES = ("targeted", "mistakes", "confusion", "hce",
                  "cognitive", "quick", "full")


def select_session(queue, mode="targeted", limit=None, weak_form=None, config=None):
    """Filter the queue into one revision mode (§12). Deterministic."""
    if mode not in REVISION_MODES:
        raise ValueError("unknown revision mode: %r" % (mode,))
    if mode == "mistakes":
        out = [e for e in queue if REPEATED_ERROR in e["reasons"] or RECENT_ERROR in e["reasons"]]
    elif mode == "confusion":
        out = [e for e in queue if CONFUSION_CLUSTER in e["reasons"]]
    elif mode == "hce":
        out = [e for e in queue if HIGH_CONF_ERROR in e["reasons"]]
    elif mode == "cognitive":
        out = [e for e in queue if COGNITIVE_GAP in e["reasons"] or INCOMPLETE_MASTERY in e["reasons"]]
        if weak_form:
            out = [e for e in out if weak_form in e["weak_forms"]]
    elif mode == "quick":
        out = list(queue)[:cfg_get(config, "quick_size")]
    else:  # targeted, full
        out = list(queue)
    out = sorted(out, key=lambda e: (-e["score"], e["ku_id"]))
    if limit is not None:
        out = out[:limit]
    return out


def build_session(queue, size=10, config=None):
    """Compose a session: top-priority, confusion, cognitive-gap, stale (§13),
    with topic balancing that yields to concentrated weakness (§14).

    Three passes: (1) recipe pools with the topic cap; (2) whole queue with
    the cap; (3) whole queue without cap, only if still short. A session
    dominated by one topic happens only when the pool allows nothing else.
    """
    recipe = list(cfg_get(config, "session_recipe"))
    if size != 10 or sum(n for _, n in recipe) != 10:
        # scale recipe proportionally; floor(x+0.5) matches JS Math.round
        total = sum(n for _, n in recipe) or 1
        recipe = [(k, max(1, int(size * n / total + 0.5))) for k, n in recipe]
    pools = {
        "priority": list(queue),
        "confusion": [e for e in queue if CONFUSION_CLUSTER in e["reasons"]],
        "cognitive": [e for e in queue if COGNITIVE_GAP in e["reasons"] or INCOMPLETE_MASTERY in e["reasons"]],
        "stale": [e for e in queue if STALE_RECALL in e["reasons"]],
    }
    cap = cfg_get(config, "topic_cap")
    picked, counts = [], {}

    def take(pool, n, enforce_cap):
        got = []
        for e in pool:
            if len(got) >= n or len(picked) + len(got) >= size:
                break
            if e["ku_id"] in {p["ku_id"] for p in picked} | {g["ku_id"] for g in got}:
                continue
            if enforce_cap and counts.get(e["topic"], 0) >= cap:
                continue
            counts[e["topic"]] = counts.get(e["topic"], 0) + 1
            got.append(e)
        return got

    by_score = sorted(queue, key=lambda e: (-e["score"], e["ku_id"]))
    for key, n in recipe:
        picked.extend(take(pools.get(key, []), n, True))
    picked.extend(take(by_score, size, True))
    picked.extend(take(by_score, size, False))
    return picked[:size]


# --------------------------------------------------------------------------
# 6. Question selection (§9, §25, §27) + generation hook (§26).
# --------------------------------------------------------------------------
def question_blob(q):
    parts = [q.get("stem", q.get("question", "")) or ""]
    for o in q.get("options") or []:
        parts.append((o.get("text", "") or "") if isinstance(o, dict) else str(o))
    return " ".join(parts)


def question_forms(q):
    if covmod is None:
        return set()
    try:
        return set(covmod.q_cognitive_forms(q))
    except Exception:
        return set()


def primary_of(q):
    for e in q.get("knowledge_units") or []:
        if isinstance(e, dict) and e.get("role") == "primary":
            return e.get("ku_id")
    return None


def _structurally_ok(q):
    """Minimal shape guard so malformed bank entries never reach learners.

    (Banks shipped in packages are pre-validated; this is defense in depth.
    Deep validity is enforced by validate_revision_question.)
    """
    if not isinstance(q, dict) or not q.get("id"):
        return False
    if len(q.get("options") or []) < 2:
        return False
    if not q.get("answer"):
        return False
    if primary_of(q) is None:
        return False
    if not (q.get("stem") or q.get("question")):
        return False
    return True


def select_for_entry(entry, questions, answered_ids=(), exclude_ids=(),
                     answered_blobs=(), last_purposes=None, fidelity="SOURCE_BOUND",
                     config=None):
    """Pick a question for one queue entry, trying its weak forms in order
    then falling back to any form on the same KU. Returns (pick, weak_used).
    Mirrors the browser session builder rule-for-rule.
    """
    last_purposes = last_purposes or {}
    weaks = list(entry.get("weak_forms") or [])
    for weak in weaks + [None]:
        pick = select_question(entry["ku_id"], weak, questions,
                               answered_ids=answered_ids, exclude_ids=exclude_ids,
                               answered_blobs=answered_blobs,
                               last_purpose=last_purposes.get(entry["ku_id"]),
                               fidelity=fidelity, config=config)
        if pick.get("question_id"):
            return pick, weak
    return pick, None


def select_question(ku_id, weak_form, questions, answered_ids=(),
                    exclude_ids=(), answered_blobs=(), last_purpose=None,
                    fidelity="SOURCE_BOUND", config=None):
    """Pick the next question for KU + weak form, or request generation.

    Preference: unanswered matching-form question, different purpose from the
    last attempt, deterministic order. Excludes exact repeats, semantic
    duplicates of answered items, invalid/unvalidated and out-of-fidelity
    questions (§27). A repeat is allowed only as final confirmation after
    `retest_after_new` newer attempts on the same KU+form (§9).
    Returns {question_id|None, strategy, reason|request}.
    """
    thr = cfg_get(config, "dup_threshold")
    excluded = set(exclude_ids or [])
    answered = set(answered_ids or [])
    cands = []
    for q in questions or []:
        if not _structurally_ok(q):
            continue
        if q.get("id") in excluded:
            continue
        if fidelity == "SOURCE_BOUND" and (q.get("origin") or "source") != "source":
            continue
        if primary_of(q) != ku_id:
            continue
        if weak_form and weak_form not in question_forms(q):
            continue
        cands.append(q)
    fresh, seen = [], []
    for q in cands:
        if q["id"] in answered:
            seen.append(q)
            continue
        blob = question_blob(q)
        if any(token_set_sim(blob, ab) >= thr for ab in (answered_blobs or [])):
            continue
        fresh.append(q)

    def rank_key(q):
        purp = q.get("purpose") or ""
        return (0 if q.get("id") not in answered else 1,
                0 if not last_purpose or purp != last_purpose else 1,
                q.get("id"))

    fresh.sort(key=lambda q: (rank_key(q)[1], q.get("id")))
    if fresh:
        q = fresh[0]
        return {"question_id": q["id"], "strategy": "new_form" if weak_form in question_forms(q) else "new_item",
                "reason": "Unanswered %s item on %s" % (weak_form or "any form", ku_id)}
    # confirmation repeat only after enough newer attempts
    if seen:
        return {"question_id": None, "strategy": "generate",
                "reason": "No fresh %s item left; repeat needs %d newer attempts first"
                          % (weak_form or "any", cfg_get(config, "retest_after_new")),
                "request": revision_request(ku_id, weak_form, None, None, None,
                                            sorted(answered | excluded), fidelity)}
    return {"question_id": None, "strategy": "generate",
            "reason": "Bank has no %s item for %s" % (weak_form or "any form", ku_id),
            "request": revision_request(ku_id, weak_form, None, None, None,
                                        sorted(answered | excluded), fidelity)}


def revision_request(ku_id, weak_form=None, confusion_cluster=None,
                     preferred_purpose=None, preferred_type=None,
                     excluded_question_ids=(), fidelity="SOURCE_BOUND"):
    """Spec for the agent-side generator: produce ONE new validated question.

    The generator must return a validated question (see
    validate_revision_question); unvalidated output never reaches learners.
    """
    form = weak_form or "recall"
    return {
        "ku_id": ku_id,
        "weak_form": form,
        "confusion_cluster": confusion_cluster,
        "preferred_purpose": preferred_purpose or FORM_TO_PURPOSE.get(form, "direct_recall"),
        "preferred_type": preferred_type or FORM_TO_QTYPE.get(form, "factual_mcq"),
        "excluded_question_ids": sorted(set(excluded_question_ids or [])),
        "fidelity": fidelity,
        "rules": [
            "Test the same KU in a different wording, purpose or form; never repeat an excluded question.",
            "Keep SOURCE_BOUND provenance: every claim traceable to the KU source evidence.",
            "Mark distractor_origin, confusion_type and ku_ref on every distractor.",
        ],
    }


def validate_revision_question(q, ctx):
    """Validate a generated revision question before it reaches a learner.

    ctx: {ku_ids, ku_map, block_ids, ntext, n_opts, mode, threshold,
          target_ku, weak_form, excluded_ids}. Returns (ok, notes).
    """
    import validate_questions as vq
    notes = []
    seen = list(ctx.get("seen_texts") or [])
    res = vq.check_one(dict(q), ctx.get("ku_ids", set()), ctx.get("ku_map", {}),
                       ctx.get("block_ids", set()), ctx.get("ntext", ""),
                       ctx.get("n_opts", 4), ctx.get("mode", "SOURCE_BOUND"),
                       ctx.get("threshold", 0.85), seen)
    notes.extend(res.get("notes", []))
    ok = res.get("status") == "validated"
    if primary_of(q) != ctx.get("target_ku"):
        ok = False
        notes.append("primary KU %r != requested %r" % (primary_of(q), ctx.get("target_ku")))
    weak = ctx.get("weak_form")
    if weak and weak not in question_forms(q):
        ok = False
        notes.append("question does not exercise requested form %r" % (weak,))
    if q.get("id") in set(ctx.get("excluded_ids") or ()):
        ok = False
        notes.append("question reuses an excluded id")
    return ok, notes


# --------------------------------------------------------------------------
# 7. Session migration (§19-20). v1 (legacy web {answers, mode}) and
# schema-shape sessions migrate to canonical v2. Never crashes on old data.
# --------------------------------------------------------------------------
def migrate_session(raw):
    """Return (session_v2, migrated: bool, notes: [str])."""
    notes = []
    if not isinstance(raw, dict):
        return ({"study_session_version": SESSION_VERSION, "answers": {},
                 "events": [], "mode": "practice",
                 "revision_state": {"queue": [], "sessions": []}},
                True, ["empty input defaulted to fresh v2 session"])
    if raw.get("study_session_version") == SESSION_VERSION and isinstance(raw.get("answers"), dict):
        s = dict(raw)
        s.setdefault("events", [])
        s.setdefault("revision_state", {"queue": [], "sessions": []})
        s.setdefault("mode", "practice")
        # forward-fill any missing answer keys (never overwrite)
        for qid, a in s["answers"].items():
            if isinstance(a, dict):
                for k, dflt in (("conf", None), ("sel", None), ("correct", None),
                                ("marked", False), ("primary_ku", None),
                                ("time", None), ("mode", None)):
                    a.setdefault(k, dflt)
        return s, False, ["already v2"]
    answers = {}
    mode = raw.get("mode", "practice") or "practice"
    if isinstance(raw.get("answers"), dict):
        for qid, a in raw["answers"].items():
            if not isinstance(a, dict):
                notes.append("dropped non-object answer %s" % qid)
                continue
            na = {"sel": a.get("sel"), "conf": a.get("conf"),
                  "correct": a.get("correct"), "distype": a.get("distype"),
                  "dpurpose": a.get("dpurpose"), "primary_ku": a.get("primary_ku"),
                  "marked": bool(a.get("marked", False)), "time": a.get("time"),
                  "mode": a.get("mode"), "dt_ms": a.get("dt_ms"),
                  "key": a.get("key"), "difficulty": a.get("difficulty"),
                  "purpose": a.get("purpose"), "cog": a.get("cog"),
                  "secondary_kus": a.get("secondary_kus"),
                  "rev_priority": a.get("rev_priority")}
            answers[qid] = na
        notes.append("migrated %d answers from legacy format" % len(answers))
    elif isinstance(raw.get("responses"), list):
        for r in raw["responses"]:
            if not isinstance(r, dict) or not r.get("question_id"):
                continue
            qid = r["question_id"]
            res = r.get("result")
            answers[qid] = {
                "sel": r.get("selected_answer"),
                "conf": r.get("confidence"), "correct": res == "correct" if res else None,
                "distype": r.get("confusion_type"), "dpurpose": None,
                "primary_ku": r.get("primary_ku"), "marked": bool(r.get("marked", False)),
                "time": r.get("timestamp"), "mode": r.get("mode"), "dt_ms": r.get("time_taken_ms"),
                "key": r.get("correct_answer"), "difficulty": r.get("difficulty"),
                "purpose": r.get("question_purpose"), "cog": r.get("cognitive_level"),
                "secondary_kus": r.get("secondary_kus"), "rev_priority": r.get("revision_priority_at_attempt"),
            }
        notes.append("migrated %d schema responses" % len(answers))
    else:
        notes.append("no answers found; fresh session")
    events = []
    for qid in sorted(answers):
        a = answers[qid]
        res = "correct" if a.get("correct") is True else ("wrong" if a.get("correct") is False else None)
        events.append({"timestamp": a.get("time"), "question_id": qid,
                       "primary_ku": a.get("primary_ku"),
                       "secondary_kus": a.get("secondary_kus") or [],
                       "result": res, "selected_answer": a.get("sel"),
                       "correct_answer": a.get("key"), "confidence": a.get("conf"),
                       "confusion_type": a.get("distype"),
                       "question_purpose": a.get("purpose"), "cognitive_level": a.get("cog"),
                       "difficulty": a.get("difficulty"), "mode": a.get("mode") or mode,
                       "time_taken_ms": a.get("dt_ms"), "marked": a.get("marked", False),
                       "revision_priority_at_attempt": a.get("rev_priority")})
    return ({"study_session_version": SESSION_VERSION, "answers": answers,
             "events": events, "mode": mode,
             "revision_state": {"queue": [], "sessions": []}}, True, notes)


# --------------------------------------------------------------------------
# 8. Analytics data layer (§21): weak KUs, HCE, clusters, gaps, mastery.
# --------------------------------------------------------------------------
def analytics_revision(aggregates, queue=None, top_n=5):
    weak = sorted(
        ((ku, a) for ku, a in (aggregates or {}).items() if a.get("attempts")),
        key=lambda kv: (kv[1].get("recent_accuracy")
                        if kv[1].get("recent_accuracy") is not None else 1.0, kv[0]),
    )[:top_n]
    hce_kus = sorted([ku for ku, a in (aggregates or {}).items()
                      if a.get("high_confidence_errors")])
    clusters = {}
    for ku, a in (aggregates or {}).items():
        for cl, n in (a.get("clusters_wrong") or {}).items():
            c = clusters.setdefault(cl, {"misses": 0, "kus": []})
            c["misses"] += n
            c["kus"].append(ku)
    mastery_counts = {}
    for ku, a in (aggregates or {}).items():
        m = mastery_of(ku, a)
        mastery_counts[m] = mastery_counts.get(m, 0) + 1
    return {
        "weak_kus": [{"ku_id": ku, "accuracy": a.get("recent_accuracy"),
                      "attempts": a.get("attempts")} for ku, a in weak],
        "high_confidence_errors": {"count": sum(
            a.get("high_confidence_errors", 0) for a in (aggregates or {}).values()),
            "kus": hce_kus},
        "confusion_clusters": [{"cluster": k, "misses": v["misses"],
                                "kus": sorted(v["kus"])} for k, v in clusters.items()],
        "cognitive_gaps": [{"ku_id": e["ku_id"], "weak_forms": e["weak_forms"]}
                           for e in (queue or []) if e.get("weak_forms")],
        "mastery_counts": mastery_counts,
        "queue_size": len(queue or []),
    }


# --------------------------------------------------------------------------
# CLI: queue / select / migrate over JSON files.
# --------------------------------------------------------------------------
def _read(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_queue(a):
    events = _read(a.events)
    if isinstance(events, dict) and "events" in events:
        events = events["events"]
    kus = _read(a.kus) if a.kus else []
    if isinstance(kus, dict) and "units" in kus:
        kus = kus["units"]
    questions = _read(a.questions) if a.questions else []
    if isinstance(questions, dict):
        questions = questions.get("questions", [])
    qmap = {q.get("id"): q for q in questions if isinstance(q, dict)}
    normed = [normalize_event(e, qmap.get(e.get("question_id") if isinstance(e, dict) else None)) for e in events]
    aggs = aggregate(normed, qmap)
    qbyku = questions_by_primary(questions)
    queue = build_queue(aggs, kus, questions)
    out = {"queue": queue,
           "mastery": {k: mastery_of(k, v) for k, v in aggs.items()},
           "summary": analytics_revision(aggs, queue)}
    save_json(a.out, out)
    print("revision queue: %d items -> %s" % (len(queue), a.out))
    for e in queue[:10]:
        print("  %s %-8s %s [%s]" % (e["ku_id"], e["priority"], ",".join(e["reasons"]) or "-",
                                     ",".join(e["weak_forms"]) or "-"))
    return 0


def cmd_select(a):
    queue = _read(a.queue)
    if isinstance(queue, dict) and "queue" in queue:
        queue = queue["queue"]
    questions = _read(a.bank)
    if isinstance(questions, dict):
        questions = questions.get("questions", [])
    session = build_session(queue, a.size) if a.mode == "auto" else select_session(
        queue, a.mode, a.size, weak_form=a.weak_form)
    raw_answered = _read(a.answered) if a.answered else {}
    if isinstance(raw_answered, dict) and "answers" in raw_answered:
        raw_answered = raw_answered["answers"]
    if isinstance(raw_answered, dict):
        answered = {k for k, v in raw_answered.items()
                    if isinstance(v, dict) and v.get("sel")}
    else:
        answered = set(raw_answered or [])
    picks = []
    blobs = []
    last_purposes = {}
    for e in session:
        pick, weak_used = select_for_entry(
            e, questions, answered_ids=answered,
            exclude_ids=set(a.exclude or []),
            answered_blobs=blobs, last_purposes=last_purposes)
        picks.append({"ku_id": e["ku_id"], "weak_forms": e.get("weak_forms"),
                      "reasons": e.get("reasons"), "weak_used": weak_used, **pick})
        if pick.get("question_id"):
            answered.add(pick["question_id"])
            blobs.append(question_blob(next(
                q for q in questions if q.get("id") == pick["question_id"])))
    save_json(a.out, {"mode": a.mode, "picks": picks})
    print("revision session: %d picks -> %s" % (len(picks), a.out))
    return 0


def cmd_migrate(a):
    raw = _read(a.session)
    s, migrated, notes = migrate_session(raw)
    save_json(a.out, s)
    print("migrate: migrated=%s notes=%s -> %s" % (migrated, notes, a.out))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Deterministic KU-level revision engine.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue", help="Score KUs and build the revision queue.")
    q.add_argument("--events", required=True)
    q.add_argument("--kus", default=None)
    q.add_argument("--questions", default=None)
    q.add_argument("--out", required=True)
    s = sub.add_parser("select", help="Select a revision session from a queue.")
    s.add_argument("--queue", required=True)
    s.add_argument("--bank", required=True)
    s.add_argument("--mode", default="auto",
                   choices=["auto"] + list(REVISION_MODES))
    s.add_argument("--size", type=int, default=10)
    s.add_argument("--weak-form", default=None)
    s.add_argument("--answered", default=None)
    s.add_argument("--exclude", nargs="*", default=[])
    s.add_argument("--out", required=True)
    m = sub.add_parser("migrate", help="Migrate a session to v2.")
    m.add_argument("--session", required=True)
    m.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "queue":
        return cmd_queue(a)
    if a.cmd == "select":
        return cmd_select(a)
    return cmd_migrate(a)


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
