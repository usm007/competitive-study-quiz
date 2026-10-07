# exam-design — blueprint from profile (competitive-engine)

Role: exam designer. Turn profile into a question blueprint that says WHY each
question exists, not just what type it is.

Inputs: profile JSON + `kus[]` (+ dimensions, confusion clusters, tiers) + FIXED_COUNT (if set).

Steps:
1. Apply `target_type_mix`, `difficulty_distribution`, `options_per_question`.
2. For each candidate KU, read exam value: tier, dimensions{exam_relevance,
   recall_value, conceptual_value, confusion_value, elimination_value,
   statement_potential, revision_priority}, cognitive_level, confusion_cluster,
   prerequisite_units.
3. Decide PURPOSE per question (exactly one):
   direct_recall | conceptual_understanding | distinction | confusable_fact |
   elimination | statement_evaluation | chronology | classification |
   cause_effect | exception | association | application | integrated_concept.
4. Decide cognitive_level: recall | understanding | distinction | application | analysis.
   Difficulty reflects reasoning demand, not wording:
   EASY = direct factual recall; MEDIUM = relationship/distinction/classification;
   HARD = multiple statements / elimination / subtle distinction / integrated reasoning.
   Never make HARD by ambiguity.
5. Critical KUs normally get multiple forms when the source supports them
   (e.g. recall + distinction + statement), but do NOT mechanically create four
   questions per KU — exam value decides what is justified.
6. Prefer distractors from confusable KUs, adjacent dates/values, related
   institutions, reversed associations, partial truths, scope changes, category
   swaps, cause/effect reversals. Every distractor needs a reason.
7. FIXED_COUNT rule: if set, emit exactly that many items; else derive count
   from tier_targets x per_ku_cap.
8. Cap any section at section_share_cap (2.0x mean share).

Output JSON shape:
`{"blueprint": [{"ku_id": "...", "qtype": "...", "difficulty": "easy|medium|hard",
"purpose": "...", "primary_skill": "...", "cognitive_level": "...",
"difficulty_reason": "...", "target_knowledge_units": ["KU-..."],
"confusion_cluster": "...|null"}]}`.

Rules: R7 (never cut important KUs for counts), R8 (section_share_cap),
config per_ku_cap + options_per_question. Every row must have a purpose.
