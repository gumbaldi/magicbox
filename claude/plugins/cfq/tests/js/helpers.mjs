// Shared test support for the portal viewer (tests/js/*.test.mjs): a minimal fake DOM, tree
// walkers, the portal loader and the data fixtures every viewer test needs, each in the full
// contract shape of `.batch-context.md` (Portal data files). Complete after batch 050 phase 11;
// later viewer phases add their own test files and never edit this one.

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const PORTAL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../portal");

// ---- fake DOM ------------------------------------------------------------------------------

class FakeNode {
  constructor(doc, tag, ns) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.namespaceURI = ns || null;
    this.nodeType = 1;
    this.className = "";
    this.attrs = {};
    this.children = [];
    this.firstChild = null;
    this.parentNode = null;
    this.listeners = {};
    this.style = {};
    this.value = "";
    this.focused = false;
    this._text = "";
    this._html = "";
  }
  get textContent() { return this._text; }
  set textContent(v) {
    this._text = v === null || v === undefined ? "" : String(v);
    this.children = [];
    this.firstChild = null;
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    this._html = String(v);
    this.ownerDocument.innerHtmlWrites.push({ node: this, value: this._html });
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) {
    c.parentNode = this;
    this.children.push(c);
    this.firstChild = this.children[0];
    return c;
  }
  insertBefore(c, ref) {
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at < 0) return this.appendChild(c);
    c.parentNode = this;
    this.children.splice(at, 0, c);
    this.firstChild = this.children[0];
    return c;
  }
  get nextSibling() {
    const sibs = this.parentNode ? this.parentNode.children : [];
    return sibs[sibs.indexOf(this) + 1] || null;
  }
  removeChild(c) {
    this.children = this.children.filter((x) => x !== c);
    this.firstChild = this.children[0] || null;
    c.parentNode = null;
    return c;
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  focus() { this.focused = true; this.ownerDocument.activeElement = this; }
  select() { this.selected = true; }
  closest(sel) {
    const tags = sel.split(",").map((s) => s.trim().toLowerCase());
    for (let n = this; n; n = n.parentNode) if (tags.includes(String(n.tagName).toLowerCase())) return n;
    return null;
  }
}

class FakeText {
  constructor(doc, text) {
    this.ownerDocument = doc;
    this.nodeType = 3;
    this.tagName = "#text";
    this.textContent = String(text);
    this.children = [];
    this.firstChild = null;
    this.parentNode = null;
  }
}

export function fakeDoc() {
  const doc = {
    innerHtmlWrites: [],
    listeners: {},
    activeElement: null,
    title: "",
    byId: {},
    execCommand: null,
    createElement(tag) { return new FakeNode(doc, tag); },
    createElementNS(ns, tag) { return new FakeNode(doc, tag, ns); },
    createTextNode(text) { return new FakeText(doc, text); },
    getElementById(id) { return doc.byId[id] || null; },
    addEventListener(type, fn) { (doc.listeners[type] = doc.listeners[type] || []).push(fn); },
    removeEventListener(type, fn) { doc.listeners[type] = (doc.listeners[type] || []).filter((f) => f !== fn); },
  };
  doc.body = new FakeNode(doc, "body");
  return doc;
}

// Runs `fn` with `globalThis.navigator.clipboard` replaced by `clipboard` (undefined = no clipboard
// API at all), then restores the original property.
export async function withClipboard(clipboard, fn) {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: clipboard === undefined ? {} : { clipboard }, configurable: true, writable: true });
  try {
    return await fn();
  } finally {
    if (saved) Object.defineProperty(globalThis, "navigator", saved);
    else delete globalThis.navigator;
  }
}

export function fakeRoot(doc) {
  return (doc || fakeDoc()).createElement("div");
}

// Fires every handler `node` (or the document) has registered for `type`.
export function fire(node, type, event) {
  const ev = Object.assign({ type, target: node, preventDefault() { this.prevented = true; } }, event || {});
  (node.listeners[type] || []).slice().forEach((fn) => fn(ev));
  return ev;
}

export function walk(node, fn) {
  fn(node);
  (node.children || []).forEach((c) => walk(c, fn));
}

