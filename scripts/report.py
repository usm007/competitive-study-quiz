import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, fail, run_main


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("audit")
    ap.add_argument("gate")
    ap.add_argument("bank", nargs="?", default=None)
    a = ap.parse_args(argv)
    for p in (a.audit, a.gate):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    au = load_json(a.audit)
    g = load_json(a.gate)
    nq = None
    if a.bank and os.path.isfile(a.bank):
        b = load_json(a.bank)
        nq = len(b.get("questions") if isinstance(b, dict) else b)
    L = []
    L.append("=" * 60)
    L.append("FINAL REPORT -- EXAM QUIZ")
    L.append("=" * 60)
    L.append("")
    L.append("DOCUMENT ANALYSIS")
    kc = au.get("ku_counts", {})
    L.append("  knowledge units: %s" % kc.get("total", "?"))
    L.append("  by tier: %s" % {k: v for k, v in kc.items() if k != "total"})
    L.append("  anchor recall: %.2f%%" % (au.get("anchor_recall", 0) * 100))
    L.append("  diff status: %s" % au.get("diff_status"))
    L.append("  density flags: %d" % len(au.get("density_flags", [])))
    for f in au.get("density_flags", []):
        L.append("    - %s: %.2f < %.2f ku/1000w" % (f.get("section"), f.get("ku_per_1000w"), f.get("floor")))
    L.append("")
    L.append("COVERAGE")
    for t, c in sorted(au.get("coverage_by_tier", {}).items()):
        L.append("  tier %s: %d/%d covered (%.1f%%)" % (t, c.get("covered", 0), c.get("total", 0), c.get("pct_covered", 0)))
    L.append("  status dist: %s" % au.get("status_dist"))
    L.append("  uncovered T1/T2: %d %s" % (len(au.get("uncovered_t1_t2", [])), au.get("uncovered_t1_t2", [])[:10]))
    L.append("  partially covered: %d" % len(au.get("partial", [])))
    L.append("  section shares: %s" % au.get("section_shares"))
    L.append("  skew flags: %d" % len(au.get("skew_flags", [])))
    L.append("")
    L.append("COGNITIVE COVERAGE (content coverage != cognitive coverage)")
    for t, c in sorted((au.get("cognitive_by_tier", {}) or {}).items()):
        L.append("  tier %s: %d/%d cognitively covered (%.1f%%)" % (
            t, c.get("cognitively_covered", 0), c.get("total", 0), c.get("pct", 0)))
    L.append("  coverage label: %s" % (au.get("coverage_label") or "n/a"))
    L.append("  cognitive label: %s" % (au.get("cognitive_label") or "n/a"))
    L.append("  cognitive gaps T1/T2: %d %s" % (
        len(au.get("cognitive_gaps", {}) or {}), sorted((au.get("cognitive_gaps", {}) or {}))[:10]))
    L.append("  distinction gaps (recall ok, distinction missing): %s" % (au.get("distinction_gaps", [])[:10]))
    L.append("  purpose coverage: %s" % (au.get("purpose_coverage", {})))
    L.append("  missing purposes: %s" % (au.get("missing_purposes", [])))
    L.append("  unaddressed confusion clusters: %s" % (au.get("unaddressed_clusters", [])[:6]))
    L.append("")
    L.append("VALIDATION")
    vr = au.get("validation_rates", {})
    L.append("  validated: %d/%d (%.1f%%)" % (vr.get("validated", 0), vr.get("total", 0), vr.get("pct_validated", 0)))
    if nq is not None:
        L.append("  bank size: %d questions" % nq)
    L.append("  type mix actual%%: %s" % au.get("type_mix_vs_target", {}).get("actual_pct"))
    L.append("  type mix target: %s" % au.get("type_mix_vs_target", {}).get("target"))
    L.append("  weak types: %s" % au.get("weak_type_flags"))
    L.append("  duplicates: %s" % au.get("duplicate_flags"))
    L.append("  downgraded tiers: %s" % au.get("downgrade_flags"))
    L.append("")
    L.append("GATE: %s" % g.get("status"))
    for r in g.get("reasons", []):
        L.append("  - %s" % r)
    L.append("")
    L.append("LIMITATIONS")
    for x in au.get("limitations", []) or ["none"]:
        L.append("  - %s" % x)
    L.append("=" * 60)
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
