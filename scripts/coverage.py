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

# Cognitive buckets: CONTENT vs COGNITIVE coverage are distinct.
# recall / distinction / application / statement(elimination)
COG_BUCKETS = ("recall", "distinction", "application", "statement")

PURPOSE_TO_COG = {
    "direct_recall": "recall",
    "conceptual_understanding": "recall",
    "distinction": "distinction",
    "confusable_fact": "distinction",
    "elimination": "statement",
    "statement_evaluation": "statement",
    "chronology": "recall",
    "classification": "distinction",
    "cause_effect": "application",
    "exception": "distinction",
    "association": "distinction",
    "application": "application",
    "integrated_concept": "application",
}

TYPE_TO_COG = {
    "factual_mcq": "recall",
    "one_liner_mcq": "recall",
    "true_false": "recall",
    "match_pairs": "distinction",
    "sequence_mcq": "distinction",
    "elimination_mcq": "statement",
    "statement_based": "statement",
    "assertion_reason": "statement",
    "reasoning_mcq": "application",
    "data_interpretation_mcq": "application",
    "pedagogy_mcq": "application",
}

COG_LEVEL_TO_COG = {
    "recall": "recall",
    "understanding": "recall",
    "distinction": "distinction",
    "application": "application",
    "analysis": "application",
}


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


def q_cognitive_forms(q):
    """Return set of COG_BUCKETS this question exercises (for its primaries)."""
    forms = set()
    purp = (q.get("purpose") or "").strip() if isinstance(q.get("purpose"), str) else None
    if purp and purp in PURPOSE_TO_COG:
        forms.add(PURPOSE_TO_COG[purp])
    cl = q.get("cognitive_level")
    if isinstance(cl, str) and cl in COG_LEVEL_TO_COG:
        forms.add(COG_LEVEL_TO_COG[cl])
    if not forms:
        forms.add(TYPE_TO_COG.get(q_form(q), "recall"))
    # statement-bearing questions always exercise statement reasoning too
    if q.get("statements"):
        forms.add("statement")
    # elimination-type questions exercise statement/elimination
    if q_form(q) in ("elimination_mcq", "statement_based", "assertion_reason"):
        forms.add("statement")
    return forms


