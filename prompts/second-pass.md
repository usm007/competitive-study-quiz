# second-pass — recall sweep for missed facts

Role: recall checker. Find facts the first pass missed.

Inputs: `source blocks[]` + `kus[]` from pass 1.

Steps:
1. Re-scan tables, lists, captions, footnotes.
2. Add missing KUs only (same schema, new KU-#### ids).
3. Never duplicate existing ids; mark weak-OCR blocks for LIMITED status.

Output JSON shape: `{"added_kus": [KnowledgeUnit], "weak_blocks": [block_id]}`.

Rules: R1, R4, R3 (unresolved diffs block COMPREHENSIVE).
