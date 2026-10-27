// Tests for portal/batch-notes.js: the Notes and Closing tabs of the batch page.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, byTag, byClass, collectText, links, loadPortal, fixtureSite, fixtureBatch,
} from "./helpers.mjs";

const CFQ = loadPortal();
const site = fixtureSite();

function renderTab(batch, tab, doc) {
  const d = doc || fakeDoc();
  const root = fakeRoot(d);
  CFQ.batch.render(d, root, {
    mode: "repo", repo: site.repo, mirror: null, site, batch, setCrumbs() {},
    route: { name: "batch", tab, batch: batch.name, phase: null, mirror: null },
  });
  return { doc: d, root, body: byClass(root, "batch-tab")[0] };
}

const tabLabels = (root) => byClass(root, "tab").map((t) => t.textContent);

test("loading batch-notes.js registers Notes (40) and Closing (50)", () => {
  const tabs = CFQ.core.registered("batchTab");
  const byId = Object.fromEntries(tabs.map((t) => [t.id, t]));
  assert.equal(byId.notes.order, 40);
  assert.equal(byId.closing.order, 50);
  const ids = tabs.map((t) => t.id);
  assert.ok(ids.indexOf("context") < ids.indexOf("notes") && ids.indexOf("notes") < ids.indexOf("closing"));
});

test("the Notes tab label counts notes, plan entries it implements and parked entries", () => {
  const { root } = renderTab(fixtureBatch("done"), "notes");
  assert.ok(tabLabels(root).includes("Notes (5)")); // 3 notes + 1 fromPlan + 1 parked
  assert.ok(tabLabels(root).includes("Closing"));
  assert.ok(tabLabels(renderTab(fixtureBatch("plan_only"), "notes").root).includes("Notes (0)"));
});

test("Notes tab: written during this batch, with links, phase, time and state", () => {
  const { body } = renderTab(fixtureBatch("done"), "notes");
  const text = collectText(body);
  assert.match(text, /Written during this batch/);
  const table = byClass(body, "notes")[0];
  assert.equal(byTag(table, "tr").length, 1 + 3);
  const hrefs = links(table);
  assert.ok(hrefs.includes("#/entry/todo-2026-10-01-open-card"));
  assert.ok(hrefs.includes("#/entry/plan-2026-10-01-done-entry"));
  assert.ok(hrefs.includes("#/batch/047-2026-10-01-demo/phase/02-second"));
  // The title goes through inlineCode: backticks become <code>.
  assert.equal(byTag(table, "code")[0].textContent, "card");
  assert.match(text, /Todo card/);
  assert.match(text, /Plan entry/);
  assert.match(text, /Open/);
  assert.match(text, /Done/);
});

test("Notes tab: a missing framework note reads external and is plain text", () => {
  const { body } = renderTab(fixtureBatch("done"), "notes");
  const table = byClass(body, "notes")[0];
  assert.match(collectText(table), /external/);
  assert.match(collectText(table), /Framework finding/);
  assert.ok(!links(table).some((h) => h.includes("plan-2026-10-01-framework")));

  const batch = fixtureBatch("done");
  batch.notes[2].framework = false;
  const other = byClass(renderTab(batch, "notes").body, "notes")[0];
  assert.match(collectText(other), /missing/);
  assert.ok(!links(other).some((h) => h.includes("plan-2026-10-01-framework")));
});

test("Notes tab: plan entries it implements and entries parked by phases are linked", () => {
  const { body } = renderTab(fixtureBatch("done"), "notes");
  const text = collectText(body);
  assert.match(text, /Implements plan entries/);
  assert.match(text, /Where it came from/);
  assert.match(text, /Parked by phases/);
  const hrefs = links(body);
  assert.ok(hrefs.includes("#/entry/plan-2026-09-30-origin"));
  assert.ok(hrefs.includes("#/entry/plan-2026-10-01-follow-up"));
  assert.match(text, /2026-10-01-follow-up\.md/);
});

