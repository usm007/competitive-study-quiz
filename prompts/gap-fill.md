# gap-fill — targeted regeneration

Role: gap filler. Replace rejected/uncovered items.

Inputs: audit report + uncovered KUs + failed question ids.

Steps:
1. Target uncovered tier-1/2 KUs first, up to max_gapfill_rounds (5).
2. Re-run generate -> statement-engine -> validators per item.
3. Stop when coverage met or rounds exhausted (then accept LIMITED).

Output JSON shape: `{"new_questions": [Question], "rounds_used": n}`.

Rules: R3 (loop until gate or max rounds), R2 (flagged KUs only).
