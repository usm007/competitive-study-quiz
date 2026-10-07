"""Phase 1 fixture maker, part 2: deterministic question banks.

Builds schema-valid, validation-passing question banks from the longdoc
inventory by exercising the engine's own rules (required_forms, purposes,
statement key-logic). Simulates the agent authoring steps deterministically.

Outputs in --out:
  question_bank.json          (full: every KU primary-covered, all forms)
  question_bank_round1.json   (full minus planted gaps for gap-fill demo)
  gap_additions.json          (the removed questions = expected gap-fill)
  question_bank_invalid.json  (5 valid controls + 10 broken questions)
  question_bank_dup.json      (same-KU different-purpose pairs + 2 clones)

Usage:
  py scripts/make_longdoc_bank.py --fixtures tests/fixtures/longdoc --struct build/longdoc-r1/document_structure.json --out tests/fixtures/longdoc
"""
import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir, fail, run_main, norm
import coverage as covmod

KEYS = ["A", "B", "C", "D"]
APSC_MIX = {"assertion_reason": 5, "elimination_mcq": 20, "factual_mcq": 40,
            "match_pairs": 10, "statement_based": 25}
HINTS = [
    "Eliminate the option that shifts the figure.",
    "Eliminate the option that reverses the relation.",
    "Test each sentence against the source before combining.",
    "Check each pairing against the table order.",
    "Trace the causal arrow before choosing.",
    "Focus on the named entity, not the familiar words.",
]


def num_of(stmt):
    m = re.findall(r"\b\d[\d,]*\b", stmt)
    return m[0] if m else None


