# classify — tier and dimension tagging

Role: classifier. Assign tier + dimensions to each KU.

Inputs: `kus[]` + profile + tier_targets.

Steps:
1. Score dimensions {importance, exam_relevance, factual_density, conceptual_density, confusion_risk, discrimination_value, revision_priority}.
2. Assign tier 1 (core) / 2 (important) / 3 (supporting) / 4 (exclude).
3. Enforce tier_targets {1:100,2:100,3:80,4:0}% coverage intent; tier 4 gets `omission_reason`.

Output JSON shape: `{"kus": [KnowledgeUnit]}`.

Rules: R3 (unjustified Tier 1/2 downgrades block COMPREHENSIVE), config tier_targets.
