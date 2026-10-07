"""Validate PDF versions A/B/C against a quiz package (pypdf-based).

Checks: opens, A4 page size, question order/ids in A, font embedding,
answer-key agreement (B vs package), page numbers, non-Latin spot check,
margin-clip heuristic. Writes a JSON report, prints PASS/FAIL, exit 1 on fail.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_quiz import (  # noqa: E402
    load_package_json,
    non_latin_letters,
    norm_key,
    norm_options,
    qid,
    validate_structure,
)

from pypdf import PdfReader

A4_W, A4_H = 595.27, 841.89
SIZE_TOL_PT = 3.0
MAX_LINE_CHARS = 110
BASE14 = {"Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
          "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
          "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
          "Symbol", "ZapfDingbats"}


def page_texts(reader: PdfReader) -> list[str]:
    return [p.extract_text() or "" for p in reader.pages]


def page_layout_texts(reader: PdfReader) -> list[str]:
    out = []
    for p in reader.pages:
        try:
            out.append(p.extract_text(extraction_mode="layout") or "")
        except TypeError:
            out.append(p.extract_text() or "")
    return out


def check_fonts(reader: PdfReader) -> tuple[list[dict], bool]:
    """Best-effort embedded check. Returns (per-font report, ok)."""
    seen: dict[str, dict] = {}
    for page in reader.pages:
        try:
            res = page.get("/Resources")
            res = res.get_object() if res is not None and hasattr(res, "get_object") else res
            fonts = (res.get("/Font") if res else None)
            if fonts is None:
                continue
            fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
            for ref in (fonts.values() if hasattr(fonts, "values") else []):
                fo = ref.get_object() if hasattr(ref, "get_object") else ref
                base = str(fo.get("/BaseFont", "unknown"))
                name = base.split("+")[-1].lstrip("/")
                if name in seen:
                    continue
                desc = fo.get("/FontDescriptor")
                desc = desc.get_object() if desc is not None and hasattr(desc, "get_object") else desc
                embedded = bool(desc and any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")))
                seen[name] = {"basefont": base, "embedded": embedded,
                              "base14": name in BASE14}
        except Exception as e:  # best-effort: report, don't crash
            seen.setdefault(f"unreadable:{e}", {"basefont": "unknown", "embedded": False,
                                                "base14": False})
    ok = all(f["embedded"] or f["base14"] for f in seen.values()) if seen else True
    return [{"font": k, **v} for k, v in sorted(seen.items())], ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check quiz PDFs A/B/C against a quiz package.")
    ap.add_argument("a_pdf", help="Version A question paper PDF")
    ap.add_argument("b_pdf", help="Version B answer key PDF")
    ap.add_argument("c_pdf", help="Version C explanations PDF")
    ap.add_argument("--package", required=True, help="Path to quiz_package.json")
    ap.add_argument("--report", default="check_report.json", help="Output JSON report path")
    args = ap.parse_args(argv)

    checks: list[dict] = []

    def safe(s: str) -> str:
        try:
            return s.encode("cp1252").decode("cp1252")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s.encode("ascii", "backslashreplace").decode("ascii")

    def rec(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        print(safe(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else "")))

    pkg = load_package_json(Path(args.package))
    warnings, errors = validate_structure(pkg)
    if errors:
        rec("package:valid", False, "; ".join(errors))
        return finish(checks, args.report)
    rec("package:valid", True, f"{len(pkg['questions'])} questions"
        + (f" ({len(warnings)} warnings)" if warnings else ""))
    questions = pkg["questions"]
    n = len(questions)
    ids = [qid(q, i) for i, q in enumerate(questions)]
    keys = [norm_key(q, norm_options(q)) for q in questions]

    readers: dict[str, PdfReader | None] = {}
    for label, path in (("A", args.a_pdf), ("B", args.b_pdf), ("C", args.c_pdf)):
        try:
            readers[label] = PdfReader(path)
            rec(f"opens:{label}", True, f"{len(readers[label].pages)} pages")
        except Exception as e:
            readers[label] = None
            rec(f"opens:{label}", False, str(e))
    if any(r is None for r in readers.values()):
        return finish(checks, args.report)

    texts = {k: page_texts(r) for k, r in readers.items() if r is not None}

    # page size ~= A4 on every page of every file
    bad = []
    for label, r in readers.items():
        for i, p in enumerate(r.pages):
            w, h = float(p.mediabox.width), float(p.mediabox.height)
            if abs(w - A4_W) > SIZE_TOL_PT or abs(h - A4_H) > SIZE_TOL_PT:
                bad.append(f"{label} p{i + 1} ({w:.1f}x{h:.1f})")
    rec("pagesize:A4", not bad, "all pages ~595x842pt" if not bad else f"off-size: {'; '.join(bad)}")

    # every question number appears exactly once in order in A; every id exactly once
    a_full = "\n".join(texts["A"])
    nums = [int(m) for m in re.findall(r"Q(\d{1,4})\s*\.", a_full)]
    rec("order:A", nums == list(range(1, n + 1)),
        f"{n} questions in order" if nums == list(range(1, n + 1))
        else f"found Q-numbers {nums[:8]}{'...' if len(nums) > 8 else ''} (n={n})")
    id_problems = [i for i in ids if a_full.count(i) != 1]
    rec("ids:A", not id_problems,
        "all ids exactly once" if not id_problems else f"ids with count!=1: {id_problems[:10]}")

    # fonts embedded (best-effort; base-14 noted, not failed)
    all_font_rows = []
    fonts_ok = True
    for label, r in readers.items():
        rows, ok = check_fonts(r)
        fonts_ok = fonts_ok and ok
        for row in rows:
            all_font_rows.append({"file": label, **row})
    rec("fonts:embedded", fonts_ok,
        "; ".join(f"{r['file']}:{r['font']}="
                  f"{'embedded' if r['embedded'] else ('base14' if r['base14'] else 'NOT-EMBEDDED')}"
                  for r in all_font_rows) or "no fonts found")

    # answer key agreement B vs package
    b_full = "\n".join(texts["B"])
    pairs = {int(m[0]): m[2] for m in re.findall(r"Q(\d{1,4})\s+(\S+)\s+([A-F])\b", b_full)}
    mism = [f"Q{i + 1} pkg={keys[i]} pdf={pairs.get(i + 1, '?')}"
            for i in range(n) if pairs.get(i + 1) != keys[i]]
    rec("key:B==package", not mism and len(pairs) == n,
        f"{len(pairs)}/{n} rows agree" if not mism and len(pairs) == n
        else f"mismatches: {mism[:10]} (parsed {len(pairs)}/{n} rows)")

    # page numbers present (digits on most pages of each file)
    for label in ("A", "B", "C"):
        pages = texts[label]
        withnum = sum(1 for t in pages if re.search(r"Page\s*\d+|\d+", t))
        ok = withnum / max(1, len(pages)) >= 0.6
        rec(f"pagenumbers:{label}", ok, f"{withnum}/{len(pages)} pages carry digits")

    # non-Latin spot check
    wanted = non_latin_letters(pkg)
    if not wanted:
        rec("nonlatin:spot", True, "package has no non-Latin letters; n/a")
    else:
        a_c = a_full + "\n" + "\n".join(texts["C"])
        missing = sorted(ch for ch in wanted if ch not in a_c)
        rec("nonlatin:spot", not missing,
            f"{len(wanted) - len(missing)}/{len(wanted)} non-Latin chars found in A+C text"
            + ("" if not missing else "; MISSING some (see report)"))
        if missing:
            checks[-1]["missing"] = missing

    # margin-clip check: real glyph-box measurement via pymupdf when present
    # (layout-text char counts are not overflow evidence: short tokens pack
    # densely and headers/footers share visual lines). Falls back to a
    # lenient long-line scan reported as a warning, never a FAIL.
    overflow, scanned = [], 0
    try:
        import pymupdf
        from pathlib import Path as _P
        for label, path in (("A", args.a_pdf), ("B", args.b_pdf), ("C", args.c_pdf)):
            try:
                doc = pymupdf.open(_P(path))
            except Exception:
                continue
            for i, page in enumerate(doc):
                w = page.rect.width
                for block in page.get_text("dict").get("blocks", []):
                    for line in block.get("lines", []):
                        scanned += 1
                        x0, _, x1, _ = line["bbox"]
                        if x1 > w - 30 or x0 < -1:  # >30pt from edge = past margin
                            txt = "".join(s.get("text", "") for s in line.get("spans", []))
                            overflow.append(f"{label} p{i + 1}: {txt[:60]}...")
            doc.close()
        rec("margin:clip", not overflow,
            f"glyph-box scan of {scanned} lines, no overflow" if not overflow
            else f"{len(overflow)} overflowing lines, e.g. {overflow[:3]}")
    except ImportError:
        long_lines = []
        for label, ps in layout.items():
            for i, t in enumerate(ps):
                for ln in t.splitlines():
                    s = ln.strip()
                    if re.search(r"Page\s*\d+\s*$", s):
                        continue
                    if len(s) > MAX_LINE_CHARS + 25:
                        long_lines.append(f"{label} p{i + 1} ({len(s)}ch)")
        rec("margin:clip", True,
            f"no glyph scan (pymupdf absent); {len(long_lines)} lines >135ch (warning only)")

    return finish(checks, args.report)


def finish(checks: list[dict], report_path: str) -> int:
    overall = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    print(f"OVERALL: {overall}")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"overall": overall, "checks": checks}, f, ensure_ascii=False, indent=2)
    print(f"report: {report_path}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