test("Notes tab: a parked entry named by several attempts is listed once per phase", () => {
  const batch = fixtureBatch("done");
  batch.phases[1].attempts[0].parkedPlanEntries = ["plan/2026-10-01-follow-up.md"];
  assert.equal(CFQ.batchNotes.parkedRows(batch).length, 1);
  assert.equal(CFQ.batchNotes.noteCount(batch), 5);
});

test("Notes tab: nothing recorded says so", () => {
  const { body } = renderTab(fixtureBatch("plan_only"), "notes");
  assert.equal(collectText(body).trim(), "No notes recorded for this batch.");
  assert.equal(byTag(body, "table").length, 0);
});

test("Closing tab: no closing data says so", () => {
  const { body } = renderTab(fixtureBatch("plan_only"), "closing");
  assert.equal(collectText(body).trim(), "No closing data recorded.");
});

test("Closing tab: every part of the closing result is shown", () => {
  const batch = fixtureBatch("done");
  batch.phases[0].attempts[0].skills = { used: ["tdd"] };
  batch.phases[1].attempts[1].skills = { used: ["simplify"] };
  const { body } = renderTab(batch, "closing");
  const text = collectText(body);
  assert.match(text, /Docs lack a German counterpart/);
  assert.match(text, /1 issue\b/);
  assert.match(text, /ran/);
  assert.match(text, /written/);
  assert.match(text, /push failed: no remote/);
  assert.match(text, /cfq\/047-2026-10-01-demo/);
  assert.match(text, /merged/);
  assert.match(text, /high: Unchecked input/);
  const sec = byClass(body, "notes")[0];
  assert.deepEqual(byTag(sec, "th").map((t) => t.textContent), ["Planning", "Now", "New"]);
  assert.deepEqual(byTag(sec, "td").map((t) => t.textContent), ["0", "1", "1"]);
  // Skills across all attempts, each name once.
  const lists = byClass(byClass(body, "closing")[0], "plain-list");
  const items = lists.map((l) => byTag(l, "li").map((li) => collectText(li)));
  assert.ok(items.some((i) => i.join() === "simplify,tdd"));
  assert.doesNotMatch(text, /Recommended/);
  const skills = CFQ.batchNotes.skillSets(batch);
  assert.deepEqual(skills, { used: ["simplify", "tdd"] });
});

test("Closing tab: missing parts show a dash, an unmerged batch says so, the snapshot hint appears", () => {
  const batch = fixtureBatch("done");
  batch.closing = { at: "", lang: null, security: null, errors: [] };
  batch.merged = false;
  batch.security = { available: false, counts: {}, findings: [], hint: "Run the security review once." };
  const { body } = renderTab(batch, "closing");
  const text = collectText(body);
  assert.match(text, /not merged yet/);
  assert.match(text, /Run the security review once\./);
  assert.equal(byTag(body, "table").length, 0);
  assert.match(text, /none/);
});

test("titles, findings and errors containing markup never reach innerHTML", () => {
  const batch = fixtureBatch("done");
  const evil = "<script>alert(1)</script>";
  batch.notes[0].title = evil;
  batch.fromPlan[0].title = evil;
  batch.closing.errors = [evil];
  batch.closing.lang.findings = [evil];
  batch.security.findings = [{ severity: "high", title: evil }];
  const doc = fakeDoc();
  const notes = renderTab(batch, "notes", doc);
  const closing = renderTab(batch, "closing", doc);
  assert.match(collectText(notes.body), /<script>alert\(1\)<\/script>/);
  assert.match(collectText(closing.body), /<script>alert\(1\)<\/script>/);
  assert.ok(doc.innerHtmlWrites.every((w) => !w.value.includes("<script>")));
  assert.equal(byTag(notes.root, "script").length + byTag(closing.root, "script").length, 0);
});
