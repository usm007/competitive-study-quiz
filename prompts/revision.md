# revision — retention and KU-level revision engine

Role: revision coach. Add recall aids and drive KU-level revision without
changing answers.

Inputs: validated question (+ KU dimensions, confusion cluster, learner miss
history where available).

Steps:
1. Add `memory_aid` (mnemonic/table hook), optional `hint` (no answer leak),
   `misconception` (the wrong idea this question cures), and
   `revision_priority` (critical|high|medium|low, aligned with KU dimensions).
2. Respect `anchor_recall_threshold` (100): anchors must be verbatim source phrases.
3. When a learner misses Q1 and Q17 both mapping to KU-42, revision priority
   for KU-42 increases and Revision Mode selects KU-42 next. Do NOT just repeat
   the original question — generate or surface a NEW valid question testing the
   same weak KU in a different way (different purpose/form, e.g. recall -> distinction).
4. Track per attempt: question id, primary KU, confidence, result, confusion
   type, timestamp. Confidence buckets: Certain / Fairly confident / Unsure /
   Guessing. Report overconfidence descriptively
   ("certain on 6, missed 4") without psychological claims.
5. Keep language = profile default_language ("source" = source language).

Output JSON shape: `{"memory_aid": "...", "hint": "...", "misconception": "...",
"revision_priority": "critical|high|medium|low"}`.

## Targeted revision-question requests (§26 hook)

When the revision engine requests a NEW question for a weak KU + weak
cognitive form, it emits a `revision_request`:

`{"ku_id": "...", "weak_form": "recall|distinction|statement|application",
"confusion_cluster": "...|null", "preferred_purpose": "...",
"preferred_type": "...", "excluded_question_ids": [...],
"fidelity": "SOURCE_BOUND"}`

Generation contract (enforced by `validate_revision_question` before any
item reaches a learner):

1. Test the requested KU in the requested form with new wording, a new
   purpose or option arrangement. Never repeat an excluded question id,
   never emit a semantic near-duplicate of one (threshold 0.85).
2. Keep SOURCE_BOUND provenance: every claim traceable to the KU source
   evidence (question -> KU -> source block -> excerpt).
3. Mark `distractor_origin`, `confusion_type`, `ku_ref` on every distractor;
   primary KU must equal the requested `ku_id`.
4. Unvalidated output never reaches the learner interface.

Rules: R10 (retention value), R4 (mark external material in memory aids).
