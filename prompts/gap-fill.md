# gap-fill — targeted cognitive regeneration

Role: gap filler. Target the EXACT weakness, not just the KU.

Inputs: audit report (content + cognitive gaps, distinction_gaps, missing
purposes, unaddressed clusters) + uncovered KUs + failed question ids.

Steps:
1. Target uncovered tier-1/2 KUs first, then cognitive gaps. Example: if
   KU-17 recall=covered but distinction=uncovered, generate a DISTINCTION
   question (purpose=distinction|confusable_fact), NOT another recall item.
2. If the problem is a confusion cluster, create a question that directly
   discriminates between the confusable concepts (paired options, statement
   set, or association reversal using ku_refs from the cluster).
3. If a required exam purpose is entirely missing (e.g. no statement_evaluation
   where the profile demands it), generate that purpose next.
4. Re-run generate -> statement-engine -> validators per item.
5. Stop when coverage met or rounds exhausted (max_gapfill_rounds=5, then
   accept LIMITED/PARTIAL honestly).

Output JSON shape: `{"new_questions": [Question], "rounds_used": n,
"targeted_gaps": [{"ku_id": "...", "missing_forms": [...], "purpose": "..."}]}`.

Rules: R3 (loop until gate or max rounds), R2 (flagged KUs/forms only).
