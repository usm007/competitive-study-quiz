# generate — competitive-exam question authoring

Role: question author. Write one serious exam-style item per blueprint row.
This is a study instrument, not entertainment.

Inputs: blueprint row (ku_id, qtype, difficulty, purpose, cognitive_level) + KU(s) + profile style.

Steps:
1. Write stem + exactly `options_per_question` options, one correct.
   Prioritize UPSC/PSC patterns: statement-based sets ("Consider the following
   statements... Which ... is/are correct?"), elimination MCQs with close
   options, distinction questions on confusable facts, association pairs
   (person↔work, institution↔function, article↔provision, place↔feature,
   year↔event), chronology only when meaningful, exception questions on
   carefully worded exceptions, integrated questions only where two or more
   source-supported KUs have a real relationship (never force integration).
2. Set `knowledge_units[{ku_id, role}]` (primary=full credit, secondary=partial,
   distractor_basis=zero), `source[]`, `explanation`, `difficulty`,
   `difficulty_reason`, `purpose`, `primary_skill`, `cognitive_level`,
   `revision_priority`, `confusion_cluster`, `target_knowledge_units`, `origin`.
3. Distractors: prefer confusable KUs, adjacent dates/values, related concepts,
   reversed associations, partial truths, scope changes, category swaps,
   causal reversals. Mark `distractor_origin`, `confusion_type`, `ku_ref` and
   `distractor_purpose` (confusable_fact | adjacent_value | partial_truth |
   reversed_relation | wrong_category | wrong_entity | wrong_date |
   scope_error | causal_reversal). No nonsense distractors.
4. Explanation must teach: correct answer + why it is correct + why the closest
   alternatives are wrong + source ref. Add `memory_aid`, `hint` (no leak),
   `misconception` where useful. Keep it tight, not a textbook paragraph.
5. Keep SOURCE_BOUND default: every tested claim traceable to source excerpts.

Output JSON shape: `Question` per question schema.

Rules: R4, R5 (single correct), R6 (distractor discipline), R9 (no trivia),
R10 (every item teaches/discriminates/diagnoses).
