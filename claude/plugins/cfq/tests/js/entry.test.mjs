// Tests for portal/entry.js: the page of one todo card or plan entry.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, byTag, byClass, collectText, collectHtml, links, loadPortal, fixtureSite, fixtureEntry,
} from "./helpers.mjs";

const CFQ = loadPortal();
const site = fixtureSite();

function renderEntry(entry, over) {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  const crumbs = [];
  CFQ.entry.render(doc, root, {
    mode: "repo", repo: site.repo, mirror: null, site, entry,
    route: { name: "entry", id: entry ? entry.id : "missing" },
    setCrumbs(c) { crumbs.push(c); },
    ...(over || {}),
  });
  return { doc, root, crumbs: crumbs[crumbs.length - 1] };
}

const factRows = (root) => {
  const dl = byClass(root, "facts")[0];
  const out = {};
  const kids = dl.children;
  for (let i = 0; i + 1 < kids.length; i += 2) out[kids[i].textContent] = kids[i + 1];
  return out;
};

test("an open todo card: inline-code title once, kind, state, date, check and body", () => {
  const { root, crumbs } = renderEntry(fixtureEntry("todo_open"));
  const h1 = byTag(root, "h1");
  assert.equal(h1.length, 1);
  assert.equal(byTag(h1[0], "code")[0].textContent, "cfq/045-2026-09-20-alpha-done");
  assert.ok(!collectText(h1[0]).includes("`"));
  assert.equal(collectText(root).split("cfq/045-2026-09-20-alpha-done").length - 1, 1);

  const rows = factRows(root);
  assert.deepEqual(Object.keys(rows), ["Kind", "State", "Date", "Check"]);
  assert.match(collectText(rows.Kind), /Todo card/);
  assert.match(collectText(rows.State), /Open/);
  assert.equal(byClass(rows.State, "pill-open").length, 1);
  assert.match(collectText(rows.Check), /git branch --merged main/);
  assert.equal(byTag(rows.Check, "code").length, 1);

  const prose = byClass(root, "prose")[0];
  assert.deepEqual(collectHtml(prose), ["<p>Body of the todo card.</p>"]);
  assert.deepEqual(crumbs.map((c) => c.label), ["demo", "Todos", "Todo card"]);
  assert.equal(crumbs[1].href, "#/todos");
});

test("a closed plan entry links its origin batch, its phase and the batch it was parked into", () => {
  const { root, crumbs } = renderEntry(fixtureEntry("plan_closed"));
  const rows = factRows(root);
  assert.deepEqual(Object.keys(rows), ["Kind", "State", "Date", "Origin", "Parked into", "Closed"]);
  assert.match(collectText(rows.Kind), /Plan entry/);
  assert.match(collectText(rows.State), /Closed/);
  assert.match(collectText(rows.Closed), /2026-10-02: parked into 049/);
  const hrefs = links(root);
  assert.ok(hrefs.includes("#/batch/045-2026-09-20-alpha-done"));
  assert.ok(hrefs.includes("#/batch/045-2026-09-20-alpha-done/phase/01-first"));
  assert.ok(hrefs.includes("#/batch/049-2026-10-05-epsilon-planned"));
  assert.equal(crumbs[1].label, "Archive");
  assert.equal(crumbs[1].href, "#/archive");
});

test("an origin without a phase links the batch only; open plan entries sit in the inbox", () => {
  const entry = { ...fixtureEntry("plan_closed"), state: "open", closed: null, parkedInto: null };
  entry.origin = { batch: "047-2026-10-01-gamma-progress", phase: "" };
  const { root, crumbs } = renderEntry(entry);
  const origin = byClass(factRows(root).Origin, "origin")[0];
  assert.deepEqual(links(origin), ["#/batch/047-2026-10-01-gamma-progress"]);
  assert.equal(crumbs[1].label, "Plan inbox");
  assert.equal(crumbs[1].href, "#/inbox");
});

test("an entry with origin null shows no origin row", () => {
  const { root } = renderEntry(fixtureEntry("todo_open"));
  assert.ok(!("Origin" in factRows(root)));
  assert.ok(!collectText(root).includes("Origin"));
});

test("a null payload says Entry not found and links back", () => {
  const { root } = renderEntry(null);
  assert.match(collectText(root), /Entry not found\./);
  assert.deepEqual(links(root), ["#/"]);
});

test("global mode prefixes every link with the mirror", () => {
  const { root, crumbs } = renderEntry(fixtureEntry("plan_closed"), { mode: "global", mirror: "demo-1a2b" });
  assert.ok(links(root).includes("#/demo-1a2b/batch/045-2026-09-20-alpha-done"));
  assert.deepEqual(crumbs.map((c) => c.label), ["All repos", "demo-1a2b", "Archive", "Plan entry"]);
  assert.equal(crumbs[0].href, "#/");
  assert.equal(crumbs[2].href, "#/demo-1a2b/archive");
});

test("a title with markup never reaches innerHTML", () => {
  const entry = { ...fixtureEntry("todo_open"), title: "Beware <script>alert(1)</script> `x`" };
  const { doc, root } = renderEntry(entry);
  assert.match(collectText(byTag(root, "h1")[0]), /<script>alert\(1\)<\/script>/);
  assert.ok(doc.innerHtmlWrites.every((w) => !w.value.includes("alert(1)")));
  assert.equal(doc.innerHtmlWrites.length, 1); // the body only
});
