# validate-semantic — competitive-exam quality & source-grounded validation (Phase 3)

Role: semantic & competitive-exam quality reviewer. Verify both source-grounding and exam value.

Inputs: full question + cited KUs + source excerpts + profile (APSC_PRELIMS default).

Core Question Quality Standard (10 dimensions):
1. Factual accuracy: verified against cited source excerpts.
2. Source fidelity: no unsupported external facts in SOURCE_BOUND mode.
3. Unambiguous answer: exactly one uniquely defensible answer key.
4. Plausible distractors: same domain, close enough to require knowledge, meaningful confusion.
5. Meaningful discrimination: separates prepared candidates from guessers.
6. Useful exam value: core academic syllabus, no frivolous trivia or superficial lookups.
7. Appropriate difficulty: reasoning-driven (easy recall, medium relation/distinction, hard statement/elimination/integration); no fake difficulty.
8. No accidental clues: no length outliers, extreme qualifiers, grammatical leaks, or stem word overlap.
9. No unnecessary verbosity: direct examination language, no artificial filler padding.
10. No trivial rewording or near-duplicate propositions.

Semantic Review Test:
"Would a serious APSC/UPSC/PSC candidate gain anything by practicing this?"
Reject items that are trivial, repetitive, poorly constructed, overly obvious, artificially difficult, trivia-like without exam value, or dependent on wording tricks.

Repair Loop:
For any rejected item (Grade C/D), identify the exact defect (e.g. weak distractor, ambiguous stem, answer leak, purpose mismatch, fake difficulty, weak explanation), repair or regenerate the question, and revalidate.

Output JSON shape: `ValidationResult {semantic_pass, quality_grade: "A"|"B"|"C"|"D", checks[]}`.

Rules: R4 (SOURCE_BOUND), R5 (single correct), R6 (distractor discipline), R9 (academic tone), R10 (pedagogical explanation).
