// Tests for portal/core.js (routing, paths, DOM helpers, formatting, slots) and portal/app.js's
// route dispatch. Fake DOM and fixtures live in helpers.mjs.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, fire, byTag, byClass, collectText, collectHtml, loadPortal, withClipboard,
  fixtureSite, fixtureQueue, fixtureBatch, fixtureEntry, fixtureRepos,
} from "./helpers.mjs";

const CFQ = loadPortal();
const C = CFQ.core;

// ---- routes -------------------------------------------------------------------------------

test("parseRoute: repo mode routes", () => {
  const r = (h) => C.parseRoute(h, "repo");
  assert.deepEqual([r("").name, r("").tab], ["overview", "batches"]);
  assert.deepEqual([r("#/").name, r("#/").tab], ["overview", "batches"]);
  assert.equal(r("#/todos").tab, "todos");
  assert.equal(r("#/inbox").tab, "inbox");
  assert.equal(r("#/archive").tab, "archive");
  assert.deepEqual([r("#/batch/045-2026-09-20-alpha.done").name, r("#/batch/045-2026-09-20-alpha.done").batch], ["batch", "045-2026-09-20-alpha.done"]);
  assert.equal(r("#/batch/x").tab, null);
  for (const tab of ["phases", "cost", "context", "notes", "closing"]) assert.equal(r(`#/batch/x/${tab}`).tab, tab);
  assert.equal(r("#/batch/x/bogus").tab, null);
  const phase = r("#/batch/x/phase/02-second");
  assert.deepEqual([phase.name, phase.batch, phase.phase], ["batch", "x", "02-second"]);
  const entry = r("#/entry/todo-2026-10-01-merge");
  assert.deepEqual([entry.name, entry.id], ["entry", "todo-2026-10-01-merge"]);
  assert.equal(r("#/nonsense/path").name, "overview", "an unknown hash falls back to the overview");
  assert.equal(r("#/batch").name, "overview", "a batch route without a name is unknown");
  assert.equal(r("#/batch/x").mirror, null);
});

test("parseRoute: global mode routes", () => {
  const r = (h) => C.parseRoute(h, "global");
  assert.equal(r("").name, "repos");
  assert.equal(r("#/").name, "repos");
  assert.deepEqual([r("#/alpha").name, r("#/alpha").mirror, r("#/alpha").tab], ["overview", "alpha", "batches"]);
  assert.equal(r("#/alpha/").mirror, "alpha");
  assert.equal(r("#/alpha/todos").tab, "todos");
  assert.equal(r("#/alpha/archive").tab, "archive");
  const b = r("#/alpha-1a2b/batch/045-x.y/cost");
  assert.deepEqual([b.name, b.mirror, b.batch, b.tab], ["batch", "alpha-1a2b", "045-x.y", "cost"]);
  const p = r("#/alpha/batch/x/phase/01-a");
  assert.deepEqual([p.name, p.mirror, p.batch, p.phase], ["batch", "alpha", "x", "01-a"]);
  const e = r("#/alpha/entry/plan-2026-10-01-a");
  assert.deepEqual([e.name, e.mirror, e.id], ["entry", "alpha", "plan-2026-10-01-a"]);
  assert.equal(r("#/alpha/junk").name, "overview");
});

test("dataPath: per-repo files move under the mirror in global mode", () => {
  assert.equal(C.dataPath("repo", null, "queue"), "data/queue");
  assert.equal(C.dataPath("repo", null, "batch/x"), "data/batch/x");
  assert.equal(C.dataPath("global", "alpha", "queue"), "alpha/data/queue");
  assert.equal(C.dataPath("global", "alpha", "entry/todo-a"), "alpha/data/entry/todo-a");
  for (const mode of ["repo", "global"]) {
    assert.equal(C.dataPath(mode, "alpha", "site"), "data/site");
    assert.equal(C.dataPath(mode, "alpha", "repos"), "data/repos");
  }
});

