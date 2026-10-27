// End-to-end walk of the viewer over the files a real `portal sync` wrote. Skipped unless
// CFQ_PORTAL_DIR names a reports directory (`<repo>/.claude/cfq/reports`); tests/test_portal_viewer.py
// builds one and sets it. No data file is evaluated up front: the router asks for each file it needs
// and the loader below reads exactly that path from disk, so a viewer requesting a path the data
// layer never writes fails here instead of rendering an empty page. With CFQ_PORTAL_GLOBAL_DIR set
// too, the same walk covers the cross-repo index of a `reportDir` mirror.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fakeDoc, fakeRoot, byClass, collectText, loadPortal } from "./helpers.mjs";

const DIR = process.env.CFQ_PORTAL_DIR;
const GLOBAL_DIR = process.env.CFQ_PORTAL_GLOBAL_DIR;
const CFQ = loadPortal();
const BATCH_TABS = ["phases", "cost", "context", "notes", "closing"];

function loaderFor(dir, failures) {
  return async function load(p) {
    const file = path.join(dir, p + ".js");
    if (!fs.existsSync(file)) {
      failures.push(`missing data file for "${p}": ${file}`);
      return null;
    }
    const sandbox = { window: {} };
    vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
    const key = p.slice(p.lastIndexOf("data/") + 5);
    const data = sandbox.window.CFQ_DATA;
    if (!data || !Object.prototype.hasOwnProperty.call(data, key)) {
      failures.push(`${file} does not register CFQ_DATA["${key}"]`);
      return null;
    }
    return data[key];
  };
}

async function walk(hash, load, failures, expectText) {
  const doc = fakeDoc();
  doc.byId.crumbs = doc.createElement("nav");
  doc.byId["site-title"] = doc.createElement("span");
  const root = fakeRoot(doc);
  try {
    await CFQ.app.render(doc, root, hash, load);
  } catch (err) {
    failures.push(`${hash}: threw ${err && err.message}`);
    return null;
  }
  const text = collectText(root);
  if (!root.children.length) failures.push(`${hash}: rendered nothing`);
  if (text.includes("This view is not available.")) failures.push(`${hash}: view not available`);
  if (text.includes("could not be rendered")) failures.push(`${hash}: ${text.slice(0, 200)}`);
  for (const want of expectText || []) {
    if (!text.includes(want)) failures.push(`${hash}: page text lacks "${want}"`);
  }
  return text;
}

// The routes of one reports directory, relative to its mount `prefix` ("" or "<mirror>/").
async function walkRepo(dir, prefix, onlyOneBatch) {
  const failures = [];
  const load = loaderFor(dir, failures);
  const base = prefix ? `#/${prefix}` : "#/";
  const dataPrefix = prefix ? `${prefix}data/` : "data/";
  const queue = await load(prefix ? `${prefix}data/queue` : "data/queue");
  assert.ok(queue && Array.isArray(queue.batches), "queue.js did not load");

  for (const tab of ["", "todos", "inbox", "archive"]) await walk(base + tab, load, failures);

  const batches = onlyOneBatch ? queue.batches.slice(0, 1) : queue.batches;
  for (const row of batches) {
    const batch = await load(`${dataPrefix}batch/${row.name}`);
    const titles = batch ? batch.phases.map((p) => p.title) : [];
    await walk(`${base}batch/${row.name}`, load, failures, titles);
    if (onlyOneBatch) continue;
    for (const tab of BATCH_TABS) await walk(`${base}batch/${row.name}/${tab}`, load, failures);
    for (const ph of batch ? batch.phases : []) {
      await walk(`${base}batch/${row.name}/phase/${ph.slug}`, load, failures);
    }
  }
  if (!onlyOneBatch) {
    for (const entry of queue.entries) await walk(`${base}entry/${entry.id}`, load, failures);
  }
  return failures;
}

test("every view renders from the files a real portal sync wrote", { skip: !DIR }, async () => {
  const failures = await walkRepo(DIR, "", false);
  assert.deepEqual(failures, []);
});

test("the open batch's header and plan tab render edit controls from a real sync", { skip: !DIR }, async () => {
  const failures = [];
  const load = loaderFor(DIR, failures);
  const queue = await load("data/queue");
  let checked = 0;
  for (const row of queue.batches) {
    const batch = await load(`data/batch/${row.name}`);
    const phase = batch.phases.find((p) => p.state !== "done");
    if (!phase) continue;
    checked += 1;
    assert.ok(batch.edit && phase.edit, `${row.name}: sync wrote no edit object`);
    const doc = fakeDoc();
    const header = fakeRoot(doc);
    CFQ.batch.render(doc, header, { mode: "repo", repo: "/x", site: {}, batch, route: { name: "batch", batch: row.name }, setCrumbs() {} });
    assert.ok(byClass(header, "edit-controls").length >= 1, `${row.name}: header lacks edit controls`);
    const plan = fakeRoot(doc);
    CFQ.core.registered("phaseTab").find((t) => t.id === "plan").render(doc, plan, { mode: "repo", site: {} }, phase);
    assert.equal(byClass(plan, "edit-controls").length, 1, `${row.name}/${phase.slug}: plan tab lacks edit controls`);
    assert.ok(byClass(plan, "edit-copy")[0].textContent === "Copy path");
  }
  assert.ok(checked >= 1, "no batch with an open phase in the synced data");
  assert.deepEqual(failures, []);
});

test("the cross-repo index and each mirror render from the global directory", { skip: !GLOBAL_DIR }, async () => {
  const failures = [];
  const load = loaderFor(GLOBAL_DIR, failures);
  const repos = await load("data/repos");
  assert.ok(Array.isArray(repos) && repos.length, "repos.js lists no repo");
  await walk("#/", load, failures, repos.map((r) => r.name));
  assert.deepEqual(failures, []);
  for (const repo of repos) {
    const mirrorFailures = await walkRepo(GLOBAL_DIR, `${repo.mirror}/`, true);
    assert.deepEqual(mirrorFailures, [], repo.mirror);
  }
});
