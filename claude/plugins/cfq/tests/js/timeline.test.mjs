// Tests for portal/timeline.js: the pure layout (collapsed idle gaps, points, missing rows), the
// DOM output and the `batchPhasesTop` registration on the batch page.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, byClass, byTag, collectText, loadPortal, fixtureSite, fixtureBatch,
} from "./helpers.mjs";

const CFQ = loadPortal();
const T = CFQ.timeline;
const site = fixtureSite();

const at = (h, m = 0, day = 1) => `2026-10-${String(day).padStart(2, "0")}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00Z`;

function renderBatch(batch, doc) {
  const d = doc || fakeDoc();
  const root = fakeRoot(d);
  CFQ.batch.render(d, root, {
    mode: "repo", repo: site.repo, mirror: null, site, batch, setCrumbs() {},
    route: { name: "batch", tab: null, batch: batch.name, phase: null, mirror: null },
  });
  return { doc: d, root };
}

test("loading timeline.js registers one batchPhasesTop item", () => {
  const items = CFQ.core.registered("batchPhasesTop");
  assert.deepEqual(items.map((i) => [i.id, i.order]), [["timeline", 10]]);
});

test("timelineLayout: two phases ten minutes apart share one stretch", () => {
  const layout = T.timelineLayout([
    { label: "a", from: at(8), until: at(8, 20) },
    { label: "b", from: at(8, 30), until: at(8, 50) },
  ], 1000);
  assert.equal(layout.breaks.length, 0);
  assert.equal(layout.rows.length, 2);
  assert.equal(layout.rows[0].x, 0);
  assert.ok(layout.rows[1].x > layout.rows[0].x + layout.rows[0].w - 0.01);
  assert.ok(layout.rows[1].x + layout.rows[1].w <= 1000.01);
  assert.deepEqual(layout.missing, []);
});

test("timelineLayout: an idle gap over an hour becomes one labelled break", () => {
  const layout = T.timelineLayout([
    { label: "a", from: at(8), until: at(9) },
    { label: "b", from: at(17), until: at(17, 30) },
  ], 1000);
  assert.equal(layout.breaks.length, 1);
  assert.equal(layout.breaks[0].label, "8h");
  const [a, b] = layout.rows;
  assert.ok(layout.breaks[0].x >= a.x + a.w - 0.01);
  assert.ok(b.x >= layout.breaks[0].x + layout.breaks[0].w - 0.01);
  assert.ok(b.x + b.w <= 1000.01);
  // The break takes a fixed width, not the eight hours: the bars stay readable.
  assert.ok(a.w > 100);
});

test("timelineLayout: a gap of exactly an hour is not collapsed; multi-day gaps read in days", () => {
  assert.equal(T.timelineLayout([
    { label: "a", from: at(8), until: at(9) },
    { label: "b", from: at(10), until: at(11) },
  ]).breaks.length, 0);
  const days = T.timelineLayout([
    { label: "a", from: at(8, 0, 1), until: at(9, 0, 1) },
    { label: "b", from: at(9, 0, 4), until: at(10, 0, 4) },
  ]);
  assert.equal(days.breaks[0].label, "3d");
  assert.equal(T.fmtGap(75 * 60000), "1h 15m");
});

test("timelineLayout: a row with only until is a point; a row with neither is missing", () => {
  const layout = T.timelineLayout([
    { label: "a", from: at(8), until: at(9) },
    { label: "p", until: at(8, 30) },
    { label: "none" },
    { label: "bad", from: "not a date", until: "" },
  ], 1000);
  assert.equal(layout.rows.length, 2);
  const point = layout.rows.filter((r) => r.label === "p")[0];
  assert.equal(point.point, true);
  assert.equal(point.w, 0);
  assert.deepEqual(layout.missing.map((r) => r.label), ["none", "bad"]);
});

test("timelineLayout: zero usable rows give null", () => {
  assert.equal(T.timelineLayout([], 1000), null);
  assert.equal(T.timelineLayout([{ label: "x" }], 1000), null);
  assert.equal(T.timelineLayout(null, 1000), null);
});

test("timeline: one bar per row with a title, one marker per break, labels as text", () => {
  const layout = T.timelineLayout([
    { label: "01-first", from: at(8), until: at(9) },
    { label: "02-second", from: at(17), until: at(17, 30) },
    { label: "03-point", until: at(17, 40) },
  ], 1000);
  const doc = fakeDoc();
  const node = T.timeline(doc, layout);
  const bars = byClass(node, "tl-bar");
  assert.equal(bars.length, 3);
  bars.forEach((b) => assert.ok(b.attrs.title && b.attrs.title.length > 0));
  assert.match(bars[0].attrs.title, /–/);
  assert.match(bars[0].attrs.title, /1:00:00/);
  assert.equal(byClass(node, "tl-point").length, 1);
  assert.equal(byClass(node, "tl-break").length, 1);
  assert.equal(byClass(node, "tl-break")[0].textContent, "8h");
  const text = collectText(node);
  ["01-first", "02-second", "03-point"].forEach((l) => assert.match(text, new RegExp(l)));
  assert.equal(byClass(T.timeline(doc, T.timelineLayout([{ label: "a", from: at(8), until: at(9) }])), "tl-break").length, 0);
});

test("batch page: the timeline sits above the phase table with Planning and one row per attempted phase", () => {
  const { root } = renderBatch(fixtureBatch("done"));
  const host = byClass(root, "top-timeline")[0];
  assert.ok(host, "the batchPhasesTop host exists");
  const labels = byClass(host, "tl-label").map((n) => n.textContent);
  assert.deepEqual(labels, ["Planning", "01-first", "02-second"]);
  assert.equal(byClass(host, "tl-bar").length, 3);
  // Above the table: the host precedes the table in document order.
  const order = [];
  (function walk(n) { order.push(n); (n.children || []).forEach(walk); })(root);
  assert.ok(order.indexOf(host) < order.indexOf(byClass(root, "phases")[0]));
});

test("batch page: a batch with a long pause shows the break, a plan-only batch renders nothing", () => {
  const batch = fixtureBatch("done");
  batch.planning.from = at(6, 0, 28);
  batch.planning.until = at(7, 0, 28);
  const { root } = renderBatch(batch);
  assert.equal(byClass(byClass(root, "top-timeline")[0], "tl-break").length, 1);

  const plan = renderBatch(fixtureBatch("plan_only"));
  const host = byClass(plan.root, "top-timeline")[0];
  assert.equal(host.children.length, 0);
});

test("batch page: a phase without timestamps is named, not drawn", () => {
  const batch = fixtureBatch("done");
  batch.phases[0].attempts[0].time = { from: "", until: "", wallclock_s: null };
  const host = byClass(renderBatch(batch).root, "top-timeline")[0];
  // The axis row (shown once a break exists) has an empty label.
  assert.deepEqual(byClass(host, "tl-label").map((n) => n.textContent).filter(Boolean), ["Planning", "02-second"]);
  assert.match(collectText(host), /No timestamps recorded for: 01-first/);
});

test("labels containing markup never reach innerHTML", () => {
  const batch = fixtureBatch("done");
  batch.phases[0].slug = "<script>alert(1)</script>";
  const { doc, root } = renderBatch(batch);
  assert.match(collectText(byClass(root, "top-timeline")[0]), /<script>alert\(1\)<\/script>/);
  assert.ok(doc.innerHtmlWrites.every((w) => !w.value.includes("<script>")));
  assert.equal(byTag(root, "script").length, 0);
});
