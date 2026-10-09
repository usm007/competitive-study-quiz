# New Design Plan: Editorial Luxury Reskin of the Study Template

Status: SUPERSEDED 2026-10-09 by the Stitch "Study Desk Editorial" language
(screens + code in `.stitch/designs/`, applied as visual language only).
Luxury tokens/type/grain removed; `--ease` and Submit/Next arrow decisions
carried over only where Stitch agrees (plain Submit, text-arrow Next).

## 1. Direction

Apply the Awwwards-tier UI/UX skill's **Editorial Luxury** archetype
(warm creams, espresso ink, paper grain, serif display) to the Study Desk
output template. Editorial Luxury was chosen because its palette is already
adjacent to the warm desk identity (`--bg:#e9e4d4`, `--surface:#fffdf7`),
making this a refinement pass, not a rewrite.

## 2. Non-negotiable constraints

- All element IDs, JS behavior, user-facing strings, and test-gated
  selectors/values stay intact (`tests/test_web_visual.py`, 39 tests).
- Offline `file://` build: no external URLs (fonts, CDNs), no new
  dependencies. The offline test allowlists only `w3.org` (data-URI SVG).
- PRODUCT.md priorities hold: accuracy → … → study usability → visual
  polish last. No gamification, no SaaS-dashboard decoration, no Learn /
  Rapid Recall modes.

## 3. Planned changes (CSS + 2 scoped HTML spans)

1. **Tokens** — remap existing token *names* to editorial values: ink →
   deep espresso, surfaces → warm creams, accent stays academic navy
   `#1e3a5f` (single-accent rule). No renames → token tests stay green.
2. **Display serif** — sheet number, question stem, brand name get a
   system serif stack (`Iowan Old Style`, Palatino, Georgia — as in the
   chemistry book). Body stays system-ui → `no_georgia_everywhere` passes.
   No webfont links → offline test passes.
3. **Paper grain** — fixed `body::after` data-URI noise overlay,
   `pointer-events:none` (meets the skill's GPU guardrails).
4. **Motion** — `--ease: cubic-bezier(0.32,0.72,0,1)` swapped onto existing
   transitions. No scroll reveals, staggers, or loops.
5. **Editorial Split at component scale** — analytics stat row
   (`repeat(3,1fr)`) becomes asymmetric: lead accuracy metric + stacked
   secondary pair. `bar-row` and all strings intact.
6. **Button-in-button arrows** — nested circular `→` spans in Submit/Next
   only. Never in Mark (JS sets its `textContent` and would wipe children).
7. **Eyebrow polish** — existing micro-labels get slightly wider tracking;
   no structural change.

## 4. Explicit waivers vs the skill

| Skill rule | Verdict | Reason |
|---|---|---|
| Inter / icon-font bans | Satisfied | System-ui + inline SVG already |
| 1px-border ban | Waived | Ledger grammar requires thin rules |
| 2rem double-bezel cards | Waived | 6px product radius; options must stay non-card (gated test) |
| Floating pill nav | Waived | App needs persistent desk chrome |
| Springs / stagger / scroll reveals | Waived | Motion dial 1 (exam focus) |
| Webfont serif (Fraunces et al.) | Waived | Offline constraint; system serif instead |
| Marketing hero rules | N/A | Application workstation has no hero |

Waivers must be appended to the DESIGN.md reason log on implementation.

## 5. Verification on implementation

1. `python -m unittest tests.test_web_visual` → green.
2. `python tests/run_all.py` → 286 tests green.
3. `scripts/build_web.py` sample builds; round-trip check passes.
4. Manual visual screenshot (hosted browser cannot reach local files).
