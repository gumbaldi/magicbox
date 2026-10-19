// Tests for portal/overview.js: KPI tiles, ordering, sorting, filtering and the rendered tabs.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, fire, byTag, byClass, findAll, collectText, collectHtml, links, loadPortal,
  fixtureSite, fixtureQueue,
} from "./helpers.mjs";

const CFQ = loadPortal();
const O = CFQ.overview;
const queue = fixtureQueue();
const names = (rows) => rows.map((r) => r.name);

function ctxFor(over) {
  return Object.assign({
    mode: "repo", repo: "/home/code/git/demo", mirror: null, site: fixtureSite(), queue,
    route: { name: "overview", tab: "batches", mirror: null }, setCrumbs() {},
  }, over || {});
}

function draw(over, doc) {
  const d = doc || fakeDoc();
  const root = fakeRoot(d);
  O.render(d, root, ctxFor(over));
  return { doc: d, root };
}

test("kpis: eight tiles from queue.totals only", () => {
  const tiles = O.kpis({ totals: queue.totals, batches: [], entries: [] });
  assert.deepEqual(tiles.map((t) => t.label), [
    "In progress", "Planned", "Done", "Open todos", "Plan inbox", "Flags", "Deviations", "Tokens"]);
  const by = Object.fromEntries(tiles.map((t) => [t.id, t]));
  assert.equal(by.inProgress.value, 1);
  assert.equal(by.planned.value, 4);
  assert.equal(by.done.value, 2);
  assert.equal(by.todos.value, 2);
  assert.equal(by.planEntries.value, 1);
  assert.equal(by.flags.value, 1);
  assert.equal(by.deviations.value, queue.totals.deviations);
  const cost = queue.totals.cost;
  assert.match(by.tokens.value, / \/ /);
  assert.equal(by.tokens.sub, `${cost.turns.toLocaleString()} turns`);
  assert.equal(O.kpis(null).length, 8);
});

test("defaultOrder: active first by status, then done by finish date, newest first", () => {
  const shuffled = [...queue.batches].reverse();
  assert.deepEqual(names(O.defaultOrder(shuffled)), [
    "047-2026-10-01-gamma-progress",
    "048-2026-10-03-delta-review",
    "050-2026-10-06-zeta-blocked",
    "049-2026-10-05-epsilon-planned",
    "051-2026-10-07-eta-planning",
    "046-2026-09-25-beta-done",
    "045-2026-09-20-alpha-done",
  ]);
  const tie = [
    { name: "a", status: "done", finished: "2026-01-01T00:00:00Z" },
    { name: "b", status: "done", finished: "2026-01-01T00:00:00Z" },
  ];
  assert.deepEqual(names(O.defaultOrder(tie)), ["b", "a"]);
});

test("sortBatches: every key, both directions, rows without cost last", () => {
  const rows = queue.batches;
  assert.deepEqual(names(O.sortBatches(rows, "name", "asc")).slice(0, 2), ["045-2026-09-20-alpha-done", "046-2026-09-25-beta-done"]);
  assert.equal(names(O.sortBatches(rows, "name", "desc"))[0], "051-2026-10-07-eta-planning");
  assert.equal(O.sortBatches(rows, "status", "asc")[0].status, "in_progress");
  assert.equal(O.sortBatches(rows, "status", "desc")[0].status, "done");
  const fin = O.sortBatches(rows, "finished", "desc");
  assert.equal(fin[0].name, "046-2026-09-25-beta-done");
  assert.equal(O.sortBatches(rows, "finished", "asc")[0].name, "045-2026-09-20-alpha-done");
  for (const key of ["turns", "in", "out"]) {
    for (const dir of ["asc", "desc"]) {
      const sorted = O.sortBatches(rows, key, dir);
      assert.equal(sorted[sorted.length - 1].cost, null, `${key} ${dir}: no-cost row last`);
    }
  }
  assert.equal(O.sortBatches(rows, "turns", "desc")[0].name, "045-2026-09-20-alpha-done");
  assert.equal(O.sortBatches(rows, "out", "desc")[0].name, "046-2026-09-25-beta-done");
  assert.equal(O.sortBatches(rows, "deviations", "desc")[0].deviations, 2);
  assert.equal(O.sortBatches(rows, "flags", "desc")[0].name, "045-2026-09-20-alpha-done");
  assert.equal(O.sortBatches(rows, "flags", "asc").at(-1).name, "045-2026-09-20-alpha-done");
  assert.deepEqual(names(rows), names(fixtureQueue().batches), "the input is not mutated");
});