def adj_num(val):
    m = re.match(r"^(\d[\d,]*)(.*)$", val or "")
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    rest = m.group(2)
    for cand in (n + 1, n - 1, n + 10):
        if cand > 0:
            s = str(cand)
            if "," in m.group(1) and cand >= 1000:
                s = "%d,%03d" % (cand // 1000, cand % 1000) if cand < 100000 else str(cand)
            return s + rest
    return None


class Builder:
    def __init__(self, inv, struct):
        self.units = inv["units"]
        self.by_id = {u["id"]: u for u in self.units}
        self.struct = struct
        self.ntext = norm(struct.get("normalized_text", ""))
        self.qn = 0
        self.key_cycle = 0
        self.hint_cycle = 0
        self.match_used_items = set()
        self.by_section = collections.defaultdict(list)
        for u in self.units:
            sp = (u.get("source") or {}).get("section_path") or []
            self.by_section[sp[0] if sp else "global"].append(u["id"])

    def next_key(self):
        k = KEYS[self.key_cycle % 4]
        self.key_cycle += 1
        return k

    def next_hint(self):
        h = HINTS[self.hint_cycle % len(HINTS)]
        self.hint_cycle += 1
        return h

    def base_q(self, ku, qtype, purpose, cog, difficulty, dreason):
        self.qn += 1
        u = self.by_id[ku]
        return {"qid": "Q-%04d" % self.qn, "ku": ku, "qtype": qtype,
                "purpose": purpose, "cog": cog, "difficulty": difficulty,
                "dreason": dreason, "key": self.next_key(), "topic": u["topic"]}

    def src_refs(self, kids):
        out = []
        for kid in kids:
            u = self.by_id[kid]
            s = u.get("source") or {}
            j = self.ntext.find(norm(u.get("supporting_excerpt", "")))
            sp = s.get("section_path") or []
            out.append({"page": s.get("page", 1),
                        "section_path": ">".join(sp) if isinstance(sp, list) else str(sp),
                        "block_id": s.get("block_id"), "char_start": max(j, 0),
                        "char_end": max(j, 0) + len(u.get("supporting_excerpt", "")),
                        "table_ref": None})
        return out

    def finalize(self, b, stem, options, answer_key, statements, kus_roles,
                 explanation, mem=None, hint=None, misc=None, tier=None):
        opts = []
        for i, o in enumerate(options):
            od = {"key": KEYS[i], "text": o["text"],
                  "is_correct": KEYS[i] == answer_key,
                  "distractor_origin": o.get("distractor_origin", "source_ku"),
                  "confusion_type": o.get("confusion_type", "near_synonym"),
                  "ku_ref": o.get("ku_ref")}
            if "covers" in o:
                od["covers"] = o["covers"]
            opts.append(od)
        u = self.by_id[b["ku"]]
        return {"id": b["qid"], "type": b["qtype"], "stem": stem, "options": opts,
                "answer": answer_key, "statements": statements,
                "knowledge_units": [{"ku_id": k, "role": r} for k, r in kus_roles],
                "source": self.src_refs([k for k, r in kus_roles]),
                "explanation": explanation, "memory_aid": mem, "hint": hint,
                "difficulty": b["difficulty"], "topic": b["topic"],
                "origin": "source", "exam_profile": "APSC_PRELIMS", "language": "en",
                "attempt_count": 0, "correct_count": 0, "last_attempted": None,
                "last_result": None, "confidence": None,
                "priority": {1: 5, 2: 3, 3: 1}.get(tier or 2, 3),
                "purpose": b["purpose"], "primary_skill": b["purpose"],
                "cognitive_level": b["cog"],
                "revision_priority": u["dimensions"].get("revision_priority", "medium"),
                "confusion_cluster": u.get("confusion_cluster"),
                "difficulty_reason": b["dreason"],
                "misconception": (misc or {}).get("misconception"),
                "target_knowledge_units": [b["ku"]]}

    # ---------------- helpers ----------------
    def peers_of(self, ku):
        u = self.by_id[ku]
        fixed = list(u.get("confusable_with") or []) + [
            k for k in (u.get("related_ku") or []) if k != ku]
        pool = []
        if len(fixed) + len(pool) < 6:
            sp = (u.get("source") or {}).get("section_path") or []
            top = sp[0] if sp else "global"
            same_sub = [c for c in self.by_section.get(top, [])
                        if c != ku and c not in fixed and c not in pool
                        and self.by_id[c].get("subtopic") == u.get("subtopic")]
            pool.extend(same_sub)
            if len(fixed) + len(pool) < 6:
                for cand in self.by_section.get(top, []):
                    if cand != ku and cand not in fixed and cand not in pool:
                        pool.append(cand)
                    if len(fixed) + len(pool) >= 6:
                        break
        # confusable/related members stay first (cluster coverage); rotate
        # only the top-up tail so consecutive questions differ (no dup sets)
        if pool:
            off = self.qn % len(pool)
            pool = pool[off:] + pool[:off]
        return (fixed + pool)[:3]

    def mutate_false(self, text):
        fv = num_of(text)
        if fv:
            av = adj_num(fv) or (fv + " (revised)")
            return text.replace(fv, av, 1), "%s replaced with %s" % (fv, av), "value_swap"
        if " not " in text:
            return text.replace(" not ", " ", 1), "negation removed", "negation"
        return ("It is not the case that " + text[0].lower() + text[1:], "negated", "negation")

    def place_key(self, keyopt, rest, key):
        texts = {key: keyopt}
        ci = 0
        for k in KEYS:
            if k not in texts:
                texts[k] = rest[ci]
                ci += 1
        return [texts[k] for k in KEYS]

    def rot_to_key(self, options, key, correct_pos):
        shift = (KEYS.index(key) - correct_pos) % 4
        return options[-shift:] + options[:-shift] if shift else options

    def uniq3(self, key_text, cands):
        seen = {norm(key_text)}
        out = []
        for d in cands:
            t = d["text"]
            if norm(t) in seen:
                continue
            seen.add(norm(t))
            out.append(d)
        fb = [
            {"text": "The neighbouring record states otherwise in this regard.",
             "confusion_type": "partial_truth", "ku_ref": None,
             "distractor_purpose": "partial_truth"},
            {"text": "No recorded figure matches this particular case.",
             "confusion_type": "overgeneralization", "ku_ref": None,
             "distractor_purpose": "scope_error"},
        ]
        for d in fb:
            if len(out) >= 3:
                break
            if norm(d["text"]) not in seen:
                seen.add(norm(d["text"]))
                out.append(d)
        assert len(out) >= 3, ("option assembly failed", key_text)
        return out[:3]

    def sibling_names(self, ku):
        """Distinct name-phrases from peer statements: 'The X of YYYY ...'."""
        names = []
        for p in self.peers_of(ku):
            m = re.match(self.NAME_PAT, self.by_id[p]["statement"])
            if m and m.group(1) not in names:
                names.append((m.group(1), p))
        return names

    def sibling_years(self, ku, exclude):
        years = []
        for p in self.peers_of(ku):
            for y in re.findall(r"\b(?:19|20)\d\d\b", self.by_id[p]["statement"]):
                if y != exclude and y not in years:
                    years.append((y, p))
        return years

    def sibling_numbers(self, ku, exclude):
        nums = []
        for p in self.peers_of(ku):
            for v in re.findall(r"\b\d[\d,]*\b", self.by_id[p]["statement"]):
                if v != exclude and v not in nums:
                    nums.append((v, p))
        return nums

    def short_options(self, correct_text, correct_ref, cands, key):
        """Assemble 4 short unique options with the correct one on key."""
        seen = {norm(correct_text)}
        clean = []
        for text, ref, ct, dp in cands:
            if norm(text) in seen:
                continue
            seen.add(norm(text))
            clean.append({"text": text, "confusion_type": ct, "ku_ref": ref,
                          "distractor_purpose": dp})
            if len(clean) == 3:
                break
        pads = [("The neighbouring record states otherwise in this regard.",
                 "partial_truth", "partial_truth"),
                ("No recorded figure matches this particular case.",
                 "overgeneralization", "scope_error"),
                ("None of the recorded values fits this blank.",
                 "overgeneralization", "scope_error")]
        for fb_text, fb_ct, fb_dp in pads:
            if len(clean) >= 3:
                break
            if norm(fb_text) not in seen:
                seen.add(norm(fb_text))
                clean.append({"text": fb_text, "confusion_type": fb_ct,
                              "ku_ref": None, "distractor_purpose": fb_dp})
        assert len(clean) == 3, ("option assembly failed", correct_text, cands)
        return self.place_key({"text": correct_text, "confusion_type": "near_synonym",
                               "ku_ref": correct_ref}, clean, key)

    # ---------------- forms ----------------
    def build_recall(self, ku, variant):
        u = self.by_id[ku]
        peers = self.peers_of(ku)
        purpose = "chronology" if (u["type"] == "date" and variant == "chrono") else "direct_recall"
        b = self.base_q(ku, "one_liner_mcq" if variant == "one_liner" else "factual_mcq",
                        purpose, "recall", "easy", "Direct factual recall of a high-value fact.")
        key_text = u["statement"]
        exc = u.get("supporting_excerpt", "")
        cells = [c.strip() for c in exc.split("|")] if "|" in exc else []
        # (c) table-row completion: blank the value cells, options are pairs
        if len(cells) >= 3 and u["type"] == "table_value":
            c1, c2, c3 = cells[0], cells[1], cells[2]
            stem = "%s: ____ / ____. Select the recorded pair." % c1
            correct = "%s; %s" % (c2, c3)
            cands = []
            av = adj_num(c2)
            if av:
                cands.append(("%s; %s" % (av, c3), ku, "adjacent_value", "adjacent_value"))
            for p in peers:
                pexc = self.by_id[p].get("supporting_excerpt", "")
                pc = [c.strip() for c in pexc.split("|")] if "|" in pexc else []
                if len(pc) >= 3 and pc[0] != c1:
                    cands.append(("%s; %s" % (pc[1], pc[2]), p, "near_synonym", "confusable_fact"))
                    if len(cands) >= 4:
                        break
            w3 = c3
            if peers:
                plast = self.by_id[peers[0]].get("supporting_excerpt", "").split("|")
                if len(plast) >= 3 and plast[-1].strip() != c3:
                    w3 = plast[-1].strip()
            cands.append(("%s; %s" % (c2, w3), peers[0] if peers else ku,
                          "partial_truth", "partial_truth"))
            options = self.short_options(correct, ku, cands, b["key"])
            return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                                 "Correct because the table records exactly this pair for %s; the others "
                                 "shift a figure or borrow a neighbouring row." % c1,
                                 hint=self.next_hint(), tier=u["tier"])
        # (b) name-of-year completion: "The X of YYYY ..." / "The X (YYYY) ..."
        m = re.match(r"^The (.+?) ((?:of (?:19|20)\d\d|\((?:19|20)\d\d\))) ?(.*)$", key_text)
        if m and u["type"] in ("amendment", "scheme", "list_item", "article", "institution"):
            name, connector, rest = m.group(1), m.group(2), m.group(3)
            cands = [("%s" % nm, pid, "near_synonym", "confusable_fact")
                     for nm, pid in self.sibling_names(ku)[:4]]
            stem = "The ____ %s %s" % (connector, rest)
            options = self.short_options(name, ku, cands, b["key"])
            return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                                 "Correct because the source names %s here; the alternatives name "
                                 "sibling provisions." % name,
                                 hint=self.next_hint(), tier=u["tier"])
        # (a) year completion: "In YYYY, rest"
        m = re.match(r"^In ((?:19|20)\d\d),? (.*)$", key_text)
        if m:
            year, rest = m.group(1), m.group(2)
            cands = [(str(int(year) + 1), ku, "wrong_date", "wrong_date"),
                     (str(int(year) - 1), ku, "wrong_date", "wrong_date")]
            for y, pid in self.sibling_years(ku, year)[:3]:
                cands.append((y, pid, "wrong_date", "confusable_fact"))
            stem = "In ____, %s" % rest
            options = self.short_options(year, ku, cands, b["key"])
            return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                                 "Correct because the source dates this event to %s; the alternatives shift "
                                 "the year or borrow a sibling date." % year,
                                 hint=self.next_hint(), tier=u["tier"])
        # (d) number completion: blank the first number
        v = num_of(key_text)
        if v and u["type"] in ("number_value", "table_value", "date"):
            cands = []
            av = adj_num(v)
            if av:
                cands.append((av, ku, "adjacent_value", "adjacent_value"))
            for n, pid in self.sibling_numbers(ku, v)[:3]:
                cands.append((n, pid, "adjacent_value", "confusable_fact"))
            stem = key_text.replace(v, "____", 1)
            options = self.short_options(v, ku, cands, b["key"])
            return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                                 "Correct because the source records %s here; the alternatives shift the "
                                 "figure or borrow a sibling value." % v,
                                 hint=self.next_hint(), tier=u["tier"])
        # (e) fallback: full-statement options, KU-specific stem
        cands = []
        excluded = set(u.get("confusable_with") or [])
        for p in peers:
            if p in excluded:
                continue  # pair members mirror; shared group Q covers them
            cands.append({"text": self.by_id[p]["statement"], "confusion_type": "near_synonym",
                          "ku_ref": p, "distractor_purpose": "confusable_fact"})
        if v:
            av = adj_num(v)
            if av:
                cands.insert(1, {"text": key_text.replace(v, av),
                                 "confusion_type": "adjacent_value", "ku_ref": ku,
                                 "distractor_purpose": "adjacent_value"})
        clean = self.uniq3(key_text, cands)
        stem = "On %s, select the correct statement." % u["subtopic"]
        options = self.place_key({"text": key_text, "confusion_type": "near_synonym", "ku_ref": ku},
                                 clean, b["key"])
        return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                             "Correct because the source records exactly this: %s The closest "
                             "alternative borrows a neighbouring figure or entity." % key_text,
                             hint=self.next_hint(), tier=u["tier"])

    def match_mates(self, ku):
        """Two mates forming a triple fully disjoint from every used match
        item (shared rows read as near-duplicates under token Jaccard)."""
        u = self.by_id[ku]
        group = sorted(x["id"] for x in self.units
                       if x.get("subtopic") == u.get("subtopic") and x["id"] != ku)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                t = {ku, a, b}
                if t & self.match_used_items:
                    continue
                self.match_used_items |= t
                return [a, b]
        # fallback: mates from other sections (cross-table matching)
        sp = (u.get("source") or {}).get("section_path") or []
        top = sp[0] if sp else "global"
        far = sorted(x["id"] for x in self.units
                     if x["id"] != ku and ((x.get("source") or {}).get("section_path") or [""])[0] != top)
        for i, a in enumerate(far):
            for b in far[i + 1:]:
                t = {ku, a, b}
                if t & self.match_used_items:
                    continue
                self.match_used_items |= t
                return [a, b]
        fail("no disjoint match triple available for %s" % ku)

    NAME_PAT = r"^The (.+?) (?:of (?:19|20)\d\d\b|\((?:19|20)\d\d\))"

    def short_label(self, stmt, excerpt):
        """A short identifying label + description for selection options."""
        m = re.match(self.NAME_PAT, stmt)
        if m:
            return m.group(1), stmt[m.end():].strip()
        cells = [c.strip() for c in excerpt.split("|")] if "|" in excerpt else []
        if len(cells) >= 3:
            return cells[0], "%s / %s" % (cells[1], cells[2])
        m = re.match(r"^In ((?:19|20)\d\d),? (.*)$", stmt)
        if m:
            return m.group(1), m.group(2)
        m = re.match(r"^Article (\S+)", stmt)
        if m:
            return "Article " + m.group(1), stmt
        return None, stmt

    def build_distinction(self, ku, variant):
        u = self.by_id[ku]
        peers = self.peers_of(ku)
        peer = peers[0] if peers else ku
        pv = self.by_id[peer]
        purpose = {"elim": "distinction", "match": "association",
                   "conf": "confusable_fact"}.get(variant, "distinction")
        qtype = {"elim": "elimination_mcq", "match": "match_pairs"}.get(variant, "factual_mcq")
        b = self.base_q(ku, qtype, purpose, "distinction", "medium",
                        "Relationship / distinction between confusable facts.")
        if variant == "match":
            mates = self.match_mates(ku)
            items = [ku] + mates[:2]
            details = [self.by_id[k]["statement"] for k in items]
            labels = ["Item %d" % (i + 1) for i in range(3)]
            perms = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (2, 1, 0)]
            codes = [", ".join("%s-%s" % (labels[i], "ABC"[p[i]]) for i in range(3)) for p in perms]
            assert len(set(codes)) == 4
            stem = ("Match List-I with List-II. List-I: %s. List-II: %s. Select the correct code."
                    % ("; ".join("%s: %s" % (labels[i], self.by_id[k]["statement"][:60])
                                 for i, k in enumerate(items)),
                       "; ".join("%s: %s" % ("ABC"[i], d[:60]) for i, d in enumerate(details))))
            options = [{"text": codes[0], "confusion_type": "near_synonym", "ku_ref": ku}]
            for c, k in zip(codes[1:4], (items[1], items[2], items[1])):
                options.append({"text": c, "confusion_type": "adjacent_value",
                                "ku_ref": k, "distractor_purpose": "reversed_relation"})
            options = self.rot_to_key(options, b["key"], 0)
            return self.finalize(b, stem, options, b["key"], None,
                                 [(ku, "primary")] + [(k, "secondary") for k in items[1:]],
                                 "Only one code matches every recorded pairing; the others swap neighbours.",
                                 misc={"misconception": "Neighbouring rows of a table are often interchanged."},
                                 hint=self.next_hint(), tier=u["tier"])
        if variant == "conf":
            clab, _ = self.short_label(u["statement"], u.get("supporting_excerpt", ""))
            stem = "Which statement correctly distinguishes the %s record (%s)?" % (
                u["subtopic"], clab or u["statement"][:40])
            key_text = "Correct distinction: %s Whereas: %s" % (u["statement"], pv["statement"][:80])
            cands = [
                {"text": "Reversed relation: %s" % pv["statement"], "confusion_type": "reversed_causality",
                 "ku_ref": peer, "distractor_purpose": "reversed_relation"},
                {"text": "Partial account: %s" % u["statement"].split(",")[0], "confusion_type": "partial_truth",
                 "ku_ref": ku, "distractor_purpose": "partial_truth"},
                {"text": pv["statement"], "confusion_type": "near_synonym",
                 "ku_ref": peer, "distractor_purpose": "wrong_entity"},
            ]
        else:
            # elimination via short identifying labels: sibling series KUs
            # would otherwise mirror full statements into identical sets
            own_label, own_desc = self.short_label(
                u["statement"], u.get("supporting_excerpt", ""))
            sibs = []
            for p in peers:
                lab, _ = self.short_label(self.by_id[p]["statement"],
                                          self.by_id[p].get("supporting_excerpt", ""))
                if lab and lab != own_label and lab not in [s[0] for s in sibs]:
                    sibs.append((lab, p))
            if own_label and len(own_desc.split()) >= 4 and len(sibs) >= 2:
                stem = "Which recorded item matches this description: %s?" % own_desc
                cands = [(lab, pid, "near_synonym", "confusable_fact")
                         for lab, pid in sibs[:3]]
                options = self.short_options(own_label, ku, cands, b["key"])
                return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                                     "Correct because only %s matches the recorded description; the others "
                                     "name sibling items with different records." % own_label,
                                     misc={"misconception": "%s is often confused with %s." % (ku, peer)},
                                     hint=self.next_hint(), tier=u["tier"])
            # fallback: full-statement options (distinctive KUs only)
            stem = "Which statement about the %s record is correct?" % u["subtopic"]
            key_text = u["statement"]
            v = num_of(key_text)
            mut = key_text.replace(v, adj_num(v), 1) if v and adj_num(v) else None
            if mut is None:
                ft, _, _ = self.mutate_false(key_text)
                mut = ft
            cands = [
                {"text": "Altered figure: %s" % mut, "confusion_type": "adjacent_value",
                 "ku_ref": ku, "distractor_purpose": "adjacent_value"},
                {"text": "Partial account: %s" % key_text.split(",")[0], "confusion_type": "partial_truth",
                 "ku_ref": ku, "distractor_purpose": "partial_truth"},
                {"text": pv["statement"][:100], "confusion_type": "near_synonym",
                 "ku_ref": peer, "distractor_purpose": "confusable_fact"},
            ]
        clean = self.uniq3(key_text, cands)
        options = self.place_key({"text": key_text, "confusion_type": "near_synonym", "ku_ref": ku},
                                 clean, b["key"])
        return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                             "Correct because it preserves the recorded distinction; the reversed and partial "
                             "options change the relation or drop its condition.",
                             misc={"misconception": "%s is often confused with %s." % (ku, peer)},
                             hint=self.next_hint(), tier=u["tier"])

    def build_shared_distinction(self, members):
        """One distinction question for a whole confusable group (all members
        primary). Per-member mirrored questions would be near-duplicates."""
        first = members[0]
        u = self.by_id[first]
        peers = members[1:]
        b = self.base_q(first, "factual_mcq", "confusable_fact", "distinction", "medium",
                        "Relationship / distinction between confusable facts.")
        combo = " ".join(self.by_id[k]["statement"] for k in members)
        key_text = "Correct distinctions: %s" % combo
        mut0, _, _ = self.mutate_false(self.by_id[members[0]]["statement"])
        mut1, _, _ = self.mutate_false(self.by_id[members[-1]]["statement"])
        cands = [
            {"text": "Altered first distinction: %s %s" % (
                mut0, " ".join(self.by_id[k]["statement"] for k in members[1:])),
             "confusion_type": "partial_truth", "ku_ref": members[0],
             "distractor_purpose": "partial_truth"},
            {"text": "Altered last distinction: %s %s" % (
                " ".join(self.by_id[k]["statement"] for k in members[:-1]), mut1),
             "confusion_type": "partial_truth", "ku_ref": members[-1],
             "distractor_purpose": "partial_truth"},
            {"text": self.by_id[peers[0]]["statement"] if peers else combo,
             "confusion_type": "near_synonym",
             "ku_ref": peers[0] if peers else members[0],
             "distractor_purpose": "wrong_entity"},
        ]
        clean = self.uniq3(key_text, cands)
        stem = ("The following recorded items are often confused: %s. "
                "Which statement correctly distinguishes them?" %
                "; ".join(self.by_id[k]["statement"][:60] for k in members))
        q = self.finalize(b, stem, self.place_key(
            {"text": key_text, "confusion_type": "near_synonym", "ku_ref": first},
            clean, b["key"]), b["key"], None,
            [(k, "primary") for k in members],
            "Correct because it preserves every recorded distinction; the altered "
            "options change one member each.",
            misc={"misconception": "Members of this cluster are often interchanged."},
            hint=self.next_hint(), tier=u["tier"])
        q["confusion_cluster"] = u.get("confusion_cluster")
        q["target_knowledge_units"] = list(members)
        return q

    def conf_groups(self):
        # group by shared confusable links (symmetric pairs/groups)
        seen = {}
        for u in self.units:
            peers = u.get("confusable_with") or []
            if not peers:
                continue
            key = tuple(sorted([u["id"]] + list(peers)))
            seen.setdefault(key, []).append(u["id"])
        out = {}
        for key, members in seen.items():
            members = sorted(set(members))
            if len(members) >= 2:
                for m in members:
                    out[m] = members
        return out

    def true_pool(self, ku):
        u = self.by_id[ku]
        pool = [(u["statement"], ku)]
        for p in self.peers_of(ku)[:2]:
            pool.append((self.by_id[p]["statement"], p))
        return pool[:3]

    def far_pool(self, ku):
        """Secondaries from other sections: mixed-statement sets like real
        prelims papers, and no shared-statement near-duplicates."""
        u = self.by_id[ku]
        sp = (u.get("source") or {}).get("section_path") or []
        top = sp[0] if sp else "global"
        cands = [x["id"] for x in self.units
                 if x["id"] != ku and ((x.get("source") or {}).get("section_path") or [""])[0] != top]
        off = self.qn % max(len(cands), 1)
        cands = cands[off:] + cands[:off]
        return [(self.by_id[k]["statement"], k) for k in cands[:2]]

    def build_statement(self, ku, variant, cycle):
        u = self.by_id[ku]
        pool = [(u["statement"], ku)] + self.far_pool(ku)
        while len(pool) < 3:
            pool.append(pool[0])
        if variant == "assertion":
            b = self.base_q(ku, "assertion_reason", "statement_evaluation", "analysis", "hard",
                            "Assertion-reason evaluation of linked facts.")
            if cycle % 2 == 0:
                stmts = [{"text": "Assertion: " + pool[0][0], "truth_value": True, "ku_basis": pool[0][1],
                          "alteration": None, "alteration_type": "none"},
                         {"text": "Reason: " + pool[1][0], "truth_value": True, "ku_basis": pool[1][1],
                          "alteration": None, "alteration_type": "none"}]
                exp = [1, 2]
            else:
                ft, al, at = self.mutate_false(pool[1][0])
                stmts = [{"text": "Assertion: " + pool[0][0], "truth_value": True, "ku_basis": pool[0][1],
                          "alteration": None, "alteration_type": "none"},
                         {"text": "Reason: " + ft, "truth_value": False, "ku_basis": pool[1][1],
                          "alteration": al, "alteration_type": at}]
                exp = [1]
            combos = [("Assertion correct, reason incorrect", [1]),
                      ("Assertion incorrect, reason correct", [2]),
                      ("Both assertion and reason are correct", [1, 2]),
                      ("Neither assertion nor reason is correct", [])]
            options = [{"text": t, "covers": c,
                        "confusion_type": "near_synonym" if c == exp else "partial_truth",
                        "ku_ref": ku} for t, c in combos]
            ci = next(i for i, o in enumerate(options) if o["covers"] == exp)
            options = self.rot_to_key(options, b["key"], ci)
            stem = ("Consider the following statements: 1. %s 2. %s Which of the above "
                    "is/are correct?" % (stmts[0]["text"][len("Assertion: "):],
                                         stmts[1]["text"][len("Reason: "):]))
            secs = [(pool[1][1], "secondary")] if pool[1][1] != ku else []
            return self.finalize(b, stem, options, b["key"], stmts, [(ku, "primary")] + secs,
                                 "The key follows the truth pattern %s; the altered reason decides it." % exp,
                                 hint=self.next_hint(), tier=u["tier"])
        b = self.base_q(ku, "statement_based", "statement_evaluation", "analysis", "hard",
                        "Multiple statements require joint evaluation.")
        exp = [[1, 2], [1, 3], [2, 3]][cycle % 3]
        texts, bases, truths, alts, altts = [], [], [], [], []
        for i in range(3):
            t, kb = pool[i]
            if (i + 1) in exp:
                texts.append(t)
                bases.append(kb)
                truths.append(True)
                alts.append(None)
                altts.append("none")
            else:
                ft, al, at = self.mutate_false(t)
                texts.append(ft)
                bases.append(kb)
                truths.append(False)
                alts.append(al)
                altts.append(at)
        stmts = [{"text": t, "truth_value": tv, "ku_basis": kb,
                  "alteration": al, "alteration_type": at}
                 for t, tv, kb, al, at in zip(texts, truths, bases, alts, altts)]
        combos = [("1 and 2 only", [1, 2]), ("1 and 3 only", [1, 3]),
                  ("2 and 3 only", [2, 3]), ("1, 2 and 3", [1, 2, 3])]
        options = [{"text": t, "covers": c,
                    "confusion_type": "near_synonym" if c == exp else "partial_truth",
                    "ku_ref": ku} for t, c in combos]
        ci = next(i for i, o in enumerate(options) if o["covers"] == exp)
        options = self.rot_to_key(options, b["key"], ci)
        stem = ("Consider the following statements: 1. %s 2. %s 3. %s Which of the above "
                "is/are correct?" % (texts[0], texts[1], texts[2]))
        secs = [(bases[1], "secondary")] if bases[1] != ku else []
        if bases[2] != ku and bases[2] != bases[1]:
            secs.append((bases[2], "secondary"))
        return self.finalize(b, stem, options, b["key"], stmts, [(ku, "primary")] + secs,
                             "Only the key option matches the true-statement pattern %s; the false "
                             "statement carries a swapped value." % exp,
                             hint=self.next_hint(), tier=u["tier"])

    def build_application(self, ku, purpose):
        u = self.by_id[ku]
        peers = self.peers_of(ku)
        b = self.base_q(ku, "reasoning_mcq", purpose, "application", "medium",
                        "Cause-effect reasoning from the recorded mechanism.")
        key_text = u["statement"]
        cands = [{"text": "Reversed mechanism: %s" % self.by_id[peers[0]]["statement"]
                  if peers else "Reversed mechanism of the recorded process.",
                  "confusion_type": "reversed_causality",
                  "ku_ref": peers[0] if peers else ku,
                  "distractor_purpose": "causal_reversal"}]
        for p in peers[1:3]:
            cands.append({"text": self.by_id[p]["statement"], "confusion_type": "near_synonym",
                          "ku_ref": p, "distractor_purpose": "wrong_entity"})
        cands.append({"text": "Partial mechanism: %s" % key_text.split(",")[0],
                      "confusion_type": "partial_truth", "ku_ref": ku,
                      "distractor_purpose": "partial_truth"})
        clean = self.uniq3(key_text, cands)
        stem = "Applying the recorded mechanism (%s), which conclusion follows?" % u["subtopic"]
        options = self.place_key({"text": key_text, "confusion_type": "near_synonym", "ku_ref": ku},
                                 clean, b["key"])
        return self.finalize(b, stem, options, b["key"], None, [(ku, "primary")],
                             "The mechanism as recorded yields only the key conclusion; the others reverse "
                             "cause and effect.",
                             hint=self.next_hint(), tier=u["tier"])

    # ---------------- assembly ----------------
    def purpose_for_distinction(self, ku):
        u = self.by_id[ku]
        if u["type"] == "exception":
            return "exception"
        if u["type"] == "classification":
            return "classification"
        if u.get("confusable_with"):
            return "confusable_fact"
        return "distinction"

    def build_bank(self):
        questions = []
        pat_cycle = 0
        match_cycle = 0
        groups = self.conf_groups()
        built_shared = set()
        for u in self.units:
            kid = u["id"]
            for form in sorted(covmod.required_forms(u)):
                if form == "recall":
                    v = "one_liner" if self.qn % 3 == 2 else "std"
                    if u["type"] == "date" and self.qn % 4 == 0:
                        v = "chrono"
                    q = self.build_recall(kid, v)
                elif form == "distinction":
                    grp = groups.get(kid)
                    if grp:
                        gid = tuple(grp)
                        if gid in built_shared:
                            continue  # covered by the shared group question
                        built_shared.add(gid)
                        q = self.build_shared_distinction(grp)
                    elif match_cycle % 4 == 3 and u["type"] in (
                            "article", "table_value", "institution", "list_item"):
                        q = self.build_distinction(kid, "match")
                    else:
                        purp = self.purpose_for_distinction(kid)
                        q = self.build_distinction(kid, "conf" if purp in (
                            "exception", "classification", "confusable_fact") else "elim")
                        q["purpose"] = purp
                        q["primary_skill"] = purp
                    match_cycle += 1
                elif form == "statement":
                    if not u.get("confusable_with") and pat_cycle % 5 == 4:
                        q = self.build_distinction(kid, "elim")
                        q["purpose"] = "elimination"
                        q["primary_skill"] = "elimination"
                    elif pat_cycle % 7 == 6:
                        q = self.build_statement(kid, "assertion", pat_cycle)
                    else:
                        q = self.build_statement(kid, "standard", pat_cycle)
                    pat_cycle += 1
                else:
                    q = self.build_application(
                        kid, "cause_effect" if u["type"] == "cause_effect" else "application")
                questions.append(q)
        return questions


