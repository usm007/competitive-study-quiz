import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, fail, run_main

TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")


def jtype(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def ok_type(v, t):
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return jtype(v) == t


def check(node, sch, path, errs):
    if not isinstance(sch, dict):
        return
    t = sch.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        if not any(ok_type(node, x) for x in ts):
            errs.append("%s: expected type %s, got %s" % (path, t, jtype(node)))
            return
    if "enum" in sch and node not in sch["enum"]:
        errs.append("%s: value %r not in allowed enum %s" % (path, node, sch["enum"]))
    if "const" in sch and node != sch["const"]:
        errs.append("%s: value %r != const %r" % (path, node, sch["const"]))
    if isinstance(node, dict):
        for r in sch.get("required", []) or []:
            if r not in node:
                errs.append("%s: missing required property '%s'" % (path, r))
        props = sch.get("properties", {}) or {}
        pats = sch.get("patternProperties", {}) or {}
        for k, v in node.items():
            if k in props:
                check(v, props[k], "%s.%s" % (path, k), errs)
                continue
            matched = False
            for pat, sub in pats.items():
                if re.search(pat, k):
                    check(v, sub, "%s.%s" % (path, k), errs)
                    matched = True
                    break
            if not matched and sch.get("additionalProperties") is False:
                errs.append("%s: additional property '%s' not allowed by schema" % (path, k))
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in sch and node < sch["minimum"]:
            errs.append("%s: value %s < minimum %s" % (path, node, sch["minimum"]))
        if "maximum" in sch and node > sch["maximum"]:
            errs.append("%s: value %s > maximum %s" % (path, node, sch["maximum"]))
    if isinstance(node, str):
        if "minLength" in sch and len(node) < sch["minLength"]:
            errs.append("%s: length %d < minLength %s" % (path, len(node), sch["minLength"]))
        if "maxLength" in sch and len(node) > sch["maxLength"]:
            errs.append("%s: length %d > maxLength %s" % (path, len(node), sch["maxLength"]))
        if "pattern" in sch and not re.search(sch["pattern"], node):
            errs.append("%s: value %r does not match pattern %s" % (path, node, sch["pattern"]))
    if isinstance(node, list):
        if "minItems" in sch and len(node) < sch["minItems"]:
            errs.append("%s: count %d < minItems %s" % (path, len(node), sch["minItems"]))
        if "maxItems" in sch and len(node) > sch["maxItems"]:
            errs.append("%s: count %d > maxItems %s" % (path, len(node), sch["maxItems"]))
        if "items" in sch:
            for i, v in enumerate(node):
                check(v, sch["items"], "%s[%d]" % (path, i), errs)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--schema", required=True)
    a = ap.parse_args(argv)
    if not os.path.isfile(a.file):
        fail("file not found: %s" % a.file)
    if not os.path.isfile(a.schema):
        fail("schema not found: %s" % a.schema)
    doc = load_json(a.file)
    sch = load_json(a.schema)
    errs = []
    check(doc, sch, "$", errs)
    if errs:
        print("schema FAIL: %d errors" % len(errs))
        for e in errs:
            print("  " + e)
        print("schema FAIL: %d errors" % len(errs), file=sys.stderr)
        return 1
    print("schema OK: %s conforms to %s" % (a.file, a.schema))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
