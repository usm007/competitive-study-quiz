"""Assemble quiz_package.json from validated + quality-accepted bank + audit + gate (Phase 3)."""
import argparse
import collections as _c
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
    ap.add_argument("--quality", default=None)
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

    bank_dir = os.path.dirname(os.path.abspath(a.bank))
    audit_dir = os.path.dirname(os.path.abspath(a.audit))
    vpath = os.path.join(audit_dir, "validation_results.json")
    if not os.path.isfile(vpath):
        vpath = os.path.join(bank_dir, "validation_results.json")
    valid = None
    if os.path.isfile(vpath):
        v = load_json(vpath)
        res = v.get("results") if isinstance(v, dict) else v
        valid = {r["id"] for r in res if r.get("status") == "validated"}

    # Quality Gate (Phase 3)
    qpath = a.quality
    if not qpath:
        cand1 = os.path.join(audit_dir, "quality_report.json")
        cand2 = os.path.join(bank_dir, "quality_report.json")
        if os.path.isfile(cand1):
            qpath = cand1
        elif os.path.isfile(cand2):
            qpath = cand2
    qual_accepted = None
    qual_grades = {}
    top_rej = []
    grade_dist = {}
    if qpath and os.path.isfile(qpath):
        qrep = load_json(qpath)
        qres = qrep.get("results") if isinstance(qrep, dict) else qrep
        qual_accepted = {r["id"] for r in qres if r.get("quality_status") == "accepted"}
        qual_grades = {r["id"]: r.get("grade") for r in qres}
        if isinstance(qrep, dict) and "summary" in qrep:
            grade_dist = qrep["summary"].get("grades", {})
            top_rej = qrep["summary"].get("top_rejection_reasons", [])

    # Filter: must be validated AND quality-accepted (if quality report exists)
    kept = []
    excluded = []
    for x in qs:
        qid = x.get("id")
        is_val = (valid is None or qid in valid)
        is_qual = (qual_accepted is None or qid in qual_accepted)
        if is_val and is_qual:
            if qid in qual_grades:
                x["quality_grade"] = qual_grades[qid]
                x["quality_status"] = "accepted"
            kept.append(x)
        else:
            excluded.append(qid)

    tiers = {}
    revpri = {}
    if a.inventory and os.path.isfile(a.inventory):
        inv = load_json(a.inventory)
        units = inv.get("units") if isinstance(inv, dict) else inv
        tiers = {u.get("id"): u.get("tier") for u in units}
        for u in units:
            rp = (u.get("dimensions") or {}).get("revision_priority")
            if rp:
                revpri[u.get("id")] = rp

    for x in kept:
        prims = [e.get("ku_id") for e in x.get("knowledge_units") or []
                 if isinstance(e, dict) and e.get("role") == "primary"]
        ts = [tiers[k] for k in prims if k in tiers]
        x["tier"] = min(ts) if ts else None
        if not x.get("revision_priority"):
            rps = [revpri[k] for k in prims if k in revpri]
            order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            if rps:
                x["revision_priority"] = sorted(rps, key=lambda r: order.get(r, 0), reverse=True)[0]

    ext = sum(1 for x in kept if x.get("origin") == "external")
    ext += sum(1 for x in kept for o in x.get("options") or []
               if isinstance(o, dict) and o.get("distractor_origin") == "external")
    prof = os.path.splitext(os.path.basename(a.profile))[0] if a.profile else "CUSTOM"

    by_type = dict(_c.Counter(x.get("type", "unknown") for x in kept))
    by_purpose = dict(_c.Counter((x.get("purpose") or "unspecified") for x in kept))
    by_diff = dict(_c.Counter((x.get("difficulty") or "unspecified") for x in kept))
    by_cog = dict(_c.Counter((x.get("cognitive_level") or x.get("type") or "unspecified") for x in kept))

    pkg = {
        "meta": {
            "title": a.title,
            "source": a.source_label,
            "profile": prof,
            "status": g.get("status"),
            "gate_reasons": g.get("reasons", []),
            "coverage_by_tier": au.get("coverage_by_tier", {}),
            "cognitive_by_tier": au.get("cognitive_by_tier", {}),
            "purpose_coverage": au.get("purpose_coverage", by_purpose),
            "coverage_label": au.get("coverage_label", ""),
            "cognitive_label": au.get("cognitive_label", ""),
            "validated": len(kept),
            "total": len(qs),
            "by_type": by_type,
            "by_purpose": by_purpose,
            "by_cognitive": by_cog,
            "by_difficulty": by_diff,
            "quality_accepted": len(kept),
            "quality_rejected": len(excluded),
            "quality_sample": grade_dist,
            "top_rejection_reasons": top_rej,
            "excluded": excluded,
            "external_count": ext
        },
        "questions": kept
    }

    dest = a.out or os.path.join(bank_dir, "quiz_package.json")
    if not dest.endswith(".json"):
        dest = os.path.join(dest, "quiz_package.json")
    save_json(dest, pkg)
    print("package: %d/%d questions (quality-accepted), status=%s -> %s" %
          (len(kept), len(qs), g.get("status"), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
