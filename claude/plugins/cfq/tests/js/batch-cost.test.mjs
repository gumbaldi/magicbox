// Tests for portal/batch-cost.js: the pure row builders, the Cost tab, the per-phase Cost sub-tab,
// the exact-numbers table with its TSV export and the safety rules.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, fire, byTag, byClass, findAll, collectText, links, loadPortal,
  fixtureSite, fixtureBatch,
} from "./helpers.mjs";

const CFQ = loadPortal();
const K = CFQ.batchCost;
const site = fixtureSite();
const FIELDS = ["turns", "input", "output", "cache_read", "cache_creation"];
const LAYERS = ["main", "main_explore", "worker", "worker_explore"];

const add = (a, b) => Object.fromEntries(FIELDS.map((k) => [k, ((a && a[k]) || 0) + ((b && b[k]) || 0)]));

const ZERO = Object.fromEntries(FIELDS.map((f) => [f, 0]));

// The sum of cost objects: total, per model, per layer (with agent counts) and agents.
function sumCostObjs(costs) {
  const total = costs.reduce((n, c) => add(n, c.total), {});
  const byModel = {};
  costs.forEach((c) => Object.keys(c.byModel).forEach((m) => { byModel[m] = add(byModel[m], c.byModel[m]); }));
  const layers = {};
  LAYERS.forEach((l) => {
    layers[l] = { total: {}, byModel: {}, count: 0 };
    costs.forEach((c) => {
      const layer = c.layers[l];
      layers[l].total = add(layers[l].total, layer.total);
      layers[l].count += layer.count;
      Object.keys(layer.byModel).forEach((m) => { layers[l].byModel[m] = add(layers[l].byModel[m], layer.byModel[m]); });
    });
  });
  return { total, byModel, layers, agents: costs.flatMap((c) => c.agents) };
}

// The shared fixture gives every attempt the same cost and the batch a single one; a consistent
// batch has `implementation.cost` equal to the sum of all attempts and `cost` equal to the sum of
// planning and implementation.
function consistentBatch(kind = "done") {
  const batch = fixtureBatch(kind);
  const attempts = batch.phases.flatMap((p) => p.attempts.map((a) => a.cost)).filter(Boolean);
  if (batch.implementation && attempts.length) batch.implementation.cost = sumCostObjs(attempts);
  batch.cost = sumCostObjs([batch.planning && batch.planning.cost].concat(attempts).filter(Boolean));
  return batch;
}

// A batch whose planning cost is what planning really records: the session and one explorer, no
// workers. Every part's output then adds up to the batch's output.
function realisticBatch() {
  const batch = consistentBatch();
  const sonnet = { ...ZERO, turns: 20, input: 300, output: 1000, cache_read: 10000, cache_creation: 800 };
  const haiku = { ...ZERO, turns: 5, input: 100, output: 500, cache_read: 2000, cache_creation: 100 };
  const empty = { total: { ...ZERO }, byModel: {}, count: 0 };
  batch.planning.cost = {
    total: add(sonnet, haiku),
    byModel: { "claude-sonnet-5-5": sonnet, "claude-haiku-5": haiku },
    layers: {
      main: { total: sonnet, byModel: { "claude-sonnet-5-5": sonnet }, count: 1 },
      main_explore: { total: haiku, byModel: { "claude-haiku-5": haiku }, count: 1 },
      worker: empty, worker_explore: empty,
    },
    agents: [{ id: "p1", type: "Explore", description: "Planning search", layer: "main_explore", parent: null, total: haiku, byModel: { "claude-haiku-5": haiku } }],
  };
  batch.cost = sumCostObjs([batch.planning.cost, batch.implementation.cost]);
  return batch;
}

function ctxFor(batch, tab, over) {
  return Object.assign({
    mode: "repo", repo: site.repo, mirror: null, site, batch, setCrumbs() {},
    route: { name: "batch", tab, batch: batch.name, phase: null, mirror: null },
  }, over || {});
}

function renderTab(batch, tab, doc) {
  const d = doc || fakeDoc();
  const root = fakeRoot(d);
  CFQ.batch.render(d, root, ctxFor(batch, tab));
  return { doc: d, root, body: byClass(root, "batch-tab")[0] };
}

const costItem = () => CFQ.core.registered("phaseTab").filter((t) => t.id === "cost")[0];