test("href: the mirror prefixes every link in global mode", () => {
  assert.equal(C.href({ mode: "repo" }, "batch/x"), "#/batch/x");
  assert.equal(C.href({ mode: "repo" }, ""), "#/");
  assert.equal(C.href({ mode: "global", mirror: "alpha" }, "batch/x"), "#/alpha/batch/x");
  assert.equal(C.href({ mode: "global", mirror: "alpha" }, ""), "#/alpha/");
});

// ---- DOM discipline -----------------------------------------------------------------------

test("el() sets text through textContent only", () => {
  const doc = fakeDoc();
  const e = C.el(doc, "div", "<img src=x onerror=boom()>", "cls");
  assert.equal(e.textContent, "<img src=x onerror=boom()>");
  assert.equal(e.innerHTML, "");
  assert.equal(e.className, "cls");
  assert.deepEqual(doc.innerHtmlWrites, []);
  assert.equal(C.el(doc, "div").textContent, "");
});

test("html() is the only helper that assigns innerHTML", () => {
  const doc = fakeDoc();
  const h = C.html(doc, "div", "<b>x</b>", "g");
  assert.equal(h.innerHTML, "<b>x</b>");
  assert.equal(doc.innerHtmlWrites.length, 1);
  C.el(doc, "p", "<b>y</b>");
  C.inlineCode(doc, "a `<i>` c");
  C.statusPill(doc, "<x>");
  C.flagBadges(doc, [{ level: "warn", text: "<s>" }]);
  C.tokenBar(doc, 5, 10);
  C.tabs(doc, [{ id: "a", label: "<A>", href: "#/" }], "a");
  C.disclosure(doc, "<l>", () => {});
  assert.equal(doc.innerHtmlWrites.length, 1, "no other helper writes innerHTML");
});

test("inlineCode splits on backticks into text, code, text", () => {
  const doc = fakeDoc();
  const span = C.inlineCode(doc, "a `b` c");
  assert.equal(span.children.length, 3);
  assert.deepEqual(span.children.map((n) => n.tagName), ["#text", "code", "#text"]);
  assert.deepEqual(span.children.map((n) => n.textContent), ["a ", "b", " c"]);
  assert.deepEqual(doc.innerHtmlWrites, []);
  assert.equal(C.inlineCode(doc, "plain").children.length, 1);
  assert.equal(C.inlineCode(doc, "").children.length, 0);
});

test("clear removes every child", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  root.appendChild(C.el(doc, "p", "a"));
  root.appendChild(C.el(doc, "p", "b"));
  C.clear(root);
  assert.equal(root.children.length, 0);
  assert.equal(root.firstChild, null);
});

// ---- formatting ---------------------------------------------------------------------------

test("fmtTokens rounds to k and M, dashes missing values", () => {
  const cases = [[0, "0"], [999, "999"], [1000, "1k"], [1500, "1.5k"], [12400, "12.4k"], [999960, "1M"],
    [1200000, "1.2M"], [12400000, "12.4M"], [null, "–"], [undefined, "–"], [NaN, "–"]];
  for (const [input, want] of cases) assert.equal(C.fmtTokens(input), want, String(input));
});

test("fmtDuration: m:ss and h:mm:ss", () => {
  assert.equal(C.fmtDuration(46), "0:46");
  assert.equal(C.fmtDuration(125), "2:05");
  assert.equal(C.fmtDuration(3723), "1:02:03");
  assert.equal(C.fmtDuration(0), "–");
  assert.equal(C.fmtDuration(null), "–");
});

test("fmtSpan: short spans in s, m, h and d", () => {
  const cases = [[0, "0s"], [45, "45s"], [59.6, "1m"], [660, "11m"], [3900, "1h 05m"], [7200, "2h 00m"],
    [273600, "3d 4h"], [277200, "3d 5h"], [null, "–"], [undefined, "–"], [NaN, "–"], [-5, "–"]];
  for (const [input, want] of cases) assert.equal(C.fmtSpan(input), want, String(input));
});

