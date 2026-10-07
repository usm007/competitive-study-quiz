import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, token_set_sim, fail, run_main


def blob(q):
    return (q.get("stem", q.get("question", "")) or "") + " " + " ".join((o.get("text", "") or "") for o in (q.get("options") or []))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("bank")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.bank):
        fail("file not found: %s" % a.bank)
    b = load_json(a.bank)
    qs = b.get("questions") if isinstance(b, dict) else b
    # ponytail: O(n^2) pairwise scan; blocking/index if banks grow past ~10k
    pairs = []
    for x, y in itertools.combinations(qs, 2):
        s = token_set_sim(blob(x), blob(y))
        if s >= a.threshold:
            pairs.append({"a": x.get("id"), "b": y.get("id"), "similarity": round(s, 3)})
    out = {"threshold": a.threshold, "pairs": pairs, "count": len(pairs)}
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.bank)), "dedupe_report.json")
    save_json(dest, out)
    print("dedupe: %d near-duplicate pairs (thr=%.2f) -> %s" % (len(pairs), a.threshold, dest))
    for p in pairs:
        print("  %s ~ %s (%.3f)" % (p["a"], p["b"], p["similarity"]))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
