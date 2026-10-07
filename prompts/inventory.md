# inventory — KU inventory and dedup

Role: deduplicator. Merge near-duplicate KUs.

Inputs: `kus[]`.

Steps:
1. Normalize statements (case/punct/whitespace).
2. Drop/merge pairs with similarity >= duplicate_threshold (default 0.85).
3. Link `related_ku[]`, `confusable_with[]`; keep `tier_history`.
4. Assign provisional tier 1-4 per importance.

Output JSON shape: `{"kus": [KnowledgeUnit], "merged": [[old_ids, kept_id]]}`.

Rules: R1 (atomize from inventory pass), R6 (record confusable_with for distractor discipline), config tier_targets + per_ku_cap.