def required_forms(ku):
    """Exam-value-driven required cognitive forms for a KU. Not mechanical x4."""
    tier = ku.get("tier", 3)
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        tier = 3
    dims = ku.get("dimensions") or {}
    conf_risk = dims.get("confusion_risk", "low")
    stmt_pot = dims.get("statement_potential", dims.get("conceptual_density", "medium"))
    conf_val = dims.get("confusion_value", conf_risk)
    has_confusable = bool(ku.get("confusable_with"))
    if tier == 1 and (conf_risk == "high" or conf_val == "high" or has_confusable):
        req = {"recall", "distinction", "statement"}
    elif tier == 1:
        req = {"recall", "statement"}
        if has_confusable or conf_risk in ("medium", "high"):
            req.add("distinction")
    elif tier == 2 and (conf_risk == "high" or has_confusable):
        req = {"recall", "distinction"}
    elif tier == 2:
        req = {"recall"}
    else:
        req = {"recall"}
    if stmt_pot == "low" and "statement" in req and tier >= 2:
        # source does not support statement forms; do not force them
        if tier == 2:
            pass  # keep recall-only default already
    # application only required when KU type supports it
    if ku.get("type") in ("cause_effect", "process", "principle", "theory", "formula",
                          "comparison", "classification", "concept"):
        if tier <= 2 and dims.get("conceptual_density", "low") in ("medium", "high"):
            req.add("application")
    return req


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("inventory")
    ap.add_argument("validation")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--quality", default=None, help="Path to quality_report.json")
    ap.add_argument("--dedupe", default=None, help="Path to dedupe_report.json")
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

    # Load quality accepted questions if quality report is explicitly provided
    qual_accepted = None
    if a.quality and os.path.isfile(a.quality):
        qrep = load_json(a.quality)
        qres = qrep.get("results") if isinstance(qrep, dict) else qrep
        qual_accepted = {r["id"] for r in qres if r.get("quality_status") == "accepted"}

    # Load dedupe excluded questions if dedupe report is explicitly provided
    dedupe_excluded = set()
    if a.dedupe and os.path.isfile(a.dedupe):
        drep = load_json(a.dedupe)
        pairs = drep.get("pairs") if isinstance(drep, dict) else drep
        for p in (pairs or []):
            if isinstance(p, dict) and p.get("type") in ("exact_duplicate", "semantic_duplicate") and p.get("b"):
                dedupe_excluded.add(p["b"])

    # Qualifying questions for coverage MUST be:
    # 1. Validated
    # 2. Quality-accepted (if quality report was explicitly passed)
    # 3. Not excluded by dedupe (if dedupe report was explicitly passed)
    qualifying_ids = set()
    for qid in valid:
        if qual_accepted is not None and qid not in qual_accepted:
            continue
        if qid in dedupe_excluded:
            continue
        qualifying_ids.add(qid)

    cap = a.cap
    if cap is None and a.config and os.path.isfile(a.config):
        cap = load_json(a.config).get("per_ku_cap", 3)
    cap = cap or 3
    primaries = collections.defaultdict(list)
    secondaries = collections.defaultdict(list)
    for q in qs:
        if q.get("id") not in qualifying_ids:
            continue
        for kid, role in ku_roles(q):
            if role == "primary":
                primaries[kid].append(q)
            elif role == "secondary":
                secondaries[kid].append(q)
            # distractor_basis: zero credit by design (D2/R2)
    ku_map = {u.get("id"): u for u in units}
    ku_type = {u.get("id"): u.get("type", "") for u in units}
    per_ku, dist, overcap = {}, collections.Counter(), []
    cognitive_per_ku = {}
    purpose_counter = collections.Counter()
    has_unspecified_purposes = False
    has_explicit_cognitive = False
    section_counter = collections.Counter()
    for q in qs:
        if q.get("id") not in qualifying_ids:
            continue
        purp = q.get("purpose")
        if not purp or str(purp).strip() in ("", "unspecified"):
            has_unspecified_purposes = True
            purpose_counter["unspecified"] += 1
        else:
            purpose_counter[str(purp).strip()] += 1
        if q.get("cognitive_level"):
            has_explicit_cognitive = True

    has_explicit_purposes = (len(qualifying_ids) > 0 and not has_unspecified_purposes and len(purpose_counter) > 0)

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
        # cognitive coverage for this KU
        covered_forms = set()
        for q in ps:
            covered_forms |= q_cognitive_forms(q)
        req = required_forms(u)
        missing = sorted(req - covered_forms)
        cog_status = "covered" if not missing else ("partial" if covered_forms else "uncovered")
        cognitive_per_ku[kid] = {
            "tier": str(u.get("tier", "?")),
            "covered_forms": sorted(covered_forms),
            "required_forms": sorted(req),
            "missing_forms": missing,
            "status": cog_status,
        }
        per_ku[kid] = {
            "tier": str(u.get("tier", "?")),
            "type": ku_type.get(kid),
            "primary_count": len(ps),
            "secondary_count": len(ss),
            "question_ids": [q.get("id") for q in ps + ss],
            "primary_ids": [q.get("id") for q in ps],
            "purposes": sorted(list({q.get("purpose") for q in ps if q.get("purpose")})),
            "status": s,
            "cognitive": cognitive_per_ku[kid]
        }
        # section accounting
        src = u.get("source") or {}
        sp = src.get("section_path")
        if isinstance(sp, list):
            sec = (sp[0] if sp else "global") or "global"
        else:
            sec = sp or "global"
        section_counter[sec] += 1
    by_tier, tiers = {}, collections.defaultdict(list)
    for kid, e in per_ku.items():
        tiers[e["tier"]].append(kid)
    for t, kids in tiers.items():
        es = [per_ku[k] for k in kids]
        cov = sum(1 for e in es if e["status"] in ("covered", "repeatedly_tested"))
        uncov = [k for k in kids if per_ku[k]["status"] == "uncovered"]
        by_tier[t] = {
            "total": len(es),
            "covered": cov,
            "pct_covered": round(100 * cov / len(es), 2) if es else 100.0,
            "required_units": len(es),
            "covered_units": cov,
            "uncovered_units": uncov,
            "coverage_percent": round(100 * cov / len(es), 2) if es else 100.0,
        }
    # cognitive by tier: % of KUs whose required forms are fully covered
    cognitive_by_tier = {}
    for t, kids in tiers.items():
        tot = len(kids)
        full = sum(1 for k in kids if not cognitive_per_ku[k]["missing_forms"])
        cognitive_by_tier[t] = {
            "total": tot,
            "cognitively_covered": full,
            "pct": round(100 * full / tot, 2) if tot else 100.0,
            "missing": sorted([k for k in kids if cognitive_per_ku[k]["missing_forms"]])
        }
    # section coverage: questions per section via primary KU block
    # honest single labels: never invent one misleading percentage
    t1 = by_tier.get("1", {}).get("pct_covered", 100.0)
    t2 = by_tier.get("2", {}).get("pct_covered", 100.0)
    content_complete = (t1 == 100.0 and t2 == 100.0)
    cog_t1 = cognitive_by_tier.get("1", {}).get("pct", 100.0)
    cog_t2 = cognitive_by_tier.get("2", {}).get("pct", 100.0)
    coverage_label = "CONTENT COMPLETE" if content_complete else "CONTENT PARTIAL"
    cognitive_label = "COGNITIVE COVERAGE COMPLETE" if (cog_t1 == 100.0 and cog_t2 == 100.0) else "COGNITIVE COVERAGE PARTIAL"
    out = {
        "per_ku": per_ku,
        "by_tier": by_tier,
        "status_dist": dict(dist),
        "per_ku_cap": cap,
        "over_cap": overcap,
        "counted_questions": len(qualifying_ids),
        "qualifying_questions": len(qualifying_ids),
        "total_bank_questions": len(qs),
        "quality_filtered": qual_accepted is not None,
        "dedupe_filtered": len(dedupe_excluded) > 0,
        "cognitive_per_ku": cognitive_per_ku,
        "cognitive_by_tier": cognitive_by_tier,
        "purpose_coverage": dict(purpose_counter),
        "has_explicit_purposes": has_explicit_purposes,
        "has_unspecified_purposes": has_unspecified_purposes,
        "has_explicit_cognitive": has_explicit_cognitive,
        "section_coverage": dict(section_counter),
        "coverage_label": coverage_label,
        "cognitive_label": cognitive_label
    }
    dest = a.out if a.out.endswith(".json") else os.path.join(a.out, "coverage_matrix.json")
    save_json(dest, out)
    print("coverage: %s" % {k: {"covered": v["covered"], "total": v["total"], "pct": v["pct_covered"]} for k, v in by_tier.items()})
    print("coverage: cognitive=%s purposes=%s" % (
        {k: v["pct"] for k, v in cognitive_by_tier.items()}, dict(purpose_counter)))
    print("coverage: %s / %s" % (coverage_label, cognitive_label))
    print("coverage: dist=%s over_cap=%d -> %s" % (dict(dist), len(overcap), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
