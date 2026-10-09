# PRODUCT.md — Competitive Quiz

## 1. Product identity
**Product:** Competitive Quiz
**Short identity:** CQ
**Repository/legacy naming:** Some repository files may still use the legacy name DocToQuiz. That is an implementation/documentation naming detail; the intended learner-facing product identity is Competitive Quiz / CQ.

Competitive Quiz is a **source-grounded competitive-exam study compiler and study workspace**.

It is not primarily a generic quiz website.

Its central job is to take an educational or reference document and systematically transform it into a rigorous, comprehensive, exam-oriented question package that a learner can then study, practise, test, revise, and inspect against the source.

---

## 2. The problem it solves

A normal document-to-MCQ workflow often looks like:

DOCUMENT → summarize → generate a handful of questions → done

That approach has a fundamental weakness: it can produce plausible questions while silently missing important information in the source.

Competitive Quiz is designed around the opposite principle:

> **Inventory the knowledge before generating the questions, then audit whether the important knowledge was actually covered.**

The system therefore treats question generation as a downstream consequence of a structured knowledge model, not as an unconstrained text-generation task.

---

## 3. Core promise

The product's core promise is:

> **Convert a source document into a highly comprehensive, validated, competitive-exam question bank without casually missing important examinable information.**

Comprehensive does not mean pretending that every possible fact in the universe has been covered.

It means:
1. identify the meaningful knowledge present in the source;
2. classify its importance and examinability;
3. determine the question forms required to test it;
4. generate questions from that inventory;
5. validate correctness and source fidelity;
6. measure both content and cognitive coverage;
7. identify gaps;
8. generate targeted gap-fill questions;
9. repeat the audit until the defined gate is satisfied or a limitation must be reported.

The system must be honest when the source itself is insufficient.

---

## 4. Intended exam context

Competitive Quiz is designed primarily for serious objective competitive examinations, including profiles such as:

- APSC
- UPSC
- State PSC examinations
- SSC
- Banking examinations
- Railways
- Teaching examinations
- other configurable objective competitive exams

The architecture is profile-driven so that exam style, difficulty, question-purpose mix, and other expectations can be adapted without changing the core compiler.

The product should always prioritize **exam utility over entertainment**.

---

## 5. The central mental model

The product has two distinct halves.

### A. Compilation

The system reasons about the source.

DOCUMENT → EXTRACTION → STRUCTURE + ANCHORS → KNOWLEDGE INVENTORY → EXAM RELEVANCE / IMPORTANCE → QUESTION BLUEPRINT → QUESTION GENERATION → VALIDATION → QUALITY REVIEW → COVERAGE AUDIT → GAP FILL → FINAL GATE

### B. Study

The learner works with the resulting package.

PRACTICE → TEST → REVISION → ANALYTICS

The study workspace is the **delivery layer for the compiled knowledge package**.

The UI must never obscure the fact that the intellectual core of the product is the first pipeline.

---

## 6. Knowledge inventory is the foundation

A **Knowledge Unit (KU)** is the atomic examinable piece of information or concept identified from the source.

Examples include:
- facts
- dates
- names/entities
- provisions
- definitions
- relationships
- classifications
- comparisons
- exceptions
- quantitative values
- conceptual rules
- cause/effect relationships
- exam-relevant distinctions

Each meaningful KU should have source provenance and exam-value information.

The inventory is not merely a summary.

It is a **testable representation of the source**.

Questions should be derived from the inventory, never casually generated from raw text without first being represented in the knowledge model.

---

## 7. Importance and tiers

Knowledge units are classified by importance, using the repository's tier model:
- **Tier 1 — Critical**
- **Tier 2 — Important**
- **Tier 3 — Supporting**
- **Tier 4 — Low value**

The exact classification is a reasoning task supported by the exam profile and source context.

The purpose of tiers is not to ignore source material arbitrarily.

It is to ensure that exam-critical knowledge receives stronger coverage guarantees than low-value material.

A fixed question count must never be allowed to silently discard important knowledge merely to hit a round number.

---

## 8. Source grounding

The default fidelity mode is **SOURCE_BOUND**.

In SOURCE_BOUND mode:

