// Tests for portal/overview-charts.js: the trend data, the two registered panels and their rendering.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  fakeDoc, fakeRoot, fire, byTag, byClass, findAll, collectText, links, loadPortal,
  fixtureSite, fixtureQueue,
} from "./helpers.mjs";

const CFQ = loadPortal();
const OC = CFQ.overviewCharts;

function ctxFor(queue) {
  return {
    mode: "repo", repo: "/home/code/git/demo", mirror: null, site: fixtureSite(), queue,
    route: { name: "overview", tab: "batches", mirror: null }, setCrumbs() {},
  };
}

const t5 = (turns, input, output, cache_read, cache_creation) => ({ turns, input, output, cache_read, cache_creation });
const svgClass = (n) => (n.attrs && n.attrs.class ? n.attrs.class.split(/\s+/) : []);

function noCost() {
  const q = fixtureQueue();
  q.batches = q.batches.map((b) => ({ ...b, cost: null }));
  return q;
}

test("trendBars: done batches with a cost, oldest finish first, per-model values by metric", () => {
  const q = fixtureQueue();
  const bars = OC.trendBars(q, "out");
  assert.deepEqual(bars.map((b) => b.name), ["045-2026-09-20-alpha-done", "046-2026-09-25-beta-done"]);
  assert.deepEqual(bars[0].values, { "claude-sonnet-5-5": 7000, "claude-haiku-5": 2000 });
  assert.equal(bars[0].total, 9000);
  assert.deepEqual(OC.trendBars(q, "turns")[0].values, { "claude-sonnet-5-5": 100, "claude-haiku-5": 20 });
  assert.deepEqual(OC.trendBars(q, "in")[0].values, { "claude-sonnet-5-5": 4500, "claude-haiku-5": 1500 });

  const shuffled = { ...q, batches: [...q.batches].reverse() };
  assert.deepEqual(OC.trendBars(shuffled, "out").map((b) => b.name), bars.map((b) => b.name));
  assert.deepEqual(OC.trendBars({ batches: [] }, "out"), []);
  assert.deepEqual(OC.trendBars(null, "out"), []);
});

test("trendBars: limited to the latest 40", () => {
  const rows = [];
  for (let i = 1; i <= 45; i++) {
    const day = String(i).padStart(2, "0");
    rows.push({
      name: `${100 + i}-2026-01-01-b${i}`, number: 100 + i, status: "done", finished: `2026-02-${day}T00:00:00Z`,
      cost: { total: t5(1, 0, 1, 0, 0), byModel: { m: t5(1, 0, 1, 0, 0) } },
    });
  }
  const bars = OC.trendBars({ batches: rows.reverse() }, "out");
  assert.equal(bars.length, 40);
  assert.equal(bars[0].number, 106);
  assert.equal(bars[39].number, 145);
});

test("registration: exactly two overviewPanel items, cost 10 and calibration 20", () => {
  const items = CFQ.core.registered("overviewPanel");
  assert.deepEqual(items.map((i) => [i.id, i.order]), [["cost", 10], ["calibration", 20]]);
  items.forEach((i) => assert.equal(typeof i.render, "function"));
});

test("rendered in the overview: both panels above the toolbar with heading, caption, legend and numbers", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  CFQ.overview.render(doc, root, ctxFor(fixtureQueue()));
  const kids = root.children;
  const panelsAt = kids.findIndex((c) => c.className === "panels");
  const toolbarAt = kids.findIndex((c) => c.className === "toolbar");
  assert.ok(panelsAt !== -1 && panelsAt < toolbarAt);
  const panels = byTag(kids[panelsAt], "section");
  assert.equal(panels.length, 2);
  assert.deepEqual(panels.map((p) => p.className), ["panel panel-cost", "panel panel-calibration"]);
  for (const panel of panels) {
    assert.equal(byTag(panel, "h3").length, 1);
    assert.equal(byClass(panel, "caption").length, 1);
    assert.equal(byClass(panel, "legend").length, 1);
    const toggle = byClass(panel, "disclosure-toggle")[0];
    assert.equal(toggle.attrs["aria-expanded"], "false", "numbers start collapsed");
    assert.equal(byClass(panel, "disclosure-body")[0].attrs.hidden, "");
  }
  assert.equal(byTag(panels[0], "h3")[0].textContent, "Cost per batch");
  assert.equal(byTag(panels[1], "h3")[0].textContent, "Size calibration");
  assert.match(collectText(byClass(panels[0], "legend")[0]), /claude-haiku-5/);
  assert.match(collectText(byClass(panels[0], "legend")[0]), /claude-sonnet-5-5/);
});

