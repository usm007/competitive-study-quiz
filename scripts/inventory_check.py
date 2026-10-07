import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, norm, toks, fail, run_main

SPEC_REASONS = {"boilerplate", "bibliography", "page_furniture", "decorative"}
LEGACY_REASONS = {"out_of_scope", "duplicate", "unverifiable", "non_examinable",
                  "table_header", "formatting_artifact"}


def reason_ok(r):
    if r in SPEC_REASONS or r in LEGACY_REASONS:
        return True
    return r.startswith("duplicate_of:") or r.startswith("non_examinable:")


def load_list(path):
    if not path or not os.path.isfile(path):
        return []
    o = load_json(path)
    return o if isinstance(o, list) else o.get("anchors", o.get("diffs", o.get("queue", o.get("items", []))))


def diff_status_of(path):
    if not path or not os.path.isfile(path):
        d = os.path.join(os.path.dirname(os.path.abspath(path or "x")), "inventory_diff.json")
        path = d if os.path.isfile(d) else None
    if not path or not os.path.isfile(path):
        return "resolved", "no diff file; treated as empty"
    o = load_json(path)
    items = o if isinstance(o, list) else o.get("diffs", o.get("queue", o.get("items", [])))
    open_items = [x for x in items if isinstance(x, dict) and str(x.get("status", "")).lower() not in ("resolved", "closed", "done", "accepted")]
    if isinstance(o, dict) and not items and not open_items:
        return "resolved", "diff queue empty"
    if open_items:
        return "pending", "%d unresolved diff items" % len(open_items)
    return "resolved", "all diff items resolved"


def compute(inv_units, struct, anchors, ignored, threshold):
    ku_text = {}
    for u in inv_units:
        ku_text[u.get("id")] = norm("%s %s" % (u.get("statement", ""), u.get("supporting_excerpt", "")))
    ign = {}
    for e in ignored:
        if isinstance(e, dict):
            if e.get("anchor_id"):
                ign[e["anchor_id"]] = e.get("reason", "")
            elif e.get("value"):
                ign[norm(e.get("value"))] = e.get("reason", "")
    covered, uncovered = 0, []
    for an in anchors:
        aid = an.get("id", "")
        v = norm(an.get("value", ""))
        hit = any(v and v in t for t in ku_text.values())
        if not hit:
            r = ign.get(aid, ign.get(v, ""))
            if reason_ok(r):
                hit = True
        if hit:
            covered += 1
        else:
            uncovered.append(aid)
    total = len(anchors)
    recall = (covered / total) if total else 1.0
    sec_words, sec_ku = {}, {}
    for b in struct.get("blocks", []):
        sp = (b.get("section_path") or ["global"])[0] or "global"
        sec_words[sp] = sec_words.get(sp, 0) + len(toks(b.get("text") or ""))
    bid_sec = {}
    for b in struct.get("blocks", []):
        bid_sec[b.get("id")] = ((b.get("section_path") or ["global"])[0]) or "global"
    for u in inv_units:
        src = u.get("source") or {}
        sp = (src.get("section_path") or [None])[0] if isinstance(src.get("section_path"), list) else None
        sp = sp or bid_sec.get(src.get("block_id"), "global")
        sec_ku[sp] = sec_ku.get(sp, 0) + 1
    rates = {}
    for sp, w in sec_words.items():
        if w >= 50:
            rates[sp] = sec_ku.get(sp, 0) / w * 1000
    # ponytail: median-floor density is noisy on tiny/uneven sections; split sections if flags look wrong
    flags = []
    if rates:
        floor = statistics.median(rates.values()) * 0.5
        for sp, r in sorted(rates.items()):
            if r < floor:
                flags.append({"section": sp, "ku_per_1000w": round(r, 2), "floor": round(floor, 2)})
    return {"covered": covered, "total": total, "recall": recall, "threshold": threshold,
            "uncovered_ids": uncovered, "density_flags": flags, "rates": {k: round(v, 2) for k, v in rates.items()}}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("struct")
    ap.add_argument("--anchors", default=None)
    ap.add_argument("--ignored", default=None)
    ap.add_argument("--diff", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    for p in (a.inventory, a.struct):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    inv = load_json(a.inventory)
    units = inv.get("units") if isinstance(inv, dict) else inv
    if not isinstance(units, list):
        fail("inventory has no units list")
    struct = load_json(a.struct)
    anchors = load_list(a.anchors) if a.anchors else []
    if a.anchors and not os.path.isfile(a.anchors):
        fail("anchors file not found: %s" % a.anchors)
    ignored = load_list(a.ignored) if a.ignored else []
    thr = a.threshold
    if thr is None and a.config and os.path.isfile(a.config):
        try:
            v = load_json(a.config).get("anchor_recall_threshold", 1.0)
            thr = (v / 100.0) if v > 1 else float(v)
        except Exception:
            thr = 1.0
    if thr is None:
        thr = 1.0
    r = compute(units, struct, anchors, ignored, thr)
    dstatus, dnote = diff_status_of(a.diff)
    ok = r["recall"] >= thr and not r["density_flags"] and dstatus == "resolved"
    res = {"anchor_recall": {"covered": r["covered"], "total": r["total"], "rate": round(r["recall"], 4), "threshold": thr, "uncovered_ids": r["uncovered_ids"]},
           "density": {"rates": r["rates"], "flags": r["density_flags"]},
           "diff": {"status": dstatus, "note": dnote}, "status": "PASS" if ok else "FAIL"}
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.struct)), "inventory_check.json")
    save_json(dest, res)
    print("ANCHOR RECALL: %d/%d = %.2f%% (threshold %.2f%%)" % (r["covered"], r["total"], r["recall"] * 100, thr * 100))
    print("DENSITY: %d sections below floor" % len(r["density_flags"]))
    for f in r["density_flags"]:
        print("  below floor: %s (%.2f < %.2f ku/1000w)" % (f["section"], f["ku_per_1000w"], f["floor"]))
    print("DIFF: %s (%s)" % (dstatus, dnote))
    print("RESULT: %s" % res["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