> No fact that is not supported by the source may be presented as true.

This applies to correct answers, explanations, distractor origins, statements, comparison claims, and source excerpts.

When the source does not support a needed relationship or contextual fact, the system must not invent it merely because it would make a more interesting question.

The correct response is to use a different question purpose, constrain the question, use only source-supported distinctions, or report the limitation.

Enhanced/external modes may exist, but external information must be explicitly tagged and surfaced rather than silently blended into source-grounded content.

---

## 9. Content coverage is not the same as question count

A bank with 100 questions is not automatically comprehensive.

Coverage is measured against the identified knowledge inventory.

The product distinguishes:

### Content coverage
Was the knowledge unit actually tested?

### Cognitive coverage
Was it tested in appropriate ways?

The current cognitive model includes forms such as recall, distinction, application, and statement evaluation.

The underlying system can also reason about more detailed question purposes, including:
- direct recall
- conceptual understanding
- distinction
- confusable fact
- statement evaluation
- elimination
- chronology
- classification
- association
- exception
- cause/effect
- application
- integrated concept

A high-priority KU may therefore require multiple forms of testing rather than one repetitive question.

---

## 10. Question quality

A valid MCQ is not automatically a good competitive-exam question.

Competitive Quiz therefore treats **validation** and **quality acceptance** as separate concepts.

### Validation asks
- Is the structure valid?
- Is there one defensible key?
- Are the options consistent?
- Is the question supported by the source?
- Are provenance and references valid?

### Quality asks
- Is the question genuinely useful for a competitive exam?
- Is the distractor plausible?
- Is the difficulty appropriate?
- Is the cognitive mechanism real?
- Is there answer leakage?
- Is the wording clear?
- Is the purpose correct?
- Does it discriminate meaningfully?
- Is the explanation useful?
- Is the question redundant?

The current quality engine uses 11 dimensions:
1. accuracy
2. source support
3. uniqueness
4. distractor quality
5. exam value
6. difficulty fit
7. clarity
8. purpose fit
9. leak prevention
10. statement quality
11. explanation quality

Only questions that meet the defined quality acceptance threshold should enter the final package.

---

## 11. Distractor philosophy

Distractors are part of the learning design.

They should normally represent genuine confusion patterns or meaningful alternatives, not random wrong answers.

Examples of useful distractor mechanisms include:
- adjacent value
- wrong date
- wrong person/entity
- wrong place
- wrong article/provision
- partial truth
- reversed relationship
- scope error
- causal reversal
- wrong category
- plausible external alternative when the mode permits it

A strong distractor should help diagnose what the learner is confusing.

A nonsense distractor reduces the exam value of the whole question.

---

## 12. Difficulty philosophy

Difficulty should come primarily from **knowledge and reasoning demand**, not from awkward wording.

General intent:
- **Easy:** direct recall / straightforward identification
- **Medium:** distinction, classification, association, relation
- **Hard:** statement evaluation, elimination, integration, multi-step discrimination

The system should never manufacture difficulty by making a question verbose, obscure, or grammatically awkward.

---

## 13. Statement-based questions

Statement questions are a first-class competitive-exam form.

A strong statement question should alter substantive properties such as date, entity, place, function, category, article, relationship, scope, causality, exception, or quantitative value.

Changing wording without changing substantive meaning is not sufficient merely to make a statement different.

The statement engine must preserve a defensible truth value and make the alteration meaningful.

---

## 14. Coverage audit and gap filling

After generation, the system audits the bank.

The audit asks:
- Which Tier 1 knowledge is covered?
- Which Tier 2 knowledge is covered?
- Which KUs have weak or missing cognitive forms?
- Which purposes are missing?
- Which confusion clusters remain unaddressed?
- Are there redundancy/skew problems?
- Are there important KUs that are only weakly tested?

The gap-fill stage then generates **only what is missing**.

It should not simply generate more questions for already saturated areas.

The loop is:

GENERATE → VALIDATE → MEASURE → AUDIT → FILL GAPS → MEASURE AGAIN

A final package is comprehensive only when the configured gate says so.

---

## 15. The gate is authoritative