def self_check(questions, inv, struct):
    import validate_questions as vq
    from lib_common import token_set_sim
    units = inv["units"]
    ku_ids = {u["id"] for u in units}
    ku_map = {u["id"]: u.get("supporting_excerpt", "") or "" for u in units}
    block_ids = {x["id"] for x in struct.get("blocks", [])}
    ntext = norm(struct.get("normalized_text", ""))
    seen = []
    for q in questions:
        for f in ("id", "type", "stem", "options", "answer", "knowledge_units",
                  "source", "explanation", "purpose"):
            assert f in q, (q["id"], f)
        assert len(q["options"]) == 4, q["id"]
        r = vq.check_one(dict(q), ku_ids, ku_map, block_ids, ntext, 4, "SOURCE_BOUND", 0.85, seen)
        assert r["status"] == "validated", (q["id"], r["notes"])
    # pairwise dedupe screen
    blobs = [(q["id"], (q.get("stem") or "") + " " + " ".join(
        o.get("text", "") for o in q["options"])) for q in questions]
    dups = []
    for i in range(len(blobs)):
        for j in range(i + 1, len(blobs)):
            if token_set_sim(blobs[i][1], blobs[j][1]) >= 0.85:
                dups.append((blobs[i][0], blobs[j][0]))
    assert not dups, "near-duplicates in full bank: %s" % dups[:5]
    tot = len(questions)
    mix = collections.Counter(q["type"] for q in questions)
    for t, target in APSC_MIX.items():
        pct = 100 * mix.get(t, 0) / tot
        assert abs(pct - target) <= 15, (t, round(pct, 1), target)
    purps = collections.Counter(q["purpose"] for q in questions)
    for p in ("statement_evaluation", "elimination", "distinction", "association", "direct_recall"):
        assert purps.get(p), "missing purpose %s" % p
    kb = collections.Counter(q["answer"] for q in questions)
    for k, v in kb.items():
        assert v / tot <= 0.45, ("key imbalance", dict(kb))
    prim = collections.defaultdict(list)
    for q in questions:
        for e in q["knowledge_units"]:
            if e["role"] == "primary":
                prim[e["ku_id"]].append(q)
    for u in units:
        req = covmod.required_forms(u)
        got = set()
        for q in prim.get(u["id"], []):
            got |= covmod.q_cognitive_forms(q)
        assert req <= got, (u["id"], req, got)
        assert len(prim.get(u["id"], [])) <= 3, u["id"]
    return {"total": tot, "mix": dict(mix), "purposes": dict(purps), "keys": dict(kb)}