test("fmtActive: active time with the calendar time as title, or the calendar time alone", () => {
  assert.deepEqual(C.fmtActive(660, 2220), { text: "≈ 11m", title: "37m" });
  assert.deepEqual(C.fmtActive(0, 2220), { text: "≈ 0s", title: "37m" });
  assert.deepEqual(C.fmtActive(null, 2220), { text: "37m", title: null });
  assert.deepEqual(C.fmtActive(undefined, null), { text: "–", title: null });
  assert.deepEqual(C.fmtActive(660, null), { text: "≈ 11m", title: null });
});

test("fmtDateTime and fmtDate use the injected formatter", () => {
  const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" });
  assert.equal(C.fmtDateTime("2026-10-01T08:05:00Z", fmt), fmt.format(new Date("2026-10-01T08:05:00Z")));
  assert.equal(C.fmtDateTime("", fmt), "–");
  assert.equal(C.fmtDateTime("not a date", fmt), "not a date");
  const day = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" });
  assert.equal(C.fmtDate("2026-10-04", day), "4 Oct 2026", "a bare date is a calendar day in every timezone");
  assert.equal(C.fmtDate(null, day), "–");
});

test("fmtInt, billableIn and addT5", () => {
  assert.equal(C.fmtInt(1234567, "en-US"), "1,234,567");
  assert.equal(C.fmtInt(null), "–");
  assert.equal(C.billableIn({ input: 10, cache_creation: 5, cache_read: 99 }), 15);
  assert.equal(C.billableIn(null), 0);
  assert.deepEqual(
    C.addT5({ turns: 1, input: 2, output: 3, cache_read: 4, cache_creation: 5 }, { turns: 1, output: 1 }),
    { turns: 2, input: 2, output: 4, cache_read: 4, cache_creation: 5 },
  );
});

// ---- widgets ------------------------------------------------------------------------------

test("statusPill renders icon and label for every status, raw text for an unknown one", () => {
  const doc = fakeDoc();
  const labels = {
    planning: "Planning", awaiting_review: "Awaiting review", planned: "Planned", blocked: "Blocked",
    in_progress: "In progress", done: "Done", green: "Green", red: "Red", question: "Question", open: "Open",
  };
  for (const [status, label] of Object.entries(labels)) {
    const pill = C.statusPill(doc, status);
    assert.ok(pill.className.includes(`pill-${status}`), status);
    assert.equal(byClass(pill, "label")[0].textContent, label);
    assert.ok(byClass(pill, "icon")[0].textContent.length > 0, `${status} has an icon`);
  }
  const odd = C.statusPill(doc, "weird");
  assert.equal(odd.textContent, "weird");
  assert.equal(byClass(odd, "icon").length, 0);
});

test("flagBadges: counts from {warn, info} or a flag array, texts in the title", () => {
  const doc = fakeDoc();
  const counts = C.flagBadges(doc, { warn: 2, info: 0 });
  assert.equal(collectText(counts), "⚠ 2");
  const list = C.flagBadges(doc, [
    { level: "warn", text: "first" }, { level: "warn", text: "second" }, { level: "info", text: "note" },
  ]);
  const [warn, info] = byTag(list, "span").filter((s) => s.className.includes("flag-"));
  assert.equal(warn.textContent, "⚠ 2");
  assert.equal(warn.attrs.title, "first\nsecond");
  assert.equal(info.textContent, "ⓘ 1");
  assert.equal(C.flagBadges(doc, { warn: 0, info: 0 }).textContent, "–");
});

test("tokenBar scales the fill and shows the rounded value with the exact one in the title", () => {
  const doc = fakeDoc();
  const bar = C.tokenBar(doc, 1500, 3000);
  assert.equal(byClass(bar, "fill")[0].style.width, "50%");
  const val = byClass(bar, "val")[0];
  assert.equal(val.textContent, "1.5k");
  assert.equal(val.attrs.title, C.fmtInt(1500));
  assert.equal(byClass(C.tokenBar(doc, 5, 0), "fill")[0].style.width, "0%");
  assert.equal(C.tokenBar(doc, null, 10).textContent, "");
  assert.equal(byClass(C.tokenBar(doc, null, 10), "val")[0].textContent, "–");
});