export function findAll(node, pred) {
  const out = [];
  walk(node, (n) => { if (pred(n)) out.push(n); });
  return out;
}

export const byTag = (node, tag) => findAll(node, (n) => n.tagName === tag);
export const byClass = (node, cls) => findAll(node, (n) => n.className && n.className.split(/\s+/).includes(cls));

export function collectText(node) {
  const parts = [];
  walk(node, (n) => { if (n.textContent) parts.push(n.textContent); });
  return parts.join(" ");
}

// Every innerHTML string in the subtree.
export function collectHtml(node) {
  const out = [];
  walk(node, (n) => { if (n.nodeType === 1 && n.innerHTML) out.push(n.innerHTML); });
  return out;
}

export const links = (node) => byTag(node, "a").map((a) => a.attrs.href);

// ---- portal loader -------------------------------------------------------------------------

// Resets `globalThis.CFQ` and requires every portal/*.js that exists: core first, app last, the
// rest alphabetically. Returns the fresh namespace.
export function loadPortal() {
  globalThis.CFQ = {};
  const files = fs.readdirSync(PORTAL_DIR).filter((f) => f.endsWith(".js")).sort();
  const order = ["core.js", ...files.filter((f) => f !== "core.js" && f !== "app.js"), "app.js"]
    .filter((f) => files.includes(f));
  for (const f of order) {
    const full = path.join(PORTAL_DIR, f);
    delete require.cache[require.resolve(full)];
    require(full);
  }
  return globalThis.CFQ;
}

// ---- fixtures ------------------------------------------------------------------------------

// The `edit` target of an editable item as `portal sync` writes it (POSIX host, `vscode` editor).
export const editTarget = (p) => ({ path: p, url: "vscode://file" + p });
// A file's `edit`: the file path plus the folder that holds it (the only part that gets a link).
export const fileEdit = (p) => ({ path: p, dir: editTarget(p.slice(0, p.lastIndexOf("/"))) });
const BATCH_DIR = "/home/code/git/demo/.claude/cfq/impl/047-2026-10-01-demo";
const batchEdit = () => ({
  dir: editTarget(BATCH_DIR),
  context: { path: BATCH_DIR + "/.batch-context.md" },
});

const t5 = (turns, input, output, cache_read, cache_creation) => ({ turns, input, output, cache_read, cache_creation });
const ZERO = t5(0, 0, 0, 0, 0);
const addT5 = (a, b) => Object.fromEntries(Object.keys(ZERO).map((k) => [k, a[k] + b[k]]));
const subT5 = (a, b) => Object.fromEntries(Object.keys(ZERO).map((k) => [k, a[k] - b[k]]));

// Batch 063 phase 05: the shared fixtures carry the planning/implementation split additively (new
// keys only) because the "fixtures stay in the contract shape" check reads the real payload shape.
// A fixed planning share of a merged cost; the implementation part is the remainder, so
// planning + implementation == total, also per model.
const PLANNING_SHARE = t5(10, 100, 500, 2000, 300);
function splitCost(cost) {
  if (!cost) return cost;
  const [first] = Object.keys(cost.byModel);
  const implModels = { ...cost.byModel, [first]: subT5(cost.byModel[first], PLANNING_SHARE) };
  return {
    ...cost,
    planning: { total: PLANNING_SHARE, byModel: { [first]: PLANNING_SHARE } },
    implementation: { total: subT5(cost.total, PLANNING_SHARE), byModel: implModels },
  };
}
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export function fixtureSite(mode = "repo") {
  if (mode === "global") return { mode: "global" };
  return {
    mode: "repo",
    repo: "/home/code/git/demo",
    commitUrl: "https://github.com/acme/demo/commit/",
    pluginVersion: "0.29.0",
  };
}