test("loading batch-cost.js registers the Cost tab (20) and the Cost sub-tab (30)", () => {
  const C = CFQ.core;
  const tab = C.registered("batchTab").filter((t) => t.id === "cost")[0];
  assert.deepEqual([tab.id, tab.label, tab.order], ["cost", "Cost", 20]);
  const sub = costItem();
  assert.deepEqual([sub.id, sub.label, sub.order], ["cost", "Cost", 30]);
  const ids = C.registered("batchTab").map((t) => t.id);
  assert.ok(ids.indexOf("phases") < ids.indexOf("cost") && ids.indexOf("cost") < ids.indexOf("context"));
  const subs = C.registered("phaseTab").map((t) => t.id);
  assert.ok(subs.indexOf("plan") < subs.indexOf("cost") && subs.indexOf("cost") < subs.indexOf("files"));
});

test("costRows: one row per model with all five fields, a totals row equal to cost.total", () => {
  const batch = consistentBatch();
  const rows = K.costRows(batch.cost);
  const models = rows.filter((r) => !r.total);
  assert.deepEqual(models.map((r) => r.model).sort(), ["claude-haiku-5", "claude-sonnet-5-5"]);
  models.forEach((r) => FIELDS.forEach((f) => assert.equal(typeof r[f], "number")));
  const total = rows[rows.length - 1];
  assert.equal(total.total, true);
  FIELDS.forEach((f) => assert.equal(total[f], batch.cost.total[f]));
  FIELDS.forEach((f) => assert.equal(models.reduce((n, r) => n + r[f], 0), total[f]));
  assert.equal(models[0].model, "claude-sonnet-5-5"); // larger output first
  assert.equal(K.costRows(null).length, 1);
});

test("layerRows: four layers in fixed order, an empty one listed, per-model rows nested", () => {
  const batch = consistentBatch();
  const rows = K.layerRows(batch.cost);
  assert.deepEqual(rows.map((r) => r.layer), LAYERS);
  assert.deepEqual(rows.map((r) => r.label), ["Session", "Session explorers", "Workers", "Worker explorers"]);
  assert.equal(rows[1].empty, true);
  assert.equal(rows[1].turns, 0);
  assert.deepEqual(rows[1].models, []);
  assert.equal(rows[0].count, 4);
  assert.equal(rows[0].turns, 80);
  assert.deepEqual(rows[2].models.map((m) => m.model), ["claude-sonnet-5-5"]);
  assert.equal(rows[2].models[0].turns, 160);
  assert.equal(K.layerRows(null).length, 4);
});

test("phaseCostRows: Planning and every phase summed over attempts; the sum equals the batch total", () => {
  const batch = consistentBatch();
  const rows = K.phaseCostRows(batch);
  assert.deepEqual(rows.map((r) => r.label), ["Planning", "01-first", "02-second"]);
  assert.deepEqual(rows.map((r) => r.provisional), [false, false, true]);
  assert.equal(rows[1].total.turns, 75);
  assert.equal(rows[2].total.turns, 150);
  assert.equal(rows[2].byModel["claude-sonnet-5-5"].turns, 120);
  const sum = rows.reduce((n, r) => add(n, r.total), {});
  assert.deepEqual(sum, batch.cost.total);
  const modelSum = rows.reduce((n, r) => add(n, r.byModel["claude-haiku-5"]), {});
  assert.deepEqual(modelSum, batch.cost.byModel["claude-haiku-5"]);
  const noPlanning = fixtureBatch("in_progress");
  assert.deepEqual(K.phaseCostRows(noPlanning).map((r) => r.label), ["01-first"]);
  assert.deepEqual(K.phaseCostRows(fixtureBatch("plan_only")), []);
});

test("exactRows: one row per scope, layer and model; every field sums to the batch total", () => {
  const batch = consistentBatch();
  const rows = K.exactRows(batch);
  const keys = new Set(rows.map((r) => `${r.scope}|${r.layer}|${r.model}`));
  assert.equal(keys.size, rows.length);
  assert.deepEqual([...new Set(rows.map((r) => r.scope))], ["planning", "01-first", "02-second"]);
  assert.ok(rows.every((r) => LAYERS.includes(r.layer)));
  // Three combinations per scope: main/sonnet, worker/sonnet, worker_explore/haiku.
  assert.equal(rows.length, 9);
  FIELDS.forEach((f) => assert.equal(rows.reduce((n, r) => n + r[f], 0), batch.cost.total[f]));
  const retried = rows.filter((r) => r.scope === "02-second" && r.layer === "worker")[0];
  assert.equal(retried.turns, 80); // two attempts of 40
  assert.deepEqual(K.exactRows({ phases: [] }), []);
});