test("tabs mark the active item", () => {
  const doc = fakeDoc();
  const nav = C.tabs(doc, [{ id: "a", label: "A", href: "#/a" }, { id: "b", label: "B", href: "#/b" }], "b");
  const [a, b] = byTag(nav, "a");
  assert.equal(a.attrs["aria-current"], undefined);
  assert.equal(b.attrs["aria-current"], "page");
  assert.equal(b.attrs.href, "#/b");
});

test("disclosure is a button that renders its body on first open only", () => {
  const doc = fakeDoc();
  let renders = 0;
  const d = C.disclosure(doc, "Details", (_doc, body) => { renders += 1; body.appendChild(C.el(doc, "p", "inside")); });
  const button = byTag(d, "button")[0];
  assert.equal(button.attrs["aria-expanded"], "false");
  const body = byClass(d, "disclosure-body")[0];
  assert.ok("hidden" in body.attrs);
  assert.equal(renders, 0);
  fire(button, "click");
  assert.equal(button.attrs["aria-expanded"], "true");
  assert.ok(!("hidden" in body.attrs));
  assert.equal(renders, 1);
  fire(button, "click");
  assert.equal(button.attrs["aria-expanded"], "false");
  fire(button, "click");
  assert.equal(renders, 1, "reopening does not render again");
});

// ---- slots --------------------------------------------------------------------------------

test("register/registered: ascending order, ties in registration order, unknown slot empty", () => {
  const fresh = loadPortal().core;
  fresh.register("testSlot", { id: "c", order: 30 });
  fresh.register("testSlot", { id: "a", order: 10 });
  fresh.register("testSlot", { id: "b1", order: 20 });
  fresh.register("testSlot", { id: "b2", order: 20 });
  assert.deepEqual(fresh.registered("testSlot").map((i) => i.id), ["a", "b1", "b2", "c"]);
  assert.deepEqual(fresh.registered("nothing"), []);
});

// ---- CFQ.app.render -----------------------------------------------------------------------

function recorder(site, payloads) {
  const loaded = [];
  const load = (p) => {
    loaded.push(p);
    if (p === "data/site") return Promise.resolve(site);
    return Promise.resolve(Object.prototype.hasOwnProperty.call(payloads, p) ? payloads[p] : null);
  };
  return { load, loaded };
}

function stubViews(cfq) {
  const calls = {};
  for (const name of ["overview", "batch", "entry", "repos"]) {
    cfq[name] = { render(doc, root, ctx) { calls[name] = ctx; } };
  }
  return calls;
}

test("app.render dispatches every repo-mode route with the right data and ctx", async () => {
  const cfq = loadPortal();
  const calls = stubViews(cfq);
  const doc = fakeDoc();
  const site = fixtureSite();
  const cases = [
    ["#/", "overview", "data/queue", "queue"],
    ["#/todos", "overview", "data/queue", "queue"],
    ["#/inbox", "overview", "data/queue", "queue"],
    ["#/archive", "overview", "data/queue", "queue"],
    ["#/batch/x", "batch", "data/batch/x", "batch"],
    ["#/batch/x/cost", "batch", "data/batch/x", "batch"],
    ["#/batch/x/phase/01-a", "batch", "data/batch/x", "batch"],
    ["#/entry/todo-a", "entry", "data/entry/todo-a", "entry"],
  ];
  for (const [hash, view, path, key] of cases) {
    for (const k of Object.keys(calls)) delete calls[k];
    const payload = { marker: hash };
    const { load, loaded } = recorder(site, { [path]: payload });
    await cfq.app.render(doc, fakeRoot(doc), hash, load);
    assert.deepEqual(loaded, ["data/site", path], hash);
    const ctx = calls[view];
    assert.ok(ctx, `${hash} dispatches to ${view}`);
    assert.deepEqual(Object.keys(calls), [view]);
    assert.equal(ctx.mode, "repo");
    assert.equal(ctx.mirror, null);
    assert.equal(ctx.site, site);
    assert.equal(ctx[key], payload);
    assert.equal(typeof ctx.setCrumbs, "function");
    assert.equal(ctx.route.name, view);
    ctx.setCrumbs([{ label: "x", href: "#/" }]);
  }
});

