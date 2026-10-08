# DESIGN.md (transcribed from the as-built Study Desk UI, 2026-10-08)

Direction source for antislop R-37. Transcribed from what the app already is, not a new proposal.

- Identity: focused exam study desk. Warm paper background, navy primary, restrained green/red/amber reserved for correct/incorrect/priority.
- Palette: paper `#f4f2ec`, surface `#fffefa`, ink `#16202e`, secondary `#3c4654`, muted `#5d6673` (darkened for WCAG AA), accent navy `#1e3a5f`, good `#1c6b3d`, bad `#a4262c`, warn `#8a6d00`.
- Typography: system-ui stack (offline exam file, no webfont dependency). Question 22-26px weight 750 is the single anchor. Uppercase wide-track labels mark metadata only.
- Layout: top desk bar, quiet study rail, centered 840px work column, desk control-strip action bar. No permanent right panel.
- Radius: 8px cards/options/buttons, 6px small badges, full-pill chips/tabs only.
- Motion: none beyond hover and transitions. No loops.

Dial: ENERGY 1 / RHYTHM 1 / MOTION 1.

Reason log (R-31):
- Navy only for primary focus actions and active mode. Reason: one accent marks the one thing to do next.
- Green/red only for correct/incorrect states. Reason: exam-result semantics.
- Amber only for priority/warning edges. Reason: warning semantics.
- Left-edge stripes mark state (learn note, priority, warning), never decoration. Reason: edge position signals state class.
- Arrows mark forward movement only. Reason: direction cue for advance affordances.
- Shimmer exists only as the boot loading placeholder mirroring question layout. Reason: loading-state shape match.
- Centered single column. Reason: one study sheet on the desk; focus over density.
