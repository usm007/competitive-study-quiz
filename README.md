# DocToQuiz — V1.0 Release Documentation

Converts complex reference and study documents into rigorous, competitive-exam question banks, interactive web study applications, and print-ready A4 PDF test papers (for UPSC, APSC, State PSC, SSC, Banking, Railways, Teaching, and other objective examinations).

Deterministic Python stdlib scripts (+ `pypdf`, `reportlab`, `openpyxl`) enforce mathematical coverage, structural validation, 11-dimension question quality, deduplication, audit gates, and rendering without external cloud dependencies.

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

## 2. Pipeline Sequence

The pipeline transforms source documents into verified study packages through sequential checkpoints:

```
DOCUMENT
  ↓ [ingest.py]
DOCUMENT STRUCTURE & ANCHORS (Dates, numbers, articles, entities, tables)
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
QUIZ PACKAGE (Validated + Quality-Accepted questions only)
  ↓ [build_web.py + build_pdf.py + check_pdf.py]
STANDALONE WEB APP & PRINT-READY A4 PDFS (Version A: Exam, B: Key, C: Explanations)
```

---

## 3. Quickstart: One-Command Pipeline

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
- `quiz.html`: Standalone offline web workspace with practice/test/revision modes
- `pdf/question-paper-A.pdf`: Printable A4 question paper with OMR grid
- `pdf/answer-key-B.pdf`: Compact answer key sheet
- `pdf/explanations-C.pdf`: Pedagogical explanation booklet with source citations
- `pdf_check_report.json`: PDF layout, font embedding, and glyph clip verification

---

## 4. End-to-End Example Walkthrough

```bash
# 1. Ingest document & detect anchors
python scripts/ingest.py examples/sample_source.md --out build --run-id demo
python scripts/anchors.py build/demo/document_structure.json --out build/demo/anchors.json

# 2. Check inventory completeness against anchors
python scripts/locate_excerpts.py examples/sample_inventory.json build/demo/document_structure.json
python scripts/inventory_check.py examples/sample_inventory.json build/demo/document_structure.json \
  --anchors build/demo/anchors.json --config config.default.json --out build/demo/inventory_check.json

# 3. Validate question bank correctness
python scripts/validate_questions.py examples/sample_bank.json examples/sample_inventory.json \
  build/demo/document_structure.json --profile profiles/APSC_PRELIMS.json --mode SOURCE_BOUND \
  --config config.default.json --out build/demo/validation_results.json

# 4. Evaluate competitive-exam question quality (Phase 3)
python scripts/quality.py examples/sample_bank.json examples/sample_inventory.json \
  build/demo/document_structure.json --profile profiles/APSC_PRELIMS.json --mode SOURCE_BOUND \
  --config config.default.json --out build/demo/quality_report.json

# 5. Measure coverage and deduplicate
python scripts/coverage.py examples/sample_bank.json examples/sample_inventory.json \
  build/demo/validation_results.json --out build/demo/coverage_matrix.json --config config.default.json
python scripts/dedupe.py examples/sample_bank.json --out build/demo/dedupe_report.json

# 6. Audit, Gate & Report
python scripts/audit.py examples/sample_inventory.json build/demo/coverage_matrix.json \
  build/demo/validation_results.json build/demo/anchors.json --profile profiles/APSC_PRELIMS.json \
  --config config.default.json --struct build/demo/document_structure.json \
  --bank examples/sample_bank.json --quality build/demo/quality_report.json --out build/demo/audit_report.json
python scripts/gate.py build/demo/audit_report.json --config config.default.json --out build/demo/gate.json
python scripts/report.py build/demo/audit_report.json build/demo/gate.json examples/sample_bank.json

# 7. Package and Deliver
python scripts/package.py examples/sample_bank.json build/demo/audit_report.json build/demo/gate.json \
  --profile profiles/APSC_PRELIMS.json --inventory examples/sample_inventory.json \
  --quality build/demo/quality_report.json --out build/demo/quiz_package.json
python scripts/build_web.py build/demo/quiz_package.json --out build/demo/quiz.html
python scripts/build_pdf.py build/demo/quiz_package.json --out build/demo/pdf --profile profiles/APSC_PRELIMS.json
python scripts/check_pdf.py build/demo/pdf/question-paper-A.pdf build/demo/pdf/answer-key-B.pdf \
  build/demo/pdf/explanations-C.pdf --package build/demo/quiz_package.json --report build/demo/pdf_check_report.json
```

---

## 5. Testing & Verification

Run the entire test suite (245 unit and integration tests):
```bash
python tests/run_all.py
```

Run the authoritative V1.0 release gate check:
```bash
python scripts/release_gate.py
```

---

## 6. Known Boundaries & Limitations

- **Source-Bound Elimination Limits**: When a source document does not provide enough cross-cutting contextual information for all 4 options within a single block, questions cannot arbitrarily introduce external facts to fabricate elimination steps. In such cases, questions are legitimately classified as `distinction` or `association` rather than forced `elimination`.
- **Scanned Document Extraction**: OCR requires an external OCR engine (like Tesseract). Scanned or pure image PDFs produce `extraction_status: unreliable` and `STATUS: LIMITED` rather than guessing ungrounded text.
- **Font Availability for Non-Latin PDF Printing**: Devanagari and Bengali/Assamese PDF rendering defaults to `Nirmala.ttc` on Windows, falling back to `DejaVuSans` or `Helvetica`.
