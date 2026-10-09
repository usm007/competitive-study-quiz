"""Build print-ready PDF versions A/B/C from a quiz package (reportlab platypus).

  Version A: question paper (numbered Qs, 4 options, OMR answer grid).
  Version B: compact answer key table (q -> key).
  Version C: explanation booklet (Q, key, explanation, source ref, memory aid).

A4, black-and-white, serif body. Unicode font: Nirmala.ttc if present,
else DejaVuSans fallback, else Helvetica (with a warning).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_quiz import (  # noqa: E402
    coverage_text,
    eff_meta,
    load_package_json,
    negative_rule_text,
    norm_key,
    norm_options,
    qid,
    qsrc_text,
    qstatements_texts,
    resolve_profile,
    validate_structure,
)

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).resolve()
DEFAULT_STYLE = HERE.parent.parent / "templates" / "pdf" / "style.json"
PROFILES_DIR = HERE.parent.parent / "profiles"
NIRMALA = Path(r"C:\Windows\Fonts\Nirmala.ttc")
DEJAVU = Path(r"C:\Windows\Fonts\DejaVuSans.ttf")
DEJAVU_BOLD = Path(r"C:\Windows\Fonts\DejaVuSans-Bold.ttf")


def qtopic(q: dict) -> str:
    return str(q.get("topic") or q.get("knowledge_area") or q.get("subject") or "General")


def qmem(q: dict) -> str:
    return str(q.get("memory_aid") or q.get("memoryAid") or q.get("mnemonic") or "")


# ---------------------------------------------------------------- fonts / style
def resolve_fonts() -> tuple[str, str, bool]:
    """Return (body_font, bold_font, embedded). Embedded is True for TTF fonts."""
    # ponytail: global first-match wins; per-script overrides via --style only.
    if NIRMALA.is_file():
        try:
            pdfmetrics.registerFont(TTFont("Nirmala", str(NIRMALA), subfontIndex=0))
            try:
                pdfmetrics.registerFont(TTFont("Nirmala-Bold", str(NIRMALA), subfontIndex=1))
                return "Nirmala", "Nirmala-Bold", True
            except Exception:
                pdfmetrics.registerFontFamily("Nirmala", normal="Nirmala", bold="Nirmala")
                return "Nirmala", "Nirmala", True
        except Exception as e:
            print(f"WARNING: found {NIRMALA} but registration failed ({e}); trying fallback",
                  file=sys.stderr)
    if DEJAVU.is_file():
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(DEJAVU)))
            if DEJAVU_BOLD.is_file():
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(DEJAVU_BOLD)))
                return "DejaVuSans", "DejaVuSans-Bold", True
            return "DejaVuSans", "DejaVuSans", True
        except Exception as e:
            print(f"WARNING: DejaVuSans registration failed ({e}); using Helvetica", file=sys.stderr)
    print("WARNING: no Unicode TTF found; using Helvetica (non-Latin glyphs may be missing)",
          file=sys.stderr)
    return "Helvetica", "Helvetica-Bold", False


def load_style(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def make_styles(cfg: dict, body: str, bold: str) -> dict[str, ParagraphStyle]:
    sz = cfg.get("sizes", {})
    sp = cfg.get("spacing", {})
    b, lb = float(sz.get("body", 10.5)), float(sz.get("leading_body", 14))
    base = {"fontName": body, "fontSize": b, "leading": lb, "textColor": "#000000"}
    small = {"fontName": body, "fontSize": float(sz.get("caption", 9)),
             "leading": float(sz.get("leading_small", 12)), "textColor": "#333333"}
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=float(sz.get("title", 18)),
                                  leading=float(sz.get("leading_title", 23)),
                                  spaceAfter=float(sp.get("after_title", 6))),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=float(sz.get("h1", 14)),
                             spaceBefore=float(sp.get("before_h1", 12)),
                             spaceAfter=float(sp.get("after_h1", 8))),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=float(sz.get("h2", 12)),
                             spaceAfter=float(sp.get("after_h2", 6))),
        "body": ParagraphStyle("body", **base),
        "option": ParagraphStyle("option", fontName=body, fontSize=float(sz.get("option", 10.5)),
                                 leading=lb, leftIndent=12),
        "small": ParagraphStyle("small", **small),
        "bold": ParagraphStyle("bold", fontName=bold, fontSize=b, leading=lb),
    }


def footer(title: str):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawString(doc.leftMargin, 30, title)
        canvas.drawRightString(A4[0] - doc.rightMargin, 30, f"Page {doc.page}")
        canvas.restoreState()
    return _draw


def doc_template(path: Path, cfg: dict, title: str) -> SimpleDocTemplate:
    pg = cfg.get("page", {})
    return SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=float(pg.get("left_margin_pt", 54)), rightMargin=float(pg.get("right_margin_pt", 54)),
        topMargin=float(pg.get("top_margin_pt", 54)), bottomMargin=float(pg.get("bottom_margin_pt", 54)),
        title=title, author="StudySynth",
    )


def esc(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- versions
def build_A(pkg: dict, meta: dict, prof: dict, cfg: dict, st: dict, fonts: tuple, out: Path) -> None:
    body, bold, _ = fonts
    title = meta["title"]
    doc = doc_template(out, cfg, title + " - Question Paper (A)")
    sp = cfg.get("spacing", {})
    cov = coverage_text(meta["coverage"])
    sub = (f"Question Paper (Version A) · Profile: {esc(prof.get('name', '?'))} · "
           f"{len(pkg['questions'])} questions" + (f" · Coverage: {esc(cov)}" if cov else ""))
    story = [
        Paragraph(esc(title), st["title"]),
        Paragraph(sub, st["small"]),
        Spacer(1, float(sp.get("after_title", 6))),
        Paragraph("Instructions", st["h2"]),
        Paragraph("1. Each question has lettered options. Choose the single best answer.<br/>"
                  f"2. {esc(negative_rule_text(prof))}<br/>"
                  "3. Mark your answers on the OMR-style grid on the last page.", st["body"]),
        Spacer(1, float(sp.get("after_block", 6))),
    ]
    last_topic = None
    for i, q in enumerate(pkg["questions"]):
        opts = norm_options(q)
        n = i + 1
        topic = qtopic(q)
        block: list = []
        if topic != last_topic:
            block.append(Paragraph(esc(topic), st["h2"]))
            last_topic = topic
        block.append(Paragraph(
            f"<b>Q{n}. [{esc(qid(q, i))}]</b>  {esc(q.get('stem') or q.get('question') or '')}",
            st["body"]))
        stmts = qstatements_texts(q)
        if stmts:
            items = [ListItem(Paragraph(esc(s), st["body"]), leftIndent=18) for s in stmts]
            block.append(ListFlowable(items, bulletType="1", start="1", leftIndent=18))
        for o in opts:
            block.append(Paragraph(f"<b>{esc(o['key'])}.</b>  {esc(o['text'])}", st["option"]))
        block.append(Spacer(1, float(sp.get("after_question", 10))))
        story.append(KeepTogether(block))
    # OMR-style answer grid
    story.append(PageBreak())
    story.append(Paragraph("OMR Answer Grid", st["h1"]))
    story.append(Paragraph("One row per question; mark a single (X) per row.", st["small"]))
    rows = [["Q", "A", "B", "C", "D"]]
    for i in range(len(pkg["questions"])):
        rows.append([f"Q{i + 1}", "( )", "( )", "( )", "( )"])
    t = Table(rows, colWidths=[40] + [45] * 4, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), body),
        ("FONTSIZE", (0, 0), (-1, -1), float(cfg.get("sizes", {}).get("omr_cell", 11))),
        ("GRID", (0, 0), (-1, -1), 0.5, "#000000"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    doc.build(story, onFirstPage=footer(title + " (A)"), onLaterPages=footer(title + " (A)"))
    print(f"OK: wrote {out}")


def build_B(pkg: dict, meta: dict, prof: dict, cfg: dict, st: dict, fonts: tuple, out: Path) -> None:
    body, bold, _ = fonts
    title = meta["title"]
    doc = doc_template(out, cfg, title + " - Answer Key (B)")
    rows = [["Q", "ID", "Key"]]
    for i, q in enumerate(pkg["questions"]):
        rows.append([f"Q{i + 1}", qid(q, i), norm_key(q, norm_options(q))])
    t = Table(rows, colWidths=[45, 120, 45], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), body),
        ("FONTSIZE", (0, 0), (-1, -1), float(cfg.get("sizes", {}).get("answer_key_cell", 10))),
        ("GRID", (0, 0), (-1, -1), 0.5, "#000000"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story = [
        Paragraph(esc(title), st["title"]),
        Paragraph(f"Answer Key (Version B) · Profile: {esc(prof.get('name', '?'))}", st["small"]),
        Spacer(1, 8), t,
    ]
    doc.build(story, onFirstPage=footer(title + " (B)"), onLaterPages=footer(title + " (B)"))
    print(f"OK: wrote {out}")


def build_C(pkg: dict, meta: dict, prof: dict, cfg: dict, st: dict, fonts: tuple, out: Path) -> None:
    body, bold, _ = fonts
    title = meta["title"]
    doc = doc_template(out, cfg, title + " - Explanations (C)")
    sp = cfg.get("spacing", {})
    story = [
        Paragraph(esc(title), st["title"]),
        Paragraph(f"Explanation Booklet (Version C) · Profile: {esc(prof.get('name', '?'))}", st["small"]),
        Spacer(1, float(sp.get("after_title", 6))),
    ]
    for i, q in enumerate(pkg["questions"]):
        opts = norm_options(q)
        key = norm_key(q, opts)
        keytext = next((o["text"] for o in opts if o["key"] == key), "")
        block: list = [
            Paragraph(f"<b>Q{i + 1}. [{esc(qid(q, i))}]</b>  "
                      f"{esc(q.get('stem') or q.get('question') or '')}", st["body"]),
            Paragraph(f"<b>Key: {esc(key)}</b> — {esc(keytext)}", st["body"]),
            Paragraph(f"<b>Explanation:</b> {esc(q.get('explanation') or '—')}", st["body"]),
        ]
        if qsrc_text(q):
            block.append(Paragraph(f"<b>Source:</b> {esc(qsrc_text(q))}", st["small"]))
        if qmem(q):
            block.append(Paragraph(f"<b>Memory aid:</b> {esc(qmem(q))}", st["body"]))
        extra = []
        if q.get("purpose"): extra.append("Purpose: %s" % q.get("purpose"))
        if q.get("cognitive_level"): extra.append("Cognitive: %s" % q.get("cognitive_level"))
        if q.get("revision_priority"): extra.append("Revision: %s" % q.get("revision_priority"))
        if q.get("misconception"): extra.append("Misconception: %s" % q.get("misconception"))
        if q.get("difficulty_reason"): extra.append("Difficulty: %s" % q.get("difficulty_reason"))
        block.append(Paragraph(f"Topic: {esc(qtopic(q))}" + (" \u00b7 " + esc(" | ".join(extra)) if extra else ""), st["small"]))
        block.append(Spacer(1, float(sp.get("after_question", 10))))
        story.append(KeepTogether(block))
    rev = [q for q in pkg["questions"] if str(q.get("revision_priority") or "") in ("critical", "high")]
    if rev:
        story.append(PageBreak())
        story.append(Paragraph("Revision Sheet (high-priority)", st["h1"]))
        story.append(Paragraph("Focus these %d items first. Re-attempt each in a different form." % len(rev), st["small"]))
        for q in rev:
            story.append(Paragraph("<b>%s</b> \u2014 %s [%s]" % (esc(qid(q, pkg["questions"].index(q))), esc(q.get("stem") or q.get("question") or ""), esc(str(q.get("revision_priority")))), st["body"]))
            if qmem(q):
                story.append(Paragraph("Aid: %s" % esc(qmem(q)), st["small"]))
    doc.build(story, onFirstPage=footer(title + " (C)"), onLaterPages=footer(title + " (C)"))
    print(f"OK: wrote {out}")


def build_single_pdf(
    pkg: dict,
    out_pdf: Path,
    profile: str | dict | None = None,
    style_path: Path | None = None,
) -> Path:
    """Build a single combined study PDF containing Question Paper, Answer Key, and Explanations."""
    import tempfile
    from pypdf import PdfWriter

    warnings, errors = validate_structure(pkg)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        raise SystemExit(f"ERROR: invalid quiz package:\n  " + "\n  ".join(errors))

    meta = eff_meta(pkg)
    prof = profile if isinstance(profile, dict) else resolve_profile(pkg, profile, PROFILES_DIR)
    cfg = load_style(Path(style_path or DEFAULT_STYLE))
    fonts = resolve_fonts()
    st = make_styles(cfg, fonts[0], fonts[1])

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        path_a = t / "question-paper-A.pdf"
        path_b = t / "answer-key-B.pdf"
        path_c = t / "explanations-C.pdf"
        build_A(pkg, meta, prof, cfg, st, fonts, path_a)
        build_B(pkg, meta, prof, cfg, st, fonts, path_b)
        build_C(pkg, meta, prof, cfg, st, fonts, path_c)

        writer = PdfWriter()
        writer.append(str(path_a))
        writer.append(str(path_b))
        writer.append(str(path_c))
        with open(out_pdf, "wb") as f:
            writer.write(f)

    print(f"OK: wrote single combined PDF {out_pdf}")
    return out_pdf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build PDF versions A/B/C from a quiz package.")
    ap.add_argument("package", help="Path to quiz_package.json")
    ap.add_argument("--out", default=None, help="Output directory for the three PDFs")
    ap.add_argument("--single-out", default=None, help="Output path for the single combined PDF")
    ap.add_argument("--profile", default=None,
                    help="Profile name (profiles/*.json), path to profile JSON, or free name override")
    ap.add_argument("--style", default=str(DEFAULT_STYLE), help="Path to templates/pdf/style.json")
    args = ap.parse_args(argv)

    if not args.out and not args.single_out:
        ap.error("At least one of --out or --single-out is required")

    pkg = load_package_json(Path(args.package))
    warnings, errors = validate_structure(pkg)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        raise SystemExit(f"ERROR: invalid quiz package {args.package}:\n  " + "\n  ".join(errors))
    meta = eff_meta(pkg)
    prof = resolve_profile(pkg, args.profile, PROFILES_DIR)
    cfg = load_style(Path(args.style))
    fonts = resolve_fonts()
    print(f"fonts: body={fonts[0]} bold={fonts[1]} embedded={fonts[2]}")
    st = make_styles(cfg, fonts[0], fonts[1])

    if args.single_out:
        build_single_pdf(pkg, Path(args.single_out), prof, Path(args.style))

    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        build_A(pkg, meta, prof, cfg, st, fonts, outdir / "question-paper-A.pdf")
        build_B(pkg, meta, prof, cfg, st, fonts, outdir / "answer-key-B.pdf")
        build_C(pkg, meta, prof, cfg, st, fonts, outdir / "explanations-C.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
