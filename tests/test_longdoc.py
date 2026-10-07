"""Phase 1 tests: long-document quality validation on the synthetic
117-page Kamarupa fixture (tests/fixtures/longdoc/).

Covers: ingest scale, inventory recall vs the manifest, atomization,
table/list preservation, section balance, intentional gap detection,
cognitive gap detection, gap-fill targeting, duplicates, invalid-question
rejection, provenance, checkpoint/resume, failure recovery, large-bank
rendering, and the full APSC end-to-end acceptance run.

Runnable via `python tests/run_all.py` (unittest discover).
"""
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
FIX = HERE / "fixtures" / "longdoc"
PY = sys.executable

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import anchors as anchors_mod
import coverage as covmod
import gate as gatemod
from lib_common import load_json, norm
from lib_common import token_set_sim


def run(*args):
    return subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                          text=True, cwd=str(ROOT), timeout=900)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def jload(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# One cached ingest of the longdoc source for all struct-dependent tests.
_STRUCT_DIR = None
_STRUCT = None


def struct():
    global _STRUCT_DIR, _STRUCT
    if _STRUCT is None:
        _STRUCT_DIR = tempfile.mkdtemp(prefix="longdoc_struct_")
        r = run("scripts/ingest.py", str(FIX / "longdoc_source.md"),
                "--out", _STRUCT_DIR, "--run-id", "s")
        assert r.returncode == 0, r.stdout + r.stderr
        _STRUCT = jload(Path(_STRUCT_DIR) / "s" / "document_structure.json")
    return _STRUCT


def inventory():
    return jload(FIX / "inventory.json")


def manifest():
    return jload(FIX / "manifest.json")


def run_chain(tmp, bank_name):
    """validate -> coverage -> audit -> gate for a fixture bank in tmp."""
    tmp = Path(tmp)
    bank = str(FIX / bank_name)
    inv = str(FIX / "inventory.json")
    st = tmp / "struct.json"
    shutil.copyfile(struct_path(), st)
    std = jload(st)
    with open(tmp / "anchors.json", "w", encoding="utf-8") as fh:
        json.dump(anchors_mod.extract(std["blocks"]), fh)
    vr = tmp / "validation.json"
    r = run("scripts/validate_questions.py", bank, inv, str(st),
            "--profile", "profiles/APSC_PRELIMS.json", "--mode", "SOURCE_BOUND",
            "--config", "config.default.json", "--out", str(vr))
    cov = tmp / "coverage.json"
    r2 = run("scripts/coverage.py", bank, inv, str(vr),
             "--out", str(cov), "--config", "config.default.json")
    au = tmp / "audit.json"
    r3 = run("scripts/audit.py", inv, str(cov), str(vr),
             str(tmp / "anchors.json"), "--profile", "profiles/APSC_PRELIMS.json",
             "--config", "config.default.json", "--struct", str(st),
             "--ignored", str(FIX / "ignored_anchors.json"),
             "--diff", str(FIX / "inventory_diff.json"),
             "--bank", bank, "--out", str(au))
    return r, r2, r3, vr, cov, au


def struct_path():
    s = struct()
    p = Path(_STRUCT_DIR) / "s" / "document_structure.json"
    assert p.is_file()
    return p


class TestLongdocIngest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = struct()
        cls.anchors = anchors_mod.extract(cls.st["blocks"])

    def test_hundred_plus_pages(self):
        pages = max(b["page"] for b in self.st["blocks"])
        self.assertGreaterEqual(pages, 100, "fixture must be ~100+ pages, got %d" % pages)

    def test_block_volume(self):
        self.assertGreaterEqual(len(self.st["blocks"]), 1000)

    def test_status_clean(self):
        self.assertEqual(self.st["extraction_status"], "ok")
        self.assertEqual(self.st["limitations"], [])

    def test_headings_sections_tables_lists(self):
        kinds = collections.Counter(b["kind"] for b in self.st["blocks"])
        self.assertGreaterEqual(kinds.get("table", 0), 5)
        self.assertGreaterEqual(kinds.get("list_item", 0), 30)
        self.assertGreaterEqual(kinds.get("heading", 0), 10)
        tops = {tuple(b.get("section_path")[:1]) for b in self.st["blocks"] if b.get("section_path")}
        self.assertGreaterEqual(len(tops), 8)

    def test_anchors_present(self):
        kinds = collections.Counter(a["kind"] for a in self.anchors)
        self.assertGreater(len(self.anchors), 200)
        for k in ("date", "number", "table_cell"):
            self.assertIn(k, kinds)


class TestInventoryRecall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = inventory()
        cls.man = manifest()
        cls.st = struct()
        cls.ntext = norm(cls.st["normalized_text"])
        cls.by_excerpt = {u["supporting_excerpt"]: u for u in cls.inv["units"]}

    def test_every_manifest_fact_has_ku(self):
        missing = [m["fact_id"] for m in self.man
                   if m["excerpt"] not in self.by_excerpt]
        self.assertEqual(missing, [])

    def test_excerpts_verbatim_and_located(self):
        for m in self.man:
            u = self.by_excerpt[m["excerpt"]]
            self.assertIn(norm(m["excerpt"]), self.ntext, m["fact_id"])
            self.assertEqual(u["id"], m["ku_id"])
            self.assertEqual(u["type"], m["ku_type"])
            self.assertEqual(u["tier"], m["tier"])
            blk = next(b for b in self.st["blocks"] if b["id"] == m["block_id"])
            self.assertIn(m["excerpt"], blk["text"], m["fact_id"])

    def test_trap_families_all_covered(self):
        traps = collections.Counter(m["trap"] for m in self.man)
        for t in ("buried_paragraph", "long_list_item", "table_cell",
                  "split_distinction", "footnote_exception", "compound_sentence",
                  "distributed_chronology", "confusable_pair", "repeated_detail",
                  "post_padding"):
            self.assertGreaterEqual(traps.get(t, 0), 1, "trap family missing: %s" % t)

    def test_table_cells_verbatim_rows(self):
        rows = [m for m in self.man if m["trap"] == "table_cell"]
        self.assertGreaterEqual(len(rows), 20)
        for m in rows:
            self.assertIn("|", m["excerpt"])

    def test_list_items_marked(self):
        items = [m for m in self.man if m["trap"] == "long_list_item"]
        self.assertGreaterEqual(len(items), 10)
        for m in items:
            self.assertTrue(m["excerpt"].startswith("- "), m["fact_id"])

    def test_footnote_facts_in_footnote_blocks(self):
        notes = [m for m in self.man if m["trap"] == "footnote_exception"]
        self.assertGreaterEqual(len(notes), 3)
        for m in notes:
            blk = next(b for b in self.st["blocks"] if b["id"] == m["block_id"])
            self.assertTrue(blk["text"].startswith("A note on exceptions"), m["fact_id"])

    def test_no_anchor_left_unexplained(self):
        ku_texts = [norm(u["statement"] + " " + u["supporting_excerpt"])
                    for u in self.inv["units"]]
        ignored = {(x.get("anchor_id"), norm(x.get("value", "")))
                   for x in jload(FIX / "ignored_anchors.json")}
        bad = []
        for an in anchors_mod.extract(self.st["blocks"]):
            v = norm(an.get("value", ""))
            if not v:
                continue
            if any(v and v in t for t in ku_texts):
                continue
            if (an.get("id"), v) in ignored or v in {i[1] for i in ignored}:
                continue
            bad.append((an["id"], an["kind"], v[:60]))
        self.assertEqual(bad, [])


class TestAtomization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = inventory()
        cls.man = manifest()

    def test_compound_sentence_yields_three_kus(self):
        comp = [m for m in self.man if m["trap"] == "compound_sentence"]
        by_block = collections.defaultdict(list)
        for m in comp:
            by_block[m["block_id"]].append(m["ku_id"])
        multi = [v for v in by_block.values() if len(v) >= 3]
        self.assertTrue(multi, "no block atomized into 3+ KUs")

    def test_kus_are_atomic(self):
        # a KU statement must not smuggle two manifest facts
        man_texts = [m["excerpt"] for m in self.man]
        for u in self.inv["units"]:
            hits = sum(1 for t in man_texts
                       if norm(t) and norm(t) in norm(u["statement"] + " " + u["supporting_excerpt"])
                       and t != u["supporting_excerpt"])
            # the KU's own fact excluded; allow at most its own single fact
            self.assertLessEqual(hits, 1, u["id"])

    def test_tributary_list_items_individual(self):
        tribs = [u for u in self.inv["units"] if u["subtopic"] == "tributaries"]
        self.assertGreaterEqual(len(tribs), 9)
        self.assertTrue(all(u["type"] == "list_item" for u in tribs))


class TestSectionBalance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_balance_"))
        shutil.copyfile(struct_path(), cls.tmp / "struct.json")
        std = jload(cls.tmp / "struct.json")
        with open(cls.tmp / "anchors.json", "w", encoding="utf-8") as fh:
            json.dump(anchors_mod.extract(std["blocks"]), fh)
        r = run("scripts/inventory_check.py", str(FIX / "inventory.json"),
                str(cls.tmp / "struct.json"), "--anchors",
                str(cls.tmp / "anchors.json"), "--config", "config.default.json",
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json"),
                "--out", str(cls.tmp / "check.json"))
        cls.check = jload(cls.tmp / "check.json")
        cls.rc = r.returncode

    def test_inventory_check_passes(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.check["status"], "PASS")
        self.assertEqual(self.check["density"]["flags"], [])

    def test_short_dense_sections_not_ignored(self):
        inv = inventory()
        by_sec = collections.defaultdict(list)
        for u in inv["units"]:
            sp = (u.get("source") or {}).get("section_path") or ["?"]
            by_sec[sp[0]].append(u)
        self.assertGreaterEqual(len(by_sec), 8)
        words = collections.Counter()
        for b in struct()["blocks"]:
            sp = (b.get("section_path") or ["?"])[0]
            if sp in by_sec:
                words[sp] += len((b.get("text") or "").split())
        shortest = min(words, key=words.get)
        t12 = [u for u in by_sec[shortest] if u["tier"] in (1, 2)]
        self.assertGreater(len(t12), 0, "shortest section has no T1/T2 KUs")

    def test_full_bank_section_coverage(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_seccov_"))
        r, r2, r3, vr, cov, au = run_chain(tmp, "question_bank.json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        covd = jload(cov)
        inv = inventory()
        tier_sec = collections.defaultdict(lambda: collections.defaultdict(int))
        covered = {k for k, e in covd["per_ku"].items()
                   if e["status"] in ("covered", "repeatedly_tested")}
        for u in inv["units"]:
            sp = ((u.get("source") or {}).get("section_path") or ["?"])[0]
            if u["id"] in covered and u["tier"] in (1, 2):
                tier_sec[sp][u["tier"]] += 1
        for sec, counts in tier_sec.items():
            total = sum(1 for u in inv["units"]
                        if ((u.get("source") or {}).get("section_path") or ["?"])[0] == sec
                        and u["tier"] in (1, 2))
            self.assertEqual(counts[1] + counts[2], total, sec)
        aud = jload(au)
        self.assertEqual(aud["skew_flags"], [])


class TestGapDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_gap_"))
        cls.r, cls.r2, cls.r3, cls.vr, cls.cov, cls.au = run_chain(
            cls.tmp, "question_bank_round1.json")
        cls.covd = jload(cls.cov)
        cls.aud = jload(cls.au)
        adds = jload(FIX / "gap_additions.json")["questions"]
        cls.added_primaries = {e["ku_id"] for q in adds for e in q["knowledge_units"]
                               if e["role"] == "primary"}

    def test_round1_partial(self):
        self.assertEqual(self.r.returncode, 0)
        g = gatemod.decide(self.aud, 1.0)
        self.assertEqual(g[0], "PARTIAL")

    def test_dropped_kus_have_no_primary(self):
        for ku in ("KU-0043", "KU-0082", "KU-0001", "KU-0087",
                   "KU-0108", "KU-0127", "KU-0071"):
            e = self.covd["per_ku"].get(ku)
            if e is not None:
                self.assertEqual(e["primary_count"], 0, ku)

    def test_audit_names_exact_content_gaps(self):
        flagged = set(self.aud["uncovered_t1_t2"]) | set(self.aud["partial"])
        for ku in ("KU-0043", "KU-0082", "KU-0001", "KU-0087",
                   "KU-0108", "KU-0127", "KU-0071"):
            if ku in self.covd["per_ku"]:
                self.assertIn(ku, flagged, ku)

    def test_cognitive_gap_points_at_stripped_forms(self):
        self.assertTrue(self.aud["cognitive_gaps"])
        self.assertTrue(self.aud["distinction_gaps"])
        for ku in self.aud["distinction_gaps"]:
            e = self.covd["per_ku"][ku]
            self.assertIn("recall", e["cognitive"]["covered_forms"], ku)


class TestGapFillTargeting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_gapfill_"))
        cls.r, cls.r2, cls.r3, cls.vr, cls.cov, cls.au = run_chain(
            cls.tmp, "question_bank_round1.json")
        cls.covd = jload(cls.cov)
        cls.aud = jload(cls.au)
        cls.adds = jload(FIX / "gap_additions.json")["questions"]

    def _missing(self):
        need = {}
        for ku, forms in self.aud["cognitive_gaps"].items():
            need.setdefault(ku, set()).update(forms)
        for ku in self.aud["uncovered_t1_t2"]:
            need.setdefault(ku, set()).add("content")
        return need

    def _real_forms(self, forms):
        return set(forms) & {"recall", "distinction", "statement", "application"}

    def test_additions_target_only_missing_kus(self):
        need = self._missing()
        for q in self.adds:
            prims = [e["ku_id"] for e in q["knowledge_units"] if e["role"] == "primary"]
            self.assertTrue(prims)
            for p in prims:
                self.assertIn(p, need, "gap-fill strays to %s (%s)" % (p, q["id"]))

    def test_additions_cover_missing_forms_not_recall_again(self):
        from collections import defaultdict
        got = defaultdict(set)
        for q in self.adds:
            for e in q["knowledge_units"]:
                if e["role"] == "primary":
                    got[e["ku_id"]] |= covmod.q_cognitive_forms(q)
        need = self._missing()
        inv = {u["id"]: u for u in inventory()["units"]}
        for ku, forms in need.items():
            real = self._real_forms(forms)
            if not real:
                self.assertTrue(got.get(ku), ku)
            else:
                self.assertTrue(real <= got.get(ku, set()),
                                "%s needs %s got %s" % (ku, real, got.get(ku)))
        # dropped KUs must regain their FULL required forms, not just recall
        for ku in ("KU-0043", "KU-0082", "KU-0001", "KU-0087",
                   "KU-0108", "KU-0127", "KU-0071"):
            if ku in inv:
                req = covmod.required_forms(inv[ku])
                self.assertTrue(req <= got.get(ku, set()), (ku, req))

    def test_full_bank_closes_everything(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_close_"))
        r, r2, r3, vr, cov, au = run_chain(tmp, "question_bank.json")
        aud = jload(au)
        self.assertEqual(aud["uncovered_t1_t2"], [])
        self.assertEqual(aud["cognitive_gaps"], {})
        self.assertEqual(gatemod.decide(aud, 1.0)[0], "COMPREHENSIVE")


class TestDuplicates(unittest.TestCase):
    def test_planted_clones_flagged_same_ku_pairs_not(self):
        bank = jload(FIX / "question_bank_dup.json")["questions"]
        pairs = set()
        seen = []
        for q in bank:
            blob = (q.get("stem") or "") + " " + " ".join(
                o.get("text", "") for o in q["options"])
            for oid, ob in seen:
                if token_set_sim(blob, ob) >= 0.85:
                    pairs.add(tuple(sorted((q["id"], oid))))
            seen.append((q["id"], blob))
        self.assertIn(tuple(sorted(("Q-DUP-01", bank[0]["id"]))), pairs)
        self.assertIn(tuple(sorted(("Q-DUP-02", bank[2]["id"]))), pairs)
        self.assertEqual(len(pairs), 2)
        outdir = Path(tempfile.mkdtemp(prefix="longdoc_dedupe_"))
        r = run("scripts/dedupe.py", str(FIX / "question_bank_dup.json"),
                "--out", str(outdir / "d.json"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(jload(outdir / "d.json")["count"], 2)


class TestInvalidRejection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_invalid_"))
        shutil.copyfile(struct_path(), cls.tmp / "struct.json")
        cls.bank = jload(FIX / "question_bank_invalid.json")
        r = run("scripts/validate_questions.py", str(FIX / "question_bank_invalid.json"),
                str(FIX / "inventory.json"), str(cls.tmp / "struct.json"),
                "--profile", "profiles/APSC_PRELIMS.json", "--mode", "SOURCE_BOUND",
                "--config", "config.default.json", "--out", str(cls.tmp / "v.json"))
        cls.rc = r.returncode
        cls.res = {x["id"]: x for x in jload(cls.tmp / "v.json")["results"]}

    def test_rejects_all_ten(self):
        self.assertNotEqual(self.rc, 0)
        expected = set(self.bank["expected_rejected"])
        rejected = {i for i, x in self.res.items() if x["status"] == "rejected"}
        self.assertEqual(rejected, expected)

    def test_each_failure_has_notes(self):
        for i in self.bank["expected_rejected"]:
            self.assertTrue(self.res[i]["notes"], i)

    def test_controls_validate(self):
        for q in self.bank["questions"]:
            if q["id"] not in self.bank["expected_rejected"]:
                self.assertEqual(self.res[q["id"]]["status"], "validated", q["id"])

    def test_rejected_contribute_no_coverage(self):
        r = run("scripts/coverage.py", str(FIX / "question_bank_invalid.json"),
                str(FIX / "inventory.json"), str(self.tmp / "v.json"),
                "--out", str(self.tmp / "cov.json"), "--config", "config.default.json")
        self.assertEqual(r.returncode, 0)
        covd = jload(self.tmp / "cov.json")
        rej = {i for i, x in self.res.items() if x["status"] == "rejected"}
        for ku, e in covd["per_ku"].items():
            for qid in e["question_ids"]:
                self.assertNotIn(qid, rej)


class TestProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_prov_"))
        shutil.copyfile(struct_path(), cls.tmp / "struct.json")
        r = run("scripts/validate_questions.py", str(FIX / "question_bank.json"),
                str(FIX / "inventory.json"), str(cls.tmp / "struct.json"),
                "--profile", "profiles/APSC_PRELIMS.json", "--mode", "SOURCE_BOUND",
                "--config", "config.default.json", "--out", str(cls.tmp / "v.json"))
        assert r.returncode == 0
        cls.st = jload(cls.tmp / "struct.json")
        cls.ntext = norm(cls.st["normalized_text"])
        cls.inv = {u["id"]: u for u in inventory()["units"]}
        cls.blocks = {b["id"] for b in cls.st["blocks"]}
        cls.bank = jload(FIX / "question_bank.json")["questions"]
        cls.valid = {x["id"] for x in jload(cls.tmp / "v.json")["results"]
                     if x["status"] == "validated"}

    def test_full_chain_per_question(self):
        self.assertEqual(len(self.valid), len(self.bank))
        for q in self.bank:
            self.assertIn(q["id"], self.valid)
            for e in q["knowledge_units"]:
                ku = self.inv.get(e["ku_id"])
                self.assertIsNotNone(ku, (q["id"], e["ku_id"]))
                self.assertIn(norm(ku["supporting_excerpt"]), self.ntext, e["ku_id"])
            for s in q.get("source") or []:
                self.assertIn(s["block_id"], self.blocks, q["id"])
            exc = q.get("supporting_excerpt") or ""
            if exc:
                self.assertIn(norm(exc), self.ntext, q["id"])


class TestResume(unittest.TestCase):
    def test_pipeline_resume_and_redo(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_resume_"))
        base = ["scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(FIX / "inventory.json"),
                "--bank", str(FIX / "question_bank.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json")]
        r1 = run(*base)
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        r2 = run(*base)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        state = jload(tmp / "r" / "pipeline_state.json")
        self.assertEqual(state["stages"]["ingest"]["status"], "skipped")
        self.assertEqual(state["stages"]["anchors"]["status"], "skipped")
        r3 = run(*base, "--redo", "validate")
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        state3 = jload(tmp / "r" / "pipeline_state.json")
        self.assertEqual(state3["stages"]["validate"]["status"], "ok")


class TestFailureRecovery(unittest.TestCase):
    def test_malformed_inventory_fails(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_fail1_"))
        bad = tmp / "bad_inv.json"
        bad.write_text("{not json", encoding="utf-8")
        r = run("scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(bad), "--bank", str(FIX / "question_bank.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json"))
        self.assertNotEqual(r.returncode, 0)

    def test_unresolved_diff_blocks(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_fail2_"))
        shutil.copyfile(struct_path(), tmp / "struct.json")
        std = jload(tmp / "struct.json")
        with open(tmp / "anchors.json", "w", encoding="utf-8") as fh:
            json.dump(anchors_mod.extract(std["blocks"]), fh)
        pend = {"pass": 2, "status": "open",
                "diffs": [{"ku_id": "KU-0001", "action": "added", "status": "open",
                           "detail": "not yet reviewed"}]}
        with open(tmp / "diff.json", "w", encoding="utf-8") as fh:
            json.dump(pend, fh)
        r = run("scripts/inventory_check.py", str(FIX / "inventory.json"),
                str(tmp / "struct.json"), "--anchors", str(tmp / "anchors.json"),
                "--config", "config.default.json",
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(tmp / "diff.json"), "--out", str(tmp / "check.json"))
        self.assertNotEqual(r.returncode, 0)
        audit = {"anchor_recall": 1.0, "diff_status": "pending", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 100.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 1},
                 "skew_flags": [], "duplicate_flags": [], "limitations": [],
                 "cognitive_by_tier": {}, "cognitive_gaps": {}, "purpose_coverage": {},
                 "has_explicit_purposes": False, "unaddressed_clusters": [],
                 "missing_purposes": []}
        status, reasons = gatemod.decide(audit, 1.0)
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("diff" in x for x in reasons))

    def test_forged_comprehensive_ignored(self):
        audit = {"anchor_recall": 1.0, "diff_status": "resolved", "density_flags": [],
                 "coverage_by_tier": {"1": {"pct_covered": 80.0}, "2": {"pct_covered": 100.0}},
                 "validation_rates": {"pct_validated": 100.0}, "ku_counts": {"total": 10},
                 "skew_flags": [], "duplicate_flags": [], "limitations": [],
                 "status": "COMPREHENSIVE",
                 "cognitive_by_tier": {}, "cognitive_gaps": {}, "purpose_coverage": {},
                 "has_explicit_purposes": False, "unaddressed_clusters": [],
                 "missing_purposes": []}
        self.assertEqual(gatemod.decide(audit, 1.0)[0], "PARTIAL")

    def test_validation_rejection_fails_pipeline(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_fail3_"))
        r = run("scripts/pipeline.py", "--source", str(FIX / "longdoc_source.md"),
                "--run-id", "r", "--profile", "profiles/APSC_PRELIMS.json",
                "--config", "config.default.json", "--build-dir", str(tmp),
                "--inventory", str(FIX / "inventory.json"),
                "--bank", str(FIX / "question_bank_invalid.json"),
                "--ignored", str(FIX / "ignored_anchors.json"),
                "--diff", str(FIX / "inventory_diff.json"))
        self.assertNotEqual(r.returncode, 0)


class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="longdoc_render_"))
        r, r2, r3, vr, cov, au = run_chain(cls.tmp, "question_bank.json")
        assert r.returncode == 0 and r2.returncode == 0
        aud = jload(au)
        gate = {"status": gatemod.decide(aud, 1.0)[0], "reasons": []}
        with open(cls.tmp / "gate.json", "w", encoding="utf-8") as fh:
            json.dump(gate, fh)
        r4 = run("scripts/package.py", str(FIX / "question_bank.json"), str(au),
                 str(cls.tmp / "gate.json"), "--profile", "profiles/APSC_PRELIMS.json",
                 "--inventory", str(FIX / "inventory.json"),
                 "--out", str(cls.tmp / "pkg.json"))
        assert r4.returncode == 0, r4.stdout + r4.stderr
        r5 = run("scripts/build_web.py", str(cls.tmp / "pkg.json"),
                 "--out", str(cls.tmp / "quiz.html"))
        assert r5.returncode == 0, r5.stdout + r5.stderr
        pdfd = cls.tmp / "pdf"
        pdfd.mkdir(exist_ok=True)
        r6 = run("scripts/build_pdf.py", str(cls.tmp / "pkg.json"),
                 "--out", str(pdfd), "--profile", "profiles/APSC_PRELIMS.json")
        assert r6.returncode == 0, r6.stdout + r6.stderr
        cls.pdfd = pdfd
        r7 = run("scripts/check_pdf.py", str(pdfd / "question-paper-A.pdf"),
                 str(pdfd / "answer-key-B.pdf"), str(pdfd / "explanations-C.pdf"),
                 "--package", str(cls.tmp / "pkg.json"),
                 "--report", str(cls.tmp / "check.json"))
        cls.check_rc = r7.returncode
        cls.check = jload(cls.tmp / "check.json")

    def test_pdf_check_passes(self):
        self.assertEqual(self.check_rc, 0)
        self.assertEqual(self.check["overall"], "PASS")

    def test_web_bank_scale(self):
        html = read(self.tmp / "quiz.html")
        i = html.find("__PACKAGE__")
        self.assertNotEqual(i, -1)
        j = html.find("{", i)
        depth, k = 0, j
        while k < len(html):
            if html[k] == "{":
                depth += 1
            elif html[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        pkg = json.loads(html[j:k + 1])
        self.assertGreaterEqual(len(pkg["questions"]), 100)
        kinds = {q["type"] for q in pkg["questions"]}
        self.assertIn("statement_based", kinds)
        self.assertIn("@media print", html)

    def test_long_stems_survive_paper(self):
        from pypdf import PdfReader
        rd = PdfReader(str(self.pdfd / "question-paper-A.pdf"))
        self.assertGreaterEqual(len(rd.pages), 20)
        pkg = jload(self.tmp / "pkg.json")
        longest = max(pkg["questions"], key=lambda q: len(q.get("stem", "")))
        self.assertGreater(len(longest["stem"]), 200)
        full = "\n".join((p.extract_text() or "") for p in rd.pages)
        self.assertIn(longest["id"], full)
        rc = PdfReader(str(self.pdfd / "explanations-C.pdf"))
        cfull = "\n".join((p.extract_text() or "") for p in rc.pages)
        longest_exp = max(pkg["questions"], key=lambda q: len(q.get("explanation", "")))
        self.assertGreater(len(longest_exp["explanation"]), 100)
        self.assertIn(longest_exp["id"], cfull)


class TestAcceptanceE2E(unittest.TestCase):
    def test_full_apsc_run(self):
        tmp = Path(tempfile.mkdtemp(prefix="longdoc_e2e_"))
        r = run("scripts/run_longdoc_acceptance.py", "--fixtures", str(FIX),
                "--run-dir", str(tmp / "r1"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("gate-final: COMPREHENSIVE", r.stdout)
        self.assertIn("OVERALL: PASS", r.stdout)
        gate = jload(tmp / "r1" / "gate.json")
        self.assertEqual(gate["status"], "COMPREHENSIVE")
        self.assertEqual(gate["reasons"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