function queueRow(name, over) {
  const [, number, date, title] = /^(\d+)-(\d{4}-\d{2}-\d{2})-(.+)$/.exec(name);
  const row = {
    name,
    number: Number(number),
    title: title.replace(/-/g, " "),
    date,
    status: "done",
    priority: "",
    dependsOn: [],
    unknownDeps: [],
    phases: { done: 2, total: 2 },
    goalHtml: `Goal of ${title.replace(/-/g, " ")}.`,
    started: `${date}T08:00:00Z`,
    finished: "",
    cost: { total: t5(100, 1000, 5000, 20000, 3000), byModel: { "claude-sonnet-5-5": t5(100, 1000, 5000, 20000, 3000) } },
    time: { planning: { wallclock_s: 3600, active_s: 900 }, implementation: { wallclock_s: 14400, active_s: 5400 } },
    deviations: 0,
    flags: { warn: 0, info: 0 },
    branch: `cfq/${name}`,
    base: "main",
    merged: null,
    settled: true,
    ...over,
  };
  return { ...row, cost: splitCost(row.cost), time: row.cost ? row.time : { planning: null, implementation: null } };
}

export function fixtureEntries() {
  return [
    {
      id: "todo-2026-10-01-merge-alpha", kind: "todo", state: "open", date: "2026-10-01",
      title: "Merge `cfq/045-2026-09-20-alpha-done`", check: "git branch --merged main",
      closed: null, origin: { batch: "045-2026-09-20-alpha-done", phase: "02-second" }, parkedInto: null,
    },
    {
      id: "todo-2026-10-02-plain", kind: "todo", state: "open", date: "2026-10-02",
      title: "Tidy the fixtures", check: null, closed: null, origin: null, parkedInto: null,
    },
    {
      id: "plan-2026-10-03-inbox", kind: "plan", state: "open", date: "2026-10-03",
      title: "Rework the `status` verb", check: null, closed: null,
      origin: { batch: "047-2026-10-01-gamma-progress", phase: "" }, parkedInto: null,
    },
    {
      id: "plan-2026-09-28-parked", kind: "plan", state: "done", date: "2026-09-28",
      title: "Parked follow-up", check: null, closed: "2026-10-02: parked into 049",
      origin: { batch: "045-2026-09-20-alpha-done", phase: "01-first" },
      parkedInto: "049-2026-10-05-epsilon-planned",
    },
    {
      id: "todo-2026-09-26-closed", kind: "todo", state: "done", date: "2026-09-26",
      title: "Old card", check: "true", closed: "2026-09-27", origin: null, parkedInto: null,
    },
  ];
}