def split_round1(questions, inv, grouped):
    tiers = {u["id"]: u["tier"] for u in inv["units"]}
    secs = collections.defaultdict(list)
    for u in inv["units"]:
        sp = (u.get("source") or {}).get("section_path") or []
        secs[sp[0] if sp else "global"].append(u["id"])
    # shared-group members stay intact: their questions serve several KUs,
    # which would blur gap attribution
    drop = []
    skeys = sorted(secs)
    for s in skeys[:4]:
        c = [k for k in secs[s] if tiers[k] == 1 and k not in grouped]
        if c:
            drop.append(c[0])
    for s in skeys[4:]:
        c = [k for k in secs[s] if tiers[k] == 2 and k not in grouped]
        if c:
            drop.append(c[0])
    drop = drop[:8]
    prim_all = collections.defaultdict(list)
    for q in questions:
        for e in q["knowledge_units"]:
            if e["role"] == "primary":
                prim_all[e["ku_id"]].append(q["id"])
    strip = [k for k, qs in prim_all.items()
             if k not in drop and k not in grouped and tiers.get(k) in (1, 2) and len(qs) > 1][:6]
    round1, removed = [], []
    for q in questions:
        prims = [e["ku_id"] for e in q["knowledge_units"] if e["role"] == "primary"]
        if any(p in drop for p in prims):
            removed.append(q)
            continue
        if any(p in strip for p in prims) and covmod.q_cognitive_forms(q) != {"recall"}:
            removed.append(q)
            continue
        round1.append(q)
    return round1, removed, drop, strip


