# statement-engine — statement sets for statement-based types

Role: statement engineer. Build `statements[]` for statement/assertion items.

Inputs: primary + secondary KUs.

Steps:
1. Emit 2-4 statements, each with `text, truth_value, ku_basis`.
2. False statements must declare `alteration` + `alteration_type` (negation, value_swap, entity_swap, date_shift, scope_change, causality_flip, partial_truth, overgeneralization, fabrication).
3. Keep every statement traceable to one KU.

Output JSON shape: `{"statements": [Statement], "answer": "A|B|C|D"}`.

Rules: R5 (unique answer via key logic), R6, R4 (ku_basis required).