export function fixtureQueue() {
  const batches = [
    queueRow("045-2026-09-20-alpha-done", {
      finished: "2026-09-22T10:00:00Z", deviations: 2, flags: { warn: 1, info: 2 }, merged: true,
      cost: { total: t5(120, 2000, 9000, 50000, 4000), byModel: { "claude-sonnet-5-5": t5(100, 1500, 7000, 40000, 3000), "claude-haiku-5": t5(20, 500, 2000, 10000, 1000) } },
    }),
    queueRow("046-2026-09-25-beta-done", {
      finished: "2026-09-28T12:00:00Z", merged: false,
      cost: { total: t5(40, 800, 1500000, 9000, 1200), byModel: { "claude-sonnet-5-5": t5(40, 800, 1500000, 9000, 1200) } },
    }),
    queueRow("047-2026-10-01-gamma-progress", {
      status: "in_progress", phases: { done: 1, total: 3 }, flags: { warn: 0, info: 1 }, deviations: 1,
      goalHtml: "Reach the <code>gamma</code> goal &amp; more",
    }),
    queueRow("048-2026-10-03-delta-review", { status: "awaiting_review", phases: { done: 0, total: 2 } }),
    queueRow("049-2026-10-05-epsilon-planned", { status: "planned", phases: { done: 0, total: 4 }, priority: "high" }),
    queueRow("050-2026-10-06-zeta-blocked", {
      status: "blocked", phases: { done: 0, total: 1 }, dependsOn: ["047-2026-10-01-gamma-progress"],
    }),
    queueRow("051-2026-10-07-eta-planning", {
      status: "planning", phases: { done: 0, total: 0 }, cost: null, goalHtml: "", settled: true,
    }),
  ];
  const entries = fixtureEntries();
  const open = entries.filter((e) => e.state === "open");
  const cost = batches.reduce((acc, b) => (b.cost ? addT5(acc, b.cost.total) : acc), ZERO);
  const finished = batches.filter((b) => b.status === "done" && b.cost)
    .sort((a, b) => (a.finished < b.finished ? 1 : a.finished > b.finished ? -1 : a.name.localeCompare(b.name)));
  const sumOf = (rows, pick) => rows.reduce((acc, b) => addT5(acc, pick(b)), ZERO);
  const modelsOf = (rows, pick) => rows.reduce((acc, b) => {
    for (const [m, t] of Object.entries(pick(b))) acc[m] = acc[m] ? addT5(acc[m], t) : t;
    return acc;
  }, {});
  const perPhase = finished.flatMap((b) => Array(b.phases.done).fill(b.cost.implementation.total.output / b.phases.done));
  const recent = {
    batches: finished.map((b) => b.name),
    planning: {
      total: sumOf(finished, (b) => b.cost.planning.total), byModel: modelsOf(finished, (b) => b.cost.planning.byModel),
      wallclock_s: finished.reduce((n, b) => n + b.time.planning.wallclock_s, 0),
      active_s: finished.reduce((n, b) => n + b.time.planning.active_s, 0),
      medianOutput: median(finished.map((b) => b.cost.planning.total.output)),
    },
    implementation: {
      total: sumOf(finished, (b) => b.cost.implementation.total), byModel: modelsOf(finished, (b) => b.cost.implementation.byModel),
      wallclock_s: finished.reduce((n, b) => n + b.time.implementation.wallclock_s, 0),
      active_s: finished.reduce((n, b) => n + b.time.implementation.active_s, 0),
      phases: perPhase.length, outputPerPhase: median(perPhase),
    },
  };
  return {
    repo: "/home/code/git/demo",
    totals: {
      batches: { inProgress: 1, planned: 4, done: 2 },
      todos: open.filter((e) => e.kind === "todo").length,
      planEntries: open.filter((e) => e.kind === "plan").length,
      deviations: batches.reduce((n, b) => n + b.deviations, 0),
      flags: {
        warn: batches.reduce((n, b) => n + b.flags.warn, 0),
        info: batches.reduce((n, b) => n + b.flags.info, 0),
      },
      cost,
    },
    baselines: {
      S: { n: 5, nAll: 5, turnsMedian: 20, outputMedian: 9000, allTimeTurnsMedian: 20, allTimeOutputMedian: 9000 },
      M: { n: 6, nAll: 6, turnsMedian: 40, outputMedian: 20000, allTimeTurnsMedian: 40, allTimeOutputMedian: 20000 },
    },
    sizes: [
      { batch: "045-2026-09-20-alpha-done", phase: "01-first", size: "S", turns: 18, output: 8000, finished: "2026-09-21T10:00:00Z" },
      { batch: "045-2026-09-20-alpha-done", phase: "02-second", size: "M", turns: 44, output: 21000, finished: "2026-09-21T12:00:00Z" },
    ],
    attention: [
      { level: "warn", code: "red-attempt", batch: "047-2026-10-01-gamma-progress", phase: "01-a", text: "phase is red" },
      { level: "plan", code: "review", batch: "049-2026-10-05-delta-review", phase: null, text: "plan review open" },
    ],
    attentionCounts: { warn: 1, plan: 1 },
    now: [
      {
        batch: "047-2026-10-01-gamma-progress", number: 47, title: "gamma progress", status: "in_progress",
        phases: { done: 1, total: 3, skipped: 0, error: 0 }, current: { num: 2, title: "Second step" }, waitsOn: [],
      },
    ],
    recent,
    batches,
    entries,
  };
}

const cost = (total, byModel, layers, agents) => ({ total, byModel, layers, agents });
const layer = (total, byModel, count) => ({ total, byModel, count });

