// The batch page's cost views: the Cost tab (key figures, per model, per layer, per phase, per
// agent, and an "Exact numbers" table with a TSV export) and the per-phase Cost sub-tab. Cost is
// turns and tokens only, split by model at every level -- no price table, no currency: the exact
// numbers table is precise enough to multiply with a price list by hand later.
//
// The row builders (`costRows`, `layerRows`, `phaseCostRows`, `exactRows`, `toTsv`) are pure so
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

  function tiles(doc, total) {
    var C = core();
    var wrap = C.el(doc, "div", null, "tiles");
    [
      ["Turns", total.turns, C.fmtInt(total.turns)],
      ["In", C.billableIn(total), null],
      ["Out", total.output, null],
      ["Cache read", total.cache_read, null],
    ].forEach(function (t) {
      var tile = C.el(doc, "div", null, "tile");
      tile.appendChild(C.el(doc, "div", t[0], "tile-label"));
      var v = C.el(doc, "div", t[2] !== null ? t[2] : C.fmtTokens(t[1]), "tile-value");
      v.setAttribute("title", C.fmtInt(t[1]));
      tile.appendChild(v);
      wrap.appendChild(tile);
    });
    return wrap;
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

  function modelCells(doc, tr, r, maxOut) {
    var C = core();
    tr.appendChild(numTd(doc, r.turns));
    var inTd = C.el(doc, "td", C.fmtInt(C.billableIn(r)), "n");
    inTd.setAttribute("title", String(C.billableIn(r)));
    tr.appendChild(inTd);
    tr.appendChild(numTd(doc, r.output, !r.total, maxOut)); // a bar for the total row would dwarf its parts
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

  function agentsTable(doc, agents) {
    var C = core();
    var table = C.el(doc, "table", null, "data cost-table agents");
    table.appendChild(headRow(doc, [["Type", ""], ["Description", ""], ["Layer", ""], ["Models", ""], ["Turns", "n"], ["In", "n", NUM_TITLE.in], ["Out", "n"]]));
    var body = C.el(doc, "tbody");
    agents.forEach(function (a) {
      var tr = C.el(doc, "tr");
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
      body.appendChild(tr);
    });
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

  // Per-phase output bars plus a table with every phase's figures and its provisional marker.
  function phaseSection(doc, ctx, batch, slots) {
    var C = core(), K = CFQ.charts;
    var rows = phaseCostRows(batch);
    var sec = section(doc, "By phase");
    if (!rows.length) {
      sec.appendChild(C.el(doc, "p", "No phase recorded telemetry.", "empty"));
      return sec;
    }
    var bars = rows.map(function (r) {
      var values = {};
      Object.keys(r.byModel).forEach(function (m) { values[m] = r.byModel[m].output; });
      return { label: r.label, href: r.slug ? C.href(ctx, "batch/" + batch.name + "/phase/" + r.slug) : null, values: values };
    });
    var svg = K.hBars(doc, bars, slots);
    if (svg) {
      sec.appendChild(C.el(doc, "p", "Output tokens per phase, stacked by model", "caption muted"));
      var wrap = C.el(doc, "div", null, "chart-wrap");
      wrap.appendChild(svg);
      sec.appendChild(wrap);
      sec.appendChild(K.legend(doc, slots));
    }
    var table = C.el(doc, "table", null, "data cost-table by-phase");
    table.appendChild(headRow(doc, [["Phase", ""], ["Turns", "n"], ["In", "n", NUM_TITLE.in], ["Out", "n"], ["Cache read", "n"], ["", ""]]));
    var body = C.el(doc, "tbody");
    rows.forEach(function (r) {
      var tr = C.el(doc, "tr");
      var label = C.el(doc, "td", null, "phase");
      if (r.slug) {
        var a = C.el(doc, "a", r.label);
        a.setAttribute("href", C.href(ctx, "batch/" + batch.name + "/phase/" + r.slug));
        label.appendChild(a);
      } else {
        label.textContent = r.label;
      }
      tr.appendChild(label);
      tr.appendChild(numTd(doc, r.total.turns));
      var inTd = C.el(doc, "td", C.fmtInt(C.billableIn(r.total)), "n");
      inTd.setAttribute("title", String(C.billableIn(r.total)));
      tr.appendChild(inTd);
      tr.appendChild(numTd(doc, r.total.output));
      tr.appendChild(numTd(doc, r.total.cache_read));
      var mark = C.el(doc, "td");
      if (r.provisional) mark.appendChild(provisionalMark(doc));
      tr.appendChild(mark);
      body.appendChild(tr);
    });
    table.appendChild(body);
    sec.appendChild(scroll(doc, table));
    return sec;
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

  function renderCostTab(doc, root, ctx) {
    var C = core(), K = CFQ.charts;
    var batch = ctx.batch;
    var cost = batch && batch.cost;
    if (!cost) {
      root.appendChild(C.el(doc, "p", "No telemetry recorded for this batch.", "empty"));
      return;
    }
    var slots = K.modelSlots(Object.keys(cost.byModel || {}));
    var anyProvisional = phaseCostRows(batch).some(function (r) { return r.provisional; });
    if (anyProvisional) root.appendChild(provisionalNote(doc));

    root.appendChild(tiles(doc, t5(cost.total)));

    var byModel = section(doc, "By model");
    byModel.appendChild(modelTable(doc, costRows(cost), slots));
    byModel.appendChild(K.legend(doc, slots));
    root.appendChild(byModel);

    var byLayer = section(doc, "By layer");
    byLayer.appendChild(layerTable(doc, layerRows(cost), slots));
    root.appendChild(byLayer);

    root.appendChild(phaseSection(doc, ctx, batch, slots));

    var agents = section(doc, "Agents");
    if ((cost.agents || []).length) agents.appendChild(agentsTable(doc, cost.agents));
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
    exactRows: exactRows,
    toTsv: toTsv,
  };

  CFQ.core.register("batchTab", { id: "cost", label: "Cost", order: 20, render: renderCostTab });
  CFQ.core.register("phaseTab", { id: "cost", label: "Cost", order: 30, render: renderPhaseCost });
})();
