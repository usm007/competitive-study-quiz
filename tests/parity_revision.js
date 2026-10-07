/* Parity harness: runs the browser revision engine on JSON fixtures.
 * Usage: node tests/parity_revision.js <input.json>
 * Input: {kus, questions, events, now, queue_modes, select_cases, session_sizes, migrate}
 * Output: JSON with queue/mastery/selections/sessions/migrated for comparison
 * against scripts/revision.py on the same inputs.
 */
"use strict";
const fs = require("fs");
const RE = require("../templates/web/revision.engine.js");

const inp = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const { kus, questions, events, now } = inp;
const qmap = {};
(questions || []).forEach(q => { if (q && q.id) qmap[q.id] = q; });
const qbyku = RE.questionsByPrimary(questions || []);

const normed = (events || []).map(e => RE.normalizeEvent(e, qmap[e.question_id], now));
const aggs = RE.aggregate(normed, qmap);

const reqOf = ku => RE.requiredFormsFor(ku, kus && kus.length ? kus : null, qbyku);
const queue = RE.buildQueue(aggs, kus && kus.length ? kus : null, questions || [], now, null);
const mastery = {};
Object.keys(aggs).forEach(k => {
  const meta = (kus || []).find(u => u.id === k) || null;
  mastery[k] = RE.masteryOf(k, aggs[k], meta, now, null, reqOf(k));
});

const sessions = {};
(inp.queue_modes || []).forEach(m => {
  const key = (m.weak_form ? m.mode + "+" + m.weak_form : m.mode);
  sessions[key] = RE.selectSession(queue, m.mode, m.limit === undefined ? null : m.limit,
                                   m.weak_form || null, null).map(e => e.ku_id);
});
(inp.session_sizes || []).forEach(s => {
  sessions["build_" + s] = RE.buildSession(queue, s, null).map(e => e.ku_id);
});

const picks = (inp.select_cases || []).map(c =>
  RE.selectQuestion(c.ku_id, c.weak_form, questions || [], {
    answeredIds: c.answered || [], excludeIds: c.exclude || [],
    answeredBlobs: c.answered_blobs || [], lastPurpose: c.last_purpose || null,
    fidelity: c.fidelity || "SOURCE_BOUND"
  }));

const migrated = inp.migrate ? RE.migrateSession(inp.migrate) : null;

console.log(JSON.stringify({ queue, mastery, sessions, picks, migrated }));
