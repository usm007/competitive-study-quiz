import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, resolve_out, fail, run_main

MONTHS = "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
PATS = [
    ("percentage", re.compile(r"\b\d+(?:\.\d+)?\s*%")),
    ("percentage", re.compile(r"\b\d+(?:\.\d+)?\s+percent\b", re.I)),
    ("date", re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|(?:19|20)\d{2}|(?:%s)\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:%s)\s+\d{4})" % (MONTHS, MONTHS), re.I)),
    ("ref", re.compile(r"\b(?:Article|Section|Clause|Schedule|Part|Chapter|Rule)s?\.?\s+\d+[A-Za-z]?(?:\s*\(\s*\d+[A-Za-z]?\s*\))?(?:\s*-\s*\d+[A-Za-z]?)?")),
    ("entity", re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,4}\b")),
    ("entity", re.compile(r"\b[A-Z]{2,}(?:s)?\b")),
    ("formula", re.compile(r"\b[A-Z][a-z]?\d+(?:[A-Z][a-z]?\d*)+\b")),
    ("number", re.compile(r"\b\d+(?:\.\d+)?\b")),
]
LIST_RE = re.compile(r"^(\d+[.)]|[-*\u2022])\b")
CAP = 150


def extract(blocks):
    out = []
    n = 0
    for b in blocks:
        bid = b.get("id", "")
        text = b.get("text") or ""
        taken = []
        # ponytail: first-match-wins overlap, capped per block; coreference across blocks out of scope
        def free(s, e):
            return not any(s < te and e > ts for ts, te in taken)
        count = [0]
        def add(kind, val):
            if count[0] >= CAP or len(val) > 200:
                return
            v = val.strip()
            if v:
                n0 = len(out)
                out.append({"id": "A-%d" % (n0 + 1), "kind": kind, "value": v, "block_id": bid})
                count[0] += 1
        if b.get("kind") == "list_item":
            m = LIST_RE.match(text.strip())
            if m:
                add("list_marker", m.group(1))
        tbl = b.get("table") or {}
        for row in tbl.get("rows") or []:
            for cell in row:
                if cell and cell.strip():
                    add("table_cell", cell.strip()[:200])
        for kind, rx in PATS:
            for m in rx.finditer(text):
                if free(m.start(), m.end()):
                    taken.append((m.start(), m.end()))
                    add(kind, m.group(0))
        if "=" in text:
            for line in text.splitlines():
                if "=" in line and len(line.strip()) < 160:
                    add("formula", line.strip())
    seen = set()
    uniq = []
    for a in out:
        k = (a["kind"], a["value"], a["block_id"])
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    for i, a in enumerate(uniq):
        a["id"] = "A-%d" % (i + 1)
    return uniq


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("struct")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.struct):
        fail("struct file not found: %s" % a.struct)
    s = load_json(a.struct)
    blocks = s.get("blocks") or []
    if not isinstance(blocks, list):
        fail("struct has no blocks list")
    anchors = extract(blocks)
    dest = resolve_out(a.out, a.run_id, "anchors.json")
    save_json(dest, anchors)
    print("anchors: %d anchors from %d blocks -> %s" % (len(anchors), len(blocks), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
