"""Build a standalone Study Module HTML file from a quiz package.

Reads the self-contained template (templates/web/app.template.html),
embeds the package JSON at the /*__PACKAGE__*/{} placeholder, the
package status at the /*__STATUS__*/"" placeholder, and the revision engine,
and writes the result with StudySynth branding and dynamic clean title metadata.

Verifies the embedded JSON parses and round-trips identically; fails loudly
otherwise. Accepts both the delivery shape (meta + questions) and the
canonical pipeline shape (run_id/profile/package_status + questions).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_quiz import (  # noqa: E402
    eff_meta,
    load_package_json,
    resolve_profile,
    validate_structure,
)
from naming import parse_clean_title  # noqa: E402

HERE = Path(__file__).resolve()
DEFAULT_TEMPLATE = HERE.parent.parent / "templates" / "web" / "app.template.html"
DEFAULT_ENGINE = HERE.parent.parent / "templates" / "web" / "revision.engine.js"
PROFILES_DIR = HERE.parent.parent / "profiles"
PKG_PLACEHOLDER = "/*__PACKAGE__*/{}"
STATUS_PLACEHOLDER = '/*__STATUS__*/""'
ENGINE_PLACEHOLDER = "/*__REVISION_ENGINE__*/"


def prepare_package(package_path: Path, title: str | None = None) -> tuple[dict, str]:
    pkg = load_package_json(package_path)
    warnings, errors = validate_structure(pkg)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        raise SystemExit(f"ERROR: invalid package {package_path}:\n  " + "\n  ".join(errors))

    pkg = json.loads(json.dumps(pkg, ensure_ascii=False))  # deep copy
    m = pkg.get("meta")
    if not isinstance(m, dict):
        m = {}
        pkg["meta"] = m

    # Determine clean title
    clean_t = title
    if not clean_t:
        raw_t = m.get("title")
        if raw_t and raw_t not in ("Exam Quiz", "Study Quiz", "Competitive Quiz", "Study Module"):
            clean_t = parse_clean_title(raw_t)
        elif m.get("source"):
            clean_t = parse_clean_title(m["source"])
        elif pkg.get("run_id"):
            clean_t = parse_clean_title(pkg["run_id"])
    if not clean_t:
        clean_t = "Study Module"

    m["title"] = clean_t

    prof = resolve_profile(pkg, None, PROFILES_DIR)
    if isinstance(prof, dict) and prof.get("negative_marking"):
        if not isinstance(m.get("profile"), dict):
            m["profile"] = prof
            print(f"profile: embedded resolved profile {prof.get('name', '?')}", file=sys.stderr)

    return pkg, clean_t


def extract_braced(text: str, marker: str) -> str:
    start = text.find(marker)
    if start < 0:
        raise SystemExit("ERROR: written file lost the embedded package marker")
    i = text.find("{", start + len(marker))
    depth, instr, esc = 0, False, False
    for j in range(i, len(text)):
        ch = text[j]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise SystemExit("ERROR: could not re-extract embedded JSON from written file")


def build(package_path: Path, out_path: Path, template: Path, title: str | None) -> Path:
    pkg, clean_title = prepare_package(package_path, title=title)
    try:
        tpl = template.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"ERROR: cannot read template {template}: {e}")
    if PKG_PLACEHOLDER not in tpl:
        raise SystemExit(f"ERROR: template missing package placeholder {PKG_PLACEHOLDER!r}: {template}")
    if STATUS_PLACEHOLDER not in tpl:
        raise SystemExit(f"ERROR: template missing status placeholder {STATUS_PLACEHOLDER!r}: {template}")
    if ENGINE_PLACEHOLDER not in tpl:
        raise SystemExit(f"ERROR: template missing revision-engine placeholder {ENGINE_PLACEHOLDER!r}: {template}")
    try:
        engine_js = DEFAULT_ENGINE.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"ERROR: cannot read revision engine {DEFAULT_ENGINE}: {e}")
    if "RevisionEngine" not in engine_js:
        raise SystemExit(f"ERROR: revision engine does not define RevisionEngine: {DEFAULT_ENGINE}")

    status = eff_meta(pkg)["status"]
    embedded_pkg = json.dumps(pkg, ensure_ascii=False, separators=(",", ":"))
    embedded_status = json.dumps(status if isinstance(status, str) else str(status), ensure_ascii=False)

    # Round-trip check BEFORE writing.
    try:
        reparsed = json.loads(embedded_pkg)
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: embedded package JSON does not parse: {e}")
    if reparsed != pkg:
        raise SystemExit("ERROR: embedded package JSON round-trip mismatch (reparsed != original)")

    out = tpl.replace(PKG_PLACEHOLDER, "/*__PACKAGE__*/" + embedded_pkg, 1)
    out = out.replace(STATUS_PLACEHOLDER, "/*__STATUS__*/" + embedded_status, 1)
    out = out.replace(ENGINE_PLACEHOLDER, engine_js, 1)
    if PKG_PLACEHOLDER in out or STATUS_PLACEHOLDER in out or ENGINE_PLACEHOLDER in out:
        raise SystemExit("ERROR: placeholder replacement incomplete; duplicate placeholders in template")

    # Dynamic <title> tag replacement
    page_title = f"{clean_title} — StudySynth"
    out = re.sub(r"<title>.*?</title>", f"<title>{html.escape(page_title)}</title>", out, count=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")

    # Round-trip check AFTER writing.
    reread = out_path.read_text(encoding="utf-8")
    try:
        final = json.loads(extract_braced(reread, "/*__PACKAGE__*/"))
    except (json.JSONDecodeError, SystemExit) as e:
        raise SystemExit(f"ERROR: written file's embedded JSON unusable: {e}")
    if final != pkg:
        raise SystemExit("ERROR: written file round-trip mismatch (file payload != package)")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build standalone Study Module HTML from a package.")
    ap.add_argument("package", help="Path to quiz_package.json")
    ap.add_argument("--out", required=True, help="Output .html file")
    ap.add_argument("--title", default=None, help="Override the clean module title")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Template HTML file")
    ap.add_argument("--dashboard", default=None, help="Path to master index.html dashboard to update")
    args = ap.parse_args(argv)

    out = build(Path(args.package), Path(args.out), Path(args.template), args.title)

    if args.dashboard:
        from dashboard import update_dashboard
        meta = eff_meta(load_package_json(Path(args.package)))
        clean_t = args.title or meta.get("title") or parse_clean_title(out.stem)
        update_dashboard(
            dashboard_path=args.dashboard,
            module_path=out,
            title=clean_t,
            metadata={"status": meta.get("status"), "question_count": len(load_package_json(Path(args.package)).get("questions", []))},
        )

    print(f"OK: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
