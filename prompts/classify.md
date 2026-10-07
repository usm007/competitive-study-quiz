# classify — tier, exam-value and cognitive tagging

Role: classifier. Assign tier + exam-value dimensions to each KU.

Inputs: `kus[]` + profile + tier_targets.

Steps:
1. Score base dimensions {importance, exam_relevance, factual_density,
   conceptual_density, confusion_risk, discrimination_value, revision_priority}.
   exam_relevance allows very_high|high|medium|low.
2. Score exam-value dimensions {recall_value, conceptual_value, confusion_value,
   elimination_value, statement_potential} (low|medium|high|very_high). These
   MUST drive blueprinting: high confusion_value -> distinction/confusable_fact
   forms; high statement_potential -> statement_evaluation; high
   elimination_value -> elimination_mcqs. They are not decoration.
3. Assign cognitive_level (recall|understanding|distinction|application|analysis),
   confusion_cluster (id shared by confusable KUs), prerequisite_units ([KU-ids]).
4. Assign tier 1 (core) / 2 (important) / 3 (supporting) / 4 (exclude).
5. Enforce tier_targets {1:100,2:100,3:80,4:0}% coverage intent; tier 4 gets `omission_reason`.

Output JSON shape: `{"kus": [KnowledgeUnit]}`.

Rules: R3 (unjustified Tier 1/2 downgrades block COMPREHENSIVE), config tier_targets.
CONTENT COVERAGE != COGNITIVE COVERAGE: a Critical KU normally needs multiple
forms (recall + distinction + statement) where the source supports them.
