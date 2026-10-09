"""StudySynth Naming & Metadata Utilities.

Provides deterministic parsing of raw source document filenames into clean,
capitalized titles and URL-friendly slugs for output study modules.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


COMMON_EXTENSIONS = (
    ".pdf", ".txt", ".md", ".html", ".htm",
    ".docx", ".pptx", ".xlsx", ".json"
)


def parse_clean_title(source: str | Path) -> str:
    """Convert a raw source document filename or path into a clean, capitalized title.

    Examples:
        'assam_geography_v2.pdf' -> 'Assam Geography v2'
        'indian_polity_part_1.docx' -> 'Indian Polity Part 1'
        'fundamental-rights-overview.md' -> 'Fundamental Rights Overview'
        'sample_source.md' -> 'Sample Source'
        'geography_quiz.pdf' -> 'Geography Study Module'
    """
    if not source:
        return "StudySynth Module"

    path_str = str(source)
    # Extract base filename without directories
    base = os.path.basename(path_str)

    # Strip recognized extensions iteratively
    for ext in COMMON_EXTENSIONS:
        if base.lower().endswith(ext):
            base = base[:-len(ext)]
            break
    # In case there's another trailing extension (e.g. .tar.gz)
    base = os.path.splitext(base)[0]

    # Replace underscores, hyphens, and multiple dots with spaces
    cleaned = re.sub(r"[_\-]+", " ", base)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return "StudySynth Module"

    # Tokenize and capitalize words intelligently
    tokens = cleaned.split(" ")
    formatted_tokens: list[str] = []

    for tok in tokens:
        lower_tok = tok.lower()

        # Purge user-facing "quiz" terminology in title parsing
        if lower_tok == "quiz":
            formatted_tokens.append("Study Module")
        elif lower_tok == "quizzes":
            formatted_tokens.append("Study Modules")
        # Handle version strings like v1, v2, v3.1
        elif re.match(r"^v\d+(\.\d+)*$", lower_tok):
            formatted_tokens.append(lower_tok)
        # Handle roman numerals like I, II, III, IV, V, VI, VII, VIII, IX, X
        elif re.match(r"^(i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)$", lower_tok):
            formatted_tokens.append(lower_tok.upper())
        # Handle standard words
        elif len(tok) == 1:
            formatted_tokens.append(tok.upper())
        else:
            # Preserve acronyms like PSC, APSC, UPSC, NCERT if already uppercase
            if tok.isupper() and len(tok) <= 5:
                formatted_tokens.append(tok)
            else:
                formatted_tokens.append(tok.capitalize())

    title = " ".join(formatted_tokens)
    # Deduplicate consecutive 'Study Module' / 'Module' phrases
    title = re.sub(r"(Study Module)(\s+Study Module)+", r"\1", title, flags=re.IGNORECASE)
    title = re.sub(r"(Study Module)(\s+Module)+", r"\1", title, flags=re.IGNORECASE)
    return title


def generate_slug(source_or_title: str | Path, suffix: str = "module") -> str:
    """Generate a URL-friendly slug for the output file.

    Examples:
        'assam_geography_v2.pdf' -> 'assam-geography-module.html'
        'Assam Geography v2' -> 'assam-geography-module.html'
        'sample_source.md' -> 'sample-source-module.html'
    """
    if not source_or_title:
        return f"studysynth-{suffix}.html" if suffix else "studysynth.html"

    # If it's a file path, extract basename and strip extension
    path_str = str(source_or_title)
    base = os.path.basename(path_str)
    for ext in COMMON_EXTENSIONS:
        if base.lower().endswith(ext):
            base = base[:-len(ext)]
            break
    base = os.path.splitext(base)[0]

    # Normalize separators first so word boundary replacements work reliably
    s = base.lower()
    s = re.sub(r"[_\s]+", "-", s)

    # Purge quiz terminology from slug
    s = re.sub(r"\bquizzes\b", "modules", s)
    s = re.sub(r"\bquiz\b", "", s)

    # If filename had e.g. _v2 and prompt specified assam_geography_v2.pdf -> assam-geography-module.html
    m = re.match(r"^(.*?)-v\d+$", s)
    if m and m.group(1):
        s = m.group(1)

    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")

    if not s:
        s = "study"

    # Avoid duplicate suffixes like assam-module-module
    clean_suffix = suffix.strip("-").lower() if suffix else ""
    if clean_suffix:
        if s.endswith(f"-{clean_suffix}") or s == clean_suffix:
            return f"{s}.html"
        return f"{s}-{clean_suffix}.html"

    return f"{s}.html"
