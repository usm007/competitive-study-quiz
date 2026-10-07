"""Assemble quiz_package.json from validated bank + audit + gate (SKILL.md package step)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("audit")
    ap.add_argument("gate")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--title", default="Study Quiz")
    ap.add_argument("--source-label", default="")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    for p in (a.bank, a.audit, a.gate):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b
    au = load_json(a.audit)
    g = load_json(a.gate)
    vpath = os.path.join(os.path.dirname(os.path.abspath(a.bank)), "validation_results.json")
    valid = None
    if os.path.isfile(vpath):
        v = load_json(vpath)
        res = v.get("results") if isinstance(v, dict) else v
        valid = {r["id"] for r in res if r.get("status") == "validated"}
    kept = [x for x in qs if valid is None or x.get("id") in valid]
    excluded = [x.get("id") for x in qs if valid is not None and x.get("id") not in valid]
    tiers = {}
    if a.inventory and os.path.isfile(a.inventory):
        inv = load_json(a.inventory)
        units = inv.get("units") if isinstance(inv, dict) else inv
        tiers = {u.get("id"): u.get("tier") for u in units}
    for x in kept:
        prims = [e.get("ku_id") for e in x.get("knowledge_units") or []
                 if isinstance(e, dict) and e.get("role") == "primary"]
        ts = [tiers[k] for k in prims if k in tiers]
        x["tier"] = min(ts) if ts else None
    ext = sum(1 for x in kept if x.get("origin") == "external")
    ext += sum(1 for x in kept for o in x.get("options") or []
               if isinstance(o, dict) and o.get("distractor_origin") == "external")
    prof = os.path.splitext(os.path.basename(a.profile))[0] if a.profile else "CUSTOM"
    import collections as _c
    by_type = dict(_c.Counter(x.get("type", "unknown") for x in kept))
    pkg = {"meta": {"title": a.title, "source": a.source_label, "profile": prof,
                    "status": g.get("status"), "gate_reasons": g.get("reasons", []),
                    "coverage_by_tier": au.get("coverage_by_tier", {}),
                    "validated": len(kept), "total": len(qs), "by_type": by_type,
                    "excluded": excluded,
                    "external_count": ext},
           "questions": kept}
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.bank)), "quiz_package.json")
    if not dest.endswith(".json"):
        dest = os.path.join(dest, "quiz_package.json")
    save_json(dest, pkg)
    print("package: %d/%d questions, status=%s -> %s" % (len(kept), len(qs), g.get("status"), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