function doneCost() {
  const sonnet = t5(60, 900, 5000, 30000, 2500);
  const haiku = t5(15, 300, 1200, 8000, 700);
  const total = addT5(sonnet, haiku);
  return cost(
    total,
    { "claude-sonnet-5-5": sonnet, "claude-haiku-5": haiku },
    {
      main: layer(t5(20, 300, 1000, 10000, 800), { "claude-sonnet-5-5": t5(20, 300, 1000, 10000, 800) }, 1),
      main_explore: layer(ZERO, {}, 0),
      worker: layer(t5(40, 600, 4000, 20000, 1700), { "claude-sonnet-5-5": t5(40, 600, 4000, 20000, 1700) }, 1),
      worker_explore: layer(t5(15, 300, 1200, 8000, 700), { "claude-haiku-5": t5(15, 300, 1200, 8000, 700) }, 1),
    },
    [
      { id: "a1", type: "cfq:cfq-phase-worker", description: "Implement phase", layer: "worker", parent: null, total: t5(40, 600, 4000, 20000, 1700), byModel: { "claude-sonnet-5-5": t5(40, 600, 4000, 20000, 1700) } },
      { id: "a2", type: "Explore", description: "Locate code", layer: "worker_explore", parent: "a1", total: t5(15, 300, 1200, 8000, 700), byModel: { "claude-haiku-5": t5(15, 300, 1200, 8000, 700) } },
    ],
  );
}

function attempt(over) {
  return {
    status: "green", summary: "Built it.", verification: "python3 -m unittest: OK", deviations: [],
    observations: [], errors: [], triggers: [], question: "", commit: "abc1234", reopened: false,
    diffstat: { files: 2, insertions: 30, deletions: 4, paths: [{ path: "scripts/a.py", added: 25, deleted: 4 }, { path: "assets/logo.png", added: null, deleted: null }] },
    filesTouched: ["/home/code/git/demo/scripts/a.py"], parkedPlanEntries: [],
    time: { from: "2026-10-01T08:00:00Z", until: "2026-10-01T08:30:00Z", wallclock_s: 1800, active_s: 1500 },
    settled: true, mode: "orchestrator", cost: doneCost(), tools: { Bash: 12, Edit: 8 },
    skills: { used: [] },
    ...over,
  };
}

