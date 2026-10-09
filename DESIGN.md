# DESIGN.md (Study Desk editorial identity, 2026-10-08)

Direction source for antislop R-37. Identity: an editorial study workstation
(premium workbook + examination paper + digital reading interface), not a
mock-test website.

- Metaphor (structural, never literal decoration): question = study sheet,
  shell = study desk, rail = study organizer/index, action row = desk control
  strip, feedback = study note, source = reference evidence, analytics = study
  plan.
- Palette: warm desk canvas `#e6dcc4`, warm cream study surface `#fdf9ee`,
  deep espresso ink `#231a10`, academic navy `#1e3a5f` (single accent).
  Green/red/amber reserved for correct/incorrect/priority. No gradients
  (shimmer placeholder excepted), glass, neon, pastels. Editorial Luxury
  reskin applied 2026-10-09 per `new_design_plan.md`; all text pairs AA.
- Typography carries identity: system-ui body (offline file, no webfont);
  system serif display (`Iowan Old Style`, Palatino, Georgia) for sheet
  number, question stem, brand name only. Uppercase wide-track labels
  mark structure only. Body never uppercase, never all-bold.
- Grammar: typography + ink rules + spacing + surfaces. Cards are not the
  default; options are ruled ledger rows; statements, revision queue, and plan
  items are separated by thin rules.
- Option marker: 30px square, 4px radius, bordered, subordinate to answer
  text. States: quiet / navy inset (selected) / green inset (correct) / red
  inset (incorrect). Never color alone: verdict text + marker fill + rule.
- Mode identities: Practice = active work; Test = inverted exam strip, aids suppressed; Revision = diagnostic board
  (why + weakness + action); Analytics = numbered study plan first, metrics second.
- Confidence meter: overall accuracy in the rail (percent + thin bar + correct/answered text, never color alone).
- Radius: 6px sheets/panels/buttons, 4px markers/small controls, 99px
  metadata pills only.
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
- Paper grain is a static data-URI noise overlay, pointer-events none.
  Reason: tactile paper feel with zero motion cost; hidden in print.
- Display serif confined to sheet number, stem, brand. Reason: editorial
  voice where authority lives; body stays system-ui for scan speed.
- Analytics lead metric spans two rows beside a stacked pair. Reason:
  accuracy-first hierarchy without touching markup or strings.
- Nested circular arrows live inside Submit/Next only, never Mark. Reason:
  Mark's label is JS-owned textContent; children would be wiped.
- Waivers vs the Editorial Luxury skill (new_design_plan.md §4): 1px-rule
  ban waived (ledger grammar needs thin rules); double-bezel cards waived
  (6px product radius, options stay non-card); floating pill nav waived
  (persistent desk chrome required); springs/staggers/reveals waived
  (motion dial 1); webfont serif waived (offline file, system serif);
  marketing-hero rules N/A (no hero).