test("toTsv: a header and one tab-separated line per row, no thousands separators", () => {
  const rows = [
    { scope: "planning", layer: "main", model: "m", turns: 1234, input: 1000000, output: 5, cache_read: 123456789, cache_creation: 0 },
    { scope: "01\tx", layer: "worker", model: "n", turns: 1, input: 2, output: 3, cache_read: 4, cache_creation: 5 },
  ];
  const lines = K.toTsv(rows).split("\n");
  assert.equal(lines.length, 3);
  assert.equal(lines[0], "scope\tlayer\tmodel\tturns\tinput\toutput\tcache_read\tcache_creation");
  assert.equal(lines[1], "planning\tmain\tm\t1234\t1000000\t5\t123456789\t0");
  assert.equal(lines[2].split("\t").length, 8); // a tab inside a value cannot add a column
  assert.equal(K.toTsv([]), lines[0]);
});

test("Cost tab: the output bar's parts and their sum equal the batch output, zero parts omitted", () => {
  const batch = realisticBatch();
  const { body } = renderTab(batch, "cost");
  assert.equal(byClass(body, "tile").length, 0);
  assert.equal(byClass(body, "by-model").length, 0);
  assert.equal(byClass(body, "by-layer").length, 0);
  assert.match(collectText(body), /Where the output went/);
  const items = byClass(body, "out-legend-item");
  assert.deepEqual(items.map((i) => collectText(byClass(i, "label")[0])),
    ["Planning session", "Planning explorers", "Orchestrator", "Phase workers", "Worker explorers"]);
  const values = items.map((i) => Number(byClass(i, "v")[0].attrs.title));
  assert.deepEqual(values, [1000, 500, 3000, 12000, 3600]);
  assert.equal(values.reduce((n, v) => n + v, 0), batch.cost.total.output);
  assert.equal(byClass(body, "out-seg").length, 5);
  assert.match(collectText(byClass(body, "out-section")[0]), /250 turns/);

  const parts = K.outputParts(batch);
  assert.deepEqual(parts.map((p) => p.tone), ["p1", "p2", "i1", "i2", "i3"]);
  batch.planning.cost.layers.main_explore.total = { ...ZERO };
  assert.deepEqual(K.outputParts(batch).map((p) => p.label), ["Planning session", "Orchestrator", "Phase workers", "Worker explorers"]);
  batch.phases.forEach((p) => p.attempts.forEach((a) => { a.mode = "classic"; }));
  assert.equal(K.outputParts(batch)[1].label, "Session");
});

test("Cost tab: the planning and implementation tables list the non-empty layers and their totals match", () => {
  const batch = realisticBatch();
  const { body } = renderTab(batch, "cost");
  const plan = byClass(body, "part-plan")[0];
  const impl = byClass(body, "part-impl")[0];
  const labels = (sec) => byClass(sec, "layer-row").map((r) => collectText(byTag(r, "td")[0]).replace(/[▸\s]+/g, " ").trim());
  assert.deepEqual(labels(plan), ["Planning session", "Planning explorers"]);
  assert.deepEqual(labels(impl), ["Orchestrator", "Phase workers ×3", "Worker explorers ×3"]);
  const totals = (sec) => byTag(byClass(sec, "total")[0], "td").map((c) => c.attrs.title);
  const planTotal = totals(plan), implTotal = totals(impl);
  assert.equal(planTotal[4], String(batch.planning.cost.total.output));
  assert.equal(implTotal[4], String(batch.implementation.cost.total.output));
  assert.equal(planTotal[2], String(batch.planning.cost.total.turns));
  assert.equal(implTotal[2], String(batch.implementation.cost.total.turns));
  assert.equal(Number(planTotal[4]) + Number(implTotal[4]), batch.cost.total.output);
  assert.match(collectText(plan), /active · .* calendar/);
  assert.match(collectText(byClass(impl, "layer-row")[0]), /sonnet/);
  assert.match(collectText(byClass(impl, "layer-row")[2]), /haiku/);
  const headers = byTag(byTag(plan, "thead")[0], "th").map((h) => h.textContent);
  assert.deepEqual(headers, ["Part", "Model", "Turns", "In new", "Out", "Cache read"]);
});