test("app.render in global mode loads from the mirror and ctx carries the mirror", async () => {
  const cfq = loadPortal();
  const calls = stubViews(cfq);
  const doc = fakeDoc();
  const site = fixtureSite("global");
  const cases = [
    ["#/", "repos", "data/repos", "repos"],
    ["", "repos", "data/repos", "repos"],
    ["#/alpha", "overview", "alpha/data/queue", "queue"],
    ["#/alpha/todos", "overview", "alpha/data/queue", "queue"],
    ["#/alpha/batch/x", "batch", "alpha/data/batch/x", "batch"],
    ["#/alpha/batch/x/phase/01-a", "batch", "alpha/data/batch/x", "batch"],
    ["#/alpha/entry/todo-a", "entry", "alpha/data/entry/todo-a", "entry"],
  ];
  for (const [hash, view, path, key] of cases) {
    for (const k of Object.keys(calls)) delete calls[k];
    const payload = [hash];
    const { load, loaded } = recorder(site, { [path]: payload });
    await cfq.app.render(doc, fakeRoot(doc), hash, load);
    // Every page of a mirror also loads the repo list for the top bar's switcher.
    assert.deepEqual(loaded, view === "repos" ? ["data/site", path] : ["data/site", path, "data/repos"], hash);
    const ctx = calls[view];
    assert.ok(ctx, `${hash} dispatches to ${view}`);
    assert.equal(ctx.mode, "global");
    assert.equal(ctx.mirror, view === "repos" ? null : "alpha");
    assert.equal(ctx[key], payload);
  }
});

test("app.render passes null when a data file cannot be loaded", async () => {
  const cfq = loadPortal();
  const calls = stubViews(cfq);
  const doc = fakeDoc();
  await cfq.app.render(doc, fakeRoot(doc), "#/batch/ghost", recorder(fixtureSite(), {}).load);
  assert.equal(calls.batch.batch, null);
  await cfq.app.render(doc, fakeRoot(doc), "#/", recorder(fixtureSite(), {}).load);
  assert.equal(calls.overview.queue, null);
});

test("app.render shows a message when the view module is not loaded", async () => {
  const cfq = loadPortal();
  delete cfq.batch;
  delete cfq.entry;
  delete cfq.repos;
  const doc = fakeDoc();
  for (const hash of ["#/batch/x", "#/entry/todo-a"]) {
    const root = fakeRoot(doc);
    await cfq.app.render(doc, root, hash, recorder(fixtureSite(), {}).load);
    assert.match(collectText(root), /This view is not available\./);
  }
  const root = fakeRoot(doc);
  await cfq.app.render(doc, root, "#/", recorder(fixtureSite("global"), { "data/repos": fixtureRepos() }).load);
  assert.match(collectText(root), /This view is not available\./);
});

test("app.render clears the root, fills the breadcrumb slot and survives a throwing view", async () => {
  const cfq = loadPortal();
  const doc = fakeDoc();
  doc.byId.crumbs = doc.createElement("nav");
  const root = fakeRoot(doc);
  root.appendChild(cfq.core.el(doc, "p", "stale"));
  cfq.overview = {
    render(d, r, ctx) {
      ctx.setCrumbs([{ label: "Home", href: "#/" }, { label: "Here", href: null }]);
      r.appendChild(cfq.core.el(d, "p", "fresh"));
    },
  };
  await cfq.app.render(doc, root, "#/", recorder(fixtureSite(), { "data/queue": fixtureQueue() }).load);
  assert.equal(collectText(root), "fresh");
  assert.equal(byTag(doc.byId.crumbs, "a")[0].attrs.href, "#/");
  assert.match(collectText(doc.byId.crumbs), /Here/);
  assert.equal(doc.title, "cfq – demo");

  cfq.overview = { render() { throw new Error("kaboom"); } };
  const root2 = fakeRoot(doc);
  const origError = console.error;
  console.error = () => {};
  try {
    await cfq.app.render(doc, root2, "#/", recorder(fixtureSite(), {}).load);
  } finally {
    console.error = origError;
  }
  assert.match(collectText(root2), /kaboom/);
});

