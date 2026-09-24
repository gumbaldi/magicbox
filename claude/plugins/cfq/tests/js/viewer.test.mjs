// Pure-function unit tests for portal/viewer.js -- run via `node --test tests/js/` (guarded by
// tests/test_portal_viewer.py, which skips this whole suite when Node isn't on PATH). ESM on
// purpose (`.mjs` is always ESM regardless of any package.json, and this plugin has none), loading
// the plain-CommonJS viewer.js through `createRequire` -- no bundler, no transpile step, matching
// the "no build step" rule for the viewer itself.

import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const viewer = require("../../portal/viewer.js");

// ---- a minimal fake DOM: just enough for the rendering functions under test, no jsdom -------

function fakeDoc() {
  return {
    createElement(tag) {
      return {
        tagName: tag,
        textContent: "",
        innerHTML: "",
        className: "",
        attrs: {},
        children: [],
        firstChild: null,
        setAttribute(k, v) { this.attrs[k] = v; },
        appendChild(c) { this.children.push(c); this.firstChild = this.children[0]; return c; },
        removeChild(c) {
          this.children = this.children.filter((x) => x !== c);
          this.firstChild = this.children[0] || null;
        },
      };
    },
  };
}

function fakeRoot() {
  return fakeDoc().createElement("div");
}

// Recursively collects every textContent/innerHTML string in a fake-DOM subtree, so a test can
// assert a value never reached innerHTML anywhere in the rendered output, not just at the top.
function collectHtml(node, acc) {
  acc = acc || [];
  if (node.innerHTML) acc.push(node.innerHTML);
  (node.children || []).forEach((c) => collectHtml(c, acc));
  return acc;
}

// ---- routine: grouping a mixed batch list into in progress / planned / done -----------------

test("groupBatches splits in_progress / planned+blocked+planning / done", () => {
  const batches = [
    { name: "a", status: "in_progress" },
    { name: "b", status: "planned" },
    { name: "c", status: "blocked" },
    { name: "d", status: "planning" },
    { name: "e", status: "done" },
  ];
  const groups = viewer.groupBatches(batches);
  assert.deepEqual(groups.inProgress.map((b) => b.name), ["a"]);
  assert.deepEqual(groups.planned.map((b) => b.name), ["b", "c", "d"]);
  assert.deepEqual(groups.done.map((b) => b.name), ["e"]);
});

test("plannedReason names the blocking dependency or the unknown one", () => {
  assert.equal(viewer.plannedReason({ status: "blocked", dependsOn: ["01-x"] }), "Waiting on 01-x");
  assert.equal(
    viewer.plannedReason({ status: "blocked", dependsOn: ["01-x"], unknownDeps: ["02-ghost"] }),
    "Unknown dependency: 02-ghost",
  );
  assert.equal(viewer.plannedReason({ status: "planning" }), "Still being planned");
  assert.equal(viewer.plannedReason({ status: "planned" }), "");
});

// ---- routine: two workers, each with one explorer, plus one orchestrator explorer -----------

test("buildCostTree groups agents into orchestrator/explorer/worker/worker-explorer with correct sums", () => {
  const implPhases = [
    {
      phase: "01-a",
      telemetry: {
        totals: { turns: 10, output: 1000, billable_in: 500 },
        layers: { main: { turns: 2, output: 200, billable_in: 100, models: ["sonnet"], efforts: ["medium"] } },
        agents: [
          { id: "orch-explore-1", type: "Explore", layer: "main_explore", parent: null,
            totals: { turns: 1, output: 50, billable_in: 20 } },
          { id: "w1", type: "cfq:cfq-phase-worker", description: "phase worker 01-a", layer: "worker",
            parent: null, totals: { turns: 3, output: 300, billable_in: 150 } },
          { id: "w1-explore-1", type: "Explore", layer: "worker_explore", parent: "w1",
            totals: { turns: 2, output: 150, billable_in: 80 } },
          { id: "w2", type: "cfq:cfq-phase-worker", description: "phase worker 01-a (2)", layer: "worker",
            parent: null, totals: { turns: 2, output: 300, billable_in: 150 } },
          { id: "w2-explore-1", type: "Explore", layer: "worker_explore", parent: "w2",
            totals: { turns: 1, output: 100, billable_in: 30 } },
        ],
      },
    },
  ];

  const tree = viewer.buildCostTree(implPhases);

  assert.equal(tree.workers.length, 2);
  tree.workers.forEach((w) => assert.equal(w.explorers.length, 1));
  assert.equal(tree.explorers.length, 1);

  assert.deepEqual(tree.orchestrator.totals, { turns: 2, output: 200, billable_in: 100 });
  assert.deepEqual(tree.explorersSum, { turns: 1, output: 50, billable_in: 20 });
  assert.deepEqual(tree.workersSum, { turns: 5, output: 600, billable_in: 300 });

  const w1 = tree.workers.find((w) => w.node.id === "w1");
  assert.deepEqual(viewer.sumNodeTotals(w1.explorers), { turns: 2, output: 150, billable_in: 80 });
  const w2 = tree.workers.find((w) => w.node.id === "w2");
  assert.deepEqual(viewer.sumNodeTotals(w2.explorers), { turns: 1, output: 100, billable_in: 30 });
});