test("filterBatches: query over number, title and goal; four groups", () => {
  const rows = queue.batches;
  assert.deepEqual(names(O.filterBatches(rows, { query: "049" })), ["049-2026-10-05-epsilon-planned"]);
  assert.deepEqual(names(O.filterBatches(rows, { query: "GAMMA" })), ["047-2026-10-01-gamma-progress"]);
  assert.deepEqual(names(O.filterBatches(rows, { query: "gamma goal" })), ["047-2026-10-01-gamma-progress"], "tags in goalHtml are ignored");
  assert.deepEqual(names(O.filterBatches(rows, { query: "goal of beta" })), ["046-2026-09-25-beta-done"]);
  assert.equal(O.filterBatches(rows, { query: "nothing like this" }).length, 0);
  assert.equal(O.filterBatches(rows, { group: "all" }).length, 7);
  assert.equal(O.filterBatches(rows, { group: "active" }).length, 5);
  assert.equal(O.filterBatches(rows, { group: "done" }).length, 2);
  assert.deepEqual(names(O.filterBatches(rows, { group: "flagged" })), ["045-2026-09-20-alpha-done"]);
  assert.deepEqual(names(O.filterBatches(rows, { group: "active", query: "eta planning" })), ["051-2026-10-07-eta-planning"]);
});

test("render: every batch has a title and a link; a missing cost says why", () => {
  const { root } = draw();
  const text = collectText(root);
  for (const b of queue.batches) {
    assert.ok(text.includes(b.title), b.title);
    assert.ok(links(root).includes(`#/batch/${b.name}`), b.name);
  }
  const row = byTag(root, "tr").find((tr) => collectText(tr).includes("eta planning"));
  const dashes = findAll(row, (n) => n.tagName === "td" && n.textContent === "–" && n.attrs.title === "no telemetry recorded");
  assert.equal(dashes.length, 3, "turns, in and out each say that no telemetry was recorded");
  const done = byTag(root, "tr").find((tr) => collectText(tr).includes("alpha done"));
  assert.ok(collectText(done).includes("merged"));
  assert.ok(findAll(done, (n) => n.className && n.className.includes("flag-warn")).length === 1);
});

test("render: a goal reaches the DOM only through html() as the escaped goalHtml", () => {
  const evil = fixtureQueue();
  evil.batches[2].goalHtml = "&lt;script&gt;alert(1)&lt;/script&gt; and <code>ok</code>";
  const { doc, root } = draw({ queue: evil });
  assert.ok(!collectText(root).includes("<script>"));
  const goal = byClass(root, "goal").find((n) => n.innerHTML.includes("alert"));
  assert.ok(goal);
  assert.equal(goal.innerHTML, evil.batches[2].goalHtml);
  const writes = doc.innerHtmlWrites.map((w) => w.value);
  assert.deepEqual(writes.sort(), evil.batches.map((b) => b.goalHtml).filter(Boolean).sort());
  assert.deepEqual(collectHtml(root).sort(), writes);
});

test("render: an empty queue shows the empty state, not an empty table", () => {
  const empty = { repo: "r", totals: { batches: { inProgress: 0, planned: 0, done: 0 }, todos: 0, planEntries: 0, deviations: 0, flags: { warn: 0, info: 0 }, cost: { turns: 0, input: 0, output: 0, cache_read: 0, cache_creation: 0 } }, baselines: {}, sizes: [], batches: [], entries: [] };
  const { root } = draw({ queue: empty });
  assert.equal(byTag(root, "table").length, 0);
  assert.match(collectText(root), /No batches yet/);
  assert.equal(byClass(root, "kpi").length, 8, "the KPI strip still renders");
  const missing = draw({ queue: null });
  assert.match(collectText(missing.root), /No queue data/);
});

