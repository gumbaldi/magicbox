// The batch page's cost views: the Cost tab (where the output went, planning and implementation
// side by side, implementation per phase against its size baseline, agents grouped by part, and an
// "Exact numbers" table with a TSV export) and the per-phase Cost sub-tab. Cost is
// turns and tokens only, split by model at every level -- no price table, no currency: the exact
// numbers table is precise enough to multiply with a price list by hand later.
//
// The row builders (`costRows`, `layerRows`, `phaseCostRows`, `implPhaseRows`, `outputParts`,
// `exactRows`, `toTsv`) are pure so
// tests/js/batch-cost.test.mjs can exercise them directly. `COST` shape: `.batch-context.md`
// (Portal data files). Every value reaches the DOM through `textContent`.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var FIELDS = ["turns", "input", "output", "cache_read", "cache_creation"];
  var LAYERS = [
    ["main", "Session"],
    ["main_explore", "Session explorers"],
    ["worker", "Workers"],
    ["worker_explore", "Worker explorers"],
  ];
  var LAYER_NAME = {};
  LAYERS.forEach(function (l) { LAYER_NAME[l[0]] = l[1]; });
  var EXACT_COLUMNS = ["scope", "layer", "model", "turns", "input", "output", "cache_read", "cache_creation"];

  function core() { return CFQ.core; }
  function isNum(n) { return typeof n === "number" && isFinite(n); }

  function t5(src) {
    var out = {};
    FIELDS.forEach(function (k) { out[k] = (src && isNum(src[k])) ? src[k] : 0; });
    return out;
  }

  function add(a, b) { return core().addT5(a, b); }

  function modelNames(byModel) { return Object.keys(byModel || {}).sort(); }

  // ---- pure row builders ------------------------------------------------------------------------

  // One row per model (largest output first), then a last row `{total: true}` equal to `cost.total`.
  function costRows(cost) {
    var by = (cost && cost.byModel) || {};
    var rows = modelNames(by).map(function (m) { return Object.assign({ model: m }, t5(by[m])); });
    rows.sort(function (a, b) { return b.output - a.output || (a.model < b.model ? -1 : a.model > b.model ? 1 : 0); });
    rows.push(Object.assign({ model: "Total", total: true }, t5(cost && cost.total)));
    return rows;
  }

  // The four layers in fixed order. A layer without turns stays in the list (`empty`), its numbers
  // all zero; `models` holds the per-model rows of the expandable part.
  function layerRows(cost) {
    var layers = (cost && cost.layers) || {};
    return LAYERS.map(function (pair) {
      var key = pair[0], layer = layers[key] || {};
      var total = t5(layer.total);
      var by = layer.byModel || {};
      return Object.assign({
        layer: key,
        label: pair[1],
        count: isNum(layer.count) ? layer.count : 0,
        empty: !total.turns,
        models: modelNames(by).map(function (m) { return Object.assign({ model: m }, t5(by[m])); }),
      }, total);
    });
  }

  function sumCosts(costs) {
    var total = t5(null), byModel = {}, any = false, provisional = false;
    costs.forEach(function (c) {
      if (!c || !c.cost) return;
      any = true;
      if (c.settled === false) provisional = true;
      total = add(total, c.cost.total);
      Object.keys(c.cost.byModel || {}).forEach(function (m) { byModel[m] = add(byModel[m], c.cost.byModel[m]); });
    });
    return any ? { total: total, byModel: byModel, provisional: provisional } : null;
  }

  // Planning (when it recorded telemetry) and one row per phase with at least one attempt that did,
  // each summed over the phase's attempts: `{label, slug, total, byModel, provisional}`.
  function phaseCostRows(batch) {
    var rows = [];
    var planning = batch && batch.planning;
    if (planning && planning.cost) {
      var p = sumCosts([planning]);
      rows.push({ label: "Planning", slug: null, total: p.total, byModel: p.byModel, provisional: p.provisional });
    }
    ((batch && batch.phases) || []).forEach(function (phase) {
      var s = sumCosts(phase.attempts || []);
      if (s) rows.push({ label: phase.slug, slug: phase.slug, total: s.total, byModel: s.byModel, provisional: s.provisional });
    });
    return rows;
  }

  // True when the batch has attempts and every one ran as a classic session (no orchestrator).
  function isClassic(batch) {
    var attempts = [];
    ((batch && batch.phases) || []).forEach(function (p) { (p.attempts || []).forEach(function (a) { attempts.push(a); }); });
    return attempts.length > 0 && attempts.every(function (a) { return a.mode === "classic"; });
  }

  // Output of the batch by part, in display order: planning session, planning explorers, the
  // orchestrator (the session when every attempt ran classic), its explorers, phase workers, worker
  // explorers. `kind` is "plan" or "impl", `tone` the tint (p1/p2 planning, i1..i3 implementation).
  // Parts without output are left out.
  function outputParts(batch) {
    var planning = batch && batch.planning && batch.planning.cost;
    var impl = batch && batch.implementation && batch.implementation.cost;
    var classic = isClassic(batch);
    var defs = [
      [planning, "main", "Planning session", "plan", "p1"],
      [planning, "main_explore", "Planning explorers", "plan", "p2"],
      [impl, "main", classic ? "Session" : "Orchestrator", "impl", "i1"],
      [impl, "main_explore", classic ? "Session explorers" : "Orchestrator explorers", "impl", "i4"],
      [impl, "worker", "Phase workers", "impl", "i2"],
      [impl, "worker_explore", "Worker explorers", "impl", "i3"],
    ];
    var parts = [];
    defs.forEach(function (d) {
      var layer = d[0] && d[0].layers && d[0].layers[d[1]];
      var total = t5(layer && layer.total);
      if (total.output > 0) parts.push({ layer: d[1], label: d[2], kind: d[3], tone: d[4], value: total.output, turns: total.turns });
    });
    return parts;
  }

  // One row per phase with telemetry, summed over its attempts. `ratio` is the phase's output over
  // its size baseline's median output (`null` without a baseline); `active` is the sum of the
  // attempts' active seconds only when every timed attempt recorded one.
  function implPhaseRows(batch) {
    var rows = [];
    ((batch && batch.phases) || []).forEach(function (phase) {
      var s = sumCosts(phase.attempts || []);
      if (!s) return;
      var wall = null, active = null, activeAll = true;
      (phase.attempts || []).forEach(function (a) {
        var w = a.time && a.time.wallclock_s;
        if (isNum(w)) wall = (wall || 0) + w;
        var act = a.time && a.time.active_s;
        if (isNum(act)) active = (active || 0) + act;
        else if (isNum(w)) activeAll = false;
      });
      var base = phase.baseline;
      var ratio = base && isNum(base.outputMedian) && base.outputMedian > 0 && s.total.output > 0
        ? s.total.output / base.outputMedian : null;
      var byModel = {};
      Object.keys(s.byModel).forEach(function (m) { byModel[m] = s.byModel[m].output; });
      rows.push({
        slug: phase.slug, num: phase.num, title: phase.title || phase.slug, size: phase.size || "",
        total: s.total, byModel: byModel, provisional: s.provisional,
        active: activeAll ? active : null, wallclock: wall, ratio: ratio,
      });
    });
    return rows;
  }

  // Agents in display order: every root (no parent in the list) followed by the agents it spawned.
  function orderAgents(agents) {
    var ids = {};
    agents.forEach(function (a) { ids[a.id] = true; });
    var out = [];
    function walk(a) {
      out.push(a);
      agents.forEach(function (b) { if (b !== a && b.parent === a.id) walk(b); });
    }
    agents.forEach(function (a) { if (!a.parent || !ids[a.parent]) walk(a); });
    return out;
  }

  // One row per (scope, layer, model); scope is "planning" or a phase slug (all attempts summed),
  // numbers unrounded. Only combinations that actually have a model row are listed.
  function exactRows(batch) {
    var rows = [];
    function collect(scope, costs) {
      LAYERS.forEach(function (pair) {
        var acc = {};
        costs.forEach(function (cost) {
          var layer = cost && cost.layers && cost.layers[pair[0]];
          Object.keys((layer && layer.byModel) || {}).forEach(function (m) { acc[m] = add(acc[m], layer.byModel[m]); });
        });
        modelNames(acc).forEach(function (m) {
          rows.push(Object.assign({ scope: scope, layer: pair[0], model: m }, t5(acc[m])));
        });
      });
    }
    if (batch && batch.planning && batch.planning.cost) collect("planning", [batch.planning.cost]);
    ((batch && batch.phases) || []).forEach(function (phase) {
      var costs = (phase.attempts || []).map(function (a) { return a.cost; }).filter(Boolean);
      if (costs.length) collect(phase.slug, costs);
    });
    return rows;
  }

  function cell(v) { return String(v === undefined || v === null ? "" : v).replace(/[\t\r\n]+/g, " "); }

  // Header line plus one tab-separated line per row; numbers are plain digits.
  function toTsv(rows) {
    var lines = [EXACT_COLUMNS.join("\t")];
    (rows || []).forEach(function (r) {
      lines.push(EXACT_COLUMNS.map(function (k) { return cell(r[k]); }).join("\t"));
    });
    return lines.join("\n");
  }

  // ---- DOM pieces -------------------------------------------------------------------------------

  var NUM_TITLE = { in: "input + cache creation (billable input)" };

  function numTd(doc, v, bar, max) {
    var C = core();
    if (bar) {
      var td = C.el(doc, "td", null, "n");
      td.appendChild(C.tokenBar(doc, v, max));
      return td;
    }
    var c = C.el(doc, "td", C.fmtInt(v), "n");
    c.setAttribute("title", String(v));
    return c;
  }

  function dashTd(doc) {
    var c = core().el(doc, "td", "–", "n faint");
    c.setAttribute("title", "no turns recorded");
    return c;
  }

  function headRow(doc, cols) {
    var C = core();
    var thead = C.el(doc, "thead"), tr = C.el(doc, "tr");
    cols.forEach(function (c) {
      var th = C.el(doc, "th", c[0], c[1] || "");
      th.setAttribute("scope", "col");
      if (c[2]) th.setAttribute("title", c[2]);
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    return thead;
  }

  function scroll(doc, table) {
    var wrap = core().el(doc, "div", null, "tscroll");
    wrap.appendChild(table);
    return wrap;
  }

  function section(doc, title) {
    var s = core().el(doc, "section", null, "cost-section");
    s.appendChild(core().el(doc, "h3", title));
    return s;
  }

  function swatchLabel(doc, model, slots) {
    var C = core();
    var span = C.el(doc, "span", null, "model-name");
    if (slots && slots[model]) {
      var sw = C.el(doc, "span", null, "swatch " + slots[model]);
      sw.setAttribute("aria-hidden", "true");
      span.appendChild(sw);
    }
    span.appendChild(C.el(doc, "span", model));
    return span;
  }

  var MODEL_COLS = [["Model", ""], ["Turns", "n"], ["In", "n", NUM_TITLE.in], ["Out", "n"], ["Cache read", "n"]];

  // `plain`: the output as a number, never a bar.
  function modelCells(doc, tr, r, maxOut, plain) {
    var C = core();
    tr.appendChild(numTd(doc, r.turns));
    var inTd = C.el(doc, "td", C.fmtInt(C.billableIn(r)), "n");
    inTd.setAttribute("title", String(C.billableIn(r)));
    tr.appendChild(inTd);
    tr.appendChild(numTd(doc, r.output, !plain && !r.total, maxOut)); // a bar for the total row would dwarf its parts
    tr.appendChild(numTd(doc, r.cache_read));
  }

  function modelTable(doc, rows, slots) {
    var C = core();
    var table = C.el(doc, "table", null, "data cost-table by-model");
    table.appendChild(headRow(doc, MODEL_COLS));
    var body = C.el(doc, "tbody");
    var maxOut = rows.reduce(function (m, r) { return r.total ? m : Math.max(m, r.output); }, 0);
    rows.forEach(function (r) {
      var tr = C.el(doc, "tr", null, r.total ? "total" : "");
      var first = C.el(doc, "td", null, "model");
      if (r.total) first.textContent = r.model; else first.appendChild(swatchLabel(doc, r.model, slots));
      tr.appendChild(first);
      modelCells(doc, tr, r, maxOut);
      body.appendChild(tr);
    });
    table.appendChild(body);
    return scroll(doc, table);
  }

  // Layer rows with a real expand button; the per-model rows below a layer toggle together.
  function layerTable(doc, rows, slots) {
    var C = core();
    var table = C.el(doc, "table", null, "data cost-table by-layer");
    table.appendChild(headRow(doc, [["Layer", ""], ["Agents", "n"], ["Turns", "n"], ["In", "n", NUM_TITLE.in], ["Out", "n"], ["Cache read", "n"]]));
    var body = C.el(doc, "tbody");
    var maxOut = rows.reduce(function (m, r) { return Math.max(m, r.output); }, 0);
    rows.forEach(function (r) {
      var tr = C.el(doc, "tr", null, "layer-row" + (r.empty ? " empty-layer" : ""));
      var first = C.el(doc, "td", null, "layer");
      var children = [];
      if (r.empty || !r.models.length) {
        first.appendChild(C.el(doc, "span", r.label));
      } else {
        var toggle = C.el(doc, "button", null, "disclosure-toggle");
        toggle.setAttribute("type", "button");
        toggle.setAttribute("aria-expanded", "false");
        toggle.appendChild(C.el(doc, "span", "▸", "caret"));
        toggle.appendChild(C.el(doc, "span", r.label));
        toggle.addEventListener("click", function () {
          var open = toggle.getAttribute("aria-expanded") !== "true";
          toggle.setAttribute("aria-expanded", open ? "true" : "false");
          children.forEach(function (c) { if (open) c.removeAttribute("hidden"); else c.setAttribute("hidden", ""); });
        });
        first.appendChild(toggle);
      }
      tr.appendChild(first);
      tr.appendChild(r.empty ? dashTd(doc) : numTd(doc, r.count));
      if (r.empty) {
        for (var i = 0; i < 4; i++) tr.appendChild(dashTd(doc));
      } else {
        modelCells(doc, tr, r, maxOut);
      }
      body.appendChild(tr);
      if (!r.empty) {
        r.models.forEach(function (m) {
          var sub = C.el(doc, "tr", null, "nested");
          sub.setAttribute("hidden", "");
          var label = C.el(doc, "td", null, "model");
          label.appendChild(swatchLabel(doc, m.model, slots));
          sub.appendChild(label);
          sub.appendChild(C.el(doc, "td", "", "n"));
          modelCells(doc, sub, m, maxOut);
          children.push(sub);
          body.appendChild(sub);
        });
      }
    });
    table.appendChild(body);
    return scroll(doc, table);
  }

  function agentRow(doc, a, withPhase, phase) {
    var C = core();
    var tr = C.el(doc, "tr");
    if (withPhase) tr.appendChild(C.el(doc, "td", phase || "–", "num"));
    tr.appendChild(C.el(doc, "td", a.type || "–", "mono"));
    tr.appendChild(C.el(doc, "td", a.description || "–", "desc"));
    tr.appendChild(C.el(doc, "td", LAYER_NAME[a.layer] || a.layer || "–"));
    tr.appendChild(C.el(doc, "td", modelNames(a.byModel).join(", ") || "–"));
    var t = t5(a.total);
    tr.appendChild(numTd(doc, t.turns));
    var inTd = C.el(doc, "td", C.fmtInt(C.billableIn(t)), "n");
    inTd.setAttribute("title", String(C.billableIn(t)));
    tr.appendChild(inTd);
    tr.appendChild(numTd(doc, t.output));
    return tr;
  }

  // A flat list of agents, or, with `groups` ([{label, rows: [{agent, phase}]}]), a table with one
  // group row per part and a Phase column.
  function agentsTable(doc, agents, groups) {
    var C = core();
    var table = C.el(doc, "table", null, "data cost-table agents");
    var cols = [["Type", ""], ["Description", ""], ["Layer", ""], ["Models", ""], ["Turns", "n"], ["In", "n", NUM_TITLE.in], ["Out", "n"]];
    if (groups) cols.unshift(["Phase", ""]);
    table.appendChild(headRow(doc, cols));
    var body = C.el(doc, "tbody");
    if (groups) {
      groups.forEach(function (g) {
        var gr = C.el(doc, "tr", null, "group-row group-" + g.kind);
        var th = C.el(doc, "th", g.label);
        th.setAttribute("colspan", String(cols.length));
        th.setAttribute("scope", "colgroup");
        gr.appendChild(th);
        body.appendChild(gr);
        g.rows.forEach(function (r) { body.appendChild(agentRow(doc, r.agent, true, r.phase)); });
      });
    } else {
      agents.forEach(function (a) { body.appendChild(agentRow(doc, a, false)); });
    }
    table.appendChild(body);
    return scroll(doc, table);
  }

  function provisionalMark(doc) {
    var m = core().el(doc, "span", "provisional", "provisional");
    m.setAttribute("title", "Recomputed once the session has ended");
    return m;
  }

  function provisionalNote(doc) {
    return core().el(doc, "p", "Some figures are provisional: their session had not ended when they were recorded, and they are recomputed once it has.", "provisional-note muted");
  }

  // ---- Where the output went, the two part tables, the phase table ------------------------------

  function shortModel(name, slot) {
    return !slot || slot === "m-other" ? name : slot.replace(/^m-/, "");
  }

  // One family dot and short name per distinct family; several dots when the models are mixed.
  function modelCell(doc, models, slots) {
    var C = core();
    var td = C.el(doc, "td", null, "model");
    var seen = {};
    models.forEach(function (m) {
      var label = shortModel(m, slots[m]);
      if (seen[label]) return;
      seen[label] = true;
      var span = C.el(doc, "span", null, "model-name");
      var dot = C.el(doc, "span", null, "mdot " + (slots[m] || "m-other"));
      dot.setAttribute("aria-hidden", "true");
      span.appendChild(dot);
      span.appendChild(C.el(doc, "span", label));
      td.appendChild(span);
    });
    return td;
  }

  function heading(doc, title, aside, kind) {
    var C = core();
    var head = C.el(doc, "div", null, "sec-head");
    if (kind) head.appendChild(C.el(doc, "span", null, "swatch sw-" + kind));
    head.appendChild(C.el(doc, "h3", title));
    if (aside) {
      var a = C.el(doc, "span", aside.text, "aside");
      if (aside.title) a.setAttribute("title", aside.title);
      head.appendChild(a);
    }
    return head;
  }

  function outputSection(doc, parts) {
    var C = core();
    var sec = C.el(doc, "section", null, "cost-section out-section");
    var total = parts.reduce(function (n, p) { return n + p.value; }, 0);
    var turns = parts.reduce(function (n, p) { return n + p.turns; }, 0);
    sec.appendChild(heading(doc, "Where the output went", {
      text: C.fmtTokens(total) + " output tokens · " + C.fmtInt(turns) + " turns", title: C.fmtInt(total) + " output tokens",
    }));
    if (!total) {
      sec.appendChild(C.el(doc, "p", "No output recorded.", "empty"));
      return sec;
    }
    var bar = C.el(doc, "div", null, "out-bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", "Output by part");
    var legend = C.el(doc, "div", null, "out-legend");
    parts.forEach(function (p) {
      var seg = C.el(doc, "i", null, "out-seg " + p.tone);
      seg.style.width = (Math.round(p.value / total * 1000) / 10) + "%";
      seg.setAttribute("title", p.label + ": " + C.fmtInt(p.value));
      bar.appendChild(seg);
      var item = C.el(doc, "div", null, "out-legend-item");
      item.appendChild(C.el(doc, "span", null, "swatch " + p.tone));
      item.appendChild(C.el(doc, "span", p.label, "label"));
      var v = C.el(doc, "span", C.fmtTokens(p.value), "v");
      v.setAttribute("title", String(p.value));
      item.appendChild(v);
      legend.appendChild(item);
    });
    sec.appendChild(bar);
    sec.appendChild(legend);
    return sec;
  }

  // One table of a part: a row per non-empty layer (expandable into its models) and a total row.
  function partTable(doc, cost, labels, slots) {
    var C = core();
    var table = C.el(doc, "table", null, "data cost-table part-table");
    table.appendChild(headRow(doc, [["Part", ""], ["Model", ""], ["Turns", "n"], ["In new", "n", NUM_TITLE.in], ["Out", "n"], ["Cache read", "n"]]));
    var body = C.el(doc, "tbody");
    layerRows(cost).filter(function (r) { return !r.empty; }).forEach(function (r) {
      var label = (labels[r.layer] || r.label) + (r.layer !== "main" && r.count > 1 ? " ×" + r.count : "");
      var tr = C.el(doc, "tr", null, "layer-row");
      var first = C.el(doc, "td", null, "layer");
      var children = [];
      if (r.models.length) {
        var toggle = C.el(doc, "button", null, "disclosure-toggle");
        toggle.setAttribute("type", "button");
        toggle.setAttribute("aria-expanded", "false");
        toggle.appendChild(C.el(doc, "span", "▸", "caret"));
        toggle.appendChild(C.el(doc, "span", label));
        toggle.addEventListener("click", function () {
          var open = toggle.getAttribute("aria-expanded") !== "true";
          toggle.setAttribute("aria-expanded", open ? "true" : "false");
          children.forEach(function (c) { if (open) c.removeAttribute("hidden"); else c.setAttribute("hidden", ""); });
        });
        first.appendChild(toggle);
      } else {
        first.appendChild(C.el(doc, "span", label));
      }
      tr.appendChild(first);
      tr.appendChild(modelCell(doc, r.models.map(function (m) { return m.model; }), slots));
      modelCells(doc, tr, r, 0, true);
      body.appendChild(tr);
      r.models.forEach(function (m) {
        var sub = C.el(doc, "tr", null, "nested");
        sub.setAttribute("hidden", "");
        var name = C.el(doc, "td", null, "model");
        name.appendChild(swatchLabel(doc, m.model, slots));
        sub.appendChild(name);
        sub.appendChild(C.el(doc, "td", ""));
        modelCells(doc, sub, m, 0, true);
        children.push(sub);
        body.appendChild(sub);
      });
    });
    var total = t5(cost && cost.total);
    var tr = C.el(doc, "tr", null, "total");
    tr.appendChild(C.el(doc, "td", "Total"));
    tr.appendChild(C.el(doc, "td", ""));
    modelCells(doc, tr, total, 0, true);
    body.appendChild(tr);
    table.appendChild(body);
    return scroll(doc, table);
  }

  function partSection(doc, kind, title, part, labels, slots) {
    var C = core();
    var sec = C.el(doc, "section", null, "cost-section part-" + kind);
    var a = part ? C.fmtActive(part.active_s, part.wallclock_s) : null;
    sec.appendChild(heading(doc, title, a && { text: a.text + (a.title ? " active · " + a.title + " calendar" : ""), title: "" }, kind));
    if (!part || !part.cost) {
      sec.appendChild(C.el(doc, "p", kind === "plan" ? "No planning telemetry recorded." : "No implementation telemetry yet.", "empty"));
      return sec;
    }
    sec.appendChild(partTable(doc, part.cost, labels, slots));
    return sec;
  }

  function ratioCell(doc, ratio) {
    var C = core();
    var td = C.el(doc, "td", null, "n ratio");
    if (ratio === null) {
      td.textContent = "–";
      td.setAttribute("title", "no size baseline");
      return td;
    }
    var text = (Math.round(ratio * 10) / 10).toFixed(1) + "×";
    td.appendChild(ratio > 2 ? C.el(doc, "span", text, "pill neutral") : C.el(doc, "span", text));
    td.setAttribute("title", "output compared with the median of finished phases of this size");
    return td;
  }

  function implPhaseSection(doc, ctx, batch, slots) {
    var C = core();
    var rows = implPhaseRows(batch);
    var sec = C.el(doc, "section", null, "cost-section");
    sec.appendChild(heading(doc, "Implementation by phase", { text: "all attempts, output stacked by model" }));
    if (!rows.length) {
      sec.appendChild(C.el(doc, "p", "No phase recorded telemetry.", "empty"));
      return sec;
    }
    var maxOut = rows.reduce(function (m, r) { return Math.max(m, r.total.output); }, 0);
    var table = C.el(doc, "table", null, "data cost-table by-phase");
    table.appendChild(headRow(doc, [["#", ""], ["Phase", ""], ["Size", ""], ["Active", "n"], ["Turns", "n"], ["Out", "n"],
      ["Output by model", ""], ["vs. baseline", "n"], ["", ""]]));
    var body = C.el(doc, "tbody");
    rows.forEach(function (r) {
      var tr = C.el(doc, "tr");
      tr.appendChild(C.el(doc, "td", String(r.num === undefined || r.num === null ? "" : r.num), "num"));
      var label = C.el(doc, "td", null, "phase");
      var a = C.el(doc, "a", r.title);
      a.setAttribute("href", C.href(ctx, "batch/" + batch.name + "/phase/" + r.slug));
      a.setAttribute("title", r.slug);
      label.appendChild(a);
      tr.appendChild(label);
      tr.appendChild(C.el(doc, "td", r.size || "–"));
      var act = C.fmtActive(r.active, r.wallclock);
      var actTd = C.el(doc, "td", act.text, "n");
      if (act.title) actTd.setAttribute("title", "calendar " + act.title);
      tr.appendChild(actTd);
      tr.appendChild(numTd(doc, r.total.turns));
      tr.appendChild(numTd(doc, r.total.output));
      var barTd = C.el(doc, "td");
      var track = C.el(doc, "span", null, "stackbar");
      Object.keys(r.byModel).sort(function (x, y) { return r.byModel[y] - r.byModel[x] || (x < y ? -1 : 1); }).forEach(function (m) {
        if (!(r.byModel[m] > 0) || !(maxOut > 0)) return;
        var seg = C.el(doc, "i", null, slots[m] || "m-other");
        seg.style.width = (Math.round(r.byModel[m] / maxOut * 1000) / 10) + "%";
        seg.setAttribute("title", m + ": " + C.fmtInt(r.byModel[m]));
        track.appendChild(seg);
      });
      barTd.appendChild(track);
      tr.appendChild(barTd);
      tr.appendChild(ratioCell(doc, r.ratio));
      var mark = C.el(doc, "td");
      if (r.provisional) mark.appendChild(provisionalMark(doc));
      tr.appendChild(mark);
      body.appendChild(tr);
    });
    table.appendChild(body);
    sec.appendChild(scroll(doc, table));
    return sec;
  }

  // Agents of the batch under a Planning and an Implementation group row; the implementation
  // agents are ordered by phase, each worker followed by the explorers it spawned.
  function agentGroups(batch) {
    var planning = batch.planning && batch.planning.cost;
    var groups = [];
    var planRows = orderAgents((planning && planning.agents) || []).map(function (a) { return { agent: a, phase: "" }; });
    if (planRows.length) groups.push({ kind: "plan", label: "Planning", rows: planRows });
    var implRows = [];
    (batch.phases || []).forEach(function (phase) {
      (phase.attempts || []).forEach(function (att) {
        orderAgents((att.cost && att.cost.agents) || []).forEach(function (a) {
          implRows.push({ agent: a, phase: phase.num === undefined || phase.num === null ? phase.slug : String(phase.num) });
        });
      });
    });
    if (!implRows.length) {
      var ic = batch.implementation && batch.implementation.cost;
      orderAgents((ic && ic.agents) || []).forEach(function (a) { implRows.push({ agent: a, phase: "" }); });
    }
    if (implRows.length) groups.push({ kind: "impl", label: "Implementation", rows: implRows });
    return groups;
  }

  // "Copy as TSV": the clipboard API when there is one; in a browser without it a read-only textarea
  // is revealed and selected; under Node the button renders and does nothing.
  function copyButton(doc, tsv) {
    var C = core();
    var wrap = C.el(doc, "div", null, "copy-tsv");
    var button = C.el(doc, "button", "Copy as TSV", "chip");
    button.setAttribute("type", "button");
    var area = C.el(doc, "textarea", null, "tsv-area");
    area.setAttribute("readonly", "");
    area.setAttribute("hidden", "");
    area.setAttribute("aria-label", "Exact numbers as tab-separated text");
    area.value = tsv;
    area.textContent = tsv;
    function reveal() {
      area.removeAttribute("hidden");
      if (typeof area.focus === "function") area.focus();
      if (typeof area.select === "function") area.select();
    }
    button.addEventListener("click", function () {
      var nav = typeof navigator !== "undefined" ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
        nav.clipboard.writeText(tsv).then(function () {
          button.textContent = "Copied";
        }, reveal);
      } else if (typeof window !== "undefined") {
        reveal();
      }
    });
    wrap.appendChild(button);
    wrap.appendChild(area);
    return wrap;
  }

  function exactSection(doc, batch) {
    var C = core();
    return C.disclosure(doc, "Exact numbers", function (d, body) {
      var rows = exactRows(batch);
      body.appendChild(C.el(d, "p", "Unrounded, per scope, layer and model; input and cache creation are separate columns.", "caption muted"));
      body.appendChild(copyButton(d, toTsv(rows)));
      var table = CFQ.charts.numbersTable(d, EXACT_COLUMNS.map(function (k, i) {
        return { key: k, label: k, num: i >= 3 };
      }), rows);
      table.className = "data numbers exact";
      body.appendChild(scroll(d, table));
    });
  }

  // ---- tabs -------------------------------------------------------------------------------------

  var PLAN_LABELS = {
    main: "Planning session", main_explore: "Planning explorers",
    worker: "Planning workers", worker_explore: "Planning worker explorers",
  };

  function implLabels(batch) {
    var classic = isClassic(batch);
    return {
      main: classic ? "Session" : "Orchestrator", main_explore: classic ? "Session explorers" : "Orchestrator explorers",
      worker: "Phase workers", worker_explore: "Worker explorers",
    };
  }

  function renderCostTab(doc, root, ctx) {
    var C = core(), K = CFQ.charts;
    var batch = ctx.batch;
    var planning = batch && batch.planning, impl = batch && batch.implementation;
    var cost = batch && batch.cost;
    if (!cost && !(planning && planning.cost) && !(impl && impl.cost)) {
      root.appendChild(C.el(doc, "p", "No telemetry recorded for this batch.", "empty"));
      return;
    }
    var names = {};
    [cost, planning && planning.cost, impl && impl.cost].forEach(function (c) {
      Object.keys((c && c.byModel) || {}).forEach(function (m) { names[m] = true; });
    });
    var slots = K.modelSlots(Object.keys(names));
    var anyProvisional = phaseCostRows(batch).some(function (r) { return r.provisional; });
    if (anyProvisional) root.appendChild(provisionalNote(doc));

    root.appendChild(outputSection(doc, outputParts(batch)));

    var two = C.el(doc, "div", null, "cost-two");
    two.appendChild(partSection(doc, "plan", "Planning", planning, PLAN_LABELS, slots));
    two.appendChild(partSection(doc, "impl", "Implementation", impl, implLabels(batch), slots));
    root.appendChild(two);

    root.appendChild(implPhaseSection(doc, ctx, batch, slots));

    var agents = section(doc, "Agents");
    var groups = agentGroups(batch);
    if (groups.length) agents.appendChild(agentsTable(doc, null, groups));
    else agents.appendChild(C.el(doc, "p", "No sub-agents recorded.", "empty"));
    root.appendChild(agents);

    var exact = C.el(doc, "section", null, "cost-section");
    exact.appendChild(exactSection(doc, batch));
    root.appendChild(exact);
  }

  function renderPhaseCost(doc, root, ctx, phase, attempt) {
    var C = core(), K = CFQ.charts;
    if (!attempt) {
      root.appendChild(C.el(doc, "p", "Not started.", "empty"));
      return;
    }
    var cost = attempt.cost;
    if (!cost) {
      root.appendChild(C.el(doc, "p", "No telemetry recorded for this attempt.", "empty"));
      return;
    }
    var slots = K.modelSlots(Object.keys(cost.byModel || {}));
    if (attempt.settled === false) root.appendChild(provisionalNote(doc));
    root.appendChild(modelTable(doc, costRows(cost), slots));
    root.appendChild(layerTable(doc, layerRows(cost), slots));
    if ((cost.agents || []).length) {
      root.appendChild(C.el(doc, "h4", "Agents"));
      root.appendChild(agentsTable(doc, cost.agents));
    }
  }

  CFQ.batchCost = {
    costRows: costRows,
    layerRows: layerRows,
    phaseCostRows: phaseCostRows,
    implPhaseRows: implPhaseRows,
    outputParts: outputParts,
    exactRows: exactRows,
    toTsv: toTsv,
  };

  CFQ.core.register("batchTab", { id: "cost", label: "Cost", order: 20, render: renderCostTab });
  CFQ.core.register("phaseTab", { id: "cost", label: "Cost", order: 30, render: renderPhaseCost });
})();