def _valid_skeleton(inv, qid, ku):
    u = next(x for x in inv["units"] if x["id"] == ku)
    s = u.get("source") or {}
    sp = s.get("section_path") or []
    return {"id": qid, "type": "factual_mcq", "stem": "Skeleton stem for %s." % ku,
            "options": [
                {"key": "A", "text": u["statement"], "is_correct": True,
                 "distractor_origin": "source_ku", "confusion_type": "near_synonym", "ku_ref": ku},
                {"key": "B", "text": "An alternative account of the same record.", "is_correct": False,
                 "distractor_origin": "source_ku", "confusion_type": "partial_truth", "ku_ref": ku},
                {"key": "C", "text": "A neighbouring figure in the same table.", "is_correct": False,
                 "distractor_origin": "source_ku", "confusion_type": "adjacent_value", "ku_ref": ku},
                {"key": "D", "text": "An unrelated account from another chapter.", "is_correct": False,
                 "distractor_origin": "source_ku", "confusion_type": "overgeneralization", "ku_ref": None}],
            "answer": "A", "statements": None,
            "knowledge_units": [{"ku_id": ku, "role": "primary"}],
            "source": [{"page": s.get("page", 1),
                        "section_path": ">".join(sp) if isinstance(sp, list) else str(sp),
                        "block_id": s.get("block_id"), "char_start": 0, "char_end": 10,
                        "table_ref": None}],
            "explanation": "Skeleton explanation.", "memory_aid": None, "hint": None,
            "difficulty": "easy", "topic": u["topic"], "origin": "source",
            "exam_profile": "APSC_PRELIMS", "language": "en", "attempt_count": 0,
            "correct_count": 0, "last_attempted": None, "last_result": None,
            "confidence": None, "priority": 3, "purpose": "direct_recall",
            "primary_skill": "direct_recall", "cognitive_level": "recall",
            "revision_priority": "medium", "confusion_cluster": None,
            "difficulty_reason": "Direct factual recall.",
            "misconception": None, "target_knowledge_units": [ku]}


