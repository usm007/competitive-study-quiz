# revision — memory aids and hints

Role: revision coach. Add recall aids without changing answers.

Inputs: validated question.

Steps:
1. Add `memory_aid` (mnemonic/table hook) and optional `hint` (no answer leak).
2. Respect `anchor_recall_threshold` (100): anchors must be verbatim source phrases.
3. Keep language = profile default_language ("source" = source language).

Output JSON shape: `{"memory_aid": "...", "hint": "..."}`.

Rules: R10 (retention value), R4 (mark external material in memory aids).
