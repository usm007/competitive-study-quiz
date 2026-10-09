# StudySynth — Local-First Study Application & Revision Engine

StudySynth converts complex reference and study documents into interactive, standalone HTML study modules, master study libraries, and print-ready A4 PDF test papers (for UPSC, APSC, State PSC, SSC, Banking, Railways, Teaching, and other competitive objective examinations).

Deterministic Python stdlib scripts (+ `pypdf`, `reportlab`, `openpyxl`) enforce mathematical coverage, structural validation, 11-dimension question quality, deduplication, audit gates, dynamic metadata extraction, and rendering without external cloud dependencies.

---

## 1. Supported Input Formats

The ingestion engine (`scripts/ingest.py`) parses, normalizes, and extracts structured blocks from:
- **PDF Documents** (`.pdf`): Multi-page extraction via `pypdf`, automatic running header/footer deduplication, table extraction, and empty page detection.
- **Word Documents** (`.docx`): Paragraphs, headings, and tables parsed directly from XML.
- **PowerPoint Slides** (`.pptx`): Slide text and tables parsed directly from XML.
- **Excel Spreadsheets** (`.xlsx`): Multi-sheet tabular data parsed via `openpyxl`.
- **Text & Markdown** (`.txt`, `.md`): Headings, markdown tables, lists, and paragraphs with whitespace/BOM normalization.
- **HTML Pages** (`.html`, `.htm`): Headings, paragraphs, and tables parsed via `html.parser`.
- *Scanned / Image-heavy files*: Gracefully flagged with `extraction_status: "unreliable"` and explicit limitation notes rather than fabricated text.

---

## 2. Key Architecture & Features

### Dynamic Metadata & Clean Naming Convention (`scripts/naming.py`)
- Automatically parses raw source filenames (e.g. `assam_geography_v2.pdf`) into clean, human-readable titles (e.g. `Assam Geography v2`).
- Dynamically injects clean titles into `<title>` tags and UI header branding (`#apptitle`).
- Generates clean, URL-friendly output file slugs (e.g. `assam-geography-module.html`).

### Master Dashboard (`index.html` Library) (`scripts/dashboard.py`)
- Automatically generates and updates a master `index.html` library dashboard in the root output folder.
- Responsive CSS grid layout featuring search filtering, module count, metadata badges, and direct launch links.

### Desktop Shortcut Automation (`scripts/desktop_shortcut.py`)
- Cross-platform utility that generates OS-level shortcuts pointing to `index.html`:
  - **Windows**: `.lnk` shell shortcut (with `.url` fallback)
  - **macOS**: `.webloc` bookmark
  - **Linux**: `.desktop` desktop entry

### Interactive Study Desk UI
- Pure standalone offline HTML file (`file://` compatible).
- Features **Practice Deck**, **Test**, **Revision Engine**, **Analytics** modes plus a sidebar **Confidence** meter.
- Purged of generic "Quiz" terminology in favor of pedagogical study module workflows.

---

## 3. Pipeline Sequence

The pipeline transforms source documents into verified study packages through sequential checkpoints:

```
DOCUMENT
  ↓ [ingest.py + naming.py]
DOCUMENT STRUCTURE & CLEAN METADATA (Dates, numbers, articles, entities, tables)
  ↓ [extract.md + locate_excerpts.py]
EXHAUSTIVE KNOWLEDGE INVENTORY (KUs, Tiers 1-4, confusion clusters, verbatim excerpts)
  ↓ [inventory_check.py]
COMPLETENESS & DENSITY AUDIT (100% anchor recall, unresolved diff resolution)
  ↓ [exam-design.md + generate.md]
QUESTION BANK (Explicit exam purposes, distractors with confusion types, alteration types)
  ↓ [validate_questions.py]
DETERMINISTIC VALIDATION (Single key, key consistency, option count, source provenance)
  ↓ [quality.py]
QUESTION QUALITY EVALUATION (11 dimensions: accuracy, distractors, leaks, difficulty fit, purpose fit, rubric A-D)
  ↓ [coverage.py + dedupe.py]
COVERAGE & REDUNDANCY AUDIT (Tier 1/2 content coverage, cognitive coverage, semantic dedupe)
  ↓ [audit.py + gate.py]
AUDIT & FINAL GATE (COMPREHENSIVE vs LIMITED vs PARTIAL)
  ↓ [package.py]
PACKAGE ASSEMBLY (Validated + Quality-Accepted questions only)
  ↓ [build_web.py + dashboard.py + desktop_shortcut.py + build_pdf.py]
STANDALONE STUDY MODULE, MASTER DASHBOARD, DESKTOP SHORTCUT & PRINT-READY PDFS
```

---

## 4. Quickstart: One-Command Pipeline

Run all deterministic stages at once from a source document, inventory, and question bank:

```bash
# Full pipeline from source document to interactive web app & verified PDFs
python scripts/pipeline.py \
  --source examples/sample_source.md \
  --inventory examples/sample_inventory.json \
  --bank examples/sample_bank.json \
  --profile profiles/APSC_PRELIMS.json \
  --config config.default.json \
  --run-id my_run \
  --build-dir build \
  --full
```

Generated outputs in `build/my_run/`:
- `document_structure.json` & `anchors.json`: Document structure and extracted anchors
- `inventory_check.json`: Anchor recall and section density audit
- `validation_results.json`: Syntactic and semantic validation results
- `quality_report.json`: 11-dimension quality analysis and A/B/C/D rubric grading
- `coverage_matrix.json`: Content coverage and cognitive coverage breakdown
- `dedupe_report.json`: Exact and semantic duplicate detection report
- `audit_report.json`: Global audit of content, cognitive coverage, shares, and clusters
- `gate.json`: Authoritative gate status (`COMPREHENSIVE`, `PARTIAL`, or `LIMITED`)
- `quiz_package.json`: Packaged delivery artifact with quality-accepted questions
- `sample-source-module.html` & `quiz.html`: Standalone offline study workspace
- `output/index.html`: Master StudySynth library dashboard
- `pdf/question-paper-A.pdf`: Printable A4 question paper with OMR grid
- `pdf/answer-key-B.pdf`: Compact answer key sheet
- `pdf/explanations-C.pdf`: Pedagogical explanation booklet with source citations
- `pdf_check_report.json`: PDF layout, font embedding, and glyph clip verification

---

## 5. Testing & Verification

Run the entire test suite (284 unit and integration tests):
```bash
python tests/run_all.py
```

Run the authoritative release gate check:
```bash
python scripts/release_gate.py
```

---

## 6. Known Boundaries & Limitations

- **Source-Bound Elimination Limits**: When a source document does not provide enough cross-cutting contextual information for all 4 options within a single block, questions cannot arbitrarily introduce external facts to fabricate elimination steps. In such cases, questions are legitimately classified as `distinction` or `association` rather than forced `elimination`.
- **Scanned Document Extraction**: OCR requires an external OCR engine (like Tesseract). Scanned or pure image PDFs produce `extraction_status: unreliable` and `STATUS: LIMITED` rather than guessing ungrounded text.
- **Font Availability for Non-Latin PDF Printing**: Devanagari and Bengali/Assamese PDF rendering defaults to `Nirmala.ttc` on Windows, falling back to `DejaVuSans` or `Helvetica`.