test("cost panel: bars link through core.href; the metric switch redraws", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  const panel = CFQ.core.registered("overviewPanel")[0];
  panel.render(doc, root, ctxFor(fixtureQueue()));
  assert.deepEqual(links(root), ["#/batch/045-2026-09-20-alpha-done", "#/batch/046-2026-09-25-beta-done"]);
  assert.equal(doc.innerHtmlWrites.length, 0);

  const buttons = byTag(byClass(root, "metric-switch")[0], "button");
  assert.deepEqual(buttons.map((b) => b.textContent), ["Turns", "In", "Out"]);
  assert.deepEqual(buttons.map((b) => b.attrs["aria-pressed"]), ["false", "false", "true"]);
  const heightOf = () => findAll(root, (n) => n.tagName === "rect" && svgClass(n).includes("m1")).map((r) => Number(r.attrs.height));
  const outH = heightOf();
  fire(buttons[0], "click");
  assert.deepEqual(buttons.map((b) => b.attrs["aria-pressed"]), ["true", "false", "false"]);
  assert.notDeepEqual(heightOf(), outH);
  assert.equal(byTag(root, "svg").length, 1, "the old chart is replaced, not appended to");
  assert.deepEqual(links(root), ["#/batch/045-2026-09-20-alpha-done", "#/batch/046-2026-09-25-beta-done"]);
});

test("cost panel: global mode prefixes the mirror; the numbers table holds the exact values", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  const ctx = { ...ctxFor(fixtureQueue()), mode: "global", mirror: "demo-1a2b3c" };
  CFQ.core.registered("overviewPanel")[0].render(doc, root, ctx);
  assert.equal(links(root)[0], "#/demo-1a2b3c/batch/045-2026-09-20-alpha-done");
  fire(byClass(root, "disclosure-toggle")[0], "click");
  const cells = byTag(byClass(root, "disclosure-body")[0], "td").map((t) => t.textContent);
  assert.ok(cells.includes("1500000"), "46's exact output, unrounded");
  assert.ok(cells.includes("7000"));
});

test("calibration panel: dots, median labels and the turns/out switch", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  CFQ.core.registered("overviewPanel")[1].render(doc, root, ctxFor(fixtureQueue()));
  assert.equal(findAll(root, (n) => n.tagName === "circle").length, 2);
  const labels = () => findAll(root, (n) => n.tagName === "text" && svgClass(n).includes("median-label")).map((t) => t.textContent);
  assert.deepEqual(labels(), ["median 20 · n=5", "median 40 · n=6"]);
  const buttons = byTag(byClass(root, "metric-switch")[0], "button");
  assert.deepEqual(buttons.map((b) => b.textContent), ["Turns", "Out"]);
  fire(buttons[1], "click");
  assert.deepEqual(labels(), ["median 9k · n=5", "median 20k · n=6"]);
  assert.equal(byTag(root, "svg").length, 1);
  const notes = findAll(root, (n) => n.tagName === "text" && svgClass(n).includes("note"));
  assert.equal(notes.length, 0, "both sizes have n >= 5");
});

test("no cost anywhere: one line instead of two empty charts", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  CFQ.overview.render(doc, root, ctxFor(noCost()));
  const panels = byTag(byClass(root, "panels")[0], "section");
  assert.equal(findAll(root, (n) => n.tagName === "svg").length, 0);
  assert.equal(byTag(root, "h3").length, 0);
  const texts = panels.map((p) => collectText(p).trim()).filter(Boolean);
  assert.deepEqual(texts, ["No cost data recorded yet."]);
});

test("cost but no calibration points: the panel says what is missing", () => {
  const q = fixtureQueue();
  q.sizes = [];
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  CFQ.core.registered("overviewPanel")[1].render(doc, root, ctxFor(q));
  assert.match(collectText(root), /No finished phase with a planned size/);
  assert.equal(findAll(root, (n) => n.tagName === "svg").length, 0);
});

test("overview-charts.js never assigns innerHTML", () => {
  const src = fs.readFileSync(new URL("../../portal/overview-charts.js", import.meta.url), "utf8");
  assert.equal((src.match(/innerHTML *=/g) || []).length, 0);
});
