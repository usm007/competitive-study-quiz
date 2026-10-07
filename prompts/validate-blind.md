# validate-blind — answer-free validation

Role: blind validator. Check the item WITHOUT seeing `answer`.

Inputs: question minus `answer`.

Steps:
1. Exactly one option derivable from KUs; no giveaway phrasing.
2. Reject duplicates (similarity >= 0.85), ambiguous stems, double-correct.
3. Return pass/fail + codes.

Output JSON shape: `ValidationResult {blind_pass, checks[]}`.

Rules: R5, R11 (record blind_answer + reasoning as evidence).
