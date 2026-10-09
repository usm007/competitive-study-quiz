"""Deterministic Packaging Validator for Final User Delivery (DocToQuiz / Competitive Study Quiz).

Validates that a delivery package folder contains ONLY:
  1. Exactly ONE self-contained .html file
  2. Exactly ONE print-ready .pdf file
and nothing else.

Verifies:
- No extra files, JSONs, or subdirectories leak into the delivery folder.
- PDF is valid, opens in pypdf, and has >= 1 page.
- HTML is completely standalone: inlined CSS, inlined JS, embedded questions.
- HTML contains NO external stylesheet links, script tags, asset image paths,
  fetch() runtime calls, module imports, or remote dependencies.
- HTML functions seamlessly under the file:// protocol.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader


def extract_embedded_package(html_content: str) -> dict | None:
    marker = "/*__PACKAGE__*/"
    start = html_content.find(marker)
    if start < 0:
        return None
    i = html_content.find("{", start + len(marker))
    if i < 0:
        return None
    depth, instr, esc = 0, False, False
    for j in range(i, len(html_content)):
        ch = html_content[j]
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
                try:
                    return json.loads(html_content[i:j + 1])
                except Exception:
                    return None
    return None


def validate_html_standalone(html_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = html_path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"Cannot read HTML file {html_path.name}: {e}"]

    if len(text) < 1000:
        errors.append(f"HTML file {html_path.name} is suspiciously small ({len(text)} bytes)")

    if "<!DOCTYPE html>" not in text and "<!doctype html>" not in text:
        errors.append(f"HTML file {html_path.name} is missing <!DOCTYPE html>")

    # Check for inlined CSS
    if "<style>" not in text or "</style>" not in text:
        errors.append(f"HTML file {html_path.name} is missing inline <style> block")
    else:
        for token in ["--bg", "--ink", "--accent", "--line"]:
            if token not in text:
                errors.append(f"HTML file {html_path.name} is missing core CSS token {token}")

    # Check for inlined JavaScript
    if "<script>" not in text or "</script>" not in text:
        errors.append(f"HTML file {html_path.name} is missing inline <script> block")
    else:
        for symbol in ["RevisionEngine", "normOptions", "render"]:
            if symbol not in text:
                errors.append(f"HTML file {html_path.name} is missing core JS logic {symbol}")

    # Check embedded package JSON
    pkg = extract_embedded_package(text)
    if pkg is None:
        errors.append(f"HTML file {html_path.name} is missing or has corrupted embedded package JSON")
    else:
        questions = pkg.get("questions")
        if not isinstance(questions, list) or len(questions) == 0:
            errors.append(f"HTML file {html_path.name} contains zero embedded questions")
        else:
            first_q = questions[0]
            if not isinstance(first_q, dict) or not (first_q.get("stem") or first_q.get("question")):
                errors.append(f"HTML file {html_path.name} has invalid question structure")

    # Anti-dependency check 1: No external CSS (<link rel="stylesheet">)
    link_matches = re.findall(r'<link[^>]+rel=["\']?stylesheet["\']?[^>]*>', text, re.IGNORECASE)
    for m in link_matches:
        errors.append(f"External stylesheet link found in HTML: {m}")

    # Anti-dependency check 2: No external scripts (<script src=...>)
    script_srcs = re.findall(r'<script[^>]+src=["\']?([^"\'\s>]+)["\']?[^>]*>', text, re.IGNORECASE)
    for s in script_srcs:
        errors.append(f"External script src dependency found in HTML: {s}")

    # Anti-dependency check 3: No external or local file img tags (<img src="...">)
    # data: URIs and empty placeholders are acceptable; relative file references or http(s) are forbidden.
    img_srcs = re.findall(r'<img[^>]+src=["\']?([^"\'\s>]+)["\']?[^>]*>', text, re.IGNORECASE)
    for src in img_srcs:
        if not src.startswith("data:"):
            errors.append(f"Unbundled image src dependency found in HTML: {src}")

    # Anti-dependency check 4: No external font/CDN URLs (Google Fonts, unpkg, cdnjs, etc.)
    cdns = ["fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com"]
    for cdn in cdns:
        if cdn in text:
            errors.append(f"Remote CDN dependency found in HTML: {cdn}")

    # Anti-dependency check 5: No runtime fetch() or XMLHttpRequest calls for local runtime data
    if re.search(r'\bfetch\s*\(', text):
        errors.append(f"Runtime fetch() call found in HTML; all data must be embedded directly")
    if re.search(r'\bnew\s+XMLHttpRequest\s*\(', text):
        errors.append(f"Runtime XMLHttpRequest found in HTML; all data must be embedded directly")

    # Anti-dependency check 6: No ES module imports
    if re.search(r'\bimport\s+.*\s+from\s+["\']', text):
        errors.append(f"ES module import found in HTML")
    if re.search(r'\bimport\s*\(["\']', text):
        errors.append(f"Dynamic import() found in HTML")

    # Anti-dependency check 7: No references to local asset directories in attributes
    for attr in re.findall(r'(?:src|href)=["\']([^"\'#]+)["\']', text):
        if any(attr.startswith(d) for d in ["assets/", "data/", "scripts/", "styles/", "./", "../"]):
            errors.append(f"Local relative asset dependency found in HTML attribute: {attr}")

    return errors


def validate_pdf(pdf_path: Path) -> list[str]:
    errors: list[str] = []
    if not pdf_path.is_file():
        return [f"PDF file does not exist: {pdf_path.name}"]
    size = pdf_path.stat().st_size
    if size < 500:
        errors.append(f"PDF file {pdf_path.name} is too small ({size} bytes)")

    try:
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                errors.append(f"PDF file {pdf_path.name} lacks valid %PDF- header")
    except Exception as e:
        errors.append(f"Failed to read PDF {pdf_path.name}: {e}")
        return errors

    try:
        reader = PdfReader(str(pdf_path))
        num_pages = len(reader.pages)
        if num_pages == 0:
            errors.append(f"PDF file {pdf_path.name} has 0 pages")
    except Exception as e:
        errors.append(f"Failed to parse PDF {pdf_path.name} with PdfReader: {e}")

    return errors


def validate_package(package_dir: Path) -> tuple[bool, list[str]]:
    """Validate a single final deliverable quiz package folder.
    
    Must contain:
      - Exactly ONE .html file
      - Exactly ONE .pdf file
      - ZERO extra files, JSONs, or subdirectories.
    """
    errors: list[str] = []
    p = Path(package_dir)
    if not p.is_dir():
        return False, [f"Package target is not a directory: {p}"]

    children = list(p.iterdir())
    if not children:
        return False, [f"Package directory is empty: {p}"]

    # Check for forbidden subdirectories
    subdirs = [c for c in children if c.is_dir()]
    if subdirs:
        for sd in subdirs:
            errors.append(f"Forbidden subdirectory in final delivery package: {sd.name}")

    # Check for forbidden files (index.html is permitted as master dashboard library)
    files = [c for c in children if c.is_file() and c.name != "index.html"]
    html_files = [f for f in files if f.suffix.lower() == ".html"]
    pdf_files = [f for f in files if f.suffix.lower() == ".pdf"]
    other_files = [f for f in files if f.suffix.lower() not in (".html", ".pdf")]

    for of in other_files:
        errors.append(f"Forbidden file in final delivery package: {of.name} (only 1 PDF and 1 HTML allowed)")

    if len(html_files) != 1:
        errors.append(f"Expected exactly 1 HTML file, found {len(html_files)}: {[f.name for f in html_files]}")
    if len(pdf_files) != 1:
        errors.append(f"Expected exactly 1 PDF file, found {len(pdf_files)}: {[f.name for f in pdf_files]}")

    if html_files:
        html_errors = validate_html_standalone(html_files[0])
        errors.extend(html_errors)

    if pdf_files:
        pdf_errors = validate_pdf(pdf_files[0])
        errors.extend(pdf_errors)

    return (len(errors) == 0), errors


def validate_delivery_dir(delivery_root: Path, mode: str = "auto") -> tuple[bool, list[str]]:
    """Validate an entire delivery root directory containing one or more packages."""
    root = Path(delivery_root)
    if not root.is_dir():
        return False, [f"Delivery root is not a directory: {root}"]

    errors: list[str] = []
    # Check if this root itself is a single package directory (has .html/.pdf and no child package dirs)
    child_dirs = [d for d in root.iterdir() if d.is_dir()]
    direct_html = [f for f in root.glob("*.html") if f.name != "index.html"]
    direct_pdf = list(root.glob("*.pdf"))
    if not child_dirs and (direct_html or direct_pdf):
        ok, errs = validate_package(root)
        return ok, errs

    # Otherwise look for subfolders
    indiv_dir = root / "Individual"
    unified_dir = root / "Unified"

    if mode in ("both", "auto") and indiv_dir.is_dir() and unified_dir.is_dir():
        # Both mode layout
        indiv_pkgs = [d for d in indiv_dir.iterdir() if d.is_dir()]
        if not indiv_pkgs:
            errors.append("No individual package directories found in Individual/")
        for ipkg in indiv_pkgs:
            ok, errs = validate_package(ipkg)
            if not ok:
                errors.extend([f"[{ipkg.name}] {e}" for e in errs])

        unified_pkgs = [d for d in unified_dir.iterdir() if d.is_dir()]
        if not unified_pkgs:
            # Check if Unified/ itself has the PDF and HTML
            u_html = list(unified_dir.glob("*.html"))
            u_pdf = list(unified_dir.glob("*.pdf"))
            if len(u_html) == 1 and len(u_pdf) == 1:
                ok, errs = validate_package(unified_dir)
                if not ok:
                    errors.extend([f"[Unified] {e}" for e in errs])
            else:
                errors.append("No master package found in Unified/")
        else:
            for upkg in unified_pkgs:
                ok, errs = validate_package(upkg)
                if not ok:
                    errors.extend([f"[{upkg.name}] {e}" for e in errs])
        return (len(errors) == 0), errors

    # Check child directories as packages
    child_dirs = [d for d in root.iterdir() if d.is_dir()]
    if not child_dirs:
        return False, [f"No package subdirectories found in {root}"]

    for cd in child_dirs:
        ok, errs = validate_package(cd)
        if not ok:
            errors.extend([f"[{cd.name}] {e}" for e in errs])

    return (len(errors) == 0), errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate final user delivery package folder(s).")
    ap.add_argument("path", help="Path to package directory or delivery root directory")
    ap.add_argument("--mode", choices=["auto", "single", "individual", "unified", "both"], default="auto")
    args = ap.parse_args(argv)

    target = Path(args.path)
    if not target.exists():
        print(f"FAIL: target does not exist: {target}", file=sys.stderr)
        return 1

    has_direct_package = target.is_dir() and any(f.name != "index.html" for f in target.glob("*.html")) and list(target.glob("*.pdf"))
    if args.mode == "single" or has_direct_package:
        ok, errors = validate_package(target)
    else:
        ok, errors = validate_delivery_dir(target, args.mode)

    if ok:
        print(f"PASS: delivery package validation succeeded for {target}")
        return 0
    else:
        print(f"FAIL: delivery package validation failed for {target}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
