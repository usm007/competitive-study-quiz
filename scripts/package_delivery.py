"""Final User Delivery Packager (StudySynth / Study Modules).

Generates strictly self-contained, user-facing Study Module deliverables:
  1. EXACTLY ONE .pdf file (print-ready question paper, answer key, and explanation booklet)
  2. EXACTLY ONE standalone .html file (Study Desk web application, 100% offline, file:// ready)
  3. Master Library Dashboard (index.html) in root delivery directory linking all modules
  4. Desktop shortcut pointing to the master library dashboard

Modes supported:
  - INDIVIDUAL: N source packages -> N independent delivery folders (01_Doc, 02_Doc, ...)
  - UNIFIED: N source packages -> 1 consolidated master delivery folder (StudySynth_Master)
  - BOTH: Generates both Individual/ and Unified/ trees.

Validates that NO internal build artifacts (JSONs, raw assets, tmp files) leak
into the final output directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_pdf
import build_web
from dashboard import update_dashboard
from dedupe import detect_duplicates
from desktop_shortcut import create_desktop_shortcut
from lib_quiz import eff_meta, load_package_json, validate_structure
from naming import parse_clean_title, generate_slug
from validate_package_delivery import validate_delivery_dir, validate_package


def sanitize_name(raw_name: str, default_suffix: str = "Quiz") -> str:
    """Produce a safe, human-readable identifier (e.g. Indian_Polity_Quiz)."""
    # Strip common file extensions
    s = re.sub(r"\.(pdf|json|html|md|txt|docx|pptx)$", "", raw_name, flags=re.IGNORECASE)
    # Replace non-alphanumeric with underscores
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s).strip("_")
    if not s:
        s = "Study"
    # Ensure human-readable title casing where applicable
    parts = s.split("_")
    cased_parts = [p.capitalize() if p.islower() else p for p in parts]
    clean = "_".join(cased_parts)
    if not clean.lower().endswith("quiz") and not clean.lower().endswith("master") and not clean.lower().endswith("module"):
        clean = f"{clean}_{default_suffix}"
    return clean


def unify_packages(
    packages: list[dict],
    master_title: str = "StudySynth Master",
    profile: str | dict | None = None,
) -> dict:
    """Merge multiple study packages into a single unified master package.

    Preserves:
    - Cross-document provenance
    - Knowledge-unit relationships
    - Deduplication
    - Source attribution
    """
    if not packages:
        raise ValueError("Cannot unify empty list of packages")

    all_questions: list[dict] = []
    merged_ku_excerpts: dict[str, str] = {}
    source_names: list[str] = []
    profiles: list = []

    for pkg_idx, pkg in enumerate(packages):
        meta = eff_meta(pkg)
        doc_label = meta.get("title") or meta.get("source") or f"Document_{pkg_idx + 1}"
        source_names.append(doc_label)
        if meta.get("profile"):
            profiles.append(meta["profile"])

        # Merge KU excerpts
        excerpts = pkg.get("ku_excerpts") or {}
        if isinstance(excerpts, dict):
            for k, v in excerpts.items():
                if k not in merged_ku_excerpts:
                    merged_ku_excerpts[k] = v

        # Collect questions with provenance stamped
        qs = pkg.get("questions") or []
        for q in qs:
            q_copy = json.loads(json.dumps(q, ensure_ascii=False))
            # Preserve or stamp provenance
            if "source_document" not in q_copy:
                q_copy["source_document"] = doc_label
            all_questions.append(q_copy)

    # Cross-document deduplication
    dup_res = detect_duplicates(all_questions, threshold=0.88)
    dup_pairs = dup_res[0] if isinstance(dup_res, tuple) else dup_res
    exclude_ids = set()
    for d in dup_pairs:
        # Exclude second occurrence of duplicate question
        if isinstance(d, dict) and d.get("type") in ("exact_duplicate", "semantic_duplicate"):
            exclude_ids.add(d["b"])

    filtered_questions = [q for q in all_questions if q.get("id") not in exclude_ids]

    # Re-index questions cleanly if needed, while recording original IDs in metadata
    unified_questions = []
    for i, q in enumerate(filtered_questions):
        orig_id = q.get("id") or f"Q{i + 1:03d}"
        q["original_id"] = orig_id
        q["id"] = f"Q{i + 1:04d}"
        unified_questions.append(q)

    # Master profile
    master_profile = profile or (profiles[0] if profiles else "GENERAL_PSC")

    unified_pkg = {
        "meta": {
            "title": master_title,
            "source": f"Unified Corpus ({len(source_names)} documents: {', '.join(source_names[:5])}{'...' if len(source_names) > 5 else ''})",
            "profile": master_profile,
            "status": "COMPREHENSIVE",
            "sources": source_names,
            "question_count": len(unified_questions),
            "deduped_count": len(exclude_ids),
        },
        "questions": unified_questions,
        "ku_excerpts": merged_ku_excerpts,
    }
    return unified_pkg


def package_single(
    pkg: dict,
    out_dir: Path,
    base_name: str,
    profile: str | dict | None = None,
    title: str | None = None,
) -> tuple[Path, Path]:
    """Compile and package exactly ONE PDF and ONE HTML into out_dir.

    Verifies that no extra files exist in out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html_name = f"{base_name}.html"
    pdf_name = f"{base_name}.pdf"
    html_path = out_dir / html_name
    pdf_path = out_dir / pdf_name

    meta = eff_meta(pkg)
    disp_title = title or meta.get("title") or parse_clean_title(base_name)

    # 1. Build standalone HTML
    build_web.build(
        package_path=None if isinstance(pkg, dict) else Path(pkg),
        out_path=html_path,
        template=build_web.DEFAULT_TEMPLATE,
        title=disp_title,
    ) if not isinstance(pkg, dict) else _build_web_from_dict(pkg, html_path, disp_title)

    # 2. Build single combined PDF
    build_pdf.build_single_pdf(
        pkg=pkg,
        out_pdf=pdf_path,
        profile=profile or meta.get("profile"),
    )

    # 3. Clean any rogue files in out_dir that aren't the PDF, HTML, or dashboard
    for child in list(out_dir.iterdir()):
        if child.name not in (html_name, pdf_name, "index.html"):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)

    # 4. Run deterministic validation
    ok, errors = validate_package(out_dir)
    if not ok:
        raise RuntimeError(f"Package validation failed for {out_dir}:\n  " + "\n  ".join(errors))

    return html_path, pdf_path