test("render: the KPI strip shows eight tiles and the tabs carry counts from queue.entries", () => {
  const { root } = draw();
  assert.equal(byClass(root, "kpi").length, 8);
  const tabs = byTag(byClass(root, "tabs")[0], "a");
  assert.deepEqual(tabs.map((a) => a.textContent), ["Batches", "Todos (2)", "Plan inbox (1)", "Archive (2)"]);
  assert.deepEqual(tabs.map((a) => a.attrs.href), ["#/", "#/todos", "#/inbox", "#/archive"]);
  assert.equal(tabs[0].attrs["aria-current"], "page");
});

test("tabs: todos, inbox and archive render their entry rows with entry links", () => {
  const todos = draw({ route: { name: "overview", tab: "todos" } }).root;
  assert.deepEqual(links(todos).filter((h) => h.startsWith("#/entry/")),
    ["#/entry/todo-2026-10-02-plain", "#/entry/todo-2026-10-01-merge-alpha"], "newest first");
  assert.equal(byTag(todos, "code").some((c) => c.textContent === "cfq/045-2026-09-20-alpha-done"), true, "backtick spans render as code");
  assert.ok(links(todos).includes("#/batch/045-2026-09-20-alpha-done"), "origin links to its batch");
  assert.ok(links(todos).includes("#/batch/045-2026-09-20-alpha-done/phase/02-second"));
  assert.equal(byTag(todos, "table").length, 1);
  assert.ok(!collectText(todos).includes("Parked into"));

  const inbox = draw({ route: { name: "overview", tab: "inbox" } }).root;
  assert.deepEqual(links(inbox).filter((h) => h.startsWith("#/entry/")), ["#/entry/plan-2026-10-03-inbox"]);

  const archive = draw({ route: { name: "overview", tab: "archive" } }).root;
  assert.deepEqual(links(archive).filter((h) => h.startsWith("#/entry/")),
    ["#/entry/plan-2026-09-28-parked", "#/entry/todo-2026-09-26-closed"]);
  const text = collectText(archive);
  for (const head of ["Kind", "Closed", "Parked into"]) assert.ok(text.includes(head), head);
  assert.ok(links(archive).includes("#/batch/049-2026-10-05-epsilon-planned"), "parked into links to the batch");

  const bare = { ...queue, entries: [] };
  assert.match(collectText(draw({ queue: bare, route: { name: "overview", tab: "todos" } }).root), /No open todos/);
});

test("global mode builds every link through the mirror", () => {
  const { root } = draw({ mode: "global", mirror: "alpha", site: fixtureSite("global"), route: { name: "overview", tab: "batches", mirror: "alpha" } });
  assert.ok(links(root).includes("#/alpha/batch/045-2026-09-20-alpha-done"));
  const tabLinks = byTag(byClass(root, "tabs")[0], "a").map((a) => a.attrs.href);
  assert.deepEqual(tabLinks, ["#/alpha/", "#/alpha/todos", "#/alpha/inbox", "#/alpha/archive"]);
  const crumbs = [];
  O.render(fakeDoc(), fakeRoot(), ctxFor({ mode: "global", mirror: "alpha", setCrumbs: (c) => crumbs.push(...c) }));
  assert.deepEqual(crumbs.map((c) => c.label), ["All repos", "alpha"]);
});

