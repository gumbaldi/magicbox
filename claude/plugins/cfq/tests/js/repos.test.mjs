// Tests for portal/repos.js: the cross-repo index of a reportDir mirror.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, byTag, byClass, collectText, links, loadPortal, fixtureRepos,
} from "./helpers.mjs";

const CFQ = loadPortal();

function renderRepos(repos) {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  CFQ.repos.render(doc, root, { mode: "global", repo: "", mirror: null, repos, route: { name: "repos" }, setCrumbs() {} });
  return root;
}

const rowsOf = (root) => byClass(root, "repo-row");

test("one row per repo, linking to the repo's own overview, with todo and inbox counts", () => {
  const root = renderRepos(fixtureRepos());
  const rows = rowsOf(root);
  assert.equal(rows.length, 2);
  assert.match(collectText(rows[0]), /alpha/);
  assert.match(collectText(rows[1]), /beta/);
  assert.match(collectText(rows[0]), /2 todos · 1 inbox/);
  assert.match(collectText(rows[1]), /0 todos · 0 inbox/);
  assert.deepEqual(links(root), ["#/alpha/", "#/beta-1a2b3c/"]);
  assert.deepEqual(byTag(root, "h1").map((h) => h.textContent), ["Repositories"]);
});

test("rows are sorted by last activity, newest first; repos without one go last by name", () => {
  const mk = (name, lastActivity) => ({ name, mirror: name, source: "/r/" + name, counts: { lastActivity } });
  const root = renderRepos([
    mk("zeta", ""), mk("old", "2026-10-01T08:00:00Z"), mk("alpha", ""), mk("new", "2026-11-21T08:00:00Z"),
  ]);
  assert.deepEqual(links(root), ["#/new/", "#/old/", "#/alpha/", "#/zeta/"]);
});

test("a repo with a running batch shows its title and phases, an idle repo shows idle", () => {
  const rows = rowsOf(renderRepos(fixtureRepos()));
  assert.match(collectText(rows[0]), /012 · Alpha work/);
  assert.match(collectText(rows[0]), /2\/5/);
  assert.equal(byClass(rows[0], "dot")[0].className.includes("run"), true);
  assert.doesNotMatch(collectText(rows[0]), /idle/);
  assert.match(collectText(rows[1]), /idle/);
  assert.equal(byClass(rows[1], "dot").length, 0);
});

test("attention pills appear only for non-zero counts", () => {
  const rows = rowsOf(renderRepos(fixtureRepos()));
  assert.deepEqual(byClass(rows[0], "pill").map((p) => p.textContent), ["⚠ 2", "1 review"]);
  assert.equal(byClass(rows[1], "pill").length, 0);
  const only = rowsOf(renderRepos([{ name: "x", mirror: "x", counts: { attention: { warn: 0, plan: 3 } } }]));
  assert.deepEqual(byClass(only[0], "pill").map((p) => p.textContent), ["3 review"]);
});

test("relDate covers today, yesterday, days ago and an older date against an injected now", () => {
  const now = new Date(2026, 10, 22, 15, 0, 0);
  const at = (y, m, d, h) => new Date(y, m, d, h, 0, 0).toISOString();
  assert.equal(CFQ.repos.relDate(at(2026, 10, 22, 1), now), "today");
  assert.equal(CFQ.repos.relDate(at(2026, 10, 21, 23), now), "yesterday");
  assert.equal(CFQ.repos.relDate(at(2026, 10, 19, 9), now), "3 days ago");
  assert.equal(CFQ.repos.relDate(at(2026, 9, 1, 9), now), "01.10.2026");
  assert.equal(CFQ.repos.relDate("", now), "–");
});

test("the row shows the relative last-active text", () => {
  const doc = fakeDoc();
  const root = fakeRoot(doc);
  const repos = fixtureRepos();
  CFQ.repos.render(doc, root, { repos, now: new Date(2026, 10, 22, 18, 0, 0), setCrumbs() {} });
  const rows = rowsOf(root);
  assert.match(collectText(rows[0]), /last active today/);
  assert.match(collectText(rows[1]), /last active –/);
});

test("an empty list says no repo has synced yet", () => {
  for (const empty of [[], null]) {
    const root = renderRepos(empty);
    assert.match(collectText(root), /No repo has synced into this report directory yet\./);
    assert.equal(rowsOf(root).length, 0);
  }
});

test("CFQ.app.render shows the repo list at #/ in global mode", async () => {
  const doc = fakeDoc();
  doc.byId.crumbs = doc.createElement("nav");
  const root = fakeRoot(doc);
  const asked = [];
  const load = async (p) => {
    asked.push(p);
    if (p === "data/site") return { mode: "global" };
    if (p === "data/repos") return fixtureRepos();
    return null;
  };
  await CFQ.app.render(doc, root, "#/", load);
  assert.deepEqual(asked, ["data/site", "data/repos"]);
  assert.equal(rowsOf(root).length, 2);
  assert.equal(byClass(root, "empty").length, 0);
  assert.match(collectText(root), /alpha/);
});
