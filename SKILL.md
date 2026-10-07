# competitive-study-quiz — operating instructions

Serious exam-prep skill (UPSC/APSC/PSC/SSC/Banking/Teaching/etc.). You are the
reasoner (extract, atomize, judge importance, write questions, blind re-solve);
scripts are deterministic (ingest, recall, schema/quote/key checks, coverage,
audit, gate, render). Every LLM step writes a JSON file that scripts validate.
Nothing is "done" until the deterministic check passes. Stdlib-only (+ reportlab
for PDF, pypdf for PDF ingest/check, openpyxl for XLSX, pymupdf optional).

## Rules R1–R12 (resolve conflicts toward accuracy first)

- R1 Knowledge inventory first. Questions come from `knowledge_inventory.json`, never raw text.
- R2 Mentioning a fact is not coverage. Only `coverage.py` statuses count. CONTENT COVERAGE != COGNITIVE COVERAGE (recall/distinction/application/statement tracked separately per KU).
- R3 Never declare COMPREHENSIVE without a passing `gate.py` on a clean `audit.py`. Use CONTENT COMPLETE / COGNITIVE COVERAGE PARTIAL labels honestly; never a single misleading percentage.
- R4 SOURCE_BOUND: no fact outside the document appears as true. Fixes are rewording, not new facts.
- R5 Single-select: exactly one defensible answer (checked by blind re-solve + `stmt_check`).
- R6 Every distractor needs `distractor_origin` + `confusion_type` (schema enums) + `ku_ref` where from source + `distractor_purpose` (confusable_fact | adjacent_value | partial_truth | reversed_relation | wrong_category | wrong_entity | wrong_date | scope_error | causal_reversal). No nonsense distractors.
- R7 Never cut important KUs to hit a round number (FIXED_COUNT keeps weighted coverage + honest report).
- R8 No section over its share: `section_share_cap` (default 2.0x) enforced in `audit.py`.
- R9 No trivia/entertainment questions; sober academic tone everywhere.
- R10 Every question teaches, discriminates, or diagnoses (explanation + confusion tag).
- R11 Quote real command output for every pass/fail claim.
- R12 Percentages/status only from `report.py`/`gate.py` output, never by hand.

## Pipeline (prompts/ → scripts/, artifacts in build/<run_id>/)

| # | LLM step (prompt) | Deterministic script | Writes |
|---|---|---|---|
| 1 | ingest config | `scripts/ingest.py SRC --out build --run-id R` | `document_structure.json`, `normalized_source.txt` |
| 2 | — | `scripts/anchors.py struct --out anchors.json` | `anchors.json` |
| 3 | `prompts/extract.md` + `prompts/inventory.md` | hand-write inventory | `knowledge_inventory.json` (draft) |
| 4 | — | `scripts/locate_excerpts.py inventory struct` | fills char spans/paths; FAILS on non-verbatim excerpts |
| 5 | `prompts/second-pass.md` (re-extract blind) | record diff | `inventory_diff.json` |
| 6 | `prompts/classify.md` | `scripts/inventory_check.py` (+ `--ignored`, `--diff`) | recall 100%, density, diff resolved |
| 7 | `prompts/exam-design.md` (+ profile: purpose + cognitive_level + difficulty_reason per row) | — | `coverage_plan.json` (per-KU cap 3, type mix, share cap, required purposes) |
| 8 | `prompts/generate.md` + `prompts/statement-engine.md` (statement/elimination/distinction/association/chronology/exception/integrated) | hand-write bank | `question_bank.json` (draft, every question has a purpose) |
| 9 | — | `scripts/validate_questions.py` (+ profile/mode/config) | `validation_results.json`; rejected = no credit |
| 10 | `prompts/validate-blind.md` (solve keyless from source) | record | `validation_semantic.json` |
| 11 | `prompts/validate-semantic.md` (checklist per question) | record | `validation_semantic.json` |
| 12 | — | `scripts/coverage.py`, `scripts/dedupe.py` | `coverage_matrix.json` (content + cognitive per-KU, purpose/section/tier coverage, CONTENT/CONGITIVE labels), `dedupe_report.json` |
| 13 | `prompts/audit-review.md` | `scripts/audit.py` | `audit_report.json` (cognitive gaps, distinction gaps, purpose coverage, cluster status) (+ keep `audit_report_roundN.json`) |
| 14 | `prompts/gap-fill.md` (exact missing forms/clusters/purposes only) | loop 9–13, max 5 rounds | gap-fill bank additions |
| 15 | — | `scripts/gate.py` → `scripts/report.py` | `gate.json` + printed FINAL REPORT (quote it) |
| 16 | `prompts/revision.md` | `scripts/package.py --inventory ...` | `quiz_package.json` (validated only, tiers stamped) |
| 17 | — | `scripts/build_web.py`, `scripts/build_pdf.py`, `scripts/check_pdf.py` | `quiz.html`, `pdf/*.pdf`, `check_report.json` |

`scripts/pipeline.py --source --run-id --profile --config [--inventory --bank --ignored --diff]`
runs the deterministic stages with checkpoints/resume (`--redo STAGE`).

## Field contracts (must match schemas/*.json)

- KU: `id KU-####`, `type` (schema enum), `supporting_excerpt` verbatim, `source{block_id,...}`,
  `origin source|external`, `tier 1-4`, `tier_history[{from,to,reason}]`, `dimensions` (base low/med/high;
  exam_relevance also allows very_high; optional recall/conceptual/confusion/elimination/statement values),
  optional `cognitive_level` (recall|understanding|distinction|application|analysis),
  `confusion_cluster`, `prerequisite_units`. Exam-value fields drive blueprinting.
- Question roles: `knowledge_units[{ku_id, role: primary|secondary|distractor_basis}]`;
  coverage = primary full, secondary partial, distractor_basis zero; only `validated` count.
- Statements: `{text, truth_value, ku_basis, alteration, alteration_type}`; options carry
  `covers: [n,...]` for key-logic checking.
- `confusion_type` enum: near_synonym, adjacent_value, reversed_causality, wrong_date,
  wrong_person, wrong_place, wrong_article, partial_truth, overgeneralization, plausible_external.
- Question `type` enum: factual_mcq, statement_based, assertion_reason, match_pairs,
  elimination_mcq, one_liner_mcq, data_interpretation_mcq, reasoning_mcq, pedagogy_mcq,
  sequence_mcq, true_false (2 options allowed).
- Gate: COMPREHENSIVE iff tier1=tier2=100% validated, recall at threshold, diff resolved,
  no density/downgrade/skew/dup flags, no limitations, plus (new-engine banks) required
  cognitive forms present, no critical KU only weakly tested, required exam purposes present,
  high-priority confusion clusters addressed. Any limitation → at most LIMITED.
  `gate.py` recomputes from the audit body; hand-edited status headers are ignored.
  Difficulty = reasoning demand (easy recall / medium relation-distinction / hard statement-elimination-integration).
- Modes: fidelity `SOURCE_BOUND` (default) | `ENHANCED` (external tagged+shown);
  scope `COMPREHENSIVE` (default) | `FIXED_COUNT` (exact N, honest coverage report).
- Never invent facts (R4); never claim 100% without script output (R12).