The product must never infer completion from:
- number of generated questions
- model confidence
- a hand-written percentage
- visual appearance
- looks complete

The authoritative status comes from the deterministic audit/gate pipeline.

Possible outcomes include:
- **COMPREHENSIVE**
- **PARTIAL**
- **LIMITED**

A source or extraction limitation must be reported honestly.

The system should prefer an honest LIMITED/PARTIAL package over a falsely complete package.

---

## 16. The final package

The compiler produces a validated study package containing the questions and the metadata required by the learner-facing experience.

The package supports:
- interactive standalone web study
- printable A4 question paper
- answer key
- explanation booklet
- source references
- learner-study metadata
- revision/test/analytics behavior

The package is intended to work offline as a standalone study artifact.

---

## 17. The Study Desk

The Study Desk is the learner-facing environment.

It should be understood as:

> **a focused digital study workspace for working through the compiled question bank.**

It is NOT:
- a generic mock-test website
- a dashboard product
- a gamified quiz
- a literal paper examination sheet
- a social learning platform

Its primary visual hierarchy is:

ACTIVE STUDY TASK → QUESTION → ANSWER → FEEDBACK / LEARNING → NEXT ACTION

The learner should always know:
- where they are
- what they are solving
- what mode they are in
- what action comes next

---

## 18. Study modes

### Practice (Practice Deck)

Purpose:
**Think → Answer → Review**

Practice permits answer selection, confidence, hints where supported, immediate feedback, explanations, source inspection, marking, and navigation.

A sidebar Confidence meter shows overall accuracy (`correct / answered`) so the learner always sees how they are doing.

### Test

Purpose:
**Exam conditions**

Test should suppress study assistance until submission.

Typical restrictions include no hints, no source, no confidence workflow, and no immediate feedback.

### Revision

Purpose:
**Targeted correction**

Revision uses learner performance signals and the existing revision engine to surface weak areas and high-priority work.

The system should explain why an item is appearing.

### Analytics

Purpose:
**Study planning**

Analytics should answer:

> **What should I study next?**

It should prioritize actionable recommendations over decorative dashboards.

---

## 19. Learner feedback philosophy

Feedback should not merely announce right/wrong.

It should teach the distinction that matters.

For a wrong answer, the learner should quickly understand:
- what they chose
- what was correct
- the key distinction
- what trap was tested
- where the information came from

The system can expose deeper explanation and technical references progressively rather than dumping internal metadata into the primary study surface.

---

## 20. Source transparency

Source-grounded study requires visible provenance.

The learner should be able to inspect:
- document
- relevant reference
- linked knowledge support
- source excerpt
- technical references when needed

The UI must communicate trust without overwhelming the learner.

Never fabricate an excerpt for visual completeness.

---

## 21. Offline-first delivery

The standalone web output is intended to work without a cloud service.

The package should contain the required study data locally.

The project does not require a cloud database, accounts, or authentication for its core document-to-quiz workflow.

Any future cloud product would be a separate product decision, not a prerequisite for the core skill.

---

## 22. Supported source philosophy

The compiler is intended to handle reference material from multiple document classes, including PDF, DOCX, PPTX, XLSX, TXT, Markdown, and HTML.

Scanned/image-heavy material may have extraction limitations.

When extraction is unreliable, the system must surface the limitation rather than fabricate content.

---

## 23. Important product boundaries

Competitive Quiz is intentionally **not** trying to become a giant adaptive learning platform.

The core product does NOT require:
- accounts
- social features
- cloud sync
- gamification
- streak systems
- badges
- chat
- AI tutoring chat
- elaborate recommendation marketplaces
- live current-affairs monitoring
- unnecessary dashboards
- subscription infrastructure

The current revision engine is useful because it directly supports studying the generated package.

New features should justify themselves against the core mission.

---

## 24. What should never be sacrificed

The following priorities are in descending order:

1. **Accuracy**
2. **Source fidelity**
3. **Coverage of important knowledge**
4. **Competitive-exam usefulness**
5. **Question quality**
6. **Honest reporting of limitations**
7. **Study usability**
8. **Visual polish**

A beautiful UI must never compensate for weak question quality.