// ---- edge: null impl data (a planned batch with no report.json yet) renders the plan-only view

test("renderBatchInto with null impl data renders the plan-only view, no crash", () => {
  const plan = {
    batch: "2026-09-23-demo",
    sections: { goal: "<p>Build the thing.</p>" },
    phases: [{ slug: "01-a", title: "First", size: "M", state: "open", bodyHtml: "<p>Do it.</p>" }],
  };
  const root = fakeRoot();
  const doc = fakeDoc();
  assert.doesNotThrow(() => viewer.renderBatchInto(doc, root, "2026-09-23-demo", plan, null));

  const html = collectHtml(root).join(" ");
  assert.match(html, /Build the thing/);
  // no cost/security section is rendered when there is no impl payload
  const texts = [];
  (function walk(n) { if (n.textContent) texts.push(n.textContent); (n.children || []).forEach(walk); })(root);
  assert.ok(texts.some((t) => /plan only/i.test(t)));
  assert.ok(!texts.some((t) => t === "Cost"));
});

// ---- edge: an unknown route falls back to the overview ---------------------------------------

test("parseRoute falls back to overview for an unrecognized hash", () => {
  assert.deepEqual(viewer.parseRoute("#/nonsense/path"), { name: "overview", param: null });
  assert.deepEqual(viewer.parseRoute(""), { name: "overview", param: null });
  assert.deepEqual(viewer.parseRoute("#/"), { name: "overview", param: null });
  assert.deepEqual(viewer.parseRoute("#/batch/"), { name: "overview", param: null });
  assert.deepEqual(viewer.parseRoute("#/batch/2026-09-23-demo"), { name: "batch", param: "2026-09-23-demo" });
  assert.deepEqual(viewer.parseRoute("#/entry/todo-2026-01-01-x"), { name: "entry", param: "todo-2026-01-01-x" });
});

// ---- must hold: a title containing <img onerror> ends up as text, never innerHTML -----------

test("el() always uses textContent, never innerHTML, even for markup-shaped text", () => {
  const doc = fakeDoc();
  const payload = "<img src=x onerror=alert(1)>";
  const e = viewer.el(doc, "h1", payload);
  assert.equal(e.textContent, payload);
  assert.equal(e.innerHTML, "");
});

test("renderEntryInto renders a malicious title as text, not as markup", () => {
  const doc = fakeDoc();
  const root = fakeRoot();
  const entry = {
    id: "todo-2026-01-01-x",
    kind: "todo",
    date: "2026-01-01",
    origin: "todo",
    check: true,
    title: "<img src=x onerror=alert(1)>",
    bodyHtml: "<p>safe pre-rendered body</p>",
  };
  viewer.renderEntryInto(doc, root, entry);

  const h1 = root.children.find((c) => c.tagName === "h1");
  assert.equal(h1.textContent, entry.title);
  assert.equal(h1.innerHTML, "");

  // the only innerHTML assignment anywhere in the tree is the pre-rendered, already-escaped body
  const htmlBlobs = collectHtml(root);
  assert.deepEqual(htmlBlobs, [entry.bodyHtml]);
  assert.ok(!htmlBlobs.some((h) => h.includes("<img")));
});

test("renderOverviewInto never leaks a batch goal or entry title into innerHTML", () => {
  const doc = fakeDoc();
  const root = fakeRoot();
  const queue = {
    batches: [{
      name: "2026-09-23-demo", status: "planned", priority: "high", open: 2, done: 0,
      goal: "<img src=x onerror=alert(1)>", cost: { total: { output: 100 } }, deviations: 0,
    }],
    entries: [{ id: "plan-x", kind: "plan", title: "<img src=x onerror=alert(2)>", date: "2026-01-01", check: false }],
  };
  viewer.renderOverviewInto(doc, root, queue);
  const htmlBlobs = collectHtml(root);
  assert.ok(!htmlBlobs.some((h) => h.includes("<img")), `innerHTML leaked markup: ${htmlBlobs}`);
});
