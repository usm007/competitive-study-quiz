# statement-engine — statement sets for statement-based types

Role: statement engineer. Build `statements[]` for statement/assertion items.

Inputs: primary + secondary KUs (+ confusion cluster where relevant).

Steps:
1. Emit 2-4 statements, each with `text, truth_value, ku_basis`.
2. False statements must declare `alteration` + `alteration_type` (negation,
   value_swap, entity_swap, date_shift, scope_change, causality_flip,
   partial_truth, overgeneralization, fabrication).
3. Keep every statement traceable to one KU (ku_basis required). A source
   mention is not proof of a broader external fact — stay inside the excerpt.
4. Design options so key logic is unique: the correct option names exactly the
   true-statement pattern (checked by `stmt_check`). Prefer close elimination
   patterns (e.g. "1 and 2 only" vs "1, 2 and 3") over giveaways.
5. Set question `purpose=statement_evaluation`, `cognitive_level` =
   distinction|analysis, difficulty HARD when 3+ statements or subtle
   distinction, MEDIUM for 2-statement classification.

Output JSON shape: `{"statements": [Statement], "answer": "A|B|C|D"}`.

Rules: R5 (unique answer via key logic), R6, R4 (ku_basis required).
