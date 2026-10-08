# Follow-up report - audit 001 fixes (2026-10-08)

Approved: all 10 findings. All fixed, verified below.

## What changed
- `templates/web/app.template.html`: 11 UI em dashes removed (commas/colons/periods/hyphens); `--muted` darkened `#68727f` to `#5d6673`; faint-text usages switched to muted; boot loading skeleton wired (visible until first render); empty-package error state with Reload; mobile arrows labelled; purpose comments added (type, arrows, stripes, radius, shimmer).
- `scripts/test_engine.py` + `templates/web/test.engine.js` + `tests/test_test_engine.py`: null-score placeholder `—` to `-` consistently (engine parity kept).
- `DESIGN.md`: created from as-built UI (palette, type, layout, radius, motion, dial ENERGY 1 / RHYTHM 1 / MOTION 1, R-31 reason log).
- Rebuilt `build/web-redesign/quiz.html`, `examples/quiz.html`; regenerated full screenset.

## Verification
- `tests/run_all.py`: 255 run, 0 failures, 0 errors, PASS.
- `test_web_visual` + `test_test_engine` + `test_test_js`: 74 run, PASS.
- `node --check`: revision.engine, test.engine PASS.
- Playwright screenset (1440/1280/768/390 + 720/800): all FIT, no pageerrors.
- Template grep `—`: zero matches. Contrast recomputed: muted/bg 5.19, muted/surface 5.76, all text pairs pass AA.
- Engine comments with `—` (two file headers) and PDF/CLI occurrences untouched: non-UI or separate surfaces, noted.

## Delivery Gate
- Hard Gate: PASS (no UI em dash; mobile FIT no overflow; no fake stats/testimonials/claims; nav/controls real; contrast AA measured; keyboard/focus intact; states now empty+loading+error; no patch scripts; no theme toggle to break; ran + click-through via Playwright with zero pageerrors; direction now on file in DESIGN.md; no fabricated content).
- Purpose-Gate: PASS (arrows, stripes, shimmer, type, uppercase labels each have a written reason in CSS comments + DESIGN.md).
- Liveliness: dials ENERGY 1 / RHYTHM 1 / MOTION 1 declared in DESIGN.md; consistent with the calm uniform static desk; focal point is the question; accent is navy at the next action; motif is the centered study sheet.
- Craftsmanship: PASS (every control works; sections follow quiz flow; empty/loading/error present; contrast AA; keyboard intact).