test("Cost tab: implementation by phase has no Planning row and compares each phase with its baseline", () => {
  const { body } = renderTab(consistentBatch(), "cost");
  const table = byClass(body, "by-phase")[0];
  assert.equal(byTag(table, "tr").length, 1 + 2);
  assert.doesNotMatch(collectText(table), /Planning/);
  const heads = byTag(byTag(table, "thead")[0], "th").map((h) => h.textContent);
  assert.deepEqual(heads.slice(0, 8), ["#", "Phase", "Size", "Active", "Turns", "Out", "Output by model", "vs. baseline"]);
  const ratios = byClass(table, "ratio");
  assert.deepEqual(ratios.map((c) => collectText(c)), ["1.0×", "2.5×"]);
  assert.equal(byClass(ratios[0], "pill").length, 0);
  assert.equal(byClass(ratios[1], "pill").length, 1);
  assert.ok(links(body).includes("#/batch/047-2026-10-01-demo/phase/02-second"));
  assert.ok(byClass(table, "stackbar").length === 2);

  const bare = consistentBatch();
  bare.phases.forEach((p) => { p.baseline = null; });
  const none = byClass(byClass(renderTab(bare, "cost").body, "by-phase")[0], "ratio");
  assert.deepEqual(none.map((c) => collectText(c)), ["–", "–"]);
});

test("implPhaseRows: ratio, summed active time and the per-model output", () => {
  const rows = K.implPhaseRows(consistentBatch());
  assert.deepEqual(rows.map((r) => r.slug), ["01-first", "02-second"]);
  assert.deepEqual(rows.map((r) => r.ratio), [1, 2.5]);
  assert.equal(rows[0].active, 1500);
  assert.equal(rows[1].active, null, "one attempt has no active_s");
  assert.equal(rows[1].wallclock, 3600);
  assert.equal(rows[1].byModel["claude-sonnet-5-5"], 10000);
  assert.deepEqual(K.implPhaseRows(fixtureBatch("plan_only")), []);
});

test("Cost tab: agents are grouped under Planning and Implementation, workers before their explorers", () => {
  const { body } = renderTab(realisticBatch(), "cost");
  const agents = byClass(body, "agents")[0];
  assert.deepEqual(byClass(agents, "group-row").map((r) => collectText(r)), ["Planning", "Implementation"]);
  assert.equal(byTag(agents, "tr").length, 1 + 2 + 1 + 6);
  assert.deepEqual(byClass(agents, "mono").map((c) => collectText(c)), [
    "Explore", "cfq:cfq-phase-worker", "Explore", "cfq:cfq-phase-worker", "Explore", "cfq:cfq-phase-worker", "Explore",
  ]);
  assert.match(collectText(agents), /Implement phase/);
  assert.match(collectText(agents), /Planning search/);
});

test("Cost tab: a batch with planning telemetry only shows the planning table and says so", () => {
  const batch = realisticBatch();
  batch.implementation = null;
  batch.phases = [];
  batch.cost = batch.planning.cost;
  const { body } = renderTab(batch, "cost");
  assert.equal(byClass(byClass(body, "part-plan")[0], "part-table").length, 1);
  assert.equal(byClass(byClass(body, "part-impl")[0], "part-table").length, 0);
  assert.match(collectText(byClass(body, "part-impl")[0]), /No implementation telemetry yet\./);
  assert.equal(byClass(body, "by-phase").length, 0);
  assert.deepEqual(byClass(byClass(body, "agents")[0], "group-row").map((r) => collectText(r)), ["Planning"]);
  assert.deepEqual(byClass(body, "out-legend-item").map((i) => collectText(byClass(i, "label")[0])), ["Planning session", "Planning explorers"]);
});

test("Cost tab: layer rows expand into their per-model rows with a real button", () => {
  const { body } = renderTab(consistentBatch(), "cost");
  const rows = byClass(body, "nested");
  assert.ok(rows.length >= 3);
  rows.forEach((r) => assert.equal(r.attrs.hidden, ""));
  const toggle = byTag(byClass(body, "layer-row")[0], "button")[0];
  assert.equal(toggle.attrs["aria-expanded"], "false");
  assert.equal(byClass(body, "empty-layer").length, 0, "empty layers are not listed");
  fire(toggle, "click");
  assert.equal(toggle.attrs["aria-expanded"], "true");
  assert.equal(rows.filter((r) => r.attrs.hidden === undefined).length, 1); // only the planning session's model row
  fire(toggle, "click");
  assert.ok(rows.every((r) => r.attrs.hidden === ""));
});