def _build_web_from_dict(pkg: dict, out_path: Path, title: str | None) -> Path:
    """Helper to run build_web directly on a package dict."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as tmp:
        json.dump(pkg, tmp, ensure_ascii=False)
        tmp_path = Path(tmp.name)
    try:
        return build_web.build(tmp_path, out_path, build_web.DEFAULT_TEMPLATE, title)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def execute_packaging(
    package_inputs: list[dict | Path | str],
    out_dir: Path,
    mode: str = "individual",
    master_title: str = "StudySynth Master",
    profile: str | dict | None = None,
) -> dict:
    """Main execution orchestrator for Individual, Unified, and Both modes.

    Returns a dictionary of generated deliverable paths and updates the master dashboard.
    """
    mode = mode.lower()
    if mode not in ("individual", "unified", "both"):
        raise ValueError(f"Invalid output mode '{mode}'; expected 'individual', 'unified', or 'both'")

    # Load packages
    packages: list[dict] = []
    item_names: list[str] = []
    for item in package_inputs:
        if isinstance(item, dict):
            packages.append(item)
            item_names.append(eff_meta(item).get("title") or "Study_Quiz")
        else:
            p = Path(item)
            if p.is_file():
                pkg = load_package_json(p)
                packages.append(pkg)
                item_names.append(p.stem)
            elif p.is_dir():
                cand = p / "quiz_package.json"
                if cand.is_file():
                    pkg = load_package_json(cand)
                    packages.append(pkg)
                    item_names.append(p.name)
                else:
                    raise FileNotFoundError(f"No quiz_package.json in directory: {p}")
            else:
                raise FileNotFoundError(f"Package input not found: {p}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict[str, str]]] = {"individual": [], "unified": []}

    # Individual Mode execution
    if mode in ("individual", "both"):
        target_root = out_dir / "Individual" if mode == "both" else out_dir
        target_root.mkdir(parents=True, exist_ok=True)

        for i, pkg in enumerate(packages):
            meta = eff_meta(pkg)
            raw_title = meta.get("title") or item_names[i]
            base_name = sanitize_name(raw_title)

            # If multiple packages, prefix folder with 01_, 02_ as specified
            if len(packages) > 1:
                folder_name = f"{i + 1:02d}_{base_name}"
            else:
                folder_name = base_name

            pkg_folder = target_root / folder_name
            clean_disp_title = parse_clean_title(meta.get("title") or raw_title)
            html_p, pdf_p = package_single(
                pkg=pkg,
                out_dir=pkg_folder,
                base_name=base_name,
                profile=profile,
                title=clean_disp_title,
            )
            results["individual"].append({
                "folder": str(pkg_folder),
                "html": str(html_p),
                "pdf": str(pdf_p),
                "title": clean_disp_title,
            })
            print(f"DELIVERABLE: Individual [{folder_name}] -> {html_p.name}, {pdf_p.name}")

    # Unified Mode execution
    if mode in ("unified", "both"):
        target_root = out_dir / "Unified" if mode == "both" else out_dir
        target_root.mkdir(parents=True, exist_ok=True)

        master_pkg = unify_packages(packages, master_title=master_title, profile=profile)
        master_base = sanitize_name(master_title, default_suffix="Master")
        master_folder = target_root / master_base
        clean_master_title = parse_clean_title(master_title)

        html_p, pdf_p = package_single(
            pkg=master_pkg,
            out_dir=master_folder,
            base_name=master_base,
            profile=profile,
            title=clean_master_title,
        )
        results["unified"].append({
            "folder": str(master_folder),
            "html": str(html_p),
            "pdf": str(pdf_p),
            "title": clean_master_title,
        })
        print(f"DELIVERABLE: Unified [{master_base}] -> {html_p.name}, {pdf_p.name}")

    # Final overall directory tree validation
    ok, errors = validate_delivery_dir(out_dir, mode=mode)
    if not ok:
        raise RuntimeError(f"Overall delivery tree validation failed for {out_dir}:\n  " + "\n  ".join(errors))

    # Update Master Library Dashboard (index.html) in root delivery directory
    dash_path = out_dir / "index.html"
    all_deliverables = results["individual"] + results["unified"]
    for item in all_deliverables:
        try:
            update_dashboard(
                dashboard_path=dash_path,
                module_path=Path(item["html"]),
                title=item.get("title") or parse_clean_title(Path(item["html"]).stem),
            )
        except Exception as e:
            print(f"Notice: dashboard update for {item['html']}: {e}", file=sys.stderr)

    # Generate OS Desktop shortcut
    try:
        create_desktop_shortcut(dash_path, "StudySynth Library")
    except Exception as e:
        print(f"Notice: desktop shortcut creation: {e}", file=sys.stderr)

    print(f"OK: Successfully packaged {len(packages)} item(s) in mode='{mode}' into {out_dir}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Package StudySynth study deliverables into final standalone PDF + HTML.")
    ap.add_argument("inputs", nargs="+", help="Path(s) to quiz_package.json file(s) or build directories")
    ap.add_argument("--mode", "-m", choices=["individual", "unified", "both"], default="individual",
                    help="Packaging output mode (individual, unified, or both)")
    ap.add_argument("--out-dir", "-o", default="output", help="Output delivery root directory (default: output)")
    ap.add_argument("--title", default="StudySynth Master", help="Master title for unified package")
    ap.add_argument("--profile", default=None, help="Profile override (e.g. profiles/GENERAL_PSC.json)")
    args = ap.parse_args(argv)

    try:
        execute_packaging(
            package_inputs=args.inputs,
            out_dir=Path(args.out_dir),
            mode=args.mode,
            master_title=args.title,
            profile=args.profile,
        )
        return 0
    except Exception as e:
        print(f"ERROR: Packaging failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
