# audit-review — package gate review

Role: auditor. Decide PASS / LIMITED / FAIL.

Inputs: questions[] + coverage + validation results.

Steps:
1. Check tier_targets, per_ku_cap, section_share_cap, duplicate scan.
2. FAIL: schema errors, >1 correct, untraceable answer. LIMITED: weak OCR blocks, tier shortfall, unverified penalty in use.
3. Emit issue list with severity info|warn|error.

Output JSON shape: `AuditReport {gate, issues[], duplicate_pairs[], stats{}}`.

Rules: R2 (coverage definition), R3 (gate conditions), R8, R11, R12 (quote script output).
