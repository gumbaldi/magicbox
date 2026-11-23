// Tests for portal/overview.js: the Now, Needs attention and Last 10 sections, ordering, sorting,
// filtering, the batch table and the rendered tabs.

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

test("defaultOrder: active first by status, then done by finish date, newest first", () => {
  const shuffled = [...queue.batches].reverse();
  assert.deepEqual(names(O.defaultOrder(shuffled)), [
    "047-2026-10-01-gamma-progress",
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
  for (const key of ["planning", "implementation"]) {
    for (const dir of ["asc", "desc"]) {
      const sorted = O.sortBatches(rows, key, dir);
      assert.equal(sorted[sorted.length - 1].cost, null, `${key} ${dir}: no-cost row last`);
    }
  }
  const custom = fixtureQueue();
  custom.batches[0].cost.planning = { ...custom.batches[0].cost.planning, total: { ...custom.batches[0].cost.planning.total, output: 900 } };
  assert.equal(O.sortBatches(custom.batches, "planning", "desc")[0].name, "045-2026-09-20-alpha-done", "orders by cost.planning.total.output");
  assert.equal(O.sortBatches(custom.batches, "planning", "asc").at(-2).name, "045-2026-09-20-alpha-done", "ascending: the largest before the no-cost row");
  assert.equal(O.sortBatches(rows, "implementation", "desc")[0].name, "046-2026-09-25-beta-done");
  assert.equal(O.sortBatches(rows, "implementation", "asc").at(-2).name, "046-2026-09-25-beta-done");
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
  assert.equal(O.filterBatches(rows, { group: "all" }).length, 6);
  assert.equal(O.filterBatches(rows, { group: "active" }).length, 4);
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
  assert.equal(dashes.length, 2, "planning and implementation each say that no telemetry was recorded");
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
  assert.match(collectText(root), /Nothing running\. Next: none queued\./);
  assert.match(collectText(root), /Nothing needs attention\./);
  assert.equal(byClass(root, "recent").length, 0);
  const missing = draw({ queue: null });
  assert.match(collectText(missing.root), /No queue data/);
});

test("render: the tabs carry counts from queue.entries and there is no KPI strip", () => {
  const { root } = draw();
  assert.equal(byClass(root, "kpi").length, 0);
  assert.equal(byClass(root, "kpis").length, 0);
  const tabs = byTag(byClass(root, "tabs")[0], "a");
  assert.deepEqual(tabs.map((a) => a.textContent), ["Batches", "Trends", "Todos (2)", "Plan inbox (1)", "Archive (2)"]);
  assert.deepEqual(tabs.map((a) => a.attrs.href), ["#/", "#/trends", "#/todos", "#/inbox", "#/archive"]);
  assert.equal(tabs[0].attrs["aria-current"], "page");
});

test("render: sections come in the order Now, Needs attention, Last 10 batches, tabs", () => {
  const { root } = draw();
  const classes = root.children.map((c) => c.className);
  assert.deepEqual(classes.slice(0, 3), ["now", "attention", "recent"]);
  assert.equal(classes[3], "tabs");
  const heads = root.children.slice(0, 3).map((c) => byTag(c, "h2")[0].textContent);
  assert.deepEqual(heads, ["Now", "Needs attention", "Last 2 batches"]);
});

const longNow = () => [
  { batch: "118-2026-11-01-docs", number: 118, title: "Document templates", status: "in_progress",
    phases: { done: 3, total: 7, skipped: 0, error: 0 }, current: { num: 4, title: "Bulk import" }, waitsOn: [] },
  { batch: "119-2026-11-02-calendar", number: 119, title: "Calendar sync", status: "planning",
    phases: { done: 0, total: 5, skipped: 0, error: 0 }, current: null, waitsOn: [] },
  { batch: "120-2026-11-03-audit", number: 120, title: "Audit export", status: "blocked",
    phases: { done: 0, total: 2, skipped: 0, error: 0 }, current: null, waitsOn: ["118-2026-11-01-docs"] },
];

test("Now: a running batch with progress, a planning item and a waiting item; the empty state", () => {
  const q = fixtureQueue();
  q.now = longNow();
  const { root } = draw({ queue: q });
  const now = byClass(root, "now")[0];
  const items = byClass(now, "item");
  assert.equal(items.length, 3);
  assert.deepEqual(items.map((i) => byClass(i, "dot")[0].className), ["dot run", "dot review", "dot wait"]);
  const subs = items.map((i) => collectText(byClass(i, "sub")[0]).trim());
  assert.equal(subs[0], "Phase 04 of 07 running · Bulk import");
  assert.equal(subs[1], "Planning in progress");
  assert.equal(subs[2], "Queued · waits on 118");
  assert.equal(collectText(byClass(items[0], "prog")[0]).trim(), "3/7");
  assert.equal(byClass(items[1], "prog").length, 0, "only a running batch gets a progress bar");
  assert.equal(byClass(items[0], "bar")[0].children[0].style.width, "43%");
  assert.deepEqual(links(now), [
    "#/batch/118-2026-11-01-docs", "#/batch/119-2026-11-02-calendar", "#/batch/120-2026-11-03-audit"]);
  assert.match(collectText(items[0]), /118 · Document templates/);
  assert.deepEqual(items.slice(1).map((i) => collectText(byClass(i, "pill")[0])), ["planning", "blocked"]);

  q.now = [];
  const empty = byClass(draw({ queue: q }).root, "now")[0];
  assert.match(collectText(empty), /Nothing running\. Next: none queued\./);
  assert.equal(byClass(empty, "item").length, 0);
});

test("renders_stale_awaiting_review_payload_as_planning", () => {
  const q = fixtureQueue();
  q.batches[2].status = "awaiting_review";
  q.now = [{ batch: "119-2026-11-02-calendar", number: 119, title: "Calendar sync", status: "awaiting_review",
    phases: { done: 0, total: 5, skipped: 0, error: 0 }, current: null, waitsOn: [] }];
  q.attention.push({ level: "plan", code: "review", batch: "049-2026-10-05-epsilon-planned", phase: null, text: "plan review open" });
  const { root } = draw({ queue: q });
  const item = byClass(byClass(root, "now")[0], "item")[0];
  assert.equal(byClass(item, "dot")[0].className, "dot review");
  assert.equal(collectText(byClass(item, "sub")[0]).trim(), "Planning in progress");
  assert.equal(collectText(byClass(item, "pill")[0]), "planning");
  const row = byTag(root, "tr").find((tr) => collectText(tr).includes(q.batches[2].title));
  assert.equal(collectText(byClass(row, "pill")[0]).trim().replace(/^\S+\s*/, ""), "Planning");
  assert.equal(byClass(byClass(root, "attention")[0], "item").length, 3);
});

test("Needs attention: warn and plan items link to their batch and phase; the empty state", () => {
  const { root } = draw();
  const sec = byClass(root, "attention")[0];
  const items = byClass(sec, "item");
  assert.equal(items.length, 2);
  assert.deepEqual(items.map((i) => byClass(i, "sev")[0].className), ["sev warn", "sev plan"]);
  assert.deepEqual(links(items[0]), ["#/batch/047-2026-10-01-gamma-progress", "#/batch/047-2026-10-01-gamma-progress/phase/01-a"]);
  assert.match(collectText(byClass(items[0], "t")[0]), /047\s+\/ 01 · A/);
  assert.equal(collectText(byClass(items[0], "sub")[0]).trim(), "phase is red");
  assert.equal(collectText(byClass(items[0], "pill")[0]), "red");
  assert.deepEqual(links(items[1]), ["#/batch/049-2026-10-05-epsilon-planned"]);
  assert.match(collectText(byClass(items[1], "t")[0]), /049 · epsilon planned/);
  assert.equal(collectText(byClass(items[1], "pill")[0]), "audit");

  const more = fixtureQueue();
  more.attention.push({ code: "more", text: "3 more" });
  const withMore = byClass(draw({ queue: more }).root, "attention")[0];
  assert.equal(byClass(withMore, "item").length, 2);
  assert.equal(collectText(byClass(withMore, "more")[0]).trim(), "3 more");

  const none = fixtureQueue();
  none.attention = [];
  assert.match(collectText(byClass(draw({ queue: none }).root, "attention")[0]), /Nothing needs attention\./);
});

test("Last 10 batches: planning and implementation cards with outputs and shares; absent without recent", () => {
  const q = fixtureQueue();
  q.recent.planning.total = { turns: 100, input: 0, output: 30000, cache_read: 0, cache_creation: 0 };
  q.recent.implementation.total = { turns: 250, input: 0, output: 70000, cache_read: 0, cache_creation: 0 };
  q.recent.planning.medianOutput = 12000;
  q.recent.implementation.outputPerPhase = 8000;
  q.recent.implementation.phases = 4;
  const { root } = draw({ queue: q });
  const sec = byClass(root, "recent")[0];
  const cards = byClass(sec, "part");
  assert.equal(cards.length, 2);
  const [plan, impl] = cards;
  assert.match(collectText(byClass(plan, "part-head")[0]), /Planning\s+30 %/);
  assert.match(collectText(byClass(impl, "part-head")[0]), /Implementation\s+70 %/);
  const fact = (card, k) => collectText(byClass(card, "fact").find((f) => collectText(byClass(f, "k")[0]).trim() === k)).replace(/\s+/g, " ").trim();
  assert.match(fact(plan, "Output"), /30k/);
  assert.match(fact(impl, "Output"), /70k/);
  assert.match(fact(plan, "Turns"), /100/);
  assert.match(fact(impl, "Turns"), /250/);
  assert.match(fact(plan, "Active"), /≈ 30m calendar 2h 00m/);
  assert.match(fact(plan, "Median / batch"), /12k/);
  assert.match(fact(impl, "Median / phase"), /8k 4 phases/);
  assert.deepEqual(byClass(plan, "mchip").map((c) => collectText(c).trim()), ["sonnet"]);
  assert.deepEqual(byClass(impl, "mchip").map((c) => collectText(c).trim()).sort(), ["haiku", "sonnet"]);
  const bar = byClass(sec, "sharebar")[0];
  assert.deepEqual(bar.children.map((c) => c.style.width), ["30%", "70%"]);

  const without = fixtureQueue();
  delete without.recent;
  assert.equal(byClass(draw({ queue: without }).root, "recent").length, 0);
  without.recent = { ...q.recent, batches: [] };
  assert.equal(byClass(draw({ queue: without }).root, "recent").length, 0);
});

test("table: the new columns, no Dev column, tooltip with turns, input and cache read", () => {
  const { root } = draw();
  const heads = byTag(byTag(root, "thead")[0], "th").map((th) => collectText(th).replace(/[▲▼]/g, "").trim());
  assert.deepEqual(heads, ["#", "Batch", "Status", "Phases", "Finished", "Planning", "Implementation", "Flags", "Merge"]);
  const row = byTag(root, "tr").find((tr) => collectText(tr).includes("alpha done"));
  const cells = byTag(row, "td");
  const planning = cells[5], impl = cells[6];
  assert.match(collectText(planning), /500/);
  assert.match(collectText(planning), /≈ 15m/, "active time under the planning output");
  assert.match(planning.attrs.title, /10 turns · 400 input new · 2,?000 cache read/);
  assert.match(collectText(impl), /8\.5k/);
  const mini = byClass(impl, "mini")[0];
  assert.deepEqual(mini.children.map((c) => c.style.width), ["6%", "94%"], "planning share of the output");
});

test("Flagged chip counts the rows with a warn flag", () => {
  const { root } = draw();
  const chip = byClass(root, "chip").find((c) => c.textContent.startsWith("Flagged"));
  const warnRows = queue.batches.filter((b) => b.flags.warn > 0).length;
  assert.equal(chip.textContent, `Flagged (${warnRows})`);
});

test("Trends: both panels render there and not on the Batches tab", () => {
  const trends = draw({ route: { name: "overview", tab: "trends" } }).root;
  assert.equal(byClass(trends, "panels").length, 1);
  assert.equal(byClass(trends, "panel-cost").length, 1);
  assert.equal(byClass(trends, "panel-calibration").length, 1);
  assert.equal(byClass(trends, "batches").length, 0, "no batch table");
  assert.equal(byTag(byClass(trends, "tabs")[0], "a").find((a) => a.textContent === "Trends").attrs["aria-current"], "page");
  const batches = draw().root;
  assert.equal(byClass(batches, "panels").length, 0);
  assert.equal(byTag(batches, "svg").length, 0);
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
  assert.deepEqual(tabLinks, ["#/alpha/", "#/alpha/trends", "#/alpha/todos", "#/alpha/inbox", "#/alpha/archive"]);
  const crumbs = [];
  O.render(fakeDoc(), fakeRoot(), ctxFor({ mode: "global", mirror: "alpha", setCrumbs: (c) => crumbs.push(...c) }));
  assert.deepEqual(crumbs.map((c) => c.label), ["All repos", "alpha"]);
});

test("trends: registered overviewPanel items render in order on the Trends tab", () => {
  const cfq = loadPortal();
  const doc = fakeDoc();
  cfq.core.register("overviewPanel", { id: "calibration", order: 20, render: (d, r) => r.appendChild(cfq.core.el(d, "p", "second panel")) });
  cfq.core.register("overviewPanel", { id: "cost", order: 10, render: (d, r) => r.appendChild(cfq.core.el(d, "p", "first panel")) });
  const root = fakeRoot(doc);
  cfq.overview.render(doc, root, ctxFor({ route: { name: "overview", tab: "trends" } }));
  const text = collectText(root);
  assert.ok(text.indexOf("first panel") < text.indexOf("second panel"));
  const kids = root.children;
  const tabsAt = kids.findIndex((c) => c.className === "tabs");
  const panelsAt = kids.findIndex((c) => c.className.startsWith("panels"));
  assert.ok(tabsAt !== -1 && tabsAt < panelsAt);

  const tab = fakeRoot(doc);
  cfq.overview.render(doc, tab, ctxFor({ route: { name: "overview", tab: "todos" } }));
  assert.equal(byClass(tab, "panels").length, 0, "panels belong to the Trends tab only");
});

test("toolbar: search, chips and sorting redraw the table", () => {
  CFQ.state.query = "";
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  O.render(doc, root, ctxFor());
  const rowNames = () => byTag(root, "tr").filter((tr) => byClass(tr, "rowlink").length).map((tr) => byClass(tr, "rowlink")[0].attrs.href);
  assert.equal(rowNames().length, 6);
  assert.equal(rowNames()[0], "#/batch/047-2026-10-01-gamma-progress", "default order: active first");

  assert.equal(byTag(root, "input").length, 0, "the search field lives in the top bar");
  CFQ.state.query = "alpha";
  CFQ.state.onQuery();
  assert.deepEqual(rowNames(), ["#/batch/045-2026-09-20-alpha-done"]);
  CFQ.state.query = "";
  CFQ.state.onQuery();

  const chip = (label) => byClass(root, "chip").find((c) => c.textContent.startsWith(label));
  fire(chip("Done"), "click");
  assert.equal(rowNames().length, 2);
  assert.equal(chip("Done").attrs["aria-pressed"], "true");
  assert.equal(chip("All").attrs["aria-pressed"], "false");
  fire(chip("Flagged"), "click");
  assert.equal(rowNames().length, 1);
  fire(chip("All"), "click");

  const sortButton = (label) => byClass(root, "sort").find((b) => b.textContent.startsWith(label));
  fire(sortButton("Implementation"), "click");
  assert.equal(rowNames()[0], "#/batch/046-2026-09-25-beta-done", "descending by implementation output first");
  assert.equal(rowNames().at(-1), "#/batch/051-2026-10-07-eta-planning", "no telemetry last");
  assert.equal(sortButton("Implementation").parentNode.attrs["aria-sort"], "descending");
  fire(sortButton("Implementation"), "click");
  assert.equal(sortButton("Implementation").parentNode.attrs["aria-sort"], "ascending");
  assert.equal(rowNames().at(-1), "#/batch/051-2026-10-07-eta-planning", "no telemetry last in either direction");

  CFQ.state.query = "zzz";
  CFQ.state.onQuery();
  assert.match(collectText(root), /No batch matches the filter/);
  CFQ.state.query = "";
  CFQ.state.onQuery = null;
});

test("the shared query pre-filters the overview and the top bar's hook redraws it", () => {
  const doc = fakeDoc();
  CFQ.state.query = "alpha";
  const root = fakeRoot(doc);
  O.render(doc, root, ctxFor());
  const rowNames = () => byTag(root, "tr").filter((tr) => byClass(tr, "rowlink").length).map((tr) => byClass(tr, "rowlink")[0].attrs.href);
  assert.deepEqual(rowNames(), ["#/batch/045-2026-09-20-alpha-done"], "the initial filter applies");

  CFQ.state.query = "beta";
  CFQ.state.onQuery();
  assert.deepEqual(rowNames(), ["#/batch/046-2026-09-25-beta-done"]);
  assert.equal(doc.listeners.keydown, undefined, "the / handler lives in app.js");

  O.render(doc, fakeRoot(doc), ctxFor({ route: { name: "overview", tab: "trends" } }));
  assert.equal(CFQ.state.onQuery, null, "a tab without the table drops the hook");
  CFQ.state.query = "";
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

test("phases cell: skipped and error phases are named, an ordinary row is unchanged", () => {
  const custom = JSON.parse(JSON.stringify(queue));
  const gamma = custom.batches.find((r) => r.name === "047-2026-10-01-gamma-progress");
  const epsilon = custom.batches.find((r) => r.name === "049-2026-10-05-epsilon-planned");
  gamma.phases = { done: 1, total: 4, skipped: 1, error: 0 };
  epsilon.phases = { done: 0, total: 4, skipped: 0, error: 1 };
  const { root } = draw({ queue: custom });
  const cells = byClass(root, "phases").filter((n) => n.tagName === "td").map((td) => collectText(td).trim());
  assert.ok(cells.includes("1/4 · 1 skipped"), cells.join("|"));
  assert.ok(cells.includes("0/4 · 1 error"), cells.join("|"));
  assert.ok(cells.includes("2/2"), cells.join("|"));
  assert.ok(cells.includes("0/1"), cells.join("|"));
});
