import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, toks, token_set_sim, fail, run_main

HARD = ("required_fields", "single_select", "key_consistent", "unique_options", "option_count",
        "ku_refs", "primary_ku", "sources_resolve", "source_quote", "statement_logic", "external_ok",
        "duplicate_ok", "hint_ok")
KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PURPOSES = {"direct_recall", "conceptual_understanding", "distinction", "confusable_fact",
            "elimination", "statement_evaluation", "chronology", "classification",
            "cause_effect", "exception", "association", "application", "integrated_concept"}
COG_LEVELS = {"recall", "understanding", "distinction", "application", "analysis"}
DISTRACTOR_PURPOSES = {"confusable_fact", "adjacent_value", "partial_truth", "reversed_relation",
                       "wrong_category", "wrong_entity", "wrong_date", "scope_error", "causal_reversal"}
DIFF_BY_REASONING = {"easy": "direct factual recall",
                     "medium": "relationship / distinction / classification",
                     "hard": "multiple statements / elimination / subtle distinction / integrated reasoning"}


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
    # ponytail: naive number-parse of option text; full NL option semantics out of scope
    return nums if nums or not t.strip() else None


def truth_of(s):
    for k in ("truth_value", "truth", "is_true", "correct"):
        if isinstance(s.get(k), bool):
            return s[k]
    return None


def stmt_check(q):
    sts = q.get("statements") or []
    truths = [truth_of(s) for s in sts if isinstance(s, dict)]
    if not sts or not all(isinstance(t, bool) for t in truths):
        return True, "n/a" if not sts else "no truth marks; key accepted as-is"
    exp = sorted(i + 1 for i, t in enumerate(truths) if t)
    opts = q.get("options") or []
    match = [o for o in opts if opt_covers(o, len(truths)) == exp]
    if len(match) == 1 and str(match[0].get("key")) == str(q.get("answer_key", q.get("answer"))):
        return True, "key matches truth pattern %s" % exp
    return False, "expected pattern %s, key=%s" % (exp, q.get("answer_key", q.get("answer")))


def ku_roles(q):
    entries = q.get("knowledge_units") or []
    if not entries and (q.get("ku_refs") or q.get("ku_ids")):
        prim = q.get("primary_ku", q.get("primary"))
        return [(k, "primary" if k == prim else "secondary")
                for k in (q.get("ku_refs") or q.get("ku_ids") or [])]
    out = []
    for e in entries:
        if isinstance(e, dict) and e.get("ku_id"):
            out.append((e["ku_id"], e.get("role", "secondary")))
        elif isinstance(e, str):
            out.append((e, "secondary"))
    return out


def src_block_ids(q):
    src = q.get("source", q.get("source_blocks", q.get("sources", [])))
    if isinstance(src, dict):
        src = [src]
    ids = []
    for s in src or []:
        if isinstance(s, dict):
            if s.get("block_id"):
                ids.append(s["block_id"])
        elif isinstance(s, str) and s:
            ids.append(s)
    return ids


