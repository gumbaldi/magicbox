// Hand-written inline SVG charts of the portal viewer: stacked bars, horizontal stacked bars and a
// strip chart per size, plus the legend and the plain numbers table every chart ships with. No
// library, no CDN, no inline colours: segments carry the CSS classes `m0`..`m5` / `m-other` that
// style.css colours for both themes. SVG nodes are built with `createElementNS`, and every text
// reaches the DOM through `textContent` -- nothing here parses markup.
//
// `keys` / `slots` arguments are the map `modelSlots()` returns: `{<model name>: <slot class>}`.
// SVG elements get their class with `setAttribute("class", ...)`: `className` is a read-only
// SVGAnimatedString on a real SVG element.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var SVG_NS = "http://www.w3.org/2000/svg";
  var MAX_SLOTS = 6;
  var OTHER = "m-other";
  var BASELINE_MIN = 5;

  function core() { return CFQ.core; }
  function isNum(n) { return typeof n === "number" && isFinite(n); }
  function r2(n) { return Math.round(n * 100) / 100; }

  // ---- scales -----------------------------------------------------------------------------------

  // Sorted model names -> `m0`..`m5`; the seventh and later share `m-other`. Deterministic.
  function modelSlots(models) {
    var names = [];
    (models || []).forEach(function (m) {
      if (typeof m === "string" && names.indexOf(m) === -1) names.push(m);
    });
    names.sort();
    var out = {};
    names.forEach(function (m, i) { out[m] = i < MAX_SLOTS ? "m" + i : OTHER; });
    return out;
  }

  // A "nice" upper bound: 1, 2 or 5 times a power of ten, at or above the maximum.
  function scaleMax(values) {
    var max = 0;
    (values || []).forEach(function (v) { if (isNum(v) && v > max) max = v; });
    if (max <= 0) return 1;
    var base = Math.pow(10, Math.floor(Math.log10(max)));
    var f = max / base;
    var nice = f <= 1 + 1e-9 ? 1 : f <= 2 + 1e-9 ? 2 : f <= 5 + 1e-9 ? 5 : 10;
    return nice * base;
  }

  function slotRank(slot) {
    var m = /^m(\d)$/.exec(slot || "");
    return m ? Number(m[1]) : 99;
  }

  // The names of `values` with a non-zero number, in slot order (bottom of the stack first).
  function activeKeys(values, slots) {
    return Object.keys(values || {}).filter(function (k) { return isNum(values[k]) && values[k] > 0; })
      .sort(function (a, b) {
        return slotRank(slots[a]) - slotRank(slots[b]) || (a < b ? -1 : a > b ? 1 : 0);
      });
  }

  function sumOf(values, keys) {
    return keys.reduce(function (n, k) { return n + values[k]; }, 0);
  }

  // ---- SVG building -----------------------------------------------------------------------------

  function svgEl(doc, tag, attrs, text) {
    var e = doc.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, String(attrs[k]));
    });
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function svgRoot(doc, w, h, label) {
    return svgEl(doc, "svg", {
      "class": "chart", viewBox: "0 0 " + w + " " + h, role: "img", "aria-label": label,
      preserveAspectRatio: "xMidYMid meet",
    });
  }

  function slotClass(slots, key) { return (slots && slots[key]) || OTHER; }

  // Wraps a bar or row group in a link when it has a target.
  function linked(doc, node, href) {
    if (!href) return node;
    var a = svgEl(doc, "a", { href: href, "class": "chart-link" });
    a.appendChild(node);
    return a;
  }

  // ---- stacked bars -----------------------------------------------------------------------------
  // bars: [{label, tick, href, values: {<model>: number}}]; metric: the axis caption.

  function stackedBars(doc, opts) {
    var C = core();
    opts = opts || {};
    var bars = opts.bars || [], slots = opts.keys || {};
    var fmt = opts.fmt || C.fmtTokens;
    var perBar = bars.map(function (b) {
      var keys = activeKeys(b.values, slots);
      return { keys: keys, total: sumOf(b.values || {}, keys) };
    });
    var max = scaleMax(perBar.map(function (p) { return p.total; }));
    if (!bars.length || !perBar.some(function (p) { return p.total > 0; })) return null;

    var W = 560, H = 230, L = 46, T = 10, B = H - 26, plotW = W - L - 6, plotH = B - T;
    var step = Math.min(plotW / bars.length, 44);
    var bw = Math.max(2, Math.min(step * 0.7, 30));
    var svg = svgRoot(doc, W, H, (opts.metric || "Value") + " per bar, stacked by model");

    [0, 0.5, 1].forEach(function (f) {
      var y = r2(B - f * plotH);
      svg.appendChild(svgEl(doc, "line", { x1: L, x2: W - 6, y1: y, y2: y, "class": f === 0 ? "axis" : "grid" }));
      svg.appendChild(svgEl(doc, "text", { x: L - 5, y: y + 3, "text-anchor": "end", "class": "tick" }, fmt(max * f)));
    });

    var every = Math.max(1, Math.ceil(22 / step));
    bars.forEach(function (b, i) {
      var p = perBar[i];
      var x = r2(L + i * step + (step - bw) / 2);
      var group = svgEl(doc, "g", { "class": "bar" });
      var lines = [b.label || ""];
      p.keys.forEach(function (k) { lines.push(k + ": " + C.fmtInt(b.values[k])); });
      lines.push("total: " + C.fmtInt(p.total));
      group.appendChild(svgEl(doc, "title", {}, lines.join("\n")));
      var acc = 0;
      p.keys.forEach(function (k) {
        var h = (b.values[k] / max) * plotH;
        acc += h;
        group.appendChild(svgEl(doc, "rect", {
          x: x, y: r2(B - acc), width: r2(bw), height: r2(h), "class": slotClass(slots, k),
        }));
      });
      if (!p.keys.length) group.appendChild(svgEl(doc, "rect", { x: x, y: B - 1, width: r2(bw), height: 1, "class": "empty" }));
      svg.appendChild(linked(doc, group, b.href));
      if (b.tick && i % every === 0) {
        svg.appendChild(svgEl(doc, "text", { x: r2(x + bw / 2), y: B + 13, "text-anchor": "middle", "class": "tick" }, b.tick));
      }
    });
    return svg;
  }

  // ---- horizontal stacked bars ------------------------------------------------------------------
  // rows: [{label, href, values: {<model>: number}}]

  function hBars(doc, rows, keys) {
    var C = core();
    rows = rows || [];
    var slots = keys || {};
    var per = rows.map(function (r) {
      var ks = activeKeys(r.values, slots);
      return { keys: ks, total: sumOf(r.values || {}, ks) };
    });
    var maxTotal = per.reduce(function (m, p) { return Math.max(m, p.total); }, 0);
    if (!rows.length || maxTotal <= 0) return null;

    var W = 560, labelW = 150, valueW = 64, rowH = 22, barH = 14;
    var area = W - labelW - valueW;
    var svg = svgRoot(doc, W, rows.length * rowH + 4, "Totals per row, stacked by model");
    rows.forEach(function (r, i) {
      var p = per[i], y = 2 + i * rowH;
      var group = svgEl(doc, "g", { "class": "row" });
      var lines = [r.label || ""];
      p.keys.forEach(function (k) { lines.push(k + ": " + C.fmtInt(r.values[k])); });
      lines.push("total: " + C.fmtInt(p.total));
      group.appendChild(svgEl(doc, "title", {}, lines.join("\n")));
      var label = String(r.label || "");
      group.appendChild(svgEl(doc, "text", { x: labelW - 6, y: y + barH - 3, "text-anchor": "end", "class": "tick" },
        label.length > 26 ? label.slice(0, 25) + "…" : label));
      var x = labelW;
      p.keys.forEach(function (k) {
        var w = (r.values[k] / maxTotal) * area;
        group.appendChild(svgEl(doc, "rect", { x: r2(x), y: y, width: r2(w), height: barH, "class": slotClass(slots, k) }));
        x += w;
      });
      group.appendChild(svgEl(doc, "text", { x: r2(x + 5), y: y + barH - 3, "class": "tick" }, C.fmtTokens(p.total)));
      svg.appendChild(linked(doc, group, r.href));
    });
    return svg;
  }

  // ---- strip chart per size ---------------------------------------------------------------------
  // points: [{batch, phase, size, turns, output}]; baselines: {<size>: {n, turnsMedian,
  // outputMedian}}; metric: "turns" | "output".

  var SIZE_ORDER = ["S", "M", "L"];

  function stripBySize(doc, opts) {
    var C = core();
    opts = opts || {};
    var metric = opts.metric || "turns";
    var fmt = opts.fmt || C.fmtTokens;
    var baselines = opts.baselines || {};
    var points = (opts.points || []).filter(function (p) { return p && isNum(p[metric]); });
    if (!points.length) return null;

    var present = [];
    points.forEach(function (p) { if (present.indexOf(p.size) === -1) present.push(p.size); });
    present.sort(function (a, b) {
      var ia = SIZE_ORDER.indexOf(a), ib = SIZE_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || (a < b ? -1 : a > b ? 1 : 0);
    });
    function median(size) {
      var b = baselines[size];
      return b && isNum(b[metric + "Median"]) ? b[metric + "Median"] : null;
    }
    var max = scaleMax(points.map(function (p) { return p[metric]; }).concat(present.map(median).filter(isNum)));

    var W = 560, H = 270, L = 46, T = 10, B = H - 64, plotW = W - L - 6, plotH = B - T;
    var colW = plotW / present.length;
    var svg = svgRoot(doc, W, H, (metric === "turns" ? "Turns" : "Output tokens") + " per finished phase, by planned size");
    [0, 0.5, 1].forEach(function (f) {
      var y = r2(B - f * plotH);
      svg.appendChild(svgEl(doc, "line", { x1: L, x2: W - 6, y1: y, y2: y, "class": f === 0 ? "axis" : "grid" }));
      svg.appendChild(svgEl(doc, "text", { x: L - 5, y: y + 3, "text-anchor": "end", "class": "tick" }, fmt(max * f)));
    });

    var jitter = [0, -9, 9, -18, 18];
    present.forEach(function (size, ci) {
      var cx = r2(L + ci * colW + colW / 2);
      var col = svgEl(doc, "g", { "class": "column" });
      var inCol = points.filter(function (p) { return p.size === size; })
        .sort(function (a, b) { return a[metric] - b[metric]; });
      inCol.forEach(function (p, i) {
        var dot = svgEl(doc, "circle", {
          cx: r2(cx + jitter[i % jitter.length]), cy: r2(B - (p[metric] / max) * plotH), r: 3.5, "class": "dot",
        });
        dot.appendChild(svgEl(doc, "title", {}, (p.batch || "") + " / " + (p.phase || "") + "\n" + metric + ": " + C.fmtInt(p[metric])));
        col.appendChild(dot);
      });
      var base = baselines[size], med = median(size);
      if (med !== null) {
        var my = r2(B - (med / max) * plotH);
        col.appendChild(svgEl(doc, "line", { x1: r2(cx - colW * 0.32), x2: r2(cx + colW * 0.32), y1: my, y2: my, "class": "median" }));
      }
      col.appendChild(svgEl(doc, "text", { x: cx, y: B + 15, "text-anchor": "middle", "class": "size-label" }, size));
      var n = base && isNum(base.n) ? base.n : 0;
      col.appendChild(svgEl(doc, "text", { x: cx, y: B + 30, "text-anchor": "middle", "class": "tick median-label" },
        "median " + (med === null ? "–" : fmt(med)) + " · n=" + n));
      if (n < BASELINE_MIN) {
        col.appendChild(svgEl(doc, "text", { x: cx, y: B + 43, "text-anchor": "middle", "class": "tick note" }, "outlier check needs " + BASELINE_MIN));
      }
      svg.appendChild(col);
    });
    return svg;
  }

  // ---- legend and numbers table -----------------------------------------------------------------

  // Every model name as text next to its swatch.
  function legend(doc, slots) {
    var C = core();
    var ul = C.el(doc, "ul", null, "legend");
    Object.keys(slots || {}).sort().forEach(function (name) {
      var li = C.el(doc, "li", null, "legend-item");
      var sw = C.el(doc, "span", null, "swatch " + slots[name]);
      sw.setAttribute("aria-hidden", "true");
      li.appendChild(sw);
      li.appendChild(C.el(doc, "span", name, "legend-name"));
      ul.appendChild(li);
    });
    return ul;
  }

  // columns: [{key, label, num}]; rows: objects. Values are shown exactly as given.
  function numbersTable(doc, columns, rows) {
    var C = core();
    var table = C.el(doc, "table", null, "data numbers");
    var thead = C.el(doc, "thead"), head = C.el(doc, "tr");
    columns.forEach(function (c) {
      var th = C.el(doc, "th", c.label, c.num ? "n" : "");
      th.setAttribute("scope", "col");
      head.appendChild(th);
    });
    thead.appendChild(head);
    table.appendChild(thead);
    var tbody = C.el(doc, "tbody");
    (rows || []).forEach(function (row) {
      var tr = C.el(doc, "tr");
      columns.forEach(function (c) {
        var v = row[c.key];
        tr.appendChild(C.el(doc, "td", v === undefined || v === null ? "–" : v, c.num ? "n" : ""));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  CFQ.charts = {
    modelSlots: modelSlots,
    scaleMax: scaleMax,
    stackedBars: stackedBars,
    hBars: hBars,
    stripBySize: stripBySize,
    legend: legend,
    numbersTable: numbersTable,
  };
})();