export function fixtureBatch(kind = "done") {
  const base = {
    name: "047-2026-10-01-demo", status: "done", priority: "", dependsOn: [], branch: "cfq/047-2026-10-01-demo",
    base: "main", merged: true, started: "2026-10-01T08:00:00Z", finished: "2026-10-01T12:00:00Z",
    outcome: "green", context: { goal: "<p>Demo goal.</p>", decisions: "<ul><li>One</li></ul>" },
    planning: null, implementation: null, phases: [], cost: null, notes: [], fromPlan: [], closing: null, security: null, flags: [],
  };
  const phase = (num, slug, title, state, attempts, flags) => ({
    slug, num, title, size: "S", state, planHtml: `<p>Plan of ${title}.</p>`,
    affectedFiles: ["scripts/a.py"], attempts, flags: flags || [], baseline: null,
  });
  const openPhase = (num, slug, title) => ({
    ...phase(num, slug, title, "open", []), edit: fileEdit(`${BATCH_DIR}/${slug}.md`),
  });
  if (kind === "plan_only") {
    return {
      ...base, status: "planned", started: "", finished: "", outcome: "", merged: null, edit: batchEdit(),
      phases: [openPhase(1, "01-first", "First"), openPhase(2, "02-second", "Second")],
    };
  }
  if (kind === "in_progress") {
    return {
      ...base, status: "in_progress", finished: "", outcome: "", merged: null, edit: batchEdit(),
      phases: [
        phase(1, "01-first", "First", "done", [attempt({})]),
        openPhase(2, "02-second", "Second"),
        openPhase(3, "03-third", "Third"),
      ],
      implementation: {
        from: "2026-10-01T08:00:00Z", until: "2026-10-01T08:30:00Z", wallclock_s: 1800, active_s: 1500,
        activeComplete: true, cost: doneCost(),
      },
      cost: doneCost(),
    };
  }
  const done = {
    ...base,
    planning: {
      from: "2026-10-01T06:00:00Z", until: "2026-10-01T07:00:00Z", wallclock_s: 3600, active_s: 1800, settled: true,
      cost: doneCost(), interviewDepth: "thorough", phaseCount: 2,
      audit: [{ started: "2026-10-01T07:00:00Z", finished: "2026-10-01T07:05:00Z", findings: 1 }],
    },
    implementation: {
      from: "2026-10-01T08:00:00Z", until: "2026-10-01T10:40:00Z", wallclock_s: 9600, active_s: 2400,
      activeComplete: false, cost: doneCost(),
    },
    phases: [
      phase(1, "01-first", "First", "done", [attempt({})]),
      phase(2, "02-second", "Second", "done", [
        attempt({ status: "red", summary: "", errors: ["AssertionError: boom"], commit: "", diffstat: null, time: { from: "2026-10-01T09:00:00Z", until: "2026-10-01T09:20:00Z", wallclock_s: 1200, active_s: 900 } }),
        attempt({
          deviations: ["Touched an extra file"], observations: ["The helper is duplicated"],
          parkedPlanEntries: ["plan/2026-10-01-follow-up.md"], settled: false,
          time: { from: "2026-10-01T10:00:00Z", until: "2026-10-01T10:40:00Z", wallclock_s: 2400, active_s: null },
        }),
      ], [{ level: "warn", code: "retry", text: "Phase needed a second attempt", phase: "02-second" }]),
    ],
    cost: doneCost(),
    notes: [
      { kind: "todo", id: "todo-2026-10-01-open-card", title: "Open `card`", at: "2026-10-01T09:30:00Z", phase: "02-second", framework: false, state: "open" },
      { kind: "plan", id: "plan-2026-10-01-done-entry", title: "Done entry", at: "2026-10-01T09:31:00Z", phase: "01-first", framework: false, state: "done" },
      { kind: "plan", id: "plan-2026-10-01-framework", title: "Framework finding", at: "2026-10-01T09:32:00Z", phase: "02-second", framework: true, state: "missing" },
    ],
    fromPlan: [{ id: "plan-2026-09-30-origin", title: "Where it came from" }],
    closing: {
      at: "2026-10-01T12:00:00Z",
      lang: { issues: 1, findings: ["Docs lack a German counterpart"] },
      maintenance: "ran", security: { planning: 0, now: 1, new: 1 }, changelog: "written",
      errors: ["push failed: no remote"],
    },
    security: { available: true, counts: { high: 1 }, findings: [{ severity: "high", title: "Unchecked input" }], hint: "" },
    flags: [{ level: "info", code: "unsettled", text: "One attempt is not settled yet", phase: null }],
  };
  // Output per phase is 6200 and 12400 (all attempts): 1.0x and 2.5x their size-S baseline.
  done.phases[0].baseline = { size: "S", outputMedian: 6200, turnsMedian: 75 };
  done.phases[1].baseline = { size: "S", outputMedian: 4960, turnsMedian: 75 };
  return done;
}

export function fixtureEntry(kind = "todo_open") {
  if (kind === "plan_closed") {
    return {
      id: "plan-2026-09-28-parked", kind: "plan", state: "done", date: "2026-09-28",
      title: "Parked follow-up", check: null, closed: "2026-10-02: parked into 049",
      origin: { batch: "045-2026-09-20-alpha-done", phase: "01-first" },
      parkedInto: "049-2026-10-05-epsilon-planned", bodyHtml: "<p>Body of the plan entry.</p>",
    };
  }
  return {
    id: "todo-2026-10-01-merge-alpha", kind: "todo", state: "open", date: "2026-10-01",
    title: "Merge `cfq/045-2026-09-20-alpha-done`", check: "git branch --merged main",
    closed: null, origin: null, parkedInto: null, bodyHtml: "<p>Body of the todo card.</p>",
    edit: fileEdit("/home/code/git/demo/.claude/cfq/todo/2026-10-01-merge-alpha.md"),
  };
}

export function fixtureRepos() {
  return [
    { name: "alpha", mirror: "alpha", source: "/home/code/git/alpha", counts: { batches: { inProgress: 1, planned: 2, done: 3 }, todos: 2, planEntries: 1 } },
    { name: "beta", mirror: "beta-1a2b3c", source: "/home/code/git/beta", counts: { batches: { inProgress: 0, planned: 0, done: 5 }, todos: 0, planEntries: 0 } },
  ];
}
