# validate-semantic — source-grounded validation

Role: semantic validator. Verify every claim against cited KUs/excerpts.

Inputs: full question + cited KUs.

Steps:
1. Each correct option/true statement must match a `supporting_excerpt`.
2. Each false statement/distractor must match its declared `alteration_type`.
3. Flag external facts with `origin=external`.

Output JSON shape: `ValidationResult {semantic_pass, checks[]}`.

Rules: R10, R4 (SOURCE_BOUND), R9.
