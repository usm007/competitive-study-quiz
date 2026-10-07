import argparse
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir, run_main

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = ("ingest", "anchors", "check", "validate", "coverage", "dedupe", "audit", "gate", "report")


def mod(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_stage(fn, argv):
    try:
        return fn(argv)
    except SystemExit as e:
        return int(e.code or 0)


def schema_each(path, key, schema_path, label):
    vs = mod("validate_schema")
    try:
        doc = load_json(path)
        sch = load_json(schema_path)
    except Exception as e:
        print("schema %s: load failed: %s" % (label, e))
        return 1
    items = doc.get(key) if isinstance(doc, dict) else doc
    errs = []
    for i, it in enumerate(items or []):
        vs.check(it, sch, "%s[%d]" % (label, i), errs)
    if errs:
        print("schema %s: FAIL %d errors" % (label, len(errs)))
        for e in errs[:10]:
            print("  " + e)
        return 1
    print("schema %s: OK %d items" % (label, len(items or [])))
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--build-dir", default="build")
    ap.add_argument("--redo", default=None)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--ignored", default=None)
    ap.add_argument("--diff", default=None)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.source):
        print("error: source not found: %s" % a.source, file=sys.stderr)
        return 1
    for p, n in ((a.profile, "profile"), (a.config, "config")):
        if not os.path.isfile(p):
            print("error: %s not found: %s" % (n, p), file=sys.stderr)
            return 1
    if a.inventory and not os.path.isfile(a.inventory):
        print("error: inventory not found: %s" % a.inventory, file=sys.stderr)
        return 1
    if a.bank and not os.path.isfile(a.bank):
        print("error: bank not found: %s" % a.bank, file=sys.stderr)
        return 1
    R = a.run_id if os.path.basename(os.path.normpath(a.build_dir)) == a.run_id else os.path.join(a.build_dir, a.run_id)
    ensure_dir(R)
    cfg = load_json(a.config)
    mode = a.mode or cfg.get("fidelity_mode", "SOURCE_BOUND")
    F = {"struct": os.path.join(R, "document_structure.json"),
         "anchors": os.path.join(R, "anchors.json"),
         "check": os.path.join(R, "inventory_check.json"),
         "validation": os.path.join(R, "validation_results.json"),
         "coverage": os.path.join(R, "coverage_matrix.json"),
         "dedupe": os.path.join(R, "dedupe_report.json"),
         "audit": os.path.join(R, "audit_report.json"),
         "gate": os.path.join(R, "gate.json")}
    sp = os.path.join(R, "pipeline_state.json")
    state = load_json(sp) if os.path.isfile(sp) else {"run_id": a.run_id, "stages": {}}
    redo = (a.redo or "").lower()

    def skip(stage, outs):
        return bool(redo not in ("all", stage)) and all(os.path.isfile(o) for o in outs)

    def mark(stage, status, detail=""):
        state["stages"][stage] = {"status": status, "detail": detail}
        save_json(sp, state)

    if skip("ingest", [F["struct"]]):
        mark("ingest", "skipped", "output exists")
    else:
        rc = run_stage(mod("ingest").main, [a.source, "--out", R, "--run-id", a.run_id])
        mark("ingest", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    if skip("anchors", [F["anchors"]]):
        mark("anchors", "skipped", "output exists")
    else:
        rc = run_stage(mod("anchors").main, [F["struct"], "--out", F["anchors"]])
        mark("anchors", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    schdir = os.path.join(os.path.dirname(HERE), "schemas")
    sstruct = os.path.join(schdir, "document_structure.schema.json")
    if os.path.isfile(sstruct):
        rc = run_stage(mod("validate_schema").main, [F["struct"], "--schema", sstruct])
        mark("validate_struct", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    else:
        mark("validate_struct", "skipped", "no schema file")
    sku = os.path.join(schdir, "knowledge-unit.schema.json")
    sq = os.path.join(schdir, "question.schema.json")
    if not a.inventory:
        mark("check", "pending", "no --inventory (LLM step)")
        mark("validate", "pending", "needs inventory")
        mark("coverage", "pending", "needs inventory/bank")
        mark("dedupe", "pending" if not a.bank else "ready", "")
        if a.bank and skip("dedupe", [F["dedupe"]]):
            mark("dedupe", "skipped", "output exists")
        elif a.bank:
            rc = run_stage(mod("dedupe").main, [a.bank, "--threshold", str(cfg.get("duplicate_threshold", 0.85)), "--out", F["dedupe"]])
            mark("dedupe", "ok" if rc == 0 else "failed")
        mark("audit", "pending", "needs inventory")
        mark("gate", "pending", "needs audit")
        mark("report", "pending", "needs audit/gate")
        save_json(sp, state)
        print("pipeline %s: deterministic stages done; inventory/bank pending (LLM steps)" % a.run_id)
        return 0
    if skip("check", [F["check"]]):
        mark("check", "skipped", "output exists")
    else:
        args = [a.inventory, F["struct"], "--anchors", F["anchors"], "--config", a.config, "--out", F["check"]]
        if a.ignored:
            args += ["--ignored", a.ignored]
        if a.diff:
            args += ["--diff", a.diff]
        rc = run_stage(mod("inventory_check").main, args)
        mark("check", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    if os.path.isfile(sku):
        rc = schema_each(a.inventory, "units", sku, "knowledge-unit")
        mark("schema_inventory", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    else:
        mark("schema_inventory", "skipped", "no schema file")
    if not a.bank:
        for s in ("validate", "coverage", "dedupe", "audit", "gate", "report"):
            mark(s, "pending", "no --bank (LLM step)")
        save_json(sp, state)
        print("pipeline %s: check done; question bank pending (LLM step)" % a.run_id)
        return 0
    if skip("validate", [F["validation"]]):
        mark("validate", "skipped", "output exists")
    else:
        rc = run_stage(mod("validate_questions").main, [a.bank, a.inventory, F["struct"], "--profile", a.profile, "--mode", mode, "--config", a.config, "--out", F["validation"]])
        mark("validate", "ok" if rc == 0 else "failed")
        if rc:
            print("pipeline %s: validation rejected questions; fix bank or rerun with --redo validate" % a.run_id)
            return rc
    if os.path.isfile(sq):
        rc = schema_each(a.bank, "questions", sq, "question")
        mark("schema_bank", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    else:
        mark("schema_bank", "skipped", "no schema file")
    if skip("coverage", [F["coverage"]]):
        mark("coverage", "skipped", "output exists")
    else:
        rc = run_stage(mod("coverage").main, [a.bank, a.inventory, F["validation"], "--out", F["coverage"], "--config", a.config])
        mark("coverage", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    if skip("dedupe", [F["dedupe"]]):
        mark("dedupe", "skipped", "output exists")
    else:
        rc = run_stage(mod("dedupe").main, [a.bank, "--threshold", str(cfg.get("duplicate_threshold", 0.85)), "--out", F["dedupe"]])
        mark("dedupe", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    if skip("audit", [F["audit"]]):
        mark("audit", "skipped", "output exists")
    else:
        args = [a.inventory, F["coverage"], F["validation"], F["anchors"], "--profile", a.profile, "--config", a.config, "--struct", F["struct"], "--out", F["audit"]]
        if a.bank:
            args += ["--bank", a.bank]
        if a.ignored:
            args += ["--ignored", a.ignored]
        if a.diff:
            args += ["--diff", a.diff]
        rc = run_stage(mod("audit").main, args)
        mark("audit", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    if skip("gate", [F["gate"]]):
        mark("gate", "skipped", "output exists")
    else:
        rc = run_stage(mod("gate").main, [F["audit"], "--config", a.config])
        mark("gate", "ok" if rc == 0 else "failed")
        if rc:
            return rc
    rc = run_stage(mod("report").main, [F["audit"], F["gate"]] + ([a.bank] if a.bank else []))
    mark("report", "ok" if rc == 0 else "failed")
    if a.count is not None:
        state["requested_count"] = a.count
    save_json(sp, state)
    print("pipeline %s: done -> %s" % (a.run_id, R))
    return rc


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
