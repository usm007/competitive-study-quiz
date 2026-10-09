"""Deduplication and Redundancy Detection Engine (Phase 3).

Detects:
1. Exact duplicates (identical stem or identical options + key)
2. Semantic duplicates (token set similarity >= threshold)
3. Same-fact + Same-purpose redundancy (same primary KU + same exam purpose)
4. Same-statement set with cosmetic changes (permutations/equivalent statements)

Preserves valuable diversity:
Multiple questions on the same KU are permitted and encouraged if they
serve different cognitive purposes (e.g. recall vs distinction vs statement).
"""
import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, token_set_sim, fail, run_main


def blob(q):
    opts = []
    for o in (q.get("options") or []):
        if isinstance(o, dict):
            opts.append(o.get("text", "") or "")
        elif isinstance(o, str):
            opts.append(o)
        else:
            opts.append(str(o))
    return (q.get("stem", q.get("question", "")) or "") + " " + " ".join(opts)


def get_prim_ku(q):
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


def detect_duplicates(questions, threshold=0.85):
    pairs = []
    diversity_preserved = []

    for x, y in itertools.combinations(questions, 2):
        x_id, y_id = x.get("id"), y.get("id")
        x_stem, y_stem = norm(x.get("stem", "")), norm(y.get("stem", ""))
        x_prim, y_prim = get_prim_ku(x), get_prim_ku(y)
        x_purp, y_purp = x.get("purpose"), y.get("purpose")

        # 1. Exact Duplicate
        if x_stem and x_stem == y_stem:
            pairs.append({
                "a": x_id, "b": y_id, "type": "exact_duplicate",
                "similarity": 1.0, "reason": "identical question stem"
            })
            continue

        # 2. Semantic Duplicate via Blob Similarity
        s = token_set_sim(blob(x), blob(y))
        if s >= threshold:
            pairs.append({
                "a": x_id, "b": y_id, "type": "semantic_duplicate",
                "similarity": round(s, 3), "reason": "high token-set similarity (%.3f)" % s
            })
            continue

        # 3. Same Statement Set with Cosmetic Changes
        sts_x = [norm(st.get("text", "")) for st in (x.get("statements") or []) if isinstance(st, dict)]
        sts_y = [norm(st.get("text", "")) for st in (y.get("statements") or []) if isinstance(st, dict)]
        if sts_x and sts_y and len(sts_x) == len(sts_y):
            matches = sum(1 for sx in sts_x if any(token_set_sim(sx, sy) >= 0.85 for sy in sts_y))
            if matches == len(sts_x):
                pairs.append({
                    "a": x_id, "b": y_id, "type": "same_statement_set",
                    "similarity": round(s, 3), "reason": "same statements with cosmetic changes"
                })
                continue

        # 4. Same Fact + Same Purpose Redundancy vs Valuable Diversity
        if x_prim and y_prim and x_prim == y_prim:
            if x_purp and y_purp and x_purp == y_purp:
                stem_sim = token_set_sim(x.get("stem", ""), y.get("stem", ""))
                if stem_sim >= 0.65 or s >= 0.70:
                    pairs.append({
                        "a": x_id, "b": y_id, "type": "same_fact_same_purpose",
                        "similarity": round(stem_sim, 3),
                        "reason": "redundant: same primary KU %s and purpose '%s'" % (x_prim, x_purp)
                    })
                    continue
            elif x_purp and y_purp and x_purp != y_purp:
                diversity_preserved.append({
                    "a": x_id, "b": y_id, "ku_id": x_prim,
                    "purpose_a": x_purp, "purpose_b": y_purp,
                    "reason": "valuable diversity: same KU tested across different purposes"
                })

    return pairs, diversity_preserved


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.bank):
        fail("file not found: %s" % a.bank)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b

    pairs, diversity = detect_duplicates(qs, a.threshold)

    out = {
        "threshold": a.threshold,
        "pairs": pairs,
        "count": len(pairs),
        "valuable_diversity_count": len(diversity),
        "valuable_diversity": diversity[:20]
    }
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.bank)), "dedupe_report.json")
    save_json(dest, out)
    print("dedupe: %d redundant/duplicate pairs, %d valuable diversity pairs preserved (thr=%.2f) -> %s" %
          (len(pairs), len(diversity), a.threshold, dest))
    for p in pairs:
        print("  %s ~ %s [%s] (%s)" % (p["a"], p["b"], p["type"], p["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
