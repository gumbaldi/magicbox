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

test("one row per repo with counts, linking to the repo's own overview", () => {
  const root = renderRepos(fixtureRepos());
  const rows = byTag(byTag(root, "tbody")[0], "tr");
  assert.equal(rows.length, 2);
  const cells = (tr) => byTag(tr, "td").map((td) => td.textContent);
  assert.deepEqual(cells(rows[0]).slice(1), ["1", "2", "3", "2", "1"]);
  assert.deepEqual(cells(rows[1]).slice(1), ["0", "0", "5", "0", "0"]);
  assert.match(collectText(rows[0]), /alpha/);
  assert.match(collectText(rows[1]), /beta/);
  assert.deepEqual(links(root), ["#/alpha/", "#/beta-1a2b3c/"]);
  const heads = byTag(root, "th").map((th) => th.textContent);
  assert.deepEqual(heads, ["Repo", "In progress", "Planned", "Done", "Open todos", "Plan inbox"]);
});

test("an empty list says no repo has synced yet", () => {
  for (const empty of [[], null]) {
    const root = renderRepos(empty);
    assert.match(collectText(root), /No repo has synced into this report directory yet\./);
    assert.equal(byTag(root, "table").length, 0);
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
  assert.equal(byTag(root, "tbody").length, 1);
  assert.equal(byClass(root, "empty").length, 0);
  assert.match(collectText(root), /alpha/);
});