test("panels: registered overviewPanel items render above the toolbar, in order", () => {
  const cfq = loadPortal();
  const none = fakeRoot();
  cfq.overview.render(fakeDoc(), none, ctxFor());
  assert.equal(byClass(none, "panels").length, 0);

  const doc = fakeDoc();
  cfq.core.register("overviewPanel", { id: "calibration", order: 20, render: (d, r) => r.appendChild(cfq.core.el(d, "p", "second panel")) });
  cfq.core.register("overviewPanel", { id: "cost", order: 10, render: (d, r) => r.appendChild(cfq.core.el(d, "p", "first panel")) });
  const root = fakeRoot(doc);
  cfq.overview.render(doc, root, ctxFor());
  const text = collectText(root);
  assert.ok(text.indexOf("first panel") < text.indexOf("second panel"));
  const kids = root.children;
  const panelsAt = kids.findIndex((c) => c.className === "panels");
  const toolbarAt = kids.findIndex((c) => c.className === "toolbar");
  assert.ok(panelsAt !== -1 && panelsAt < toolbarAt);

  const tab = fakeRoot(doc);
  cfq.overview.render(doc, tab, ctxFor({ route: { name: "overview", tab: "todos" } }));
  assert.equal(byClass(tab, "panels").length, 0, "panels belong to the Batches tab only");
});

test("toolbar: search, chips and sorting redraw the table; / focuses the search field", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  O.render(doc, root, ctxFor());
  const rowNames = () => byTag(root, "tr").filter((tr) => byClass(tr, "rowlink").length).map((tr) => byClass(tr, "rowlink")[0].attrs.href);
  assert.equal(rowNames().length, 7);
  assert.equal(rowNames()[0], "#/batch/047-2026-10-01-gamma-progress", "default order: active first");

  const search = byTag(root, "input")[0];
  search.value = "alpha";
  fire(search, "input");
  assert.deepEqual(rowNames(), ["#/batch/045-2026-09-20-alpha-done"]);
  search.value = "";
  fire(search, "input");

  const chip = (label) => byClass(root, "chip").find((c) => c.textContent.startsWith(label));
  fire(chip("Done"), "click");
  assert.equal(rowNames().length, 2);
  assert.equal(chip("Done").attrs["aria-pressed"], "true");
  assert.equal(chip("All").attrs["aria-pressed"], "false");
  fire(chip("Flagged"), "click");
  assert.equal(rowNames().length, 1);
  fire(chip("All"), "click");

  const sortButton = (label) => byClass(root, "sort").find((b) => b.textContent.startsWith(label));
  fire(sortButton("Out"), "click");
  assert.equal(rowNames()[0], "#/batch/046-2026-09-25-beta-done", "descending by output first");
  assert.equal(rowNames().at(-1), "#/batch/051-2026-10-07-eta-planning", "no telemetry last");
  assert.equal(sortButton("Out").parentNode.attrs["aria-sort"], "descending");
  fire(sortButton("Out"), "click");
  assert.equal(sortButton("Out").parentNode.attrs["aria-sort"], "ascending");
  assert.equal(rowNames().at(-1), "#/batch/051-2026-10-07-eta-planning", "no telemetry last in either direction");

  search.value = "zzz";
  fire(search, "input");
  assert.match(collectText(root), /No batch matches the filter/);

  const ev = fire(doc, "keydown", { key: "/", target: root });
  assert.equal(search.focused, true);
  assert.equal(ev.prevented, true);
  search.focused = false;
  fire(doc, "keydown", { key: "/", target: search });
  assert.equal(search.focused, false, "typing / inside a field is left alone");

  O.render(doc, fakeRoot(doc), ctxFor());
  assert.equal(doc.listeners.keydown.length, 1, "one slash handler per document");
});

test("rows follow their link on click except on inner links", () => {
  const root = draw().root;
  const tr = byTag(root, "tr").find((r) => byClass(r, "rowlink").length);
  globalThis.location = { hash: "" };
  try {
    fire(tr, "click", { target: tr });
    assert.equal(globalThis.location.hash, tr.children[1].children[0].attrs.href);
    globalThis.location.hash = "";
    const a = byClass(tr, "rowlink")[0];
    a.closest = () => a;
    fire(tr, "click", { target: a });
    assert.equal(globalThis.location.hash, "", "the link itself handles its own click");
  } finally {
    delete globalThis.location;
  }
});