def make_invalid(inv):
    ku = inv["units"][0]["id"]
    ku2 = inv["units"][1]["id"]
    out = []
    q = _valid_skeleton(inv, "Q-INV-01", ku)
    q["options"][1]["is_correct"] = True
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-02", ku)
    for o in q["options"]:
        o["is_correct"] = False
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-03", ku)
    q["knowledge_units"] = [{"ku_id": "KU-9999", "role": "primary"}]
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-04", ku)
    q["source"] = [{"page": 1, "section_path": "x", "block_id": "B-9999",
                    "char_start": 0, "char_end": 5, "table_ref": None}]
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-05", ku)
    q["options"][1]["text"] = q["options"][0]["text"]
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-06", ku)
    q["options"] = q["options"][:3]
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-07", ku)
    q["hint"] = q["options"][0]["text"]
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-08", ku)
    q["type"] = "statement_based"
    q["statements"] = [{"text": "First record.", "truth_value": True, "ku_basis": ku,
                        "alteration": None, "alteration_type": "none"},
                       {"text": "Second record.", "truth_value": False, "ku_basis": ku2,
                        "alteration": "negated", "alteration_type": "negation"}]
    for o in q["options"]:
        o["covers"] = [1]
    q["answer"] = "B"
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-09", ku)
    q["origin"] = "external"
    out.append(q)
    q = _valid_skeleton(inv, "Q-INV-10", ku)
    q["supporting_excerpt"] = "This sentence was never in the source document at all."
    out.append(q)
    return out


