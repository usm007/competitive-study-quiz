"""Fill/verify KU char offsets from verbatim excerpts (SKILL.md locate step)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, fail, run_main


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("struct")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    for p in (a.inventory, a.struct):
        if not os.path.isfile(p):
            fail("file not found: %s" % p)
    inv = load_json(a.inventory)
    units = inv.get("units") if isinstance(inv, dict) else inv
    st = load_json(a.struct)
    ntext = st.get("normalized_text", "")
    blocks = {b.get("id"): b for b in st.get("blocks", [])}
    bad = []
    for u in units:
        exc = u.get("supporting_excerpt", "") or ""
        j = ntext.find(exc) if exc else -1
        src = u.get("source") or {}
        if j < 0:
            bad.append(u.get("id"))
            continue
        src["char_start"], src["char_end"] = j, j + len(exc)
        blk = blocks.get(src.get("block_id"))
        if blk is not None:
            src["page"] = blk.get("page", src.get("page"))
            src["section_path"] = blk.get("section_path", src.get("section_path"))
            if not u.get("language"):
                u["language"] = blk.get("language") or "en"
        u["source"] = src
    if bad:
        print("unlocatable excerpts (not verbatim in source): %s" % bad)
        fail("%d excerpts not verbatim; fix inventory" % len(bad))
    dest = a.out or a.inventory
    if isinstance(inv, dict):
        inv["units"] = units
        save_json(dest, inv)
    else:
        save_json(dest, units)
    print("located %d excerpts -> %s" % (len(units), dest))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
