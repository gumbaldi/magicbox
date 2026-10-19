// The two chart panels above the overview's batch table: cost per batch (stacked by model, with a
// metric switch) and size calibration (planned S/M/L against actual turns or output). Both plug
// into the `overviewPanel` slot; `charts.js` draws, this file only picks and shapes the data.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var LATEST = 40;
  var NO_COST = "No cost data recorded yet.";

  function core() { return CFQ.core; }
  function charts() { return CFQ.charts; }

  var COST_METRICS = [
    { id: "turns", label: "Turns", name: "Turns" },
    { id: "in", label: "In", name: "Input tokens (input + cache creation)" },
    { id: "out", label: "Out", name: "Output tokens" },
  ];
  var SIZE_METRICS = [
    { id: "turns", label: "Turns", name: "Turns" },
    { id: "output", label: "Out", name: "Output tokens" },
  ];

  function metricOf(t, metric) {
    if (!t) return 0;
    if (metric === "turns") return t.turns || 0;
    if (metric === "in") return core().billableIn(t);
    return t.output || 0;
  }

  function hasCost(queue) {
    return ((queue && queue.batches) || []).some(function (b) { return b && b.cost; });
  }

  function allModels(queue) {
    var seen = [];
    ((queue && queue.batches) || []).forEach(function (b) {
      Object.keys((b && b.cost && b.cost.byModel) || {}).forEach(function (m) {
        if (seen.indexOf(m) === -1) seen.push(m);
      });
    });
    return seen;
  }

  // Done batches with a cost, oldest finish first, the latest 40. `values` maps model -> metric.
  function trendBars(queue, metric) {
    var rows = ((queue && queue.batches) || []).filter(function (b) {
      return b && b.status === "done" && b.cost;
    });
    rows.sort(function (a, b) {
      var fa = a.finished || "", fb = b.finished || "";
      return fa < fb ? -1 : fa > fb ? 1 : (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    return rows.slice(-LATEST).map(function (b) {
      var values = {}, total = 0;
      var byModel = b.cost.byModel || {};
      Object.keys(byModel).forEach(function (m) {
        values[m] = metricOf(byModel[m], metric);
        total += values[m];
      });
      return { name: b.name, number: b.number, finished: b.finished || "", values: values, total: total };
    });
  }

  // ---- shared panel frame -----------------------------------------------------------------------

  function frame(doc, root, title, caption) {
    var C = core();
    root.appendChild(C.el(doc, "h3", title, "panel-title"));
    root.appendChild(C.el(doc, "p", caption, "caption muted"));
  }

  // A two- or three-button switch; `onPick(id)` redraws the panel's view.
  function metricSwitch(doc, metrics, start, onPick) {
    var C = core();
    var wrap = C.el(doc, "div", null, "metric-switch");
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Metric");
    var buttons = [];
    metrics.forEach(function (m) {
      var b = C.el(doc, "button", m.label, "chip");
      b.setAttribute("type", "button");
      b.setAttribute("title", m.name);
      b.setAttribute("aria-pressed", m.id === start ? "true" : "false");
      b.addEventListener("click", function () {
        buttons.forEach(function (x) { x.node.setAttribute("aria-pressed", x.id === m.id ? "true" : "false"); });
        onPick(m.id);
      });
      buttons.push({ id: m.id, node: b });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function numbersDisclosure(doc, columns, rows) {
    var C = core();
    return C.disclosure(doc, "Numbers", function (d, body) {
      var scroll = C.el(d, "div", null, "tscroll");
      scroll.appendChild(charts().numbersTable(d, columns, rows));
      body.appendChild(scroll);
    });
  }

  // ---- cost per batch ---------------------------------------------------------------------------

  function renderCost(doc, root, ctx) {
    var C = core(), K = charts();
    var queue = ctx && ctx.queue;
    if (!hasCost(queue)) {
      root.appendChild(C.el(doc, "p", NO_COST, "empty"));
      return;
    }
    frame(doc, root, "Cost per batch",
      "Finished batches, oldest to newest (latest " + LATEST + "), stacked by model. Each bar opens its batch.");
    var slots = K.modelSlots(allModels(queue));
    var view = C.el(doc, "div", null, "chart-view");

    function draw(metric) {
      C.clear(view);
      var def = COST_METRICS.filter(function (m) { return m.id === metric; })[0];
      var rows = trendBars(queue, metric);
      var bars = rows.map(function (r) {
        return {
          label: r.name + (r.finished ? "  (" + C.fmtDate(r.finished.slice(0, 10)) + ")" : ""),
          tick: String(r.number),
          href: C.href(ctx, "batch/" + r.name),
          values: r.values,
        };
      });
      var svg = K.stackedBars(doc, { bars: bars, keys: slots, metric: def.name });
      if (!svg) {
        view.appendChild(C.el(doc, "p", rows.length ? "No " + def.name.toLowerCase() + " recorded for the finished batches."
          : "No finished batch with recorded cost yet.", "empty"));
        return;
      }
      var wrap = C.el(doc, "div", null, "chart-wrap");
      wrap.appendChild(svg);
      view.appendChild(wrap);
      var used = {};
      rows.forEach(function (r) { Object.keys(r.values).forEach(function (m) { if (r.values[m] > 0) used[m] = slots[m]; }); });
      view.appendChild(K.legend(doc, used));
      var models = Object.keys(used).sort();
      var columns = [{ key: "batch", label: "Batch" }, { key: "finished", label: "Finished" }]
        .concat(models.map(function (m) { return { key: "m:" + m, label: m, num: true }; }))
        .concat([{ key: "total", label: "Total " + def.label.toLowerCase(), num: true }]);
      view.appendChild(numbersDisclosure(doc, columns, rows.map(function (r) {
        var row = { batch: r.name, finished: r.finished ? r.finished.slice(0, 10) : "–", total: r.total };
        models.forEach(function (m) { row["m:" + m] = r.values[m] || 0; });
        return row;
      })));
    }

    root.appendChild(metricSwitch(doc, COST_METRICS, "out", draw));
    root.appendChild(view);
    draw("out");
  }

  // ---- size calibration -------------------------------------------------------------------------

  function calibrationLegend(doc) {
    var C = core();
    var ul = C.el(doc, "ul", null, "legend");
    [["dot-key", "One finished phase"], ["median-key", "Median of its size (baseline)"]].forEach(function (p) {
      var li = C.el(doc, "li", null, "legend-item");
      var sw = C.el(doc, "span", null, "swatch " + p[0]);
      sw.setAttribute("aria-hidden", "true");
      li.appendChild(sw);
      li.appendChild(C.el(doc, "span", p[1], "legend-name"));
      ul.appendChild(li);
    });
    return ul;
  }

  function renderCalibration(doc, root, ctx) {
    var C = core(), K = charts();
    var queue = ctx && ctx.queue;
    // With no cost anywhere the cost panel already says so in one line.
    if (!hasCost(queue)) return;
    frame(doc, root, "Size calibration",
      "Planned size against the turns or output a finished phase actually used. A size needs 5 phases before its median flags outliers.");
    var points = (queue && queue.sizes) || [];
    var baselines = (queue && queue.baselines) || {};
    var view = C.el(doc, "div", null, "chart-view");

    function draw(metric) {
      C.clear(view);
      var def = SIZE_METRICS.filter(function (m) { return m.id === metric; })[0];
      var svg = K.stripBySize(doc, { points: points, baselines: baselines, metric: metric });
      if (!svg) {
        view.appendChild(C.el(doc, "p", "No finished phase with a planned size and recorded cost yet.", "empty"));
        return;
      }
      var wrap = C.el(doc, "div", null, "chart-wrap");
      wrap.appendChild(svg);
      view.appendChild(wrap);
      view.appendChild(calibrationLegend(doc));
      view.appendChild(numbersDisclosure(doc, [
        { key: "size", label: "Size" }, { key: "batch", label: "Batch" }, { key: "phase", label: "Phase" },
        { key: "turns", label: "Turns", num: true }, { key: "output", label: "Output", num: true },
      ], points.slice().sort(function (a, b) {
        return String(a.size).localeCompare(String(b.size)) || String(a.batch).localeCompare(String(b.batch))
          || String(a.phase).localeCompare(String(b.phase));
      })));
    }

    root.appendChild(metricSwitch(doc, SIZE_METRICS, "turns", draw));
    root.appendChild(view);
    draw("turns");
  }

  // ---- registration -----------------------------------------------------------------------------

  CFQ.overviewCharts = { trendBars: trendBars };

  CFQ.core.register("overviewPanel", { id: "cost", order: 10, render: renderCost });
  CFQ.core.register("overviewPanel", { id: "calibration", order: 20, render: renderCalibration });
})();
