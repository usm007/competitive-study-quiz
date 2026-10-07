import difflib
import json
import os
import re
import sys
import unicodedata


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)


def fail(msg, code=1):
    print("error: %s" % msg, file=sys.stderr)
    raise SystemExit(code)


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower()
    return re.sub(r"\s+", " ", s).strip()


def toks(s):
    return re.findall(r"[a-z0-9]+", norm(s))


def token_set_sim(a, b):
    sa, sb = set(toks(a)), set(toks(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    # ponytail: naive Jaccard on raw tokens, no stemming/synonyms; upgrade if paraphrase dupes slip through
    return len(sa & sb) / len(sa | sb)


def norm_sim(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def resolve_out(out, run_id, fname):
    if out.endswith(".json"):
        return out
    base = out
    if run_id and os.path.basename(os.path.normpath(out)) != run_id:
        base = os.path.join(out, run_id)
    ensure_dir(base)
    return os.path.join(base, fname)


def run_main(fn, argv):
    try:
        return fn(argv)
    except SystemExit:
        raise
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
