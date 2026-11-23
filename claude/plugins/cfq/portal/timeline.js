// The batch timeline: when each phase (and the planning session) was worked on, as one bar per row
// on a shared time axis. Idle gaps longer than an hour are replaced by a fixed-width break marker
// that carries the gap's length, so a batch spread over several days stays readable. The planning
// bar is drawn in the planning colour, the phase bars in the implementation colour, and a clock axis
// (local time, at most six labels) with the date as its caption sits under the rows. Registers
// itself under the `batchPhasesTop` slot, above the phase table.
//
// `timelineLayout` is pure (no DOM) so tests/js/timeline.test.mjs can exercise it directly; every
// text reaches the DOM through `textContent`.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var GAP_MS = 60 * 60 * 1000;   // an idle gap longer than this becomes a break
  var BREAK_W = 36;              // width of a break, in layout units
  var MIN_W = 4;                 // narrowest drawn bar, in layout units
  var DEFAULT_W = 1000;
  var MAX_TICKS = 6;             // most clock labels on the time axis
  var TICK_GAP = 90;             // least distance between two labels, in layout units (of 1000)
  var STEPS = [10, 15, 30, 60, 120, 180, 360, 720, 1440];   // even label steps, in minutes

  function core() { return CFQ.core; }
  function isNum(n) { return typeof n === "number" && isFinite(n); }
  function r2(n) { return Math.round(n * 100) / 100; }

  function ts(iso) {
    if (!iso) return null;
    var t = new Date(iso).getTime();
    return isFinite(t) ? t : null;
  }

  // "8h", "1h 15m", "3d".
  function fmtGap(ms) {
    var m = Math.round(ms / 60000);
    if (m >= 2880) return Math.round(m / 1440) + "d";
    var h = Math.floor(m / 60), rest = m % 60;
    return rest ? h + "h " + rest + "m" : h + "h";
  }

  // rows: [{label, from, until}] (ISO strings, either may be missing). Returns null without a usable
  // row; otherwise {width, rows, breaks, missing, start, end} where every row carries `x`, `w` (layout
  // units, 0..width) and `point` (drawn as a marker: only one timestamp, or both equal).
  function timelineLayout(rows, width) {
    width = isNum(width) && width > 0 ? width : DEFAULT_W;
    var items = [], missing = [];
    (rows || []).forEach(function (r) {
      var a = ts(r.from), b = ts(r.until);
      if (a === null && b === null) { missing.push(r); return; }
      var s = a === null ? b : a, e = b === null ? a : b;
      if (e < s) { var t = s; s = e; e = t; }
      items.push({
        label: r.label, kind: r.kind || "impl", from: r.from || null, until: r.until || null, s: s, e: e,
        point: a === null || b === null || s === e,
      });
    });
    if (!items.length) return null;

    var sorted = items.slice().sort(function (x, y) { return x.s - y.s || x.e - y.e; });
    var segs = [];
    sorted.forEach(function (it) {
      var last = segs[segs.length - 1];
      if (last && it.s - last.e <= GAP_MS) { if (it.e > last.e) last.e = it.e; }
      else segs.push({ s: it.s, e: it.e });
    });
    var active = segs.reduce(function (n, sg) { return n + (sg.e - sg.s); }, 0);
    var avail = Math.max(width - (segs.length - 1) * BREAK_W, 1);
    var scale = active > 0 ? avail / active : 0;

    // Left offset of each segment: the widths of the segments before it plus one break per gap.
    var offsets = [], acc = 0;
    segs.forEach(function (sg, k) {
      offsets.push(acc);
      acc += (sg.e - sg.s) * scale + (k < segs.length - 1 ? BREAK_W : 0);
    });

    var breaks = [];
    for (var k = 0; k < segs.length - 1; k++) {
      breaks.push({
        x: r2(offsets[k] + (segs[k].e - segs[k].s) * scale),
        w: BREAK_W,
        gapMs: segs[k + 1].s - segs[k].e,
        label: fmtGap(segs[k + 1].s - segs[k].e),
      });
    }

    var out = items.map(function (it) {
      var k = 0;
      while (k < segs.length - 1 && it.s > segs[k].e) k++;
      var x = offsets[k] + (it.s - segs[k].s) * scale;
      var w = it.point ? 0 : Math.max(MIN_W, (it.e - it.s) * scale);
      if (!it.point && x + w > width) x = Math.max(0, width - w);
      return {
        label: it.label, kind: it.kind, from: it.from, until: it.until, x: r2(x), w: r2(w), point: it.point,
        seconds: (it.e - it.s) / 1000,
      };
    });
    var segments = segs.map(function (sg, k) {
      return { s: sg.s, e: sg.e, x: r2(offsets[k]), w: r2((sg.e - sg.s) * scale) };
    });
    return {
      width: width, rows: out, breaks: breaks, missing: missing, start: segs[0].s, end: segs[segs.length - 1].e,
      segments: segments, scale: scale,
    };
  }

  // Clock labels for the axis under the rows: [{x, t, label}] with strictly increasing x. The start and
  // end of every stretch come first (the stretch starts before the ends), then even 10/15/30/60...
  // minute marks in local time, in the smallest step that gives at most MAX_TICKS marks; a mark is
  // dropped when it would sit closer than TICK_GAP to one already placed.
  function axisTicks(layout) {
    var C = core();
    if (!layout || !layout.segments || !layout.segments.length) return [];
    var segs = layout.segments, tickGap = TICK_GAP * layout.width / DEFAULT_W;
    var offMs = function (t) { return -new Date(t).getTimezoneOffset() * 60000; };
    var evenMarks = function (stepMin) {
      var out = [], step = stepMin * 60000;
      segs.forEach(function (sg) {
        var off = offMs(sg.s);
        for (var t = Math.ceil((sg.s + off) / step) * step - off; t <= sg.e; t += step) {
          out.push({ t: t, x: sg.x + (t - sg.s) * layout.scale });
        }
      });
      return out;
    };
    var marks = [];
    for (var i = 0; i < STEPS.length; i++) {
      marks = evenMarks(STEPS[i]);
      if (marks.length <= MAX_TICKS) break;
    }
    var candidates = [];
    segs.forEach(function (sg) { candidates.push({ t: sg.s, x: sg.x }); });
    segs.forEach(function (sg) { if (sg.e > sg.s) candidates.push({ t: sg.e, x: sg.x + sg.w }); });
    candidates = candidates.concat(marks);
    var picked = [];
    candidates.forEach(function (c) {
      if (picked.length >= MAX_TICKS) return;
      if (picked.some(function (p) { return Math.abs(p.x - c.x) < tickGap; })) return;
      picked.push(c);
    });
    picked.sort(function (a, b) { return a.x - b.x; });
    return picked.map(function (p) {
      return { x: r2(p.x), t: p.t, label: C.fmtClock(new Date(p.t).toISOString()) };
    });
  }

  // "17.11.2026 · local time", or "17.11.2026 – 18.11.2026 · local time" when the batch spans days.
  function axisCaption(layout) {
    var C = core();
    if (!layout) return "";
    var a = C.fmtDmy(new Date(layout.start).toISOString()), b = C.fmtDmy(new Date(layout.end).toISOString());
    return (a === b ? a : a + " – " + b) + " · local time";
  }

  function pct(v, width) { return r2((v / width) * 100) + "%"; }

  function barTitle(C, row) {
    if (row.point) return C.fmtDateTime(row.from || row.until);
    return C.fmtDateTime(row.from) + " – " + C.fmtDateTime(row.until) + " · " + C.fmtDuration(row.seconds);
  }

  // One row per layout row (label as text, bar with a `title`), plus one marker per break on a
  // shared axis row.
  function timeline(doc, layout) {
    var C = core();
    var wrap = C.el(doc, "div", null, "timeline");
    if (!layout) return wrap;

    if (layout.breaks.length) {
      var axis = C.el(doc, "div", null, "tl-row tl-axis");
      axis.appendChild(C.el(doc, "span", "", "tl-label"));
      var atrack = C.el(doc, "div", null, "tl-track");
      layout.breaks.forEach(function (b) {
        var mark = C.el(doc, "span", b.label, "tl-break");
        mark.style.left = pct(b.x, layout.width);
        mark.style.width = pct(b.w, layout.width);
        mark.setAttribute("title", b.label + " without activity");
        atrack.appendChild(mark);
      });
      axis.appendChild(atrack);
      wrap.appendChild(axis);
    }

    layout.rows.forEach(function (row) {
      var tr = C.el(doc, "div", null, "tl-row");
      var label = C.el(doc, "span", row.label, "tl-label");
      label.setAttribute("title", String(row.label));
      tr.appendChild(label);
      var track = C.el(doc, "div", null, "tl-track");
      layout.breaks.forEach(function (b) {
        var gap = C.el(doc, "span", null, "tl-gap");
        gap.style.left = pct(b.x, layout.width);
        gap.style.width = pct(b.w, layout.width);
        track.appendChild(gap);
      });
      var bar = C.el(doc, "span", null, "tl-bar " + (row.kind === "plan" ? "tl-plan" : "tl-impl") + (row.point ? " tl-point" : ""));
      bar.style.left = pct(row.x, layout.width);
      if (!row.point) bar.style.width = pct(row.w, layout.width);
      bar.setAttribute("title", barTitle(C, row));
      track.appendChild(bar);
      tr.appendChild(track);
      wrap.appendChild(tr);
    });
    var ticks = axisTicks(layout);
    if (ticks.length) {
      var trow = C.el(doc, "div", null, "tl-row tl-ticks");
      trow.appendChild(C.el(doc, "span", null, "tl-spacer"));
      var ttrack = C.el(doc, "div", null, "tl-track");
      ticks.forEach(function (tk) {
        var edge = tk.x / layout.width < 0.03 ? " edge-l" : tk.x / layout.width > 0.97 ? " edge-r" : "";
        var mark = C.el(doc, "span", tk.label, "tl-tick" + edge);
        mark.style.left = pct(tk.x, layout.width);
        ttrack.appendChild(mark);
      });
      trow.appendChild(ttrack);
      wrap.appendChild(trow);
      wrap.appendChild(C.el(doc, "p", axisCaption(layout), "tl-note tl-caption faint"));
    }
    if (layout.breaks.length) {
      wrap.appendChild(C.el(doc, "p", "Idle gaps over 60 minutes are collapsed into breaks.", "tl-note faint"));
    }
    return wrap;
  }

  // Planning plus one row per phase with an attempt; a phase's bar spans all of its attempts.
  function batchRows(batch) {
    var rows = [];
    if (batch && batch.planning) {
      rows.push({ label: "Planning", kind: "plan", from: batch.planning.from || null, until: batch.planning.until || null });
    }
    ((batch && batch.phases) || []).forEach(function (phase) {
      var attempts = phase.attempts || [];
      if (!attempts.length) return;
      var from = null, until = null;
      attempts.forEach(function (a) {
        var t = a.time || {};
        if (ts(t.from) !== null && (from === null || ts(t.from) < ts(from))) from = t.from;
        if (ts(t.until) !== null && (until === null || ts(t.until) > ts(until))) until = t.until;
      });
      rows.push({ label: phase.slug, kind: "impl", from: from, until: until });
    });
    return rows;
  }

  function render(doc, root, ctx) {
    var C = core();
    var layout = timelineLayout(batchRows(ctx && ctx.batch));
    if (!layout) return;
    var section = C.el(doc, "section", null, "timeline-section");
    section.appendChild(C.el(doc, "h3", "Timeline"));
    section.appendChild(timeline(doc, layout));
    if (layout.missing.length) {
      section.appendChild(C.el(doc, "p", "No timestamps recorded for: " + layout.missing.map(function (r) { return r.label; }).join(", "), "tl-note faint"));
    }
    root.appendChild(section);
  }

  CFQ.timeline = {
    timelineLayout: timelineLayout,
    axisTicks: axisTicks,
    axisCaption: axisCaption,
    timeline: timeline,
    batchRows: batchRows,
    fmtGap: fmtGap,
  };

  CFQ.core.register("batchPhasesTop", { id: "timeline", order: 10, render: render });
})();
