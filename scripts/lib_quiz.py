"""Shared quiz-package normalizers for build_web / build_pdf / check_pdf.

Accepts both the delivery artifact shape::

    {"meta": {"title", "source", "profile", "status", "coverage",
              "external_count"},
     "questions": [...]}

and the canonical pipeline shape (schemas/quiz-package.schema.json)::

    {"run_id", "profile", "questions", "coverage", "package_status",
     "extraction_status", "config_snapshot"}

Question objects may use schema options [{key, text, is_correct, ...}],
plain string lists, answer as letter or index; source as string, dict, or
list of dicts; statements as strings or {text, ...} objects.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

LETTERS = "ABCDEF"


def load_package_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"ERROR: cannot read package {path}: {e}")
    if not isinstance(pkg, dict):
        raise SystemExit(f"ERROR: package root must be an object: {path}")
    return pkg


def validate_structure(pkg: dict) -> tuple[list[str], list[str]]:
    """Return (warnings, errors). Errors are fatal; warnings auto-repair."""
    warnings: list[str] = []
    errors: list[str] = []
    qs = pkg.get("questions")
    if not isinstance(qs, list) or not qs:
        errors.append("package has no non-empty questions list")
        return warnings, errors
    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            errors.append(f"questions[{i}] is not an object")
            continue
        if not q.get("id"):
            auto = f"Q{i + 1:03d}"
            q["id"] = auto
            warnings.append(f"questions[{i}] missing id; assigned {auto}")
        if not (q.get("stem") or q.get("question")):
            errors.append(f"questions[{i}] ({q.get('id')}) has no stem/question")
        opts = q.get("options") or q.get("choices")
        if not isinstance(opts, list) or len(opts) < 2:
            errors.append(f"questions[{i}] ({q.get('id')}) needs >=2 options")
    return warnings, errors


def coverage_text(cov) -> str:
    if not cov:
        return ""
    if isinstance(cov, str):
        return cov
    if isinstance(cov, dict):
        try:
            topics = cov.get("topics")
            if isinstance(topics, list) and topics:
                return f"{len(topics)} topics"
            parts = [f"{k}: {v}" for k, v in list(cov.items())[:4]]
            return ", ".join(parts)[:120]
        except Exception:
            return ""
    return str(cov)[:120]


def eff_meta(pkg: dict) -> dict:
    """Effective delivery metadata from either package shape."""
    m = pkg.get("meta") if isinstance(pkg.get("meta"), dict) else {}
    prof = m.get("profile", pkg.get("profile", {}))
    status = m.get("status", pkg.get("package_status", "unknown"))
    title = m.get("title") or pkg.get("run_id") or "Exam Quiz"
    source = m.get("source") or pkg.get("run_id") or "?"
    cov = m.get("coverage", pkg.get("coverage", ""))
    ext = m.get("external_count")
    if ext is None:
        try:
            n = sum(1 for q in pkg.get("questions", [])
                    if isinstance(q, dict) and q.get("origin") == "external")
            ext = n if n else ""
        except Exception:
            ext = ""
    return {"title": str(title), "source": str(source), "profile": prof,
            "status": str(status), "coverage": cov, "external_count": ext}


def resolve_profile(pkg: dict, override: str | None, profiles_dir: Path) -> dict:
    if override:
        p = Path(override)
        if p.suffix.lower() == ".json" or p.is_file():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        cand = profiles_dir / (override if override.endswith(".json") else override + ".json")
        if cand.is_file():
            with open(cand, encoding="utf-8") as f:
                return json.load(f)
        return {"name": override}
    prof = eff_meta(pkg)["profile"]
    if isinstance(prof, dict):
        return prof
    if isinstance(prof, str) and prof:
        cand = profiles_dir / (prof if prof.endswith(".json") else prof + ".json")
        if cand.is_file():
            with open(cand, encoding="utf-8") as f:
                loaded = json.load(f)
                loaded.setdefault("name", prof)
                return loaded
        return {"name": prof}
    return {}


def negative_rule_text(prof: dict) -> str:
    nm = prof.get("negative_marking", {}) if isinstance(prof, dict) else {}
    if not isinstance(nm, dict):
        nm = {}
    if nm.get("enabled"):
        try:
            frac = float(nm.get("penalty_fraction", 0))
        except (TypeError, ValueError):
            frac = 0
        return (f"Each correct answer carries 1 mark. Each wrong answer deducts {frac:g} marks. "
                "Unattempted questions score 0. There is negative marking.")
    return ("Each correct answer carries 1 mark. Unattempted questions score 0. "
            "There is no negative marking.")


def qid(q: dict, i: int) -> str:
    return str(q.get("id") or q.get("qid") or f"Q{i + 1:03d}")


def norm_options(q: dict) -> list[dict]:
    o = q.get("options") or q.get("choices") or []
    if o and isinstance(o[0], str):
        return [{"key": LETTERS[i], "text": t, "confusion_type": ""} for i, t in enumerate(o)]
    out = []
    for i, x in enumerate(o):
        if isinstance(x, str):
            out.append({"key": LETTERS[i], "text": x, "confusion_type": ""})
        else:
            out.append({"key": x.get("key") or LETTERS[i],
                        "text": x.get("text") or x.get("label") or "",
                        "confusion_type": x.get("confusion_type") or ""})
    return out


def norm_key(q: dict, opts: list[dict]) -> str:
    raw = q.get("options") or q.get("choices") or []
    if raw and isinstance(raw[0], dict):
        for x in raw:
            if isinstance(x, dict) and x.get("is_correct"):
                return (x.get("key") or "A").strip().upper()
    a = q.get("answer", q.get("key", q.get("correct", None)))
    if isinstance(a, int) and 0 <= a < len(opts):
        return opts[a]["key"]
    if isinstance(a, str):
        s = a.strip().upper()
        if len(s) == 1 and s in LETTERS:
            return s
        for o in opts:
            if o["text"] == a:
                return o["key"]
    if opts:
        return opts[0]["key"]
    raise SystemExit(f"ERROR: question has no options/answer: {q.get('id')}")


def _src_ref_text(s) -> str:
    if not s:
        return ""
    if isinstance(s, str):
        return s
    parts = [s.get("section_path", ""), s.get("block_id", "")]
    if s.get("page"):
        parts.append(f"p.{s['page']}")
    if s.get("table_ref"):
        parts.append(str(s["table_ref"]))
    return " \u00b7 ".join(p for p in parts if p)


def qsrc_text(q: dict) -> str:
    s = q.get("source", q.get("source_ref", ""))
    if isinstance(s, list):
        return " | ".join(t for t in (_src_ref_text(x) for x in s) if t)
    return _src_ref_text(s)


def qstatements_texts(q: dict) -> list[str]:
    out = []
    for s in q.get("statements") or []:
        if isinstance(s, str):
            out.append(s)
        elif isinstance(s, dict) and s.get("text"):
            out.append(str(s["text"]))
    return out


def non_latin_letters(pkg: dict) -> set[str]:
    chars: set[str] = set()

    def scan(s: object) -> None:
        if isinstance(s, str):
            for ch in s:
                if ord(ch) > 127 and unicodedata.category(ch).startswith("L"):
                    chars.add(ch)
        elif isinstance(s, dict):
            for v in s.values():
                scan(v)
        elif isinstance(s, list):
            for v in s:
                scan(v)

    scan(pkg)
    return chars
