/* Deterministic KU-level revision engine (Phase 2) — browser mirror.
 *
 * Mirrors scripts/revision.py exactly: same constants, same rules, same
 * ordering (score desc, ku_id asc). The Python module is the source of
 * truth; tests/test_revision_js.py checks parity on shared fixtures.
 * Inlined offline into the built page by scripts/build_web.py.
 */
"use strict";
var RevisionEngine = (function () {
  var SESSION_VERSION = 2;

  var DEFAULT_CONFIG = {
    tier_weight: { "1": 30, "2": 15, "3": 5 },
    exam_relevance_weight: { very_high: 12, high: 8, medium: 4, low: 0 },
    ku_priority_weight: { critical: 8, high: 5, medium: 2, low: 0 },
    w_recent_wrong: 20,
    w_repeat_wrong: 8, repeat_cap: 3,
    w_hce_certain: 12, hce_certain_cap: 2,
    w_hce_fairly: 6, hce_fairly_cap: 2,
    w_confusion_repeat: 10,
    w_cognitive_gap: 10, cog_gap_cap: 2,
    w_stale: 8, w_never_correct: 6,
    w_marked: 4,
    relief_per_recent_correct: 6, relief_cap: 18,
    recent_days: 7, mid_days: 30,
    recent_mult: 1.0, mid_mult: 0.7, old_mult: 0.4,
    recent_window_n: 5, stale_days: 14,
    band_critical: 60, band_high: 35, band_medium: 15,
    stable_min_attempts: 4, stable_window: 3, stable_no_hce_days: 30,
    form_stable_min_correct: 2,
    quick_size: 5,
    session_recipe: [["priority", 4], ["confusion", 3], ["cognitive", 2], ["stale", 1]],
    topic_cap: 3,
    dup_threshold: 0.85,
    retest_after_new: 3,
    conf_certain: "Certain", conf_fairly: "Fairly confident",
    conf_unsure: "Unsure", conf_guessing: "Guessing"
  };

  var RECENT_ERROR = "recent_error", REPEATED_ERROR = "repeated_error",
      HIGH_CONF_ERROR = "high_confidence_error", CONFUSION_CLUSTER = "confusion_cluster",
      COGNITIVE_GAP = "cognitive_gap", STALE_RECALL = "stale_recall",
      MARKED = "marked_for_revision", LOW_RECENT_ACC = "low_recent_accuracy",
      INCOMPLETE_MASTERY = "incomplete_mastery";

  var REASON_LABELS = {};
  REASON_LABELS[RECENT_ERROR] = "Recent incorrect answer";
  REASON_LABELS[REPEATED_ERROR] = "Repeated errors detected";
  REASON_LABELS[HIGH_CONF_ERROR] = "Recent high-confidence error";
  REASON_LABELS[CONFUSION_CLUSTER] = "Repeated confusion in one cluster";
  REASON_LABELS[COGNITIVE_GAP] = "Weak cognitive form";
  REASON_LABELS[STALE_RECALL] = "No recent successful recall";
  REASON_LABELS[MARKED] = "Marked for revisit";
  REASON_LABELS[LOW_RECENT_ACC] = "Recent accuracy is below target";
  REASON_LABELS[INCOMPLETE_MASTERY] = "Required forms not yet demonstrated";

  var NEW = "NEW", LEARNING = "LEARNING", WEAK = "WEAK",
      IMPROVING = "IMPROVING", STABLE = "STABLE";

  var FORM_TO_QTYPE = { recall: "factual_mcq", distinction: "elimination_mcq",
                        statement: "statement_based", application: "reasoning_mcq" };
  var FORM_TO_PURPOSE = { recall: "direct_recall", distinction: "distinction",
                          statement: "statement_evaluation", application: "application" };
  var COG_ORDER = ["recall", "distinction", "statement", "application"];

  var PURPOSE_TO_COG = { direct_recall: "recall", conceptual_understanding: "recall",
    distinction: "distinction", confusable_fact: "distinction", elimination: "statement",
    statement_evaluation: "statement", chronology: "recall", classification: "distinction",
    cause_effect: "application", exception: "distinction", association: "distinction",
    application: "application", integrated_concept: "application" };
  var TYPE_TO_COG = { factual_mcq: "recall", one_liner_mcq: "recall", true_false: "recall",
    match_pairs: "distinction", sequence_mcq: "distinction", elimination_mcq: "statement",
    statement_based: "statement", assertion_reason: "statement",
    reasoning_mcq: "application", data_interpretation_mcq: "application",
    pedagogy_mcq: "application" };
  var COG_LEVEL_TO_COG = { recall: "recall", understanding: "recall",
    distinction: "distinction", application: "application", analysis: "application" };

  var REVISION_MODES = ["targeted", "mistakes", "confusion", "hce",
                        "cognitive", "quick", "full"];

  function cfg(config, key) {
    if (config && config[key] !== undefined) return config[key];
    return DEFAULT_CONFIG[key];
  }
  function toEpoch(ts) {
    if (ts === null || ts === undefined) return null;
    if (typeof ts === "number") return ts;
    var n = Number(ts);
    if (ts !== "" && !isNaN(n) && !/[T:\-Z]/.test(String(ts))) return n;
    var ms = Date.parse(ts);
    return isNaN(ms) ? null : ms / 1000;
  }
  function daysSince(ts, now) {
    var t = toEpoch(ts), n = toEpoch(now);
    if (t === null || n === null) return null;
    return Math.max(0, (n - t) / 86400);
  }
  function toks(s) {
    s = String(s == null ? "" : s).normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
    var m = s.match(/[a-z0-9]+/g);
    return m || [];
  }
  function tokenSetSim(a, b) {
    var sa = {}, sb = {}, ka = 0, kb = 0, inter = 0, k;
    toks(a).forEach(function (t) { if (!sa[t]) { sa[t] = 1; ka++; } });
    toks(b).forEach(function (t) { if (!sb[t]) { sb[t] = 1; kb++; } });
    if (!ka && !kb) return 1;
    if (!ka || !kb) return 0;
    for (k in sa) if (sb[k]) inter++;
    return inter / (ka + kb - inter);
  }

  function primaryOf(q) {
    var kus = (q && q.knowledge_units) || [];
    for (var i = 0; i < kus.length; i++)
      if (kus[i] && kus[i].role === "primary") return kus[i].ku_id;
    return null;
  }
  function questionForms(q) {
    var forms = {};
    var purp = (q && typeof q.purpose === "string") ? q.purpose.trim() : "";
    if (purp && PURPOSE_TO_COG[purp]) forms[PURPOSE_TO_COG[purp]] = 1;
    var cl = q && q.cognitive_level;
    if (typeof cl === "string" && COG_LEVEL_TO_COG[cl]) forms[COG_LEVEL_TO_COG[cl]] = 1;
    if (!Object.keys(forms).length) {
      var t = (q && (q.type || q.qtype)) || "unknown";
      forms[TYPE_TO_COG[t] || "recall"] = 1;
    }
    if (q && q.statements) forms.statement = 1;
    var ft = (q && (q.type || q.qtype)) || "";
    if (ft === "elimination_mcq" || ft === "statement_based" || ft === "assertion_reason")
      forms.statement = 1;
    return forms;
  }
  function questionBlob(q) {
    var parts = [(q && (q.stem || q.question)) || ""];
    ((q && q.options) || []).forEach(function (o) {
      parts.push((o && typeof o === "object") ? (o.text || "") : String(o));
    });
    return parts.join(" ");
  }
  function questionsByPrimary(questions) {
    var out = {};
    (questions || []).forEach(function (q) {
      if (!q || typeof q !== "object") return;
      ((q && q.knowledge_units) || []).forEach(function (e) {
        if (e && e.role === "primary" && e.ku_id) {
          (out[e.ku_id] = out[e.ku_id] || []).push(q);
        }
      });
    });
    return out;
  }
  function requiredForms(ku) {
    // Port of coverage.required_forms: exam-value-driven required forms.
    var t = parseInt(ku && ku.tier, 10);
    var tier = isNaN(t) ? 3 : t;
    var dims = (ku && ku.dimensions) || {};
    var confRisk = dims.confusion_risk || "low";
    var stmtPot = dims.statement_potential || dims.conceptual_density || "medium";
    var confVal = dims.confusion_value || confRisk;
    var hasConfusable = !!((ku && ku.confusable_with) || []).length;
    var req = {};
    if (tier === 1 && (confRisk === "high" || confVal === "high" || hasConfusable)) {
      req = { recall: 1, distinction: 1, statement: 1 };
    } else if (tier === 1) {
      req = { recall: 1, statement: 1 };
      if (hasConfusable || confRisk === "medium" || confRisk === "high") req.distinction = 1;
    } else if (tier === 2 && (confRisk === "high" || hasConfusable)) {
      req = { recall: 1, distinction: 1 };
    } else if (tier === 2) {
      req = { recall: 1 };
    } else {
      req = { recall: 1 };
    }
    var trig = { cause_effect: 1, process: 1, principle: 1, theory: 1, formula: 1,
                 comparison: 1, classification: 1, concept: 1 };
    if (trig[ku && ku.type] && tier <= 2 &&
        (dims.conceptual_density === "medium" || dims.conceptual_density === "high"))
      req.application = 1;
    return Object.keys(req);
  }
  function requiredFormsFor(kuId, kuMetas, questionsByKu) {
    // With inventory metadata: exam-value rules. Without (browser has only
    // the bank): forms available per KU. Python uses the same fallback.
    if (kuMetas && kuMetas.length) {
      for (var i = 0; i < kuMetas.length; i++) {
        if (kuMetas[i] && kuMetas[i].id === kuId) {
          try { return requiredForms(kuMetas[i]); } catch (e) { break; }
        }
      }
    }
    var forms = {};
    ((questionsByKu || {})[kuId] || []).forEach(function (q) {
      var f = questionForms(q);
      Object.keys(f).forEach(function (k) { forms[k] = 1; });
    });
    var ks = Object.keys(forms);
    return ks.length ? ks : ["recall"];
  }

  function normalizeEvent(raw, question, now) {
    raw = (raw && typeof raw === "object") ? raw : {};
    var q = (question && typeof question === "object") ? question : {};
    var kus = q.knowledge_units || [];
    var prim = null, secs = [];
    kus.forEach(function (e) {
      if (e && e.ku_id) {
        if (e.role === "primary" && prim === null) prim = e.ku_id;
        else if (e.role === "secondary") secs.push(e.ku_id);
      }
    });
    var res = raw.result;
    if (res === undefined || res === null) {
      var c = raw.correct;
      res = (c === true) ? "correct" : ((c === false) ? "wrong" : null);
    }
    if (res !== "correct" && res !== "wrong" && res !== "skipped") res = null;
    var ev = {
      timestamp: (raw.timestamp !== undefined) ? raw.timestamp : raw.time,
      question_id: (raw.question_id !== undefined) ? raw.question_id : raw.qid,
      primary_ku: raw.primary_ku || raw.primaryKu || prim,
      secondary_kus: raw.secondary_kus || secs,
      result: res,
      selected_answer: (raw.selected_answer !== undefined) ? raw.selected_answer : raw.sel,
      correct_answer: (raw.correct_answer !== undefined) ? raw.correct_answer : raw.key,
      confidence: (raw.confidence !== undefined) ? raw.confidence : raw.conf,
      confusion_type: (raw.confusion_type !== undefined) ? raw.confusion_type : raw.distype,
      question_purpose: raw.question_purpose || raw.purpose || q.purpose || null,
      cognitive_level: raw.cognitive_level || raw.cog || q.cognitive_level || null,
      difficulty: raw.difficulty || q.difficulty || null,
      mode: raw.mode || null,
      time_taken_ms: (raw.time_taken_ms !== undefined) ? raw.time_taken_ms : (raw.dt_ms !== undefined ? raw.dt_ms : null),
      marked: !!raw.marked,
      revision_priority_at_attempt: (raw.revision_priority_at_attempt !== undefined)
        ? raw.revision_priority_at_attempt : (raw.rev_priority !== undefined ? raw.rev_priority : null)
    };
    if ((ev.timestamp === undefined || ev.timestamp === null) && now !== undefined && now !== null)
      ev.timestamp = now;
    return ev;
  }

  function emptyAgg() {
    return { attempts: 0, correct: 0, incorrect: 0, skipped: 0,
      accuracy: null, recent: [], recent_accuracy: null,
      certain_wrong: 0, fairly_wrong: 0, unsure_correct: 0, guessing_correct: 0,
      high_confidence_errors: 0, low_confidence_correct: 0,
      last_attempted: null, last_correct: null, last_result: null, last_confidence: null,
      consecutive_correct: 0, consecutive_incorrect: 0,
      forms: {}, types: {}, purposes: {},
      confusion_wrong: {}, confusion_all: {}, clusters_wrong: {},
      marked: false, secondary_exposure: 0 };
  }
  function bump(d, k) { if (k) d[k] = (d[k] || 0) + 1; }

  function aggregate(events, questionsById, config) {
    config = config || null;
    var qmap = questionsById || {};
    var aggs = {};
    var ordered = (events || []).filter(function (e) {
      return e && typeof e === "object" && e.primary_ku;
    }).slice().sort(function (a, b) {
      var ta = toEpoch(a.timestamp), tb = toEpoch(b.timestamp);
      ta = (ta === null) ? 0 : ta; tb = (tb === null) ? 0 : tb;
      if (ta !== tb) return ta - tb;
      return String(a.question_id || "") < String(b.question_id || "") ? -1 : 1;
    });
    var CC = cfg(config, "conf_certain"), CF = cfg(config, "conf_fairly"),
        CU = cfg(config, "conf_unsure"), CG = cfg(config, "conf_guessing");
    ordered.forEach(function (e) {
      var ku = e.primary_ku;
      var a = aggs[ku] || (aggs[ku] = emptyAgg());
      var res = e.result, conf = e.confidence;
      a.attempts++;
      a.last_attempted = e.timestamp;
      a.last_result = res;
      a.last_confidence = conf;
      if (e.marked) a.marked = true;
      if (res === "skipped") { a.skipped++; }
      else if (res === "correct") {
        a.correct++; a.last_correct = e.timestamp;
        a.consecutive_correct++; a.consecutive_incorrect = 0;
        if (conf === CU || conf === CG) a.low_confidence_correct++;
        if (conf === CU) a.unsure_correct++;
        if (conf === CG) a.guessing_correct++;
      } else if (res === "wrong") {
        a.incorrect++; a.consecutive_incorrect++; a.consecutive_correct = 0;
        if (conf === CC) { a.certain_wrong++; a.high_confidence_errors++; }
        if (conf === CF) a.fairly_wrong++;
      }
      var q = qmap[e.question_id] || {};
      var forms = questionForms(Object.assign({}, q, {
        purpose: (e.question_purpose !== null && e.question_purpose !== undefined) ? e.question_purpose : q.purpose,
        cognitive_level: (e.cognitive_level !== null && e.cognitive_level !== undefined) ? e.cognitive_level : q.cognitive_level,
        type: q.type, statements: q.statements
      }));
      Object.keys(forms).forEach(function (f) {
        var st = a.forms[f] || (a.forms[f] = { attempts: 0, correct: 0 });
        if (res === "correct" || res === "wrong") {
          st.attempts++;
          if (res === "correct") st.correct++;
        }
      });
      if (q.type) bump(a.types, q.type);
      var purp = e.question_purpose || q.purpose;
      if (purp) bump(a.purposes, purp);
      var ct = e.confusion_type;
      if (ct) { bump(a.confusion_all, ct); if (res === "wrong") bump(a.confusion_wrong, ct); }
      if (q.confusion_cluster && res === "wrong") bump(a.clusters_wrong, q.confusion_cluster);
      if (res === "correct" || res === "wrong")
        a.recent.push({ result: res, confidence: conf, timestamp: e.timestamp,
                        forms: Object.keys(forms).sort() });
    });
    ordered.forEach(function (e) {
      ((e && e.secondary_kus) || []).forEach(function (sk) {
        if (typeof sk === "string" && sk) {
          var a = aggs[sk] || (aggs[sk] = emptyAgg());
          a.secondary_exposure++;
        }
      });
    });
    var W = cfg(config, "recent_window_n");
    Object.keys(aggs).forEach(function (k) {
      var a = aggs[k], n = a.correct + a.incorrect;
      a.accuracy = n ? a.correct / n : null;
      var tail = a.recent.slice(-W).filter(function (r) {
        return r.result === "correct" || r.result === "wrong";
      });
      a.recent_accuracy = tail.length ?
        tail.filter(function (r) { return r.result === "correct"; }).length / tail.length : null;
    });
    return aggs;
  }

  function recencyMult(daysAgo, config) {
    if (daysAgo === null || daysAgo === undefined) return cfg(config, "mid_mult");
    if (daysAgo <= cfg(config, "recent_days")) return cfg(config, "recent_mult");
    if (daysAgo <= cfg(config, "mid_days")) return cfg(config, "mid_mult");
    return cfg(config, "old_mult");
  }
  function kuImportance(kuMeta, config) {
    if (!kuMeta || typeof kuMeta !== "object") return [0, {}];
    var tw = cfg(config, "tier_weight"), erw = cfg(config, "exam_relevance_weight"),
        kpw = cfg(config, "ku_priority_weight");
    var dims = kuMeta.dimensions || {};
    var parts = {
      tier: tw[String(kuMeta.tier !== undefined ? kuMeta.tier : "")] || 0,
      exam_relevance: erw[dims.exam_relevance] || 0,
      ku_priority: kpw[dims.revision_priority] || 0
    };
    // question-tier fallback when inventory metadata is absent (browser)
    if (!parts.tier && kuMeta.fallback_tier !== undefined)
      parts.tier = tw[String(kuMeta.fallback_tier)] || 0;
    return [parts.tier + parts.exam_relevance + parts.ku_priority, parts];
  }
  function bandOf(score, config) {
    if (score >= cfg(config, "band_critical")) return "critical";
    if (score >= cfg(config, "band_high")) return "high";
    if (score >= cfg(config, "band_medium")) return "medium";
    return "low";
  }
  function scoreKu(kuId, agg, kuMeta, now, config, requiredForms) {
    config = config || null;
    var reasons = [], weakForms = [];
    var breakdown = { base: 0, error: 0, relief: 0, marked: 0, mult: 1 };
    if (!agg || !(agg.attempts > 0)) {
      if (agg && agg.marked) {
        reasons.push(MARKED);
        breakdown.marked = cfg(config, "w_marked");
      }
      var sc0 = breakdown.marked;
      return { score: Math.round(sc0 * 10) / 10, band: bandOf(sc0, config),
               reasons: reasons, weak_forms: weakForms, breakdown: breakdown };
    }
    var imp = kuImportance(kuMeta, config);
    var evidence = agg.incorrect > 0;
    breakdown.base = Math.round((evidence ? imp[0] : imp[0] * 0.25) * 10) / 10;
    var err = 0;
    if (agg.last_result === "wrong") { err += cfg(config, "w_recent_wrong"); reasons.push(RECENT_ERROR); }
    var extra = Math.max(0, (agg.incorrect || 0) - 1);
    if (extra > 0) {
      err += Math.min(extra, cfg(config, "repeat_cap")) * cfg(config, "w_repeat_wrong");
      reasons.push(REPEATED_ERROR);
    }
    var hce = Math.min(agg.certain_wrong || 0, cfg(config, "hce_certain_cap"));
    if (hce > 0) { err += hce * cfg(config, "w_hce_certain"); reasons.push(HIGH_CONF_ERROR); }
    var hcf = Math.min(agg.fairly_wrong || 0, cfg(config, "hce_fairly_cap"));
    if (hcf > 0) err += hcf * cfg(config, "w_hce_fairly");
    var rep = Object.keys(agg.confusion_wrong || {}).some(function (k) { return agg.confusion_wrong[k] >= 2; }) ||
              Object.keys(agg.clusters_wrong || {}).some(function (k) { return agg.clusters_wrong[k] >= 2; });
    if (rep) { err += cfg(config, "w_confusion_repeat"); reasons.push(CONFUSION_CLUSTER); }
    var req = requiredForms || [];
    var failed = [], untried = [];
    COG_ORDER.forEach(function (f) {
      if (req.indexOf(f) < 0) return;
      var st = (agg.forms || {})[f] || { attempts: 0, correct: 0 };
      if (st.attempts > 0 && st.correct === 0) failed.push(f);
      else if (st.correct === 0) untried.push(f);
    });
    weakForms = failed.concat(untried);
    if (failed.length) {
      err += Math.min(failed.length, cfg(config, "cog_gap_cap")) * cfg(config, "w_cognitive_gap");
      reasons.push(COGNITIVE_GAP);
    } else if (weakForms.length) reasons.push(INCOMPLETE_MASTERY);
    var dCorrect = daysSince(agg.last_correct, now), dLast = daysSince(agg.last_attempted, now);
    var staleDays = cfg(config, "stale_days");
    if ((agg.last_correct === null || agg.last_correct === undefined) && (agg.attempts || 0) > 0 &&
        (dLast === null || dLast >= staleDays)) {
      err += cfg(config, "w_never_correct"); reasons.push(STALE_RECALL);
    } else if (dCorrect !== null && dCorrect >= staleDays) {
      err += cfg(config, "w_stale"); reasons.push(STALE_RECALL);
    }
    if (agg.marked) {
      breakdown.marked = cfg(config, "w_marked");
      if (reasons.indexOf(MARKED) < 0) reasons.push(MARKED);
    }
    var mult = recencyMult(dLast, config);
    breakdown.mult = mult;
    breakdown.error = Math.round(err * mult * 10) / 10;
    var W = cfg(config, "recent_window_n");
    var recentCorrect = (agg.recent || []).slice(-W).filter(function (r) { return r.result === "correct"; }).length;
    breakdown.relief = -Math.min(recentCorrect * cfg(config, "relief_per_recent_correct"),
                                 cfg(config, "relief_cap"));
    var score = Math.max(0, breakdown.base + breakdown.error + breakdown.relief + breakdown.marked);
    var ra = agg.recent_accuracy;
    if ((agg.last_result === "wrong") ||
        (ra !== null && ra !== undefined && ra < 0.5 && (agg.attempts || 0) >= 2)) {
      if (reasons.indexOf(LOW_RECENT_ACC) < 0) reasons.push(LOW_RECENT_ACC);
    }
    return { score: Math.round(score * 10) / 10, band: bandOf(score, config),
             reasons: reasons, weak_forms: weakForms, breakdown: breakdown };
  }

  function masteryOf(kuId, agg, kuMeta, now, config, requiredForms) {
    config = config || null;
    if (!agg || !(agg.attempts > 0)) return NEW;
    var n = cfg(config, "stable_min_attempts"), w = cfg(config, "stable_window");
    var tail = (agg.recent || []).slice(-w).filter(function (r) {
      return r.result === "correct" || r.result === "wrong";
    }).map(function (r) { return r.result; });
    var hceDays = cfg(config, "stable_no_hce_days");
    var CC = cfg(config, "conf_certain");
    var recentHce = (agg.recent || []).some(function (r) {
      if (!(r.result === "wrong" && r.confidence === CC)) return false;
      var d = daysSince(r.timestamp, now);
      return d === null || d <= hceDays;
    });
    var req = requiredForms || [];
    var formsOk = req.every(function (f) {
      var st = (agg.forms || {})[f] || { attempts: 0, correct: 0 };
      return st.attempts === 0 || st.correct > 0;
    });
    if ((agg.attempts || 0) >= n && tail.length >= Math.min(w, 3) &&
        tail.every(function (r) { return r === "correct"; }) && !recentHce && formsOk)
      return STABLE;
    if ((agg.incorrect || 0) >= 1) {
      var last2 = (agg.recent || []).slice(-2).filter(function (r) {
        return r.result === "correct" || r.result === "wrong";
      }).map(function (r) { return r.result; });
      if (last2.length === 2 && last2[0] === "correct" && last2[1] === "correct")
        return IMPROVING;
    }
    var ra = agg.recent_accuracy;
    if (agg.last_result === "wrong" ||
        (ra !== null && ra !== undefined && ra < 0.5 && (agg.attempts || 0) >= 2))
      return WEAK;
    return LEARNING;
  }
  function formMastery(agg, form, now, config) {
    var st = ((agg && agg.forms) || {})[form] || { attempts: 0, correct: 0 };
    if (!agg || !st.attempts) return NEW;
    if (st.correct >= cfg(config, "form_stable_min_correct")) return STABLE;
    if (st.correct > 0) return IMPROVING;
    return WEAK;
  }

  function kuSourceRef(kuMeta, questionsArray) {
    if (kuMeta && typeof kuMeta === "object") {
      var src = kuMeta.source || {};
      if (src.block_id) {
        var sec = Array.isArray(src.section_path) ? src.section_path.join(" > ") : (src.section_path || "");
        return { block_id: src.block_id, page: src.page, section: sec, table_ref: src.table_ref || null };
      }
    }
    var arr = questionsArray || [];
    for (var i = 0; i < arr.length; i++) {
      var qq = arr[i], ss = (qq && qq.source) || [];
      for (var j = 0; j < ss.length; j++) {
        var s = ss[j];
        if (s && typeof s === "object" && s.block_id) {
          var sec2 = Array.isArray(s.section_path) ? s.section_path.join(" > ") : (s.section_path || "");
          return { block_id: s.block_id, page: s.page, section: sec2, table_ref: s.table_ref || null };
        }
      }
    }
    return {};
  }
  function buildQueue(aggregates, kuMetas, questions, now, config) {
    config = config || null;
    var metas = {};
    (kuMetas || []).forEach(function (k) { if (k && k.id) metas[k.id] = k; });
    var qbyku = questionsByPrimary(questions || []);
    var entries = [];
    Object.keys(aggregates || {}).forEach(function (kuId) {
      var agg = aggregates[kuId];
      var meta = metas[kuId];
      var req = requiredFormsFor(kuId, kuMetas, qbyku);
      var s = scoreKu(kuId, agg, meta, now, config, req);
      if (!(s.score > 0) && !s.reasons.length) return;
      var topic = (meta && meta.topic) || "";
      if (!topic && (qbyku[kuId] || []).length) topic = qbyku[kuId][0].topic || "";
      var firstWeak = (s.weak_forms && s.weak_forms.length) ? s.weak_forms[0] : "recall";
      entries.push({
        ku_id: kuId, topic: topic, subtopic: (meta && meta.subtopic) || "",
        priority: s.band, score: s.score, reasons: s.reasons, weak_forms: s.weak_forms,
        source: kuSourceRef(meta, qbyku[kuId] || []),
        recommended_type: FORM_TO_QTYPE[firstWeak] || "factual_mcq",
        last_result: agg.last_result, confidence_signal: agg.last_confidence,
        mastery: masteryOf(kuId, agg, meta, now, config, req),
        next_action: "Practise " + firstWeak + " items"
      });
    });
    entries.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return a.ku_id < b.ku_id ? -1 : 1;
    });
    return entries;
  }

  var REVISION_MODES_LIST = REVISION_MODES.slice();
  function selectSession(queue, mode, limit, weakForm, config) {
    if (REVISION_MODES.indexOf(mode) < 0) throw new Error("unknown revision mode: " + mode);
    var out;
    if (mode === "mistakes")
      out = queue.filter(function (e) {
        return e.reasons.indexOf(REPEATED_ERROR) >= 0 || e.reasons.indexOf(RECENT_ERROR) >= 0;
      });
    else if (mode === "confusion")
      out = queue.filter(function (e) { return e.reasons.indexOf(CONFUSION_CLUSTER) >= 0; });
    else if (mode === "hce")
      out = queue.filter(function (e) { return e.reasons.indexOf(HIGH_CONF_ERROR) >= 0; });
    else if (mode === "cognitive") {
      out = queue.filter(function (e) {
        return e.reasons.indexOf(COGNITIVE_GAP) >= 0 || e.reasons.indexOf(INCOMPLETE_MASTERY) >= 0;
      });
      if (weakForm) out = out.filter(function (e) { return e.weak_forms.indexOf(weakForm) >= 0; });
    }
    else if (mode === "quick") out = queue.slice(0, cfg(config, "quick_size"));
    else out = queue.slice();
    out = out.slice().sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return a.ku_id < b.ku_id ? -1 : 1;
    });
    if (limit !== undefined && limit !== null) out = out.slice(0, limit);
    return out;
  }
  function buildSession(queue, size, config) {
    size = (size === undefined || size === null) ? 10 : size;
    var recipe = cfg(config, "session_recipe").map(function (r) { return [r[0], r[1]]; });
    var sum = 0, i;
    for (i = 0; i < recipe.length; i++) sum += recipe[i][1];
    if (size !== 10 || sum !== 10) {
      recipe = recipe.map(function (r) {
        return [r[0], Math.max(1, Math.round(size * r[1] / (sum || 1)))];
      });
    }
    function pool(key) {
      if (key === "priority") return queue.slice();
      if (key === "confusion") return queue.filter(function (e) { return e.reasons.indexOf(CONFUSION_CLUSTER) >= 0; });
      if (key === "cognitive") return queue.filter(function (e) {
        return e.reasons.indexOf(COGNITIVE_GAP) >= 0 || e.reasons.indexOf(INCOMPLETE_MASTERY) >= 0;
      });
      return queue.filter(function (e) { return e.reasons.indexOf(STALE_RECALL) >= 0; });
    }
    var cap = cfg(config, "topic_cap");
    var picked = [], counts = {};
    function has(id) {
      return picked.some(function (p) { return p.ku_id === id; });
    }
    function take(list, n, enforceCap) {
      var got = [];
      for (var j = 0; j < list.length; j++) {
        if (got.length >= n || picked.length + got.length >= size) break;
        var e = list[j];
        if (has(e.ku_id) || got.some(function (g) { return g.ku_id === e.ku_id; })) continue;
        if (enforceCap && (counts[e.topic] || 0) >= cap) continue;
        counts[e.topic] = (counts[e.topic] || 0) + 1;
        got.push(e);
      }
      return got;
    }
    var byScore = queue.slice().sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return a.ku_id < b.ku_id ? -1 : 1;
    });
    recipe.forEach(function (r) {
      take(pool(r[0]), r[1], true).forEach(function (e) { picked.push(e); });
    });
    take(byScore, size, true).forEach(function (e) { picked.push(e); });
    take(byScore, size, false).forEach(function (e) { picked.push(e); });
    return picked.slice(0, size);
  }

  function structurallyOk(q) {
    if (!q || typeof q !== "object" || !q.id) return false;
    if (((q.options) || []).length < 2) return false;
    if (!q.answer) return false;
    if (primaryOf(q) === null) return false;
    if (!(q.stem || q.question)) return false;
    return true;
  }
  function selectQuestion(kuId, weakForm, questions, opts) {
    opts = opts || {};
    var answered = {}, i;
    (opts.answeredIds || []).forEach(function (id) { answered[id] = 1; });
    var excluded = {};
    (opts.excludeIds || []).forEach(function (id) { excluded[id] = 1; });
    var answeredBlobs = opts.answeredBlobs || [];
    var lastPurpose = opts.lastPurpose || null;
    var fidelity = opts.fidelity || "SOURCE_BOUND";
    var thr = (opts.dupThreshold !== undefined) ? opts.dupThreshold : cfg(opts.config, "dup_threshold");
    var cands = [];
    (questions || []).forEach(function (q) {
      if (!structurallyOk(q)) return;
      if (excluded[q.id]) return;
      if (fidelity === "SOURCE_BOUND" && (q.origin || "source") !== "source") return;
      if (primaryOf(q) !== kuId) return;
      if (weakForm) {
        var has = false, f = questionForms(q);
        if (f[weakForm]) has = true;
        if (!has) return;
      }
      cands.push(q);
    });
    var fresh = [], seen = [];
    cands.forEach(function (q) {
      if (answered[q.id]) { seen.push(q); return; }
      var blob = questionBlob(q);
      var dup = answeredBlobs.some(function (ab) { return tokenSetSim(blob, ab) >= thr; });
      if (!dup) fresh.push(q);
    });
    function rank(q) {
      var purp = q.purpose || "";
      return [answered[q.id] ? 1 : 0,
              (!lastPurpose || purp !== lastPurpose) ? 0 : 1, q.id];
    }
    fresh.sort(function (a, b) {
      var ra = rank(a), rb = rank(b);
      if (ra[1] !== rb[1]) return ra[1] - rb[1];
      return ra[2] < rb[2] ? -1 : 1;
    });
    if (fresh.length) {
      var q = fresh[0];
      return { question_id: q.id,
               strategy: (weakForm && questionForms(q)[weakForm]) ? "new_form" : "new_item",
               reason: "Unanswered " + (weakForm || "any form") + " item on " + kuId };
    }
    var need = (opts.config && opts.config.retest_after_new !== undefined)
      ? opts.config.retest_after_new : cfg(opts.config, "retest_after_new");
    return { question_id: null, strategy: "generate",
      reason: "No fresh " + (weakForm || "any form") + " item left; repeat needs " + need + " newer attempts first",
      request: revisionRequest(kuId, weakForm, null, null, null,
        Object.keys(answered).concat(Object.keys(excluded)).sort(), fidelity) };
  }

  function revisionRequest(kuId, weakForm, confusionCluster, preferredPurpose,
                           preferredType, excludedQuestionIds, fidelity) {
    var form = weakForm || "recall";
    var excl = Array.from(new Set(excludedQuestionIds || [])).sort();
    return {
      ku_id: kuId, weak_form: form, confusion_cluster: confusionCluster || null,
      preferred_purpose: preferredPurpose || FORM_TO_PURPOSE[form] || "direct_recall",
      preferred_type: preferredType || FORM_TO_QTYPE[form] || "factual_mcq",
      excluded_question_ids: excl, fidelity: fidelity || "SOURCE_BOUND",
      rules: [
        "Test the same KU in a different wording, purpose or form; never repeat an excluded question.",
        "Keep SOURCE_BOUND provenance: every claim traceable to the KU source evidence.",
        "Mark distractor_origin, confusion_type and ku_ref on every distractor."
      ]
    };
  }

  function migrateSession(raw) {
    function fresh(reason) {
      return [{ study_session_version: SESSION_VERSION, answers: {}, events: [],
                mode: "practice", revision_state: { queue: [], sessions: [] } },
              true, [reason]];
    }
    if (!raw || typeof raw !== "object") return fresh("empty input defaulted to fresh v2 session");
    if (raw.study_session_version === SESSION_VERSION &&
        raw.answers && typeof raw.answers === "object") {
      var s = {}, k;
      for (k in raw) s[k] = raw[k];
      if (!Array.isArray(s.events)) s.events = [];
      if (!s.revision_state || typeof s.revision_state !== "object")
        s.revision_state = { queue: [], sessions: [] };
      if (!s.mode) s.mode = "practice";
      Object.keys(s.answers).forEach(function (qid) {
        var a = s.answers[qid];
        if (a && typeof a === "object") {
          ["conf", "sel", "correct", "marked", "primary_ku", "time", "mode"].forEach(function (f) {
            if (a[f] === undefined) a[f] = (f === "marked") ? false : null;
          });
        }
      });
      return [s, false, ["already v2"]];
    }
    var answers = {}, notes = [];
    var mode = raw.mode || "practice";
    if (raw.answers && typeof raw.answers === "object") {
      Object.keys(raw.answers).forEach(function (qid) {
        var a = raw.answers[qid];
        if (!a || typeof a !== "object") { notes.push("dropped non-object answer " + qid); return; }
        answers[qid] = {
          sel: (a.sel !== undefined) ? a.sel : null,
          conf: (a.conf !== undefined) ? a.conf : null,
          correct: (a.correct !== undefined) ? a.correct : null,
          distype: (a.distype !== undefined) ? a.distype : null,
          dpurpose: (a.dpurpose !== undefined) ? a.dpurpose : null,
          primary_ku: (a.primary_ku !== undefined) ? a.primary_ku : null,
          marked: !!a.marked, time: (a.time !== undefined) ? a.time : null,
          mode: (a.mode !== undefined) ? a.mode : null,
          dt_ms: (a.dt_ms !== undefined) ? a.dt_ms : null,
          key: (a.key !== undefined) ? a.key : null,
          difficulty: (a.difficulty !== undefined) ? a.difficulty : null,
          purpose: (a.purpose !== undefined) ? a.purpose : null,
          cog: (a.cog !== undefined) ? a.cog : null,
          secondary_kus: (a.secondary_kus !== undefined) ? a.secondary_kus : null,
          rev_priority: (a.rev_priority !== undefined) ? a.rev_priority : null
        };
      });
      notes.push("migrated " + Object.keys(answers).length + " answers from legacy format");
    } else if (Array.isArray(raw.responses)) {
      raw.responses.forEach(function (r) {
        if (!r || typeof r !== "object" || !r.question_id) return;
        answers[r.question_id] = {
          sel: (r.selected_answer !== undefined) ? r.selected_answer : null,
          conf: (r.confidence !== undefined) ? r.confidence : null,
          correct: (r.result === "correct") ? true : ((r.result === "wrong") ? false : null),
          distype: (r.confusion_type !== undefined) ? r.confusion_type : null,
          dpurpose: null, primary_ku: (r.primary_ku !== undefined) ? r.primary_ku : null,
          marked: !!r.marked, time: (r.timestamp !== undefined) ? r.timestamp : null,
          mode: (r.mode !== undefined) ? r.mode : null,
          dt_ms: (r.time_taken_ms !== undefined) ? r.time_taken_ms : null,
          key: (r.correct_answer !== undefined) ? r.correct_answer : null,
          difficulty: (r.difficulty !== undefined) ? r.difficulty : null,
          purpose: (r.question_purpose !== undefined) ? r.question_purpose : null,
          cog: (r.cognitive_level !== undefined) ? r.cognitive_level : null,
          secondary_kus: (r.secondary_kus !== undefined) ? r.secondary_kus : null,
          rev_priority: (r.revision_priority_at_attempt !== undefined) ? r.revision_priority_at_attempt : null
        };
      });
      notes.push("migrated " + Object.keys(answers).length + " schema responses");
    } else {
      notes.push("no answers found; fresh session");
    }
    var events = Object.keys(answers).sort().map(function (qid) {
      var a = answers[qid];
      return {
        timestamp: a.time, question_id: qid, primary_ku: a.primary_ku,
        secondary_kus: a.secondary_kus || [],
        result: (a.correct === true) ? "correct" : ((a.correct === false) ? "wrong" : null),
        selected_answer: a.sel, correct_answer: a.key, confidence: a.conf,
        confusion_type: a.distype, question_purpose: a.purpose,
        cognitive_level: a.cog, difficulty: a.difficulty, mode: a.mode || mode,
        time_taken_ms: a.dt_ms, marked: !!a.marked,
        revision_priority_at_attempt: a.rev_priority
      };
    });
    return [{ study_session_version: SESSION_VERSION, answers: answers,
              events: events, mode: mode,
              revision_state: { queue: [], sessions: [] } }, true, notes];
  }

  return {
    SESSION_VERSION: SESSION_VERSION,
    DEFAULT_CONFIG: DEFAULT_CONFIG,
    REVISION_MODES: REVISION_MODES_LIST,
    REASON_LABELS: REASON_LABELS,
    reasons: { RECENT_ERROR: RECENT_ERROR, REPEATED_ERROR: REPEATED_ERROR,
      HIGH_CONF_ERROR: HIGH_CONF_ERROR, CONFUSION_CLUSTER: CONFUSION_CLUSTER,
      COGNITIVE_GAP: COGNITIVE_GAP, STALE_RECALL: STALE_RECALL, MARKED: MARKED,
      LOW_RECENT_ACC: LOW_RECENT_ACC, INCOMPLETE_MASTERY: INCOMPLETE_MASTERY },
    mastery: { NEW: NEW, LEARNING: LEARNING, WEAK: WEAK, IMPROVING: IMPROVING, STABLE: STABLE },
    normalizeEvent: normalizeEvent,
    aggregate: aggregate,
    requiredForms: requiredForms,
    requiredFormsFor: requiredFormsFor,
    questionsByPrimary: questionsByPrimary,
    scoreKu: scoreKu,
    bandOf: bandOf,
    masteryOf: masteryOf,
    formMastery: formMastery,
    buildQueue: buildQueue,
    selectSession: selectSession,
    buildSession: buildSession,
    selectQuestion: selectQuestion,
    revisionRequest: revisionRequest,
    migrateSession: migrateSession,
    tokenSetSim: tokenSetSim
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = RevisionEngine;