test("Cost tab: the exact numbers render on first open with every figure unrounded, plus a TSV button", () => {
  const batch = consistentBatch();
  const { body } = renderTab(batch, "cost");
  assert.equal(byClass(body, "exact").length, 0);
  const toggle = byTag(body, "button").filter((b) => collectText(b).includes("Exact numbers"))[0];
  assert.equal(toggle.attrs["aria-expanded"], "false");
  fire(toggle, "click");
  const table = byClass(body, "exact")[0];
  assert.equal(byTag(table, "tr").length, 1 + 9);
  const cells = byTag(table, "td").map((c) => c.textContent);
  assert.ok(cells.includes("1700"), "cache creation shown as 1700");
  assert.ok(cells.includes("20000"), "cache read shown as 20000, not 20k");
  const copy = byTag(body, "button").filter((b) => b.textContent === "Copy as TSV")[0];
  assert.ok(copy);
  fire(copy, "click"); // under Node (no clipboard, no window) this does nothing and must not throw
  assert.equal(byTag(body, "textarea")[0].attrs.hidden, "");
  assert.equal(byTag(body, "textarea")[0].value, K.toTsv(K.exactRows(batch)));
});

test("Cost tab: a batch without telemetry says so and shows no table", () => {
  const { body } = renderTab(fixtureBatch("plan_only"), "cost");
  assert.equal(collectText(body).trim(), "No telemetry recorded for this batch.");
  assert.equal(byTag(body, "table").length, 0);
  assert.equal(byClass(body, "tile").length, 0);
});

test("Cost tab: an unsettled attempt marks its phase row and adds one explanatory line", () => {
  const { body } = renderTab(consistentBatch(), "cost");
  assert.equal(byClass(body, "provisional-note").length, 1);
  assert.match(collectText(byClass(body, "provisional-note")[0]), /provisional/);
  const marks = byClass(byClass(body, "by-phase")[0], "provisional");
  assert.equal(marks.length, 1);
  const row = findAll(byClass(body, "by-phase")[0], (n) => n.tagName === "tr" && collectText(n).includes("Second"))[0];
  assert.match(collectText(row), /provisional/);

  const settled = consistentBatch();
  settled.phases.forEach((p) => p.attempts.forEach((a) => { a.settled = true; }));
  const calm = renderTab(settled, "cost").body;
  assert.equal(byClass(calm, "provisional-note").length, 0);
  assert.equal(byClass(calm, "provisional").length, 0);
});

test("phase Cost sub-tab: model and layer tables and the agents of the selected attempt", () => {
  const batch = fixtureBatch("done");
  const phase = batch.phases[1];
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  costItem().render(doc, root, ctxFor(batch, null), phase, phase.attempts[1]);
  assert.equal(byClass(root, "by-model").length, 1);
  assert.equal(byClass(root, "by-layer").length, 1);
  assert.equal(byClass(root, "agents").length, 1);
  assert.equal(byTag(byClass(root, "agents")[0], "tr").length, 1 + 2);
  assert.equal(byClass(root, "provisional-note").length, 1); // attempt 2 is unsettled

  const first = fakeRoot(doc);
  costItem().render(doc, first, ctxFor(batch, null), phase, phase.attempts[0]);
  assert.equal(byClass(first, "provisional-note").length, 0);
});

test("phase Cost sub-tab: no telemetry and no attempt are stated", () => {
  const batch = fixtureBatch("done");
  const phase = batch.phases[0];
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  costItem().render(doc, root, ctxFor(batch, null), phase, Object.assign({}, phase.attempts[0], { cost: null }));
  assert.equal(collectText(root).trim(), "No telemetry recorded for this attempt.");
  assert.equal(byTag(root, "table").length, 0);
  const none = fakeRoot(doc);
  costItem().render(doc, none, ctxFor(batch, null), phase, null);
  assert.equal(collectText(none).trim(), "Not started.");
});

test("the Cost sub-tab is reachable through the phase detail", () => {
  const batch = fixtureBatch("done");
  const { root } = renderTab(batch, null);
  const toggle = byClass(byClass(root, "phase-row")[0], "disclosure-toggle")[0];
  fire(toggle, "click");
  const sub = byClass(root, "subtab").filter((b) => b.textContent === "Cost")[0];
  assert.ok(sub);
  fire(sub, "click");
  assert.equal(byClass(byClass(root, "detail-body")[0], "by-model").length, 1);
});

test("agent descriptions and model names containing markup never reach innerHTML", () => {
  const batch = consistentBatch();
  batch.cost.agents[0].description = "<script>alert(1)</script>";
  batch.cost.agents[0].type = "<img src=x onerror=alert(1)>";
  const doc = fakeDoc();
  const { body } = renderTab(batch, "cost", doc);
  assert.match(collectText(byClass(body, "agents")[0]), /<script>alert\(1\)<\/script>/);
  assert.ok(doc.innerHtmlWrites.every((w) => !w.value.includes("<script>") && !w.value.includes("<img")));
  assert.equal(byTag(body, "script").length, 0);
});
