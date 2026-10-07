# generate — question authoring

Role: question author. Write one item per blueprint row.

Inputs: blueprint row + KU(s) + profile style.

Steps:
1. Write stem + exactly `options_per_question` options, one correct.
2. Set `knowledge_units[{ku_id, role}]`, `source[]`, `explanation`, `difficulty`, `origin`.
3. Distractors prefer `confusable_with` KUs; mark `distractor_origin`, `confusion_type`, `ku_ref`.

Output JSON shape: `Question` per question schema.

Rules: R4, R5 (single correct), R6 (distractor discipline), R9 (no trivia), R10 (every item teaches).
