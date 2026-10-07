import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main

# D2: distractor_basis = no credit; secondary = partial; primary = full.
# covered = >=1 validated primary; repeatedly_tested = >=2 validated
# primaries with different forms or confusion types.
WEAK_SINGLE_FORMS = {"true_false"}


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


def q_form(q):
    return q.get("type", q.get("qtype", "unknown"))


def q_confusions(q):
    s = set()
    for o in q.get("options") or []:
        if isinstance(o, dict) and o.get("confusion_type"):
            s.add(o["confusion_type"])
    return s


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("inventory")
    ap.add_argument("validation")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--cap", type=int, default=None)
    a = ap.parse_args(argv)
    for p in (a.bank, a.inventory, a.validation):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b
    inv = load_json(a.inventory)
    units = inv.get("units") if isinstance(inv, dict) else inv
    v = load_json(a.validation)
    res = v.get("results") if isinstance(v, dict) else v
    valid = {r["id"] for r in res if r.get("status") == "validated"}
    cap = a.cap
    if cap is None and a.config and os.path.isfile(a.config):
        cap = load_json(a.config).get("per_ku_cap", 3)
    cap = cap or 3
    primaries = collections.defaultdict(list)
    secondaries = collections.defaultdict(list)
    for q in qs:
        if q.get("id") not in valid:
            continue
        for kid, role in ku_roles(q):
            if role == "primary":
                primaries[kid].append(q)
            elif role == "secondary":
                secondaries[kid].append(q)
            # distractor_basis: zero credit by design (D2/R2)
    ku_type = {u.get("id"): u.get("type", "") for u in units}
    per_ku, dist, overcap = {}, collections.Counter(), []
    for u in units:
        kid = u.get("id")
        ps = primaries.get(kid, [])
        ss = secondaries.get(kid, [])
        if len(ps) >= 2:
            forms = {q_form(q) for q in ps}
            confs = set()
            for q in ps:
                confs |= q_confusions(q)
            s = "repeatedly_tested" if (len(forms) > 1 or len(confs) > 1) else "covered"
        elif len(ps) == 1:
            # single weak form for a distinction-heavy KU is only partial (D2)
            if q_form(ps[0]) in WEAK_SINGLE_FORMS and ku_type.get(kid) in (
                    "distinction", "comparison", "classification", "concept"):
                s = "partially_covered"
            else:
                s = "covered"
        elif ss:
            s = "partially_covered"
        else:
            s = "uncovered"
        if len(ps) > cap:
            overcap.append({"ku_id": kid, "primary_count": len(ps), "cap": cap})
        dist[s] += 1
        per_ku[kid] = {"tier": str(u.get("tier", "?")), "type": ku_type.get(kid),
                       "primary_count": len(ps), "secondary_count": len(ss),
                       "question_ids": [q.get("id") for q in ps + ss],
                       "primary_ids": [q.get("id") for q in ps], "status": s}
    by_tier, tiers = {}, collections.defaultdict(list)
    for kid, e in per_ku.items():
        tiers[e["tier"]].append(e)
    for t, es in tiers.items():
        cov = sum(1 for e in es if e["status"] in ("covered", "repeatedly_tested"))
        by_tier[t] = {"total": len(es), "covered": cov,
                      "pct_covered": round(100 * cov / len(es), 2) if es else 100.0}
    out = {"per_ku": per_ku, "by_tier": by_tier, "status_dist": dict(dist),
           "per_ku_cap": cap, "over_cap": overcap, "counted_questions": len(valid)}
    dest = a.out if a.out.endswith(".json") else os.path.join(a.out, "coverage_matrix.json")
    save_json(dest, out)
    print("coverage: %s" % {k: dict(v) for k, v in by_tier.items()})
    print("coverage: dist=%s over_cap=%d -> %s" % (dict(dist), len(overcap), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
