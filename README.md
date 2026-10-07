# competitive-study-quiz — user documentation

Converts source documents into an exam-oriented question bank + study
interface (UPSC/APSC/State PSC/SSC/Banking/Railways/Teaching/Defence and other
objective exams). Scripts are deterministic and need no LLM API at runtime;
the agent performs extraction, authoring and blind review via `prompts/`.
See `SKILL.md` for the full procedure.

## Install

```bash
pip install pypdf reportlab openpyxl pymupdf   # pymupdf optional (PDF margin scan)
```

## Run on a new document

```bash
cd competitive-study-quiz
# 1. deterministic ingest + anchors
python scripts/ingest.py ../docs/mybook.pdf --out build --run-id r1
python scripts/anchors.py build/r1/document_structure.json --out build/r1/anchors.json
# 2. agent writes build/r1/knowledge_inventory.json (prompts/extract.md, inventory.md)
python scripts/locate_excerpts.py build/r1/knowledge_inventory.json build/r1/document_structure.json
# 3. agent second pass -> build/r1/inventory_diff.json, ignores -> ignored_anchors.json
python scripts/inventory_check.py build/r1/knowledge_inventory.json build/r1/document_structure.json \
  --anchors build/r1/anchors.json --ignored build/r1/ignored_anchors.json --diff build/r1/inventory_diff.json
# 4. agent writes build/r1/question_bank.json (prompts/generate.md, statement-engine.md)
python scripts/validate_questions.py build/r1/question_bank.json build/r1/knowledge_inventory.json \
  build/r1/document_structure.json --profile profiles/APSC_PRELIMS.json --mode SOURCE_BOUND --config config.default.json
# 5. agent blind re-solve (prompts/validate-blind.md) -> build/r1/validation_semantic.json
python scripts/coverage.py build/r1/question_bank.json build/r1/knowledge_inventory.json \
  build/r1/validation_results.json --out build/r1/coverage_matrix.json --config config.default.json
python scripts/dedupe.py build/r1/question_bank.json --out build/r1/dedupe_report.json
python scripts/audit.py build/r1/knowledge_inventory.json build/r1/coverage_matrix.json \
  build/r1/validation_results.json build/r1/anchors.json --profile profiles/APSC_PRELIMS.json \
  --config config.default.json --struct build/r1/document_structure.json --out build/r1/audit_report.json
# 6. gap-fill flagged KUs only (prompts/gap-fill.md), re-run 4-5, then:
python scripts/gate.py build/r1/audit_report.json --config config.default.json
python scripts/report.py build/r1/audit_report.json build/r1/gate.json build/r1/question_bank.json
# 7. deliver
python scripts/package.py build/r1/question_bank.json build/r1/audit_report.json build/r1/gate.json \
  --profile profiles/APSC_PRELIMS.json --inventory build/r1/knowledge_inventory.json --out build/r1/quiz_package.json
python scripts/build_web.py build/r1/quiz_package.json --out build/r1/quiz.html
python scripts/build_pdf.py build/r1/quiz_package.json --out build/r1/pdf --profile profiles/APSC_PRELIMS.json
python scripts/check_pdf.py build/r1/pdf/question-paper-A.pdf build/r1/pdf/answer-key-B.pdf \
  build/r1/pdf/explanations-C.pdf --package build/r1/quiz_package.json
```

Or run all deterministic stages at once (LLM artifacts supplied via flags):

```bash
python scripts/pipeline.py --source ../docs/mybook.pdf --run-id r1 \
  --profile profiles/APSC_PRELIMS.json --config config.default.json \
  --inventory build/r1/knowledge_inventory.json --bank build/r1/question_bank.json
```

FIXED_COUNT: generate exactly N questions, still run the full audit, and report
`Requested / Generated / Tier 1 % / Tier 2 % / uncovered` honestly — never label
a fixed-count package COMPREHENSIVE unless the gate passes.

## Limitations (verified, not silent)

- OCR needs tesseract (absent on the authoring host): scanned/image PDFs yield
  `extraction_status: unreliable` and STATUS LIMITED — never guessed content.
- DOCX/PPTX parsed with stdlib zip/xml; XLSX needs openpyxl; complex formatting may be lossy.
- Exam-profile figures marked `"verified": false` must be checked against the
  current official notification (negative marking, paper pattern, counts).
- Section-share accounting is coarse when source headings do not nest cleanly.
- Semantic correctness rests on the agent's blind re-solve + spot review; scripts
  prove structure, provenance, coverage arithmetic and key logic — not meaning.
- Non-Latin scripts: Latin + Devanagari + Bengali/Assamese via Nirmala.ttc
  (Windows) with DejaVu/Helvetica fallback; verify rendering with a fixture.

## Add a profile

1. Copy `profiles/CUSTOM.json` to `profiles/MY_EXAM.json`.
2. Fill `target_type_mix`, `difficulty_distribution`, `negative_marking`
   (keep `"verified": false` until checked against the official notification).
3. Validate: `python scripts/validate_schema.py profiles/MY_EXAM.json --schema schemas/exam-profile.schema.json`
