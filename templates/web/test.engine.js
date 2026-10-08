/* Deterministic competitive-exam test engine (Phase 3) — browser mirror.
 *
 * Mirrors scripts/test_engine.py exactly: same seeded RNG, same assembly,
 * same exact scoring, same analysis thresholds. The Python module is the
 * source of truth; tests/test_test_js.py checks parity on shared fixtures.
 * Inlined offline into the built page by scripts/build_web.py.
 */
"use strict";
var TestEngine = (function () {
  var TEST_ENGINE_VERSION = 1;
  var DEFAULT_SEED = 20261007;

  var SUPPORTED_TYPES = {
    factual_mcq: 1, statement_based: 1, assertion_reason: 1, match_pairs: 1,
    elimination_mcq: 1, one_liner_mcq: 1, data_interpretation_mcq: 1,
    reasoning_mcq: 1, pedagogy_mcq: 1, sequence_mcq: 1, true_false: 1
  };
  var SELECTION_MODES = { RANDOM: 1, BALANCED: 1, CUSTOM_BLUEPRINT: 1 };

  var HIGH_UNANSWERED_RATE = 0.2;
  var HCE_RATE = 0.1;
  var TIME_CONCENTRATION = 0.5;
  var TIME_PRESSURE_USED = 0.9;
  var MIN_TIME_SAMPLE = 3;

  // ---- seeded RNG: xfnv1a + mulberry32, bit-identical to Python ----
  function xfnv1a(text) {
    var h = 2166136261;
    var u = unescape(encodeURIComponent(String(text)));
    for (var i = 0; i < u.length; i++) {
      h ^= u.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }
  function RNG(seed) {
    if (typeof seed === "string") seed = xfnv1a(seed);
    this.s = (Number(seed) || 0) >>> 0;
  }
  RNG.prototype.random = function () {
    var s = (this.s + 0x6D2B79F5) | 0;
    this.s = s >>> 0;
    var t = s;
    t = Math.imul(t ^ (t >>> 15), (1 | t));
    t = (t + Math.imul(t ^ (t >>> 7), (61 | t))) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  RNG.prototype.shuffle = function (items) {
    items = items.slice();
    for (var i = items.length - 1; i > 0; i--) {
      var j = Math.floor(this.random() * (i + 1));
      var tmp = items[i]; items[i] = items[j]; items[j] = tmp;
    }
    return items;
  };

  // ---- canonical JSON for hashing (sorted keys, compact, raw UTF-8) ----
  // Integral floats normalize to ints so Python float(30) and JS 30 agree.
  function canonNorm(obj) {
    if (typeof obj === "number" && isFinite(obj) && Math.floor(obj) === obj) return obj;
    if (obj !== null && typeof obj === "object") {
      if (Array.isArray(obj)) return obj.map(canonNorm);
      var out = {};
      Object.keys(obj).forEach(function (k) { out[k] = canonNorm(obj[k]); });
      return out;
    }
    return obj;
  }
  function canonicalJson(obj) {
    obj = canonNorm(obj);
    if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
    if (Array.isArray(obj)) return "[" + obj.map(canonicalJson).join(",") + "]";
    return "{" + Object.keys(obj).sort().map(function (k) {
      return JSON.stringify(k) + ":" + canonicalJson(obj[k]);
    }).join(",") + "}";
  }

  // ---- exact rational arithmetic (mirrors Python Fraction) ----
  function gcd(a, b) {
    a = Math.abs(a); b = Math.abs(b);
    while (b) { var t = a % b; a = b; b = t; }
    return a || 1;
  }
  function fracFromDecimal(x) {
    if (typeof x === "string") {
      var s = x.trim();
      var m = s.match(/^(-?\d+)\s*\/\s*(-?\d+)$/);
      if (m) {
        var fn = parseInt(m[1], 10), fd = parseInt(m[2], 10);
        var g0 = gcd(fn, fd);
        var nn = fn / g0, dd = fd / g0;
        if (dd < 0) { nn = -nn; dd = -dd; }
        return { n: nn, d: dd };
      }
    }
    var s = String(x);
    var neg = false;
    if (s.charAt(0) === "-") { neg = true; s = s.slice(1); }
    var parts = s.split(".");
    var den = 1, num;
    if (parts.length === 1) { num = parseInt(parts[0], 10) || 0; }
    else {
      var dec = (parts[1] || "").replace(/[^0-9].*$/, "");
      den = Math.pow(10, dec.length);
      num = (parseInt(parts[0], 10) || 0) * den + (parseInt(dec, 10) || 0);
    }
    if (neg) num = -num;
    var g = gcd(num, den);
    return { n: num / g, d: den / g };
  }
  function fmul(fr, k) { var g = gcd(fr.n * k, fr.d); return { n: fr.n * k / g, d: fr.d / g }; }
  function fsub(a, b) {
    var n = a.n * b.d - b.n * a.d, d = a.d * b.d, g = gcd(n, d);
    return { n: n / g, d: d / g };
  }
  function fdivToFloat(fr) { return fr.n / fr.d; }
  function fmtFrac(fr) {
    var f = fdivToFloat(fr);
    var r = Math.round(f * 10) / 10;
    if (Math.abs(f - r) < 1e-9) {
      var s = String(r);
      return s;
    }
    return r.toFixed(1);
  }

  // ---- question accessors ----
  function qTopic(q) { return (q && (q.topic || q.knowledge_area || q.subject)) || "General"; }
  function qDiff(q) { return String((q && q.difficulty) || "medium").toLowerCase(); }
  function qType(q) { return (q && (q.type || q.question_type)) || "factual_mcq"; }
  function qPurpose(q) { return (q && q.purpose) || "unspecified"; }
  function qSection(q) {
    var src = (q && (q.source || q.source_ref)) || "";
    var refs = Array.isArray(src) ? src : [src];
    for (var i = 0; i < refs.length; i++) {
      var s = refs[i];
      if (typeof s === "string") {
        if (s) return s.split(">")[0].trim() || "General";
        continue;
      }
      if (!s || typeof s !== "object") continue;
      var sp = s.section_path;
      if (Array.isArray(sp)) {
        if (sp.length && String(sp[0]).trim()) return String(sp[0]).trim();
      } else if (typeof sp === "string" && sp.trim()) {
        return sp.split(">")[0].trim();
      }
    }
    return "General";
  }
  function qCorrectKey(q) {
    var opts = (q && (q.options || q.choices)) || [];
    for (var i = 0; i < opts.length; i++) {
      var x = opts[i];
      if (x && typeof x === "object" && x.is_correct)
        return String(x.key || "A").trim().toUpperCase();
    }
    var a = q ? (q.answer !== undefined ? q.answer : (q.key !== undefined ? q.key : q.correct)) : null;
    if (typeof a === "string" && a.trim().length === 1) return a.trim().toUpperCase();
    return null;
  }
  function scoringRuleFor(qtype) {
    if (!SUPPORTED_TYPES[qtype]) throw new Error("no defined scoring behavior for question type " + JSON.stringify(qtype));
    return "single_select_mcq";
  }

  // ---- config ----
  function defaultConfig() {
    return {
      title: "Practice Test", exam_profile: "GENERAL_PSC", question_count: 20,
      duration_minutes: 30, marks_per_correct: 1.0,
      negative_marking: { enabled: true, penalty_fraction: 0.25 },
      max_attempts: 1, topics: [], difficulty: null, qtypes: null,
      collect_confidence: true, allow_mark: true, allow_navigation: true,
      selection: "BALANCED", seed: DEFAULT_SEED, blueprint: null, exclude_ids: []
    };
  }
  function validateConfig(cfg) {
    var errors = [];
    var base = defaultConfig();
    if (!cfg || typeof cfg !== "object") return { config: base, errors: ["configuration must be an object"] };
    var out = {}, k;
    for (k in base) out[k] = base[k];
    for (k in cfg) {
      if (k in out || k === "verified_rules") out[k] = cfg[k];
      else errors.push("unknown configuration field " + JSON.stringify(k));
    }
    out.question_count = parseInt(out.question_count, 10);
    if (isNaN(out.question_count)) { errors.push("question_count must be an integer"); out.question_count = base.question_count; }
    if (!(out.question_count >= 1)) errors.push("question_count must be >= 1");
    out.duration_minutes = Number(out.duration_minutes);
    if (isNaN(out.duration_minutes)) { errors.push("duration_minutes must be a number"); out.duration_minutes = base.duration_minutes; }
    if (!(out.duration_minutes > 0)) errors.push("duration_minutes must be > 0");
    out.marks_per_correct = Number(out.marks_per_correct);
    if (isNaN(out.marks_per_correct)) { errors.push("marks_per_correct must be a number"); out.marks_per_correct = base.marks_per_correct; }
    if (!(out.marks_per_correct > 0)) errors.push("marks_per_correct must be > 0");
    var nm = out.negative_marking || {};
    if (!nm || typeof nm !== "object") { errors.push("negative_marking must be an object"); nm = {}; }
    var pen = Number(nm.penalty_fraction !== undefined ? nm.penalty_fraction : 0);
    if (isNaN(pen)) { errors.push("negative_marking.penalty_fraction must be a number"); pen = 0; }
    if (!(pen >= 0)) errors.push("negative_marking.penalty_fraction must be >= 0");
    out.negative_marking = { enabled: !!nm.enabled, penalty_fraction: pen };
    out.max_attempts = parseInt(out.max_attempts === undefined ? 1 : out.max_attempts, 10);
    if (isNaN(out.max_attempts)) { errors.push("max_attempts must be an integer"); out.max_attempts = 1; }
    if (!(out.max_attempts >= 1)) errors.push("max_attempts must be >= 1");
    if (!Array.isArray(out.topics)) { errors.push("topics must be a list"); out.topics = []; }
    ["difficulty", "qtypes"].forEach(function (name) {
      var dist = out[name];
      if (dist === null || dist === undefined) { out[name] = null; return; }
      if (typeof dist !== "object" || !Object.keys(dist).length) {
        errors.push(name + " must be an object or null"); out[name] = null; return;
      }
      var tot = 0, ok = true;
      Object.keys(dist).forEach(function (kk) {
        var v = Number(dist[kk]);
        if (isNaN(v)) ok = false; else tot += v;
      });
      if (!ok) { errors.push(name + " values must be numbers"); out[name] = null; return; }
      if (Math.abs(tot - 100) > 0.01) errors.push(name + " must sum to 100 (got " + tot.toFixed(2) + ")");
    });
    ["collect_confidence", "allow_mark", "allow_navigation"].forEach(function (f) {
      out[f] = out[f] === undefined ? true : !!out[f];
    });
    if (!SELECTION_MODES[out.selection]) {
      errors.push("selection must be one of " + Object.keys(SELECTION_MODES).join(", "));
      out.selection = "BALANCED";
    }
    if (out.blueprint !== null && out.blueprint !== undefined) {
      if (out.selection !== "CUSTOM_BLUEPRINT") errors.push("blueprint requires selection CUSTOM_BLUEPRINT");
      else if (!Array.isArray(out.blueprint) || !out.blueprint.length) errors.push("blueprint must be a non-empty list");
      else out.blueprint.forEach(function (row, i) {
        if (!row || typeof row !== "object" || !(parseInt(row.count, 10) >= 1))
          errors.push("blueprint row " + i + " needs count >= 1");
      });
    }
    if (!Array.isArray(out.exclude_ids)) { errors.push("exclude_ids must be a list"); out.exclude_ids = []; }
    if (out.seed === null || out.seed === undefined) out.seed = DEFAULT_SEED;
    return { config: out, errors: errors };
  }
  function resolveRules(profile, config) {
    profile = profile || {}; config = config || {};
    var nm = profile.negative_marking || {};
    var cfgNm = config.negative_marking || {};
    var enabled = cfgNm.enabled !== undefined ? !!cfgNm.enabled : !!nm.enabled;
    var penRaw = cfgNm.penalty_fraction !== undefined ? cfgNm.penalty_fraction
      : (nm.penalty_fraction !== undefined ? nm.penalty_fraction : 0);
    var pen = Number(penRaw);
    // exact fractions ("1/3") pass through as strings; scoring parses them
    if (isNaN(pen)) pen = (typeof penRaw === "string") ? penRaw : 0;
    var marks = Number(config.marks_per_correct !== undefined ? config.marks_per_correct : 1.0);
    if (isNaN(marks)) marks = 1.0;
    return {
      marks_per_correct: marks,
      penalty_fraction: enabled ? pen : 0,
      negative_marking: enabled,
      profile_verified: !!nm.verified,
      profile_name: profile.name || config.exam_profile || "CUSTOM"
    };
  }

  // ---- assembly ----
  function largestRemainder(total, fracs) {
    var keys = Object.keys(fracs).sort();
    var quotas = {}, rema = total, i;
    keys.forEach(function (k) { quotas[k] = Math.floor(total * fracs[k]); rema -= quotas[k]; });
    var order = keys.slice().sort(function (a, b) {
      var fa = total * fracs[a] - Math.floor(total * fracs[a]);
      var fb = total * fracs[b] - Math.floor(total * fracs[b]);
      if (fb !== fa) return fb - fa;
      return a < b ? -1 : 1;
    });
    i = 0;
    while (rema > 0 && order.length) {
      quotas[order[i % order.length]] += 1;
      rema--; i++;
    }
    return quotas;
  }
  function normDist(dist, keys) {
    var ks = keys.slice().sort();
    if (!dist) {
      var eq = {};
      ks.forEach(function (k) { eq[k] = ks.length ? 1 / ks.length : 0; });
      return eq;
    }
    var tot = 0;
    ks.forEach(function (k) { tot += Number(dist[k] || 0); });
    var out = {};
    if (!(tot > 0)) { ks.forEach(function (k) { out[k] = ks.length ? 1 / ks.length : 0; }); return out; }
    ks.forEach(function (k) { out[k] = Number(dist[k] || 0) / tot; });
    return out;
  }
  function assemble(questions, validation, config, inventory, profile) {
    var errors = [];
    var valid = {};
    if (validation && typeof validation === "object" && validation.results) {
      validation.results.forEach(function (r) { if (r && r.status === "validated") valid[r.id] = 1; });
    } else if (validation && typeof validation === "object" && !Array.isArray(validation)) {
      Object.keys(validation).forEach(function (qid) { if (validation[qid] === true) valid[qid] = 1; });
    } else {
      (validation || []).forEach(function (qid) { valid[qid] = 1; });
    }
    var pool = [];
    (questions || []).forEach(function (q) {
      if (!q || typeof q !== "object" || !q.id) return;
      if (!valid[q.id]) return;
      try { scoringRuleFor(qType(q)); } catch (e) {
        errors.push("question " + q.id + ": " + e.message); return;
      }
      pool.push(q);
    });
    if (config.topics && config.topics.length) {
      var want = {};
      config.topics.forEach(function (t) { want[t] = 1; });
      pool = pool.filter(function (q) { return !!want[qTopic(q)]; });
    }
    var excluded = {};
    (config.exclude_ids || []).forEach(function (id) { excluded[id] = 1; });
    var fresh = pool.filter(function (q) { return !excluded[q.id]; });
    var n = config.question_count;
    var reusedNote = [];
    if (fresh.length < n) {
      if (pool.length < n) {
        var msg = "insufficient validated questions: need " + n + ", have " + pool.length;
        if (config.topics && config.topics.length) msg += " for topics " + config.topics.slice().sort().join(", ");
        return { paper: null, errors: [msg] };
      }
      pool = fresh.concat(pool.filter(function (q) { return !!excluded[q.id]; }));
      pool.forEach(function (q) { if (excluded[q.id]) reusedNote.push(q.id); });
    } else {
      pool = fresh;
    }
    var rng = new RNG(config.seed === undefined ? DEFAULT_SEED : config.seed);
    var mode = config.selection || "BALANCED";
    var order;
    if (mode === "RANDOM") {
      order = rng.shuffle(pool.map(function (q) { return q.id; })).slice(0, n);
    } else if (mode === "CUSTOM_BLUEPRINT") {
      var br = assembleBlueprint(pool, config.blueprint, rng);
      if (br.errors.length) return { paper: null, errors: br.errors };
      order = br.order;
    } else {
      order = assembleBalanced(pool, n, config, rng);
    }
    if (order.length < n)
      return { paper: null, errors: ["assembler shortfall: need " + n + ", selected " + order.length] };
    order = rng.shuffle(order);
    var cfgHash = xfnv1a(canonicalJson(config)).toString(16);
    while (cfgHash.length < 8) cfgHash = "0" + cfgHash;
    var paper = {
      test_id: "T-" + (config.seed === undefined ? DEFAULT_SEED : config.seed) + "-" + cfgHash,
      test_version: 1,
      seed: (config.seed === undefined ? DEFAULT_SEED : config.seed),
      selection: mode,
      config: (function () {
        var keep = ["title", "exam_profile", "question_count", "duration_minutes",
          "marks_per_correct", "negative_marking", "max_attempts", "topics",
          "difficulty", "qtypes", "collect_confidence", "allow_mark",
          "allow_navigation", "blueprint"];
        var c = {};
        keep.forEach(function (k) { c[k] = config[k]; });
        return c;
      })(),
      rules: resolveRules(profile, config),
      question_ids: order,
      stats: paperStats(pool, order),
      reused_from_excluded: order.filter(function (id) { return !!excluded[id]; }).sort(),
      created_by: "test_engine"
    };
    return { paper: paper, errors: [] };
  }
  function paperStats(pool, order) {
    var byId = {};
    pool.forEach(function (q) { byId[q.id] = q; });
    function count(fn) {
      var c = {};
      order.forEach(function (id) { var k = fn(byId[id]); c[k] = (c[k] || 0) + 1; });
      return c;
    }
    return {
      by_topic: count(qTopic), by_difficulty: count(qDiff), by_type: count(qType),
      by_purpose: count(qPurpose), by_section: count(qSection)
    };
  }
  function assembleBalanced(pool, n, config, rng) {
    var topics = [], diffs = [], types = [];
    pool.forEach(function (q) {
      if (topics.indexOf(qTopic(q)) < 0) topics.push(qTopic(q));
      if (diffs.indexOf(qDiff(q)) < 0) diffs.push(qDiff(q));
      if (types.indexOf(qType(q)) < 0) types.push(qType(q));
    });
    topics.sort(); diffs.sort(); types.sort();
    function evenSplit(keys) {
      var o = {};
      keys.forEach(function (k) { o[k] = keys.length ? 1 / keys.length : 0; });
      return o;
    }
    var needT = largestRemainder(n, evenSplit(topics));
    var needD = largestRemainder(n, normDist(config.difficulty, diffs));
    var needY = largestRemainder(n, normDist(config.qtypes, types));
    var secOf = {};
    pool.forEach(function (q) { secOf[q.id] = qSection(q); });
    var cells = {};
    pool.forEach(function (q) {
      // NUL separator: sorts before alphanumerics, matching tuple order
      var k = qTopic(q) + "\x00" + qDiff(q) + "\x00" + qType(q);
      (cells[k] = cells[k] || []).push(q.id);
    });
    Object.keys(cells).sort().forEach(function (key) {
      var bySec = {};
      cells[key].slice().sort().forEach(function (qid) {
        var s = secOf[qid];
        (bySec[s] = bySec[s] || []).push(qid);
      });
      var secs = Object.keys(bySec).sort();
      secs.forEach(function (s) { bySec[s] = rng.shuffle(bySec[s]); });
      var order = [], kk = 0, more = true;
      while (more) {
        more = false;
        secs.forEach(function (s) {
          if (kk < bySec[s].length) { order.push(bySec[s][kk]); more = true; }
        });
        kk++;
      }
      cells[key] = order;
    });
    var cap = Math.max(1, Math.floor(n * 0.5));
    var picked = [], secCount = {}, pending = [], inPending = {};
    var pos = {};
    Object.keys(cells).forEach(function (k) { pos[k] = 0; });
    function bestCell() {
      var best = null;
      Object.keys(cells).sort().forEach(function (k) {
        if (pos[k] >= cells[k].length) return;
        var parts = k.split("\x00");
        var s = (needT[parts[0]] || 0) + (needD[parts[1]] || 0) + (needY[parts[2]] || 0);
        if (best === null || s > best[0]) best = [s, k];
      });
      return best ? best[1] : null;
    }
    var guard = 0;
    while (picked.length < n && guard < n * 4 + 10) {
      guard++;
      var bk = bestCell();
      if (bk === null) break;
      var parts = bk.split("\x00");
      var qid = null;
      while (pos[bk] < cells[bk].length) {
        var cand = cells[bk][pos[bk]++];
        if ((secCount[secOf[cand]] || 0) >= cap) {
          if (!inPending[cand]) { pending.push(cand); inPending[cand] = 1; }
          continue;
        }
        qid = cand;
        break;
      }
      if (qid === null) continue;
      picked.push(qid);
      secCount[secOf[qid]] = (secCount[secOf[qid]] || 0) + 1;
      needT[parts[0]] = (needT[parts[0]] || 0) - 1;
      needD[parts[1]] = (needD[parts[1]] || 0) - 1;
      needY[parts[2]] = (needY[parts[2]] || 0) - 1;
    }
    var used = {};
    picked.forEach(function (id) { used[id] = 1; });
    pending.forEach(function (qid) {
      if (picked.length >= n || used[qid]) return;
      if ((secCount[secOf[qid]] || 0) < cap) {
        picked.push(qid); used[qid] = 1;
        secCount[secOf[qid]] = (secCount[secOf[qid]] || 0) + 1;
      }
    });
    pending.forEach(function (qid) {
      if (picked.length >= n || used[qid]) return;
      picked.push(qid); used[qid] = 1;
    });
    if (picked.length < n) {
      pool.forEach(function (q) {
        if (picked.length >= n) return;
        if (!used[q.id]) { picked.push(q.id); used[q.id] = 1; }
      });
    }
    return picked.slice(0, n);
  }
  function assembleBlueprint(pool, blueprint, rng) {
    var byId = {};
    pool.forEach(function (q) { byId[q.id] = q; });
    var used = {}, order = [];
    for (var ri = 0; ri < blueprint.length; ri++) {
      var row = blueprint[ri] || {};
      var need = parseInt(row.count, 10) || 0;
      var cand = Object.keys(byId).filter(function (qid) {
        if (used[qid]) return false;
        var q = byId[qid];
        if (row.topic && qTopic(q) !== row.topic) return false;
        if (row.difficulty && qDiff(q) !== String(row.difficulty).toLowerCase()) return false;
        var rt = row.qtype || row.type;
        if (rt && qType(q) !== rt) return false;
        if (row.purpose && qPurpose(q) !== row.purpose) return false;
        return true;
      });
      cand = rng.shuffle(cand.sort());
      if (cand.length < need) {
        return { order: null, errors: ["blueprint row " + ri + " needs " + need + ", only " +
          cand.length + " match (topic=" + row.topic + " difficulty=" + row.difficulty +
          " type=" + (row.qtype || row.type) + " purpose=" + row.purpose + ")"] };
      }
      cand.slice(0, need).forEach(function (qid) { order.push(qid); used[qid] = 1; });
    }
    return { order: order, errors: [] };
  }

  // ---- pre-test validation ----
  function pretestCheck(questions, validation, config, profile) {
    var errors = [];
    var vr = validateConfig(config || {});
    var ok = vr.config;
    errors = errors.concat(vr.errors);
    var valid = {};
    if (validation && typeof validation === "object" && validation.results) {
      validation.results.forEach(function (r) {
        if (r && r.status === "validated") valid[r.id] = 1;
        else if (r) errors.push("bank question not validated: " + r.id);
      });
      // NOTE: keep message stable with Python ("N bank questions not validated")
      var rej = (validation.results || []).filter(function (r) { return r && r.status !== "validated"; }).length;
      if (rej) { errors = errors.filter(function (e) { return e.indexOf("bank question not validated") !== 0; });
        errors.push(rej + " bank questions not validated"); }
    } else if (validation && typeof validation === "object" && !Array.isArray(validation)) {
      Object.keys(validation).forEach(function (qid) { if (validation[qid] === true) valid[qid] = 1; });
    } else {
      (validation || []).forEach(function (qid) { valid[qid] = 1; });
    }
    var seen = {}, dups = [];
    (questions || []).forEach(function (q) {
      var qid = (q && typeof q === "object") ? q.id : null;
      if (!qid) { errors.push("bank contains a question without id"); return; }
      if (seen[qid]) dups.push(qid);
      seen[qid] = 1;
      if (valid[qid]) {
        try { scoringRuleFor(qType(q)); }
        catch (e) { errors.push("question " + qid + ": " + e.message); }
      }
    });
    if (dups.length) errors.push("duplicate question ids: " + dups.sort().join(", "));
    var n = ok.question_count;
    var pool = (questions || []).filter(function (q) {
      return q && q.id && valid[q.id] && (!ok.topics.length || ok.topics.indexOf(qTopic(q)) >= 0);
    });
    var fresh = pool.filter(function (q) { return (ok.exclude_ids || []).indexOf(q.id) < 0; });
    var usable = fresh.length >= n ? fresh : pool;
    if (usable.length < n)
      errors.push("insufficient validated questions: need " + n + ", have " + usable.length);
    var rules = resolveRules(profile, ok);
    if (!(rules.marks_per_correct > 0)) errors.push("marks_per_correct must be > 0");
    return { ok: !errors.length, errors: errors };
  }

  // ---- scoring (exact rationals; display rounds to 1 decimal) ----
  function scoreSession(paperOrRules, answers, questions) {
    var rules = (paperOrRules && paperOrRules.rules) ? paperOrRules.rules : (paperOrRules || {});
    var marks = fracFromDecimal(rules.marks_per_correct !== undefined ? rules.marks_per_correct : 1.0);
    var penalty = rules.negative_marking ? fracFromDecimal(rules.penalty_fraction !== undefined ? rules.penalty_fraction : 0) : { n: 0, d: 1 };
    var qids = (paperOrRules && paperOrRules.question_ids) ? paperOrRules.question_ids : Object.keys(questions || {});
    var correct = 0, incorrect = 0, unanswered = 0, perQ = {};
    qids.forEach(function (qid) {
      var raw = (answers || {})[qid];
      var sel = (raw && typeof raw === "object") ? (raw.sel !== undefined ? raw.sel : null) : (raw !== undefined ? raw : null);
      if (typeof sel === "string") { sel = sel.trim(); if (!sel) sel = null; }
      else if (sel !== null && sel !== undefined) sel = String(sel);
      var q = (questions || {})[qid];
      if (!q) return;
      var key = qCorrectKey(q);
      if (!sel) { unanswered++; perQ[qid] = { selected: null, correct: false, attempted: false }; }
      else if (key !== null && String(sel).trim().toUpperCase() === key) {
        correct++; perQ[qid] = { selected: sel, correct: true, attempted: true };
      } else { incorrect++; perQ[qid] = { selected: sel, correct: false, attempted: true }; }
    });
    var attempted = correct + incorrect;
    var positive = fmul(marks, correct);
    var penaltyTotal = fmul(penalty, incorrect);
    var final = fsub(positive, penaltyTotal);
    function fracOrNull(num, den) {
      if (!den) return null;
      var g = gcd(num, den);
      return { n: num / g, d: den / g };
    }
    return {
      correct: correct, incorrect: incorrect, unanswered: unanswered,
      attempted: attempted, total: qids.length,
      positive: positive, penalty_total: penaltyTotal, final: final,
      accuracy: attempted ? fracOrNull(correct, attempted) : null,
      attempt_rate: qids.length ? fracOrNull(attempted, qids.length) : null,
      per_question: perQ
    };
  }
  function fmtFrac(fr) {
    // Integer-exact half-away-from-zero to 1 decimal (mirrors Python).
    if (fr === null || fr === undefined) return "-";
    var neg = (fr.n < 0) !== (fr.d < 0);
    var m = Math.floor((20 * Math.abs(fr.n) + Math.abs(fr.d)) / (2 * Math.abs(fr.d)));
    var whole = Math.floor(m / 10), tenth = m % 10;
    var sign = neg && m !== 0 ? "-" : "";
    if (tenth === 0) return sign + String(whole);
    return sign + String(whole) + "." + String(tenth);
  }

  // ---- analysis ----
  function sliceRows(rows, keyFn, paper) {
    var rules = (paper && paper.rules) || {};
    var marks = fracFromDecimal(rules.marks_per_correct !== undefined ? rules.marks_per_correct : 1.0);
    var penalty = rules.negative_marking
      ? fracFromDecimal(rules.penalty_fraction !== undefined ? rules.penalty_fraction : 0) : { n: 0, d: 1 };
    function fnum(fr) { return fr.n / fr.d; }
    var groups = {};
    rows.forEach(function (r) {
      var k = keyFn(r);
      (groups[k] = groups[k] || []).push(r);
    });
    var out = {};
    Object.keys(groups).sort().forEach(function (k) {
      var rs = groups[k];
      var att = rs.filter(function (r) { return r.attempted; });
      var c = att.filter(function (r) { return r.correct; }).length;
      out[k] = { attempted: att.length, correct: c, incorrect: att.length - c,
                 total: rs.length, accuracy: att.length ? c / att.length : null,
                 contribution: c * fnum(marks) - (att.length - c) * fnum(penalty) };
    });
    return out;
  }
  function analyzeResults(paper, answers, questions, kus, nowMs) {
    var score = scoreSession(paper, answers, questions);
    var qmap = questions || {}, kmap = kus || {};
    var rows = [];
    (paper.question_ids || []).forEach(function (qid) {
      var q = qmap[qid];
      if (!q) return;
      var r = score.per_question[qid] || {};
      var a = (answers || {})[qid] || {};
      var prim = null, secs = [];
      ((q && q.knowledge_units) || []).forEach(function (e) {
        if (e && typeof e === "object" && e.ku_id) {
          if (e.role === "primary" && prim === null) prim = e.ku_id;
          else if (e.role === "secondary") secs.push(e.ku_id);
        }
      });
      rows.push({
        qid: qid, topic: qTopic(q), difficulty: qDiff(q), type: qType(q),
        purpose: qPurpose(q), primary_ku: prim, secondary_kus: secs,
        cluster: (q && q.confusion_cluster) || null,
        selected: (r.selected !== undefined) ? r.selected : null,
        correct: !!r.correct, attempted: !!r.attempted,
        confidence: a.conf !== undefined ? a.conf : (a.confidence !== undefined ? a.confidence : null),
        marked: !!a.marked,
        dt_ms: (a.dt_ms !== undefined) ? a.dt_ms : (a.time_taken_ms !== undefined ? a.time_taken_ms : null)
      });
    });
    var byTopic = sliceRows(rows, function (r) { return r.topic; }, paper);
    var byDiff = sliceRows(rows, function (r) { return r.difficulty; }, paper);
    var byPurpose = sliceRows(rows, function (r) { return r.purpose; }, paper);
    var kuGroups = {}, tier1 = {}, tier2 = {};
    rows.forEach(function (r) {
      if (r.correct || !r.attempted || !r.primary_ku) return;
      var g = kuGroups[r.primary_ku] || (kuGroups[r.primary_ku] = { misses: 0, question_ids: [] });
      g.misses++; g.question_ids.push(r.qid);
      var ku = kmap[r.primary_ku];
      var t = (ku && typeof ku === "object") ? parseInt(ku.tier, 10) : NaN;
      if (t === 1) tier1[r.primary_ku] = 1;
      else if (t === 2) tier2[r.primary_ku] = 1;
    });
    var kuGaps = Object.keys(kuGroups).sort(function (a, b) {
      if (kuGroups[b].misses !== kuGroups[a].misses) return kuGroups[b].misses - kuGroups[a].misses;
      return a < b ? -1 : 1;
    }).map(function (k) {
      var ku = kmap[k];
      return { ku_id: k, misses: kuGroups[k].misses, question_ids: kuGroups[k].question_ids,
               tier: (ku && typeof ku === "object") ? (ku.tier !== undefined ? ku.tier : null) : null };
    });
    var clusters = {};
    rows.forEach(function (r) {
      if (!r.correct && r.attempted && r.cluster) clusters[r.cluster] = (clusters[r.cluster] || 0) + 1;
    });
    var clusterList = Object.keys(clusters).sort(function (a, b) {
      if (clusters[b] !== clusters[a]) return clusters[b] - clusters[a];
      return a < b ? -1 : 1;
    }).map(function (k) { return { cluster: k, misses: clusters[k] }; });
    var hce = rows.filter(function (r) {
      return r.attempted && !r.correct && (r.confidence === "Certain" || r.confidence === "Fairly confident");
    }).map(function (r) { return { qid: r.qid, primary_ku: r.primary_ku, confidence: r.confidence }; });
    var unansKus = [];
    rows.forEach(function (r) {
      if (!r.attempted && r.primary_ku && unansKus.indexOf(r.primary_ku) < 0) unansKus.push(r.primary_ku);
    });
    unansKus.sort();
    var times = rows.filter(function (r) {
      return typeof r.dt_ms === "number" && r.dt_ms >= 0;
    }).map(function (r) { return [r.qid, r.dt_ms]; });
    var timeRep = { samples: times.length };
    if (times.length >= MIN_TIME_SAMPLE) {
      var vals = times.map(function (kv) { return kv[1]; }).sort(function (a, b) { return a - b; });
      var byT = {}, tc = {}, ti = {}, totT = 0;
      rows.forEach(function (r) {
        if (typeof r.dt_ms === "number" && r.dt_ms >= 0) {
          (byT[r.topic] = byT[r.topic] || []).push(r.dt_ms);
          tc[r.topic] = (tc[r.topic] || 0) + r.dt_ms;
          ti[r.topic] = (ti[r.topic] || 0) + 1;
          totT += r.dt_ms;
        }
      });
      if (!totT) totT = 1;
      var slow = times.slice().sort(function (a, b) { return b[1] - a[1]; }).slice(0, 3);
      var corrT = rows.filter(function (r) { return r.attempted && r.correct && typeof r.dt_ms === "number"; }).map(function (r) { return r.dt_ms; });
      var incorrT = rows.filter(function (r) { return r.attempted && !r.correct && typeof r.dt_ms === "number"; }).map(function (r) { return r.dt_ms; });
      function avg(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : null; }
      var byTopicMs = {}, share = {};
      Object.keys(byT).forEach(function (k) { byTopicMs[k] = avg(byT[k]); share[k] = tc[k] / totT; });
      timeRep.average_ms = avg(vals);
      timeRep.median_ms = vals[Math.floor(vals.length / 2)];
      timeRep.slowest = slow.map(function (kv) { return { qid: kv[0], dt_ms: kv[1] }; });
      timeRep.by_topic_ms = byTopicMs;
      timeRep.topic_time_share = share;
      timeRep.correct_avg_ms = avg(corrT);
      timeRep.incorrect_avg_ms = avg(incorrT);
    } else {
      timeRep.note = "insufficient timing samples";
    }
    var obs = [];
    var att = score.attempted, tot = score.total || 1;
    if (score.unanswered / tot > HIGH_UNANSWERED_RATE)
      obs.push({ code: "high_unanswered",
                 text: "Unanswered rate is " + Math.round(100 * score.unanswered / tot) + "%." });
    var unresolved = rows.filter(function (r) { return r.marked && !r.attempted; }).length;
    if (unresolved)
      obs.push({ code: "marked_unresolved",
                 text: unresolved + " marked question(s) left unanswered." });
    if (att && hce.length / att > HCE_RATE)
      obs.push({ code: "hce_rate",
                 text: "High-confidence errors on " + hce.length + " of " + att + " attempted." });
    if (times.length >= MIN_TIME_SAMPLE) {
      var shareKeys = Object.keys(timeRep.topic_time_share || {});
      for (var i = 0; i < shareKeys.length; i++) {
        var topic = shareKeys[i];
        var n = rows.filter(function (r) {
          return r.topic === topic && typeof r.dt_ms === "number";
        }).length;
        if (timeRep.topic_time_share[topic] > TIME_CONCENTRATION && n >= MIN_TIME_SAMPLE) {
          obs.push({ code: "time_concentration",
                     text: topic + " took " + Math.floor(100 * timeRep.topic_time_share[topic] + 0.5) + "% of total time." });
          break;
        }
      }
    }
    function fracOut(fr) { return fr === null ? null : { n: fr.n, d: fr.d }; }
    function fracOut(fr) { return fr === null ? null : { n: fr.n, d: fr.d }; }
    function pctOf(fr) {
      if (fr === null) return null;
      return fmtFrac({ n: 100 * fr.n, d: fr.d });
    }
    return {
      score: {
        correct: score.correct, incorrect: score.incorrect, unanswered: score.unanswered,
        attempted: score.attempted, total: score.total,
        positive: score.positive, penalty_total: score.penalty_total, final: score.final,
        accuracy: fracOut(score.accuracy), attempt_rate: fracOut(score.attempt_rate),
        display: {
          final: fmtFrac(score.final),
          accuracy_pct: pctOf(score.accuracy),
          attempt_pct: pctOf(score.attempt_rate)
        }
      },
      per_question: score.per_question,
      by_topic: byTopic, by_difficulty: byDiff, by_purpose: byPurpose,
      ku_gaps: kuGaps,
      tier1_misses: Object.keys(tier1).sort(), tier2_misses: Object.keys(tier2).sort(),
      confusion_clusters: clusterList, high_confidence_errors: hce,
      unanswered_kus: unansKus, time: timeRep, observations: obs
    };
  }

  // ---- sessions ----
  function newTestSession(paper, config, nowMs) {
    var dur = Number((paper.config || {}).duration_minutes !== undefined
      ? paper.config.duration_minutes
      : (config || {}).duration_minutes !== undefined ? config.duration_minutes : 30);
    return {
      test_id: paper.test_id, test_version: paper.test_version || 1,
      profile: (paper.config || {}).exam_profile || "CUSTOM",
      config: paper.config || {}, rules: paper.rules || {},
      question_ids: (paper.question_ids || []).slice(),
      start_time: Math.floor(nowMs),
      expires_at: Math.floor(nowMs + dur * 60000),
      answers: {}, marked: [], submitted: false,
      submission_time: null, submit_reason: null, result: null
    };
  }
  function remainingMs(session, nowMs) {
    var exp = Number(session ? session.expires_at : 0);
    var now = Number(nowMs);
    if (isNaN(exp) || isNaN(now)) return 0;
    return Math.max(0, exp - now);
  }
  function isExpired(session, nowMs) {
    var exp = Number(session ? session.expires_at : NaN);
    var now = Number(nowMs);
    if (isNaN(exp) || isNaN(now)) return true;
    return now >= exp;
  }
  function finalizeSession(session, questions, nowMs, reason) {
    if (session.submitted) return session.result;
    var qmap = {};
    (questions || []).forEach(function (q) { if (q && q.id) qmap[q.id] = q; });
    var paper = { question_ids: (session.question_ids || []).slice(), rules: session.rules || {} };
    var analysis = analyzeResults(paper, session.answers || {}, qmap);
    var result = {
      test_id: session.test_id, test_version: session.test_version || 1,
      submit_reason: reason || "submitted", submission_time: Math.floor(nowMs),
      score: analysis.score,
      time_used_ms: Math.max(0, Math.floor(nowMs) - Math.floor(session.start_time || nowMs)),
      duration_minutes: (session.config || {}).duration_minutes,
      analysis: (function () {
        var a = {}, k;
        for (k in analysis) if (k !== "score") a[k] = analysis[k];
        return a;
      })(),
      answers: JSON.parse(JSON.stringify(session.answers || {})),
      marked: (session.marked || []).slice(),
      config: JSON.parse(JSON.stringify(session.config || {})),
      rules: JSON.parse(JSON.stringify(session.rules || {})),
      question_ids: (session.question_ids || []).slice()
    };
    session.submitted = true;
    session.submission_time = Math.floor(nowMs);
    session.submit_reason = reason || "submitted";
    session.result = result;
    return result;
  }
  function retakeSeed(seed) {
    if (typeof seed === "boolean") return String(seed) + "-r2";
    if (typeof seed === "number" && isFinite(seed)) return Math.floor(seed) + 1;
    if (typeof seed === "string" && /^-?\d+$/.test(seed.trim())) {
      var n = parseInt(seed.trim(), 10);
      if (!isNaN(n)) return n + 1;
    }
    return String(seed) + "-r2";
  }

  return {
    TEST_ENGINE_VERSION: TEST_ENGINE_VERSION,
    DEFAULT_SEED: DEFAULT_SEED,
    SUPPORTED_TYPES: SUPPORTED_TYPES,
    SELECTION_MODES: SELECTION_MODES,
    xfnv1a: xfnv1a, RNG: RNG,
    qTopic: qTopic, qDiff: qDiff, qType: qType, qPurpose: qPurpose,
    qSection: qSection, qCorrectKey: qCorrectKey, scoringRuleFor: scoringRuleFor,
    defaultConfig: defaultConfig, validateConfig: validateConfig, resolveRules: resolveRules,
    assemble: assemble, pretestCheck: pretestCheck,
    scoreSession: scoreSession, fmtFrac: fmtFrac,
    analyzeResults: analyzeResults,
    newTestSession: newTestSession, remainingMs: remainingMs, isExpired: isExpired,
    finalizeSession: finalizeSession, retakeSeed: retakeSeed,
    fracFromDecimal: fracFromDecimal
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = TestEngine;