def make_dup(inv, struct):
    units = inv["units"]
    B = Builder(inv, struct)
    qa = B.build_recall(units[0]["id"], "std")
    qb = B.build_distinction(units[0]["id"], "elim")
    qc = B.build_recall(units[1]["id"], "std")
    qd = B.build_statement(units[1]["id"], "standard", 0)
    c1 = dict(qa)
    c1["id"] = "Q-DUP-01"
    c1["stem"] = qa["stem"] + " (as recorded)"
    c1["options"] = [dict(o) for o in qa["options"]]
    c2 = dict(qc)
    c2["id"] = "Q-DUP-02"
    c2["options"] = [dict(o) for o in qc["options"]]
    c2["options"][3] = dict(c2["options"][3], text=c2["options"][3]["text"] + " here")
    return [qa, qb, qc, qd, c1, c2]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", required=True)
    ap.add_argument("--struct", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ensure_dir(a.out)
    inv = load_json(os.path.join(a.fixtures, "inventory.json"))
    struct = load_json(a.struct)
    B = Builder(inv, struct)
    questions = B.build_bank()
    rep = self_check(questions, inv, struct)
    print("bank: %d questions mix=%s" % (rep["total"], rep["mix"]))
    print("bank: purposes=%s keys=%s" % (rep["purposes"], rep["keys"]))
    save_json(os.path.join(a.out, "question_bank.json"), {"questions": questions})
    round1, removed, drop, strip = split_round1(questions, inv, set(Builder(inv, struct).conf_groups()))
    save_json(os.path.join(a.out, "question_bank_round1.json"), {"questions": round1})
    save_json(os.path.join(a.out, "gap_additions.json"), {"questions": removed})
    print("round1: %d kept, %d removed (drop=%s strip=%s)" % (len(round1), len(removed), drop, strip))
    bad = make_invalid(inv)
    ok5 = questions[:5]
    save_json(os.path.join(a.out, "question_bank_invalid.json"),
              {"questions": ok5 + bad, "expected_rejected": [q["id"] for q in bad]})
    dupb = make_dup(inv, struct)
    save_json(os.path.join(a.out, "question_bank_dup.json"), {"questions": dupb})
    print("wrote invalid (%d) + dup (%d) banks" % (len(bad) + 5, len(dupb)))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
