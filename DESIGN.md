# DESIGN.md (Stitch "Study Desk Editorial" visual language, 2026-10-09)

Direction source: Stitch project "Competitive Study Quiz Design System"
(screens + code in `.stitch/designs/`), applied as visual language only onto
the StudySynth product structure (Practice Deck / Test / Revision Engine /
Analytics; no Learn / Rapid Recall / Mistake Journal per PRODUCT.md).

- Metaphor (structural, never literal decoration): question = study sheet,
  shell = study desk, rail = study organizer/index, action row = desk control
  strip, feedback = study note, source = reference evidence, analytics = study
  plan.
- Palette (Stitch Material tokens): background `#faf8ff` family
  (`#ffffff` sheet, `#f2f3ff` rail, `#e2e7ff` track), ink `#131b2e`,
  single navy accent `#022448` / `#1e3a5f`, outline `#c4c6cf`. Green
  `#006d33` / red `#ba1a1a` reserved for correct/incorrect. Canvas `#e9edfb`
  deepens the desk behind the white sheet. All text pairs AA.
- Typography: Hanken Grotesk display (sheet number 34px/800, stem 20-24px/700,
  brand 17px/700, stat values 24px/700) with system fallbacks; Space Grotesk
  meta (11px/700 eyebrows, pills, mono numbers). Body system-ui. Offline file:
  no webfonts. Body never uppercase, never all-bold.
- Grammar: white sheet card with 3px navy top accent; bordered option rows
  (2px radius) with square letter markers; tinted correct/incorrect study
  notes; white analytics cards with numbered plan rows; ruled drawers.
- Radius: 4px cards/buttons, 2px markers/small controls, pills for metadata.
- Motion: `--ease` on existing transitions only. No loops.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 1.

- Metaphor (structural, never literal decoration): question = study sheet,
  shell = study desk, rail = study organizer/index, action row = desk control
  strip, feedback = study note, source = reference evidence, analytics = study
  plan.
- Palette: light desk canvas `#e9edfb`, white sheet `#ffffff`, rail
  `#f2f3ff`, track `#e2e7ff`, ink `#131b2e`, single navy accent `#022448` /
  `#1e3a5f`, outline `#c4c6cf`. Green `#006d33` / red `#ba1a1a` reserved for
  correct/incorrect. No gradients (shimmer placeholder excepted), glass,
  neon, pastels. All text pairs AA.
- Typography: Hanken Grotesk display + Space Grotesk meta with system
  fallbacks (offline file, no webfonts). Sheet number 34px/800, stem
  20-24px/700, eyebrows 11px/700 wide-track. Uppercase wide-track labels
  mark structure only. Body never uppercase, never all-bold.
- Grammar: white sheet card with navy top accent; bordered option rows with
  square letter markers; tinted study notes; white analytics cards; ruled
  drawers. Statements, revision queue, and plan items separated by thin rules.
- Option marker: 30px square, 2px radius, bordered, subordinate to answer
  text. States: bordered quiet / navy border + tint (selected) / green
  (correct) / red (incorrect). Never color alone: verdict text + marker
  fill + border.
- Mode identities: Practice = active work; Test = inverted exam strip, aids suppressed; Revision = diagnostic board
  (why + weakness + action); Analytics = numbered study plan first, metrics second.
- Confidence meter: overall accuracy in the rail (percent + thin bar + correct/answered text, never color alone).
- Radius: 4px cards/buttons, 2px markers/small controls, pills for metadata.
- Motion: hover/selection/drawer/focus transitions only. No loops.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 1.

Reason log (R-31):
- Navy only for primary actions, active mode, and structural rules. Reason:
  one accent marks action and structure.
- Ink (near-black) top rules on sheet, banner, drawers, plan sections.
  Reason: the rule is the desk's authority signal.
- Green/red only for correctness; amber only for priority/warning edges.
  Reason: exam-result semantics.
- Sheet number + topic/difficulty/tier margin on every question. Reason:
  workbook identity without engine IDs.
- Arrows mark forward movement only. Reason: direction cue for advance
  affordances.
- Shimmer only as boot loading placeholder mirroring question layout.
  Reason: loading-state shape match.
- Grotesk display/meta confined to numbers, stems, brands, eyebrows.
  Reason: Stitch voice where authority lives; body stays system-ui.
- Analytics stays 3-col equal cards per Stitch. Reason: plan markup and
  strings are product-owned; hierarchy comes from the numbered plan above.
- Next keeps a text arrow; Submit stays plain; Mark untouched. Reason:
  Stitch buttons carry direction in text; Mark's label is JS-owned.