A large question count must never compensate for poor coverage.

A 100% label must never be used without the authoritative gate.

---

## 25. What the product should feel like

The intellectual feeling: **rigorous**

The examination feeling: **serious**

The study feeling: **focused**

The interface feeling: **modern and purposeful**

The product should feel like a tool built by people who understand competitive-exam preparation, not a generic quiz template with exam labels added.

---

## 26. What the product should NOT feel like

### Generic ed-tech
Pick a quiz, click an answer, see a score.

### SaaS dashboard
Cards, metrics, charts, filters everywhere.

### Paper simulation
Beige sheet, heavy rules, rigid form layout.

### Gamification
Streaks, points, badges, confetti.

### AI toy
Chat-first, novelty-first, exam-second.

---

## 27. Architecture principle

The system is intentionally hybrid.

### Reasoning belongs to the model/LLM layer

Examples:
- extract meaning
- atomize knowledge
- judge importance
- design exam purposes
- write questions
- create meaningful distractors
- explain reasoning
- perform blind semantic review
- identify conceptual gaps

### Determinism belongs to scripts

Examples:
- ingestion
- anchor extraction
- schema checks
- quote/provenance verification
- option/key checks
- coverage calculation
- deduplication
- audit
- gating
- rendering checks

This separation is a major product principle.

---

## 28. Why this separation matters

A model can say: looks comprehensive.

That is not sufficient.

A script can verify: Tier 1 is 100% validated coverage.

That is materially useful.

Likewise, a model can write a plausible question.

The validator/quality system must still check key uniqueness, source support, distractors, purpose, redundancy, and quality threshold.

The product is designed around this division of responsibility.

---

## 29. Definition of product success

A successful run should produce a package in which:

### Source understanding
The meaningful source knowledge has been inventoried.

### Exam relevance
Important material receives stronger attention.

### Question quality
Questions are defensible, useful, and competitive-exam appropriate.

### Coverage
Important knowledge is demonstrably covered.

### Cognitive coverage
Important knowledge is tested in suitable forms.

### Trust
Every supported question can be traced to source evidence.

### Gap handling
Missing forms are explicitly identified and filled where possible.

### Delivery
The final package is usable in web and print form.

### Study
A learner can actually use the package to learn, practise, test, and revise.

---

## 30. Definition of failure

The product has failed even if the code runs when:
- important source facts were silently omitted
- questions are hallucinated
- distractors are nonsense
- multiple answers are defensible
- the same idea is repeatedly asked without purpose
- coverage is claimed without evidence
- the source cannot support the question
- quality filtering is bypassed
- a fixed question count removes important knowledge
- the UI makes studying cumbersome
- technical metadata overwhelms the learner
- the product looks like a generic mock-test template

---

## 31. Relationship between the major repository documents

Use these documents for different responsibilities.

### PRODUCT.md
The **why** and **what** of the product.
It defines the product mission, boundaries, mental model, priorities, and overall system philosophy.

### SKILL.md
The **how** at operational level.
It defines rules, pipeline stages, field contracts, gates, and execution behavior.

### README.md
The **how to use it** documentation.
It should explain supported inputs, quickstart commands, generated outputs, and user-facing repository operation.

### DESIGN.md
The **current UI design language**.
It records the visual/system rules for the Study Desk and should not redefine the intellectual mission of the skill.

### prompts/
The detailed reasoning instructions used by the LLM stages.

### schemas/
The machine-readable contracts.

### scripts/
The deterministic enforcement and reporting layer.

---

## 32. Decision rule for future changes

Before adding a feature, engine, UI pattern, or workflow, ask:

> **Does this directly improve the compilation of a source into a high-quality competitive-exam study package, or materially improve the learner's ability to study that package?**

If neither answer is clearly yes, it probably does not belong in the core skill.

If it improves the product but introduces a major new product category, treat that as a separate future project rather than silently expanding the core.

---

## 33. North-star statement

Competitive Quiz exists to do one thing exceptionally well:

> **Turn serious study material into a comprehensive, trustworthy, competitive-exam question bank and give the learner a focused environment in which to master it.**

Everything else is supporting infrastructure.