// ---- top bar ------------------------------------------------------------------------------

function topbarDoc() {
  const doc = fakeDoc();
  for (const id of ["crumbs", "repo-switch"]) doc.byId[id] = doc.createElement(id === "crumbs" ? "nav" : "span");
  doc.byId.search = doc.createElement("input");
  return doc;
}

test("top bar: repo mode shows the repo name as plain text", async () => {
  const cfq = loadPortal();
  stubViews(cfq);
  const doc = topbarDoc();
  await cfq.app.render(doc, fakeRoot(doc), "#/", recorder(fixtureSite(), { "data/queue": fixtureQueue() }).load);
  const slot = doc.byId["repo-switch"];
  assert.equal(byTag(slot, "select").length, 0);
  assert.equal(collectText(slot), "demo");
});

test("top bar: global mode has a switcher over the repo list that opens the chosen overview", async () => {
  const cfq = loadPortal();
  stubViews(cfq);
  const doc = topbarDoc();
  const data = { "data/repos": fixtureRepos(), "alpha/data/queue": fixtureQueue() };
  await cfq.app.render(doc, fakeRoot(doc), "#/alpha/", recorder(fixtureSite("global"), data).load);
  const select = byTag(doc.byId["repo-switch"], "select")[0];
  assert.ok(select, "a <select> in global mode");
  const options = byTag(select, "option");
  assert.deepEqual(options.map((o) => [o.attrs.value, o.textContent]), [["alpha", "alpha"], ["beta-1a2b3c", "beta"]]);
  assert.equal(select.value, "alpha", "the current repo is selected");

  const savedLocation = globalThis.location;
  globalThis.location = { hash: "#/alpha/" };
  try {
    select.value = "beta-1a2b3c";
    fire(select, "change");
    assert.equal(globalThis.location.hash, "#/beta-1a2b3c/");
  } finally {
    if (savedLocation === undefined) delete globalThis.location;
    else globalThis.location = savedLocation;
  }

  // the repo index itself offers "All repos" in front
  const doc2 = topbarDoc();
  await cfq.app.render(doc2, fakeRoot(doc2), "#/", recorder(fixtureSite("global"), data).load);
  const first = byTag(byTag(doc2.byId["repo-switch"], "select")[0], "option")[0];
  assert.equal(first.textContent, "All repos");
});

test("top bar: / focuses the search field, one handler per document", async () => {
  const cfq = loadPortal();
  stubViews(cfq);
  const doc = topbarDoc();
  const load = recorder(fixtureSite(), { "data/queue": fixtureQueue() }).load;
  await cfq.app.render(doc, fakeRoot(doc), "#/", load);
  await cfq.app.render(doc, fakeRoot(doc), "#/", load);
  const search = doc.byId.search;
  const ev = fire(doc, "keydown", { key: "/", target: fakeRoot(doc) });
  assert.equal(search.focused, true);
  assert.equal(ev.prevented, true);
  search.focused = false;
  fire(doc, "keydown", { key: "/", target: search });
  assert.equal(search.focused, false, "typing / inside a field is left alone");
  assert.equal(doc.listeners.keydown.length, 1, "one slash handler per document");
});

