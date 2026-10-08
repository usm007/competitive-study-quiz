import argparse
import collections
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, toks, fail, run_main


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("coverage")
    ap.add_argument("validation")
    ap.add_argument("anchors")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--struct", default=None)
    ap.add_argument("--ignored", default=None)
    ap.add_argument("--diff", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--quality", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    for p in (a.inventory, a.coverage, a.validation, a.anchors):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    inv = load_json(a.inventory)
    units = inv.get("units") if isinstance(inv, dict) else inv
    cov = load_json(a.coverage)
    val = load_json(a.validation)
    results = val.get("results") if isinstance(val, dict) else val
    anchors = load_json(a.anchors)
    struct = load_json(a.struct) if a.struct and os.path.isfile(a.struct) else {"blocks": [], "limitations": [], "extraction_status": "unknown"}
    prof = load_json(a.profile) if a.profile and os.path.isfile(a.profile) else {}
    cfg = load_json(a.config) if a.config and os.path.isfile(a.config) else {}
    ku_counts = dict(collections.Counter(str(u.get("tier", "?")) for u in units))
    ku_counts["total"] = len(units)
    per_ku = cov.get("per_ku", {})
    tier_of = {u.get("id"): str(u.get("tier", "?")) for u in units}
    uncovered = [k for k, e in per_ku.items() if e.get("status") == "uncovered"]
    partial = [k for k, e in per_ku.items() if e.get("status") == "partially_covered"]
    uncov_t1t2 = [k for k in uncovered if tier_of.get(k) in ("1", "2")]
    kut = {u.get("id"): norm("%s %s" % (u.get("statement", ""), u.get("supporting_excerpt", ""))) for u in units}
    ign = set()
    if a.ignored and os.path.isfile(a.ignored):
        o = load_json(a.ignored)
        items = o if isinstance(o, list) else o.get("anchors", o.get("items", []))
        ign = {x.get("anchor_id", norm(x.get("value", ""))) for x in items if isinstance(x, dict)}
    hit = sum(1 for an in anchors if any(norm(an.get("value", "")) and norm(an.get("value", "")) in t for t in kut.values()) or an.get("id") in ign)
    recall = hit / len(anchors) if anchors else 1.0
    dstatus = "resolved"
    for cand in ([a.diff] if a.diff else []) + [os.path.join(os.path.dirname(os.path.abspath(a.inventory)), "inventory_diff.json")]:
        if cand and os.path.isfile(cand):
            o = load_json(cand)
            items = o if isinstance(o, list) else o.get("diffs", o.get("queue", o.get("items", [])))
            if [x for x in items if isinstance(x, dict) and str(x.get("status", "")).lower() not in ("resolved", "closed", "done", "accepted")]:
                dstatus = "pending"
    bid_sec = {}
    for b in struct.get("blocks", []):
        bid_sec[b.get("id")] = ((b.get("section_path") or ["global"])[0]) or "global"
    qsec = collections.Counter()
    qsec_total = 0
    ku_block = {}
    for u in units:
        ku_block[u.get("id")] = (u.get("source") or {}).get("block_id")
    validated_qs = [r for r in results if r.get("status") == "validated"]
    valid_ids = {r["id"] for r in validated_qs}
    def find_bank():
        cands = []
        if a.bank and os.path.isfile(a.bank):
            cands.append(a.bank)
        cands.append(os.path.join(os.path.dirname(os.path.abspath(a.coverage)), "question_bank.json"))
        cands.append(os.path.join(os.path.dirname(os.path.abspath(a.validation)), "question_bank.json"))
        for cand in cands:
            if cand and os.path.isfile(cand):
                bobj = load_json(cand)
                return bobj.get("questions") if isinstance(bobj, dict) else bobj
        return []
    try:
        bqs = find_bank()
        if bqs:
            prim_ku = {}
            for q in bqs:
                if q.get("id") in valid_ids:
                    prim = None
                    for e in q.get("knowledge_units") or []:
                        if isinstance(e, dict) and e.get("role") == "primary":
                            prim = e.get("ku_id")
                            break
                    prim_ku[q.get("id")] = prim or q.get("primary_ku", q.get("primary"))
            for qid, kid in prim_ku.items():
                sec = bid_sec.get(ku_block.get(kid), "global")
                qsec[sec] += 1
                qsec_total += 1
    except Exception:
        pass
    shares = {s: round(n / qsec_total, 4) for s, n in qsec.items()} if qsec_total else {}
    cap = cfg.get("section_share_cap", 2.0)
    skew = []
    if shares:
        exp = 1 / len(shares)
        for s, sh in shares.items():
            if sh > exp * cap:
                skew.append({"section": s, "share": sh, "expected": round(exp, 4)})
    dup_flags = [r["id"] for r in results if r.get("checks", {}).get("duplicate_ok") is False]
    type_of = {}
    try:
        for q in find_bank():
            if q.get("id") in valid_ids:
                type_of[q.get("id")] = q.get("type", q.get("qtype", "unknown"))
    except Exception:
        pass
    mix = collections.Counter(type_of.values())
    tot = sum(mix.values()) or 1
    mix_pct = {k: round(100 * v / tot, 1) for k, v in mix.items()}
    target = prof.get("target_type_mix", {}) or {}
    weak = [k for k, v in target.items() if abs(mix_pct.get(k, 0) - v) > 15]
    nv = len(validated_qs)
    nt = len(results)
    downgrade = []
    for u in units:
        for h in u.get("tier_history") or []:
            if not isinstance(h, dict):
                downgrade.append({"ku_id": u.get("id"), "entry": h, "reason": None,
                                  "flag": "malformed tier_history entry"})
                continue
            fr, to, reason = h.get("from"), h.get("to"), h.get("reason")
            try:
                is_down = int(to) > int(fr)
            except (TypeError, ValueError):
                is_down = False
            if is_down and not reason:
                downgrade.append({"ku_id": u.get("id"), "from": fr, "to": to,
                                  "reason": None, "flag": "downgrade without reason"})
            elif is_down:
                downgrade.append({"ku_id": u.get("id"), "from": fr, "to": to,
                                  "reason": reason, "flag": "downgrade (reason given)"})
    sw, sk = {}, {}
    for bl in struct.get("blocks", []):
        sp = ((bl.get("section_path") or ["global"])[0]) or "global"
        sw[sp] = sw.get(sp, 0) + len(toks(bl.get("text") or ""))
    for u in units:
        src = u.get("source") or {}
        sp = (src.get("section_path") or [None])[0] if isinstance(src.get("section_path"), list) else None
        sp = sp or bid_sec.get(src.get("block_id"), "global")
        sk[sp] = sk.get(sp, 0) + 1
    rates = {s: sk.get(s, 0) / w * 1000 for s, w in sw.items() if w >= 50}
    dens = []
    if rates:
        fl = statistics.median(rates.values()) * 0.5
        dens = [{"section": s, "ku_per_1000w": round(r, 2), "floor": round(fl, 2)} for s, r in rates.items() if r < fl]
    lims = list(struct.get("limitations", []))
    if struct.get("extraction_status") not in ("ok",):
        lims.append("extraction_status=%s" % struct.get("extraction_status"))
    if not anchors:
        lims.append("no anchors extracted")
    # ---- competitive-engine extensions (backward compatible) ----
    cog_by_tier = cov.get("cognitive_by_tier", {}) or {}
    cog_per_ku = cov.get("cognitive_per_ku", {}) or {}
    purpose_cov = cov.get("purpose_coverage", {}) or {}
    # cognitive gaps: KUs with missing required forms
    cognitive_gaps = {}
    for kid, ce in cog_per_ku.items():
        if isinstance(ce, dict) and ce.get("missing_forms"):
            if tier_of.get(kid) in ("1", "2"):
                cognitive_gaps[kid] = ce.get("missing_forms")
    # distinction gaps: recall covered but distinction missing
    distinction_gaps = sorted([k for k, ce in cog_per_ku.items()
                               if isinstance(ce, dict) and "distinction" in (ce.get("missing_forms") or [])
                               and "recall" in (ce.get("covered_forms") or [])])
    # confusion clusters: group KUs by confusion_cluster or confusable_with links
    clusters = collections.defaultdict(list)
    for u in units:
        cc = u.get("confusion_cluster")
        if cc:
            clusters[str(cc)].append(u.get("id"))
        elif u.get("confusable_with"):
            key = "+".join(sorted([u.get("id")] + list(u.get("confusable_with") or []))[:4])
            clusters["link:" + key].append(u.get("id"))
    # cluster addressed? need >=1 validated question whose primaries span >=2 members
    # or whose distractors reference another member (best-effort via bank)
    cluster_status = {}
    try:
        bqs2 = find_bank()
        for cname, members in clusters.items():
            mset = set(members)
            addressed = False
            for q in (bqs2 or []):
                if q.get("id") not in valid_ids:
                    continue
                kus = [e.get("ku_id") for e in (q.get("knowledge_units") or []) if isinstance(e, dict)]
                opts_refs = [o.get("ku_ref") for o in (q.get("options") or []) if isinstance(o, dict) and o.get("ku_ref")]
                hit = (set(kus) & mset) | (set(opts_refs or []) & mset)
                prims = [e.get("ku_id") for e in (q.get("knowledge_units") or [])
                         if isinstance(e, dict) and e.get("role") == "primary"]
                if len(set(kus) & mset) >= 2 or (prims and any(r in mset for r in (opts_refs or []))):
                    addressed = True
                    break
            cluster_status[cname] = {"members": members, "addressed": addressed}
    except Exception:
        for cname, members in clusters.items():
            cluster_status[cname] = {"members": members, "addressed": False}
    unaddressed_clusters = sorted([k for k, v in cluster_status.items() if not v["addressed"]])
    # exam-purpose coverage vs profile required_purposes
    required_purposes = prof.get("required_purposes", []) or []
    missing_purposes = [p for p in required_purposes if not purpose_cov.get(p)]
    # Phase 3 Quality Stats
    qpath = a.quality
    if not qpath:
        for d in [os.path.dirname(os.path.abspath(a.validation)),
                  os.path.dirname(os.path.abspath(a.coverage)),
                  os.path.dirname(os.path.abspath(a.out))]:
            cand = os.path.join(d, "quality_report.json")
            if os.path.isfile(cand):
                qpath = cand
                break
    quality_stats = {}
    if qpath and os.path.isfile(qpath):
        qrep = load_json(qpath)
        qs_sum = qrep.get("summary", {})
        tot_gen = qs_sum.get("total", nt)
        quality_stats = {
            "generated": tot_gen,
            "validated": nv,
            "quality_accepted": qs_sum.get("quality_accepted", 0),
            "quality_rejected": qs_sum.get("quality_rejected", 0),
            "pct_quality_accepted": round(100.0 * qs_sum.get("quality_accepted", 0) / max(tot_gen, 1), 2),
            "quality_sample": qs_sum.get("grades", {}),
            "by_purpose": qs_sum.get("by_purpose", {}),
            "by_difficulty": qs_sum.get("by_difficulty", {}),
            "by_type": qs_sum.get("by_type", {}),
            "top_rejection_reasons": qs_sum.get("top_rejection_reasons", [])
        }

    # tier cognitive summary
    audit = {"ku_counts": ku_counts, "coverage_by_tier": cov.get("by_tier", {}), "status_dist": cov.get("status_dist", {}),
             "quality_stats": quality_stats,
             "uncovered_t1_t2": uncov_t1t2, "partial": partial, "section_shares": shares, "skew_flags": skew,
             "duplicate_flags": dup_flags, "weak_type_flags": weak, "anchor_recall": round(recall, 4),
             "diff_status": dstatus, "density_flags": dens,
             "downgrade_flags": downgrade,
             "validation_rates": {"total": nt, "validated": nv, "rejected": nt - nv, "pct_validated": round(100 * nv / nt, 2) if nt else 0.0},
             "type_mix_vs_target": {"actual_pct": mix_pct, "target": target}, "limitations": lims,
             "cognitive_by_tier": cog_by_tier, "cognitive_gaps": cognitive_gaps,
             "distinction_gaps": distinction_gaps,
             "purpose_coverage": purpose_cov, "missing_purposes": missing_purposes,
             "cluster_status": cluster_status, "unaddressed_clusters": unaddressed_clusters,
             "section_coverage": cov.get("section_coverage", {}),
             "has_explicit_purposes": cov.get("has_explicit_purposes", False),
             "coverage_label": cov.get("coverage_label", ""), "cognitive_label": cov.get("cognitive_label", "")}
    dest = a.out if a.out.endswith(".json") else os.path.join(a.out, "audit_report.json")
    save_json(dest, audit)
    print("audit: T1/T2 uncovered=%d partial=%d recall=%.2f%% val=%d/%d cog_gaps=%d purposes=%s -> %s" % (len(uncov_t1t2), len(partial), recall * 100, nv, nt, len(cognitive_gaps), dict(purpose_cov), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
