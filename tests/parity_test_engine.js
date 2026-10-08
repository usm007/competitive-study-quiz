/* Parity harness: runs the browser test engine on JSON fixtures.
 * Usage: node tests/parity_test_engine.js <input.json>
 * Output: JSON with rng/assembly/scoring/analysis/session outputs for
 * comparison against scripts/test_engine.py on the same inputs.
 */
"use strict";
const fs = require("fs");
const TE = require("../templates/web/test.engine.js");

const inp = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const out = {};

out.rng = (inp.rng_cases || []).map(c => {
  const rng = new TE.RNG(c.seed);
  const seq = [];
  for (let i = 0; i < 5; i++) seq.push(rng.random());
  return { seed: c.seed, seq: seq,
           shuffle: new TE.RNG(c.seed).shuffle([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) };
});
out.hashes = (inp.hash_cases || []).map(s => TE.xfnv1a(s));

out.assembled = (inp.assemble_cases || []).map(c => {
  try {
    const r = TE.assemble(c.questions, c.validation, c.config, c.inventory || null, c.profile || null);
    return { paper: r.paper, errors: r.errors };
  } catch (e) {
    return { paper: null, errors: ["threw: " + e.message] };
  }
});
out.validated = (inp.config_cases || []).map(c => TE.validateConfig(c));
out.rules = (inp.rule_cases || []).map(c => TE.resolveRules(c.profile || null, c.config || null));
out.scored = (inp.score_cases || []).map(c => {
  const qmap = {};
  (c.questions || []).forEach(q => { if (q && q.id) qmap[q.id] = q; });
  return TE.scoreSession(c.paper_or_rules, c.answers, qmap);
});
out.analyzed = (inp.analyze_cases || []).map(c => {
  const qmap = {};
  (c.questions || []).forEach(q => { if (q && q.id) qmap[q.id] = q; });
  return TE.analyzeResults(c.paper, c.answers, qmap, c.kus || null, c.now_ms === undefined ? null : c.now_ms);
});
out.sessions = (inp.session_cases || []).map(c => {
  const s = TE.newTestSession(c.paper, c.config || null, c.now_ms);
  return {
    session: { test_id: s.test_id, expires_at: s.expires_at, question_ids: s.question_ids },
    remaining: TE.remainingMs(s, c.at),
    expired: TE.isExpired(s, c.at)
  };
});
out.finalized = (inp.finalize_cases || []).map(c => {
  const s = JSON.parse(JSON.stringify(c.session));
  const res = TE.finalizeSession(s, c.questions || [], c.now_ms, c.reason || "submitted");
  const res2 = TE.finalizeSession(s, c.questions || [], c.now_ms + 99999, "submitted");
  return { result: res, frozen: res === res2, submitted: s.submitted };
});
out.fmt = (inp.fmt_cases || []).map(f => TE.fmtFrac(f));
out.retake_seeds = (inp.retake_cases || []).map(s => TE.retakeSeed(s));

console.log(JSON.stringify(out));