test("top bar: search filters the overview, and Enter elsewhere opens the overview with the query", async () => {
  const cfq = loadPortal();
  stubViews(cfq);
  const doc = topbarDoc();
  const search = doc.byId.search;
  const load = recorder(fixtureSite(), { "data/queue": fixtureQueue(), "data/batch/x": { name: "x" } }).load;
  const savedLocation = globalThis.location;
  globalThis.location = { hash: "#/batch/x" };
  try {
    await cfq.app.render(doc, fakeRoot(doc), "#/batch/x", load);
    search.value = "alpha";
    fire(search, "input");
    assert.equal(cfq.state.query, "alpha");
    fire(search, "keydown", { key: "Enter" });
    assert.equal(globalThis.location.hash, "#/", "Enter on a batch page navigates to the overview");

    // On the overview, typing redraws through the hook the overview registered; Enter stays put.
    let redraws = 0;
    cfq.overview = { render() { cfq.state.onQuery = () => { redraws++; }; } };
    await cfq.app.render(doc, fakeRoot(doc), "#/", load);
    assert.equal(search.value, "alpha", "the field shows the shared query");
    search.value = "beta";
    fire(search, "input");
    assert.equal(redraws, 1);
    globalThis.location.hash = "#/";
    fire(search, "keydown", { key: "Enter" });
    assert.equal(globalThis.location.hash, "#/");

    // Another page drops the overview's hook.
    await cfq.app.render(doc, fakeRoot(doc), "#/batch/x", load);
    assert.equal(cfq.state.onQuery, null);
    assert.equal(search.value, "beta");
  } finally {
    if (savedLocation === undefined) delete globalThis.location;
    else globalThis.location = savedLocation;
  }
});

test("fixtures stay in the contract shape", () => {
  const q = fixtureQueue();
  assert.deepEqual([...new Set(q.batches.map((b) => b.status))].sort(),
    ["awaiting_review", "blocked", "done", "in_progress", "planned", "planning"]);
  assert.equal(q.batches.filter((b) => b.cost === null).length, 1);
  assert.ok(fixtureEntry("todo_open").origin === null && fixtureEntry("plan_closed").origin);
  const done = fixtureBatch("done");
  assert.equal(done.phases[1].attempts.length, 2);
  assert.equal(done.notes.length, 3);
  assert.equal(fixtureBatch("plan_only").cost, null);
  assert.equal(fixtureBatch("in_progress").phases.filter((p) => p.state === "open").length, 2);
  assert.equal(collectHtml(fakeRoot()).length, 0);
});

// ---- edit controls ------------------------------------------------------------------------

const EDIT = {
  path: "\\\\wsl.localhost\\Alma\\home\\x.md",
  dir: { path: "\\\\wsl.localhost\\Alma\\home", url: "vscode://vscode-remote/wsl+Alma/home" },
};
const LABELS = { open: "Open folder", copy: "Copy path" };
const tick = () => new Promise((resolve) => setImmediate(resolve));

test("fileEditControls: link, copy button and hint; no url means no link", () => {
  const doc = fakeDoc();
  const row = C.fileEditControls(doc, EDIT, LABELS);
  assert.equal(row.className, "edit-controls");
  const open = byClass(row, "edit-open");
  assert.equal(open.length, 1);
  assert.equal(open[0].tagName, "a");
  assert.equal(open[0].attrs.href, EDIT.dir.url);
  assert.equal(open[0].textContent, "Open folder");
  const copy = byClass(row, "edit-copy");
  assert.equal(copy.length, 1);
  assert.equal(copy[0].tagName, "button");
  assert.equal(copy[0].attrs.type, "button");
  assert.equal(copy[0].textContent, "Copy path");
  const hint = byClass(row, "edit-hint");
  assert.equal(hint.length, 1);
  assert.match(hint[0].className, /faint/);
  assert.match(collectText(hint[0]), /Changes appear after the next sync/);
  assert.equal(byTag(hint[0], "code")[0].textContent, "bin/cfq portal sync <repo-root>");

  const noUrl = C.fileEditControls(doc, { path: EDIT.path }, LABELS);
  assert.equal(byClass(noUrl, "edit-open").length, 0);
  assert.equal(byClass(noUrl, "edit-copy").length, 1);
  assert.equal(C.fileEditControls(doc, null, LABELS), null);

  // data of an older cfq: file-level url, no dir -> only the copy button, the old url is never used
  const old = C.fileEditControls(doc, { path: EDIT.path, url: "vscode://file/old" }, LABELS);
  assert.equal(byClass(old, "edit-open").length, 0);
  assert.deepEqual(byClass(old, "edit-copy").map((b) => b.textContent), ["Copy path"]);
});