def check_one(q, ku_ids, ku_map, block_ids, ntext, n_opts, mode, thr, seen_texts):
    c, notes = {}, []
    qid = q.get("id", "?")
    q_form_t = q.get("type", q.get("qtype", ""))
    stem = q.get("stem", q.get("question", "")) or ""
    opts = q.get("options") or []
    key = str(q.get("answer_key", q.get("answer", "")))
    roles = ku_roles(q)
    kurefs = [k for k, _ in roles]
    prim_roles = [k for k, r in roles if r == "primary"]
    prim = prim_roles[0] if prim_roles else q.get("primary_ku", q.get("primary"))
    srcs = src_block_ids(q)
    exc = q.get("supporting_excerpt", q.get("source_excerpt", q.get("excerpt", ""))) or ""
    hint = q.get("hint", "") or ""
    qorigin = (q.get("origin") or "source")
    ext_opts = [o for o in opts if isinstance(o, dict) and o.get("distractor_origin") == "external"]
    okeys = [str(o.get("key", KEYS[i] if i < 26 else i)) for i, o in enumerate(opts)]
    otexts = [(o.get("text", "") or "") for o in opts]
    correct = [o for o in opts if o.get("is_correct") is True]
    c["required_fields"] = bool(q.get("id") and stem.strip() and len(opts) >= 2 and key and kurefs and srcs)
    if not c["required_fields"]:
        notes.append("missing required fields")
    c["single_select"] = len(correct) == 1
    if not c["single_select"]:
        notes.append("is_correct count=%d, need exactly 1" % len(correct))
    c["key_consistent"] = (len(correct) == 1 and str(correct[0].get("key", "")) == key and key in okeys)
    if not c["key_consistent"]:
        notes.append("answer_key=%s inconsistent with options" % key)
    c["unique_options"] = len({norm(t) for t in otexts}) == len(otexts)
    if not c["unique_options"]:
        notes.append("duplicate option texts")
    c["option_count"] = len(opts) == n_opts or (q_form_t == "true_false" and len(opts) == 2)
    if not c["option_count"]:
        notes.append("options=%d, profile wants %d" % (len(opts), n_opts))
    c["ku_refs"] = bool(kurefs) and all(k in ku_ids for k in kurefs)
    if not c["ku_refs"]:
        notes.append("unknown ku_refs=%s" % [k for k in kurefs if k not in ku_ids])
    c["primary_ku"] = prim in kurefs
    if not c["primary_ku"]:
        notes.append("primary_ku missing/not in ku_refs")
    c["sources_resolve"] = bool(srcs) and all(s in block_ids for s in srcs)
    if not c["sources_resolve"]:
        notes.append("unresolved source block_ids")
    if exc:
        c["source_quote"] = bool(norm(exc)) and norm(exc) in ntext
        if not c["source_quote"]:
            notes.append("supporting_excerpt not verbatim in source")
    else:
        missing = [k for k in kurefs
                   if not (ku_map.get(k) and norm(ku_map[k]) and norm(ku_map[k]) in ntext)]
        c["source_quote"] = not missing
        if missing:
            notes.append("KU supporting_excerpt not verbatim in source: %s" % missing)
    c["statement_logic"], smsg = stmt_check(q)
    if not c["statement_logic"]:
        notes.append(smsg)
    # C8: in SOURCE_BOUND, question origin must be source; external
    # distractors are allowed only when explicitly tagged distractor_origin.
    c["external_ok"] = True
    if mode == "SOURCE_BOUND" and qorigin == "external":
        c["external_ok"] = False
        notes.append("origin: external not allowed in SOURCE_BOUND")
    c["external_distractors"] = len(ext_opts)
    blob = stem + " " + " ".join(otexts)
    dup = [oid for oid, ob in seen_texts if token_set_sim(blob, ob) >= thr]
    c["duplicate_ok"] = not dup
    if dup:
        notes.append("near-duplicate of %s" % dup)
    seen_texts.append((qid, blob))
    ktext = next((o.get("text", "") or "" for o in opts if str(o.get("key", "")) == key), "")
    c["hint_ok"] = True
    if hint.strip() and len(norm(ktext)) > 15:
        if norm(ktext) in norm(hint) or norm(hint) in norm(ktext) or token_set_sim(hint, ktext) >= 0.9:
            c["hint_ok"] = False
            notes.append("hint leaks answer text")
    c["clue_longest_ok"] = True
    if ktext and len(opts) > 1:
        others = [len(o.get("text", "") or "") for o in opts if str(o.get("key", "")) != key]
        if others and len(ktext) > 1.2 * (sum(others) / len(others)):
            c["clue_longest_ok"] = False
            notes.append("flag: key option longest (>20% over mean)")
    c["clue_stem_overlap_ok"] = True
    swords = {w for w in toks(stem) if len(w) >= 7}
    if swords and ktext:
        ko = set(toks(ktext))
        oo = set()
        for o in opts:
            if str(o.get("key", "")) != key:
                oo |= set(toks(o.get("text", "") or ""))
        leaked = [w for w in swords if w in ko and w not in oo]
        if leaked:
            c["clue_stem_overlap_ok"] = False
            notes.append("flag: stem words only in key: %s" % leaked[:3])
    # ---- competitive-engine soft checks (flags, never hard-fail legacy) ----
    # purpose: if present must be known; if absent, informational only
    purp = q.get("purpose")
    c["purpose_ok"] = True
    if purp not in (None, "") and purp not in PURPOSES:
        c["purpose_ok"] = False
        notes.append("flag: unknown purpose %r" % (purp,))
    # cognitive_level: if present must be known
    c["cognitive_ok"] = True
    if q.get("cognitive_level") not in (None, "") and q.get("cognitive_level") not in COG_LEVELS:
        c["cognitive_ok"] = False
        notes.append("flag: unknown cognitive_level %r" % (q.get("cognitive_level"),))
    # distractor discipline: every distractor should carry a reason
    c["distractor_purpose_ok"] = True
    for o in opts:
        if isinstance(o, dict) and not o.get("is_correct"):
            dp = o.get("distractor_purpose")
            if dp not in (None, "") and dp not in DISTRACTOR_PURPOSES:
                c["distractor_purpose_ok"] = False
                notes.append("flag: unknown distractor_purpose %r in %s" % (dp, o.get("key")))
                break
    # difficulty must reflect reasoning demand: hard questions should use
    # statement/elimination/integrated forms, not just obscure wording
    c["difficulty_ok"] = True
    diff = (q.get("difficulty") or "").lower()
    if diff == "hard" and q_form_t in ("factual_mcq", "one_liner_mcq", "true_false") and not q.get("statements"):
        c["difficulty_ok"] = False
        notes.append("flag: hard difficulty on plain recall form; needs statements/elimination/distinction")
    # statement integrity: statement_based must carry 2+ statements with truth marks
    c["statement_integrity_ok"] = True
    if q_form_t in ("statement_based", "assertion_reason"):
        sts = q.get("statements") or []
        if len(sts) < 2:
            c["statement_integrity_ok"] = False
            notes.append("flag: %s needs >=2 statements" % q_form_t)
        elif not all(isinstance(s, dict) and isinstance(truth_of(s), bool) for s in sts):
            c["statement_integrity_ok"] = False
            notes.append("flag: every statement needs a truth_value")
    status = "validated" if all(c[k] for k in HARD) else "rejected"
    return {"id": qid, "checks": c, "status": status, "notes": notes}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("inventory")
    ap.add_argument("struct")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--mode", default="SOURCE_BOUND")
    ap.add_argument("--config", default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    for p in (a.bank, a.inventory, a.struct):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b
    inv = load_json(a.inventory)
    units = inv.get("units") if isinstance(inv, dict) else inv
    st = load_json(a.struct)
    n_opts, thr = 4, 0.85
    if a.profile and os.path.isfile(a.profile):
        n_opts = load_json(a.profile).get("options_per_question", 4)
    if a.config and os.path.isfile(a.config):
        cfg = load_json(a.config)
        thr = cfg.get("duplicate_threshold", thr)
        n_opts = cfg.get("options_per_question", n_opts)
    if a.threshold is not None:
        thr = a.threshold
    ku_ids = {u.get("id") for u in units}
    ku_map = {u.get("id"): u.get("supporting_excerpt", "") or "" for u in units}
    block_ids = {x.get("id") for x in st.get("blocks", [])}
    ntext = norm(st.get("normalized_text", ""))
    seen, results = [], []
    for q in qs:
        results.append(check_one(q, ku_ids, ku_map, block_ids, ntext, n_opts, a.mode, thr, seen))
    bal = collections.Counter(r["checks"] and q_key(qs, r["id"]) for r in results)
    nb = len(bal) or 1
    kbflag = any(v / max(sum(bal.values()), 1) > 1 / nb + 0.2 for v in bal.values())
    nv = sum(1 for r in results if r["status"] == "validated")
    out = {"results": results, "summary": {"total": len(results), "validated": nv,
           "rejected": len(results) - nv, "key_balance": dict(bal), "key_balance_flag": kbflag}}
    dest = a.out if (a.out or "").endswith(".json") else None
    if dest is None:
        base = a.out or os.path.dirname(os.path.abspath(a.bank))
        from lib_common import resolve_out as ro
        dest = ro(base, None, "validation_results.json")
    save_json(dest, out)
    print("validation: %d/%d validated -> %s" % (nv, len(results), dest))
    for r in results:
        if r["status"] == "rejected":
            print("  REJECT %s: %s" % (r["id"], "; ".join(r["notes"])))
    if kbflag:
        print("  FLAG key-position imbalance: %s" % dict(bal))
    return 0 if nv == len(results) else 1


def q_key(qs, qid):
    for q in qs:
        if q.get("id") == qid:
            return str(q.get("answer_key", q.get("answer", "?")))
    return "?"


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