test("editControlRow: several pairs share one row and one hint", () => {
  const row = C.editControlRow(fakeDoc(), [
    [EDIT.dir, { open: "Open folder", copy: "Copy folder path" }],
    [{ path: "/p" }, { copy: "Copy context path" }],
    [null, LABELS],
  ]);
  assert.equal(byClass(row, "edit-open").length, 1);
  assert.deepEqual(byClass(row, "edit-copy").map((b) => b.textContent), ["Copy folder path", "Copy context path"]);
  assert.equal(byClass(row, "edit-hint").length, 1);
  assert.equal(C.editControlRow(fakeDoc(), [[null, LABELS]]), null);
});

test("fileEditControls: the clipboard API copies the path and the label reads Copied", async () => {
  const copied = [];
  await withClipboard({ writeText: (s) => { copied.push(s); return Promise.resolve(); } }, async () => {
    const row = C.fileEditControls(fakeDoc(), EDIT, LABELS);
    const button = byClass(row, "edit-copy")[0];
    fire(button, "click");
    await tick();
    assert.deepEqual(copied, [EDIT.path]);
    assert.equal(button.textContent, "Copied");
    assert.equal(byTag(row, "code").filter((c) => c.className === "edit-path").length, 0);
  });
});

test("fileEditControls: without the clipboard API the execCommand fallback copies from a textarea", async () => {
  await withClipboard(undefined, async () => {
    const doc = fakeDoc();
    let seen = null;
    doc.execCommand = (cmd) => {
      seen = { cmd, value: byTag(doc.body, "textarea")[0].value };
      return true;
    };
    const row = C.fileEditControls(doc, EDIT, LABELS);
    const button = byClass(row, "edit-copy")[0];
    fire(button, "click");
    await tick();
    assert.deepEqual(seen, { cmd: "copy", value: EDIT.path });
    assert.equal(button.textContent, "Copied");
    assert.equal(byTag(doc.body, "textarea").length, 0);
  });
});

test("fileEditControls: a rejected clipboard write falls back to execCommand", async () => {
  await withClipboard({ writeText: () => Promise.reject(new Error("denied")) }, async () => {
    const doc = fakeDoc();
    doc.execCommand = () => true;
    const button = byClass(C.fileEditControls(doc, EDIT, LABELS), "edit-copy")[0];
    fire(button, "click");
    await tick();
    assert.equal(button.textContent, "Copied");
  });
});

test("fileEditControls: when every copy way fails the path appears as selectable code", async () => {
  await withClipboard(undefined, async () => {
    for (const execCommand of [null, () => false, () => { throw new Error("nope"); }]) {
      const doc = fakeDoc();
      doc.execCommand = execCommand;
      const row = C.fileEditControls(doc, EDIT, LABELS);
      const button = byClass(row, "edit-copy")[0];
      fire(button, "click");
      await tick();
      fire(button, "click");
      await tick();
      assert.equal(button.textContent, "Copy path");
      const shown = byClass(row, "edit-path");
      assert.equal(shown.length, 1);
      assert.equal(shown[0].tagName, "code");
      assert.equal(shown[0].textContent, EDIT.path);
    }
  });
});

test("fileEditControls: markup in a path stays text and never reaches innerHTML", async () => {
  const evil = "/home/<b>x</b>/plan.md";
  await withClipboard(undefined, async () => {
    const doc = fakeDoc();
    const row = C.fileEditControls(doc, { path: evil, dir: { url: "vscode://file/x" } }, LABELS);
    fire(byClass(row, "edit-copy")[0], "click");
    await tick();
    assert.equal(byTag(row, "b").length, 0);
    assert.equal(byClass(row, "edit-path")[0].textContent, evil);
    assert.deepEqual(doc.innerHtmlWrites, []);
  });
});
