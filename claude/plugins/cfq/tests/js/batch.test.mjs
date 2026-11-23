// Tests for portal/batch.js: slots, pure helpers, the header, the tab bar, the phase table with its
// per-phase detail, the Plan context tab and the safety rules.

import test from "node:test";
import assert from "node:assert/strict";
import {
  fakeDoc, fakeRoot, fire, byTag, byClass, findAll, collectText, collectHtml, links, loadPortal,
  fixtureSite, fixtureBatch,
} from "./helpers.mjs";

const CFQ = loadPortal();
const B = CFQ.batch;
const site = fixtureSite();

function ctxFor(batch, over) {
  const route = Object.assign({ name: "batch", tab: null, batch: batch ? batch.name : "x", phase: null, mirror: null }, (over && over.route) || {});
  return Object.assign({
    mode: "repo", repo: site.repo, mirror: null, site, batch, setCrumbs() {},
  }, over || {}, { route });
}

function draw(batch, over, doc) {
  const d = doc || fakeDoc();
  const root = fakeRoot(d);
  const crumbs = [];
  B.render(d, root, ctxFor(batch, Object.assign({ setCrumbs: (c) => crumbs.push(c) }, over || {})));
  return { doc: d, root, crumbs };
}

const buttons = (node, label) => byTag(node, "button").filter((b) => collectText(b).includes(label));
const rowToggles = (node) => byClass(node, "phase-row").map((tr) => byClass(tr, "disclosure-toggle")[0]);

test("loading batch.js registers its tabs and sub-tabs", () => {
  // loadPortal() loads every script, so the cost, notes and closing parts of batch 050 phase 14 are
  // registered next to batch.js's own.
  const C = CFQ.core;
  assert.deepEqual(C.registered("batchTab").map((t) => [t.id, t.order]),
    [["phases", 10], ["cost", 20], ["context", 30], ["notes", 40], ["closing", 50]]);
  assert.deepEqual(C.registered("phaseTab").map((t) => [t.id, t.order]), [["result", 10], ["plan", 20], ["cost", 30], ["files", 40]]);
  assert.deepEqual(C.registered("batchTab").map((t) => t.label), ["Phases", "Cost", "Plan context", "Notes", "Closing"]);
});

test("phaseRows: one row per phase with sums, latest attempt and status", () => {
  const rows = B.phaseRows(fixtureBatch("done"));
  assert.equal(rows.length, 2);
  const [one, two] = rows;
  assert.equal(one.status, "green");
  assert.equal(one.failed, 0);
  assert.equal(one.turns, 75);
  assert.equal(one.worked, "2026-10-01T08:00:00Z");
  assert.equal(one.duration, 1800);
  assert.equal(one.devCount, 0);
  assert.equal(two.failed, 1);
  assert.equal(two.turns, 150);
  assert.equal(two.out, 2 * 6200);
  assert.equal(two.in, 2 * (1200 + 3200));
  assert.equal(two.duration, 3600);
  assert.equal(two.devCount, 1);
  assert.equal(two.worked, "2026-10-01T10:00:00Z");
  assert.equal(two.latest.status, "green");
  const open = B.phaseRows(fixtureBatch("plan_only"));
  assert.equal(open[0].status, "open");
  assert.equal(open[0].latest, null);
  assert.equal(open[0].turns, null);
  assert.equal(open[0].duration, null);
  assert.equal(open[0].worked, null);
  assert.deepEqual(B.phaseRows(null), []);
});

test("fileRows: planned, unplanned, untouched; fallback to filesTouched; empty", () => {
  const phase = { affectedFiles: ["scripts/a.py", "docs/x.md"] };
  const withStat = { diffstat: { paths: [{ path: "scripts/a.py", added: 3, deleted: 1 }, { path: "img/b.png", added: null, deleted: null }] } };
  assert.deepEqual(B.fileRows(phase, withStat), [
    { path: "scripts/a.py", added: 3, deleted: 1, kind: "planned" },
    { path: "img/b.png", added: null, deleted: null, kind: "unplanned" },
    { path: "docs/x.md", added: null, deleted: null, kind: "untouched" },
  ]);
  const touched = { diffstat: null, filesTouched: ["/home/code/git/demo/scripts/a.py", "/home/code/git/demo/other.py"] };
  assert.deepEqual(B.fileRows(phase, touched, "/home/code/git/demo"), [
    { path: "scripts/a.py", added: null, deleted: null, kind: "planned" },
    { path: "other.py", added: null, deleted: null, kind: "unplanned" },
  ]);
  // Without the repo root an absolute path still becomes the plan's relative form.
  assert.equal(B.fileRows(phase, touched)[0].path, "scripts/a.py");
  assert.deepEqual(B.fileRows(phase, null), []);
  assert.deepEqual(B.fileRows(phase, { diffstat: null, filesTouched: [] }), []);
});

test("shortSha and commitHref", () => {
  assert.equal(B.shortSha("abcdef1234567"), "abcdef1");
  assert.equal(B.shortSha(""), "");
  assert.equal(B.commitHref(site, "abc1234"), "https://github.com/acme/demo/commit/abc1234");
  assert.equal(B.commitHref({ commitUrl: "" }, "abc1234"), null);
  assert.equal(B.commitHref(null, "abc1234"), null);
});

test("headerFacts: figures from the batch, null without telemetry", () => {
  const f = B.headerFacts(fixtureBatch("done"));
  assert.equal(f.elapsed, 4 * 3600);
  assert.deepEqual(f.phases, { done: 2, total: 2 });
  assert.equal(f.turns, 75);
  assert.equal(f.in, 900 + 300 + 2500 + 700);
  assert.equal(f.out, 6200);
  assert.equal(f.branch, "cfq/047-2026-10-01-demo");
  assert.equal(f.base, "main");
  assert.equal(f.merged, true);
  const p = B.headerFacts(fixtureBatch("plan_only"));
  assert.equal(p.turns, null);
  assert.equal(p.in, null);
  assert.equal(p.out, null);
  assert.equal(p.started, null);
  assert.equal(p.elapsed, null);
  assert.equal(p.merged, null);
  assert.deepEqual(p.phases, { done: 0, total: 2 });
});

test("header: title, status, priority, dependencies, goal, facts and flags", () => {
  const batch = fixtureBatch("done");
  batch.priority = "high";
  batch.dependsOn = ["045-2026-09-20-alpha-done"];
  batch.flags = [
    { level: "warn", code: "retry", text: "Phase needed a second attempt", phase: "02-second" },
    { level: "info", code: "a", text: "Note A", phase: null },
    { level: "info", code: "b", text: "Note B", phase: "01-first" },
  ];
  const { root, crumbs } = draw(batch);
  const text = collectText(root);
  assert.equal(byTag(root, "h1")[0].textContent, "047 · demo");
  assert.match(text, /Done/);
  assert.equal(byClass(root, "priority")[0].textContent, "high");
  assert.ok(links(root).includes("#/batch/045-2026-09-20-alpha-done"));
  assert.ok(collectHtml(root).includes("<p>Demo goal.</p>"));
  assert.match(text, /Phase needed a second attempt/);
  assert.ok(links(root).includes("#/batch/047-2026-10-01-demo/phase/02-second"));
  assert.match(text, /1 a note · 1 b note/);
  assert.doesNotMatch(text, /Note A/); // info flags stay collapsed
  assert.doesNotMatch(text, /no warnings/); // a warn flag is present
  assert.match(text, /cfq\/047-2026-10-01-demo/);
  assert.match(text, /2 of 2 phases green/);
  assert.deepEqual(crumbs[0].map((c) => c.href), ["#/", null]);
  assert.equal(crumbs[0][1].label, "047-2026-10-01-demo");
});

test("tab bar lists exactly the registered tabs; unknown tab falls back to Phases", () => {
  const batch = fixtureBatch("done");
  const { root } = draw(batch);
  const nav = byTag(root, "nav")[0];
  assert.deepEqual(byTag(nav, "a").map((a) => a.textContent), ["Phases (2)", "Cost", "Plan context", "Notes (5)", "Closing"]);
  assert.deepEqual(links(nav), ["phases", "cost", "context", "notes", "closing"].map((t) => "#/batch/047-2026-10-01-demo/" + t));

  const ctx = draw(batch, { route: { tab: "context" } });
  assert.match(collectText(ctx.root), /Decisions/);
  assert.equal(byClass(ctx.root, "active")[0].textContent, "Plan context");

  const unknown = draw(batch, { route: { tab: "nonsense" } });
  assert.equal(byClass(unknown.root, "active")[0].textContent, "Phases (2)");
  assert.equal(byTag(unknown.root, "table").length, 1);
});

test("a phase title with backticks shows the words as code, not the backtick characters", () => {
  const batch = fixtureBatch("done");
  batch.phases[0].title = "`bin/cfq portal sync`: data files";
  const { root } = draw(batch);
  const title = byClass(root, "phase-title")[0];
  assert.ok(byTag(title, "code").some((c) => c.textContent === "bin/cfq portal sync"));
  assert.doesNotMatch(collectText(title), /`/);
  assert.match(collectText(title), /data files/);
});

test("phases table: columns, one row per phase, closed by default", () => {
  const { root } = draw(fixtureBatch("done"));
  const table = byTag(root, "table")[0];
  assert.deepEqual(byTag(table, "th").map((th) => th.textContent),
    ["#", "Phase", "Size", "Status", "Time", "Active", "Turns", "Out", "Notes"]);
  assert.equal(byClass(table, "phase-row").length, 2);
  const toggles = rowToggles(table);
  assert.equal(toggles.length, 2);
  assert.ok(toggles.every((b) => b.tagName === "button" && b.attrs["aria-expanded"] === "false"));
  assert.equal(byClass(table, "phase-detail").length, 0);
  // The red first attempt of phase 2 is visible next to its green status.
  assert.match(collectText(table), /1 earlier red/);
  // Out is a token bar scaled to the largest phase.
  assert.equal(byClass(table, "tokbar").length, 2);
});

test("opening a row shows sub-tabs and the Result of the latest attempt", () => {
  const { root } = draw(fixtureBatch("done"));
  const toggle = rowToggles(root)[1];
  fire(toggle, "click");
  assert.equal(toggle.attrs["aria-expanded"], "true");
  const panel = byClass(root, "phase-detail")[0];
  assert.deepEqual(byClass(panel, "subtab").map((b) => b.textContent), ["Result", "Plan", "Cost", "Files"]);
  assert.equal(byClass(panel, "subtab active")[0]?.textContent ?? byClass(panel, "active")[0].textContent, "Result");
  const text = collectText(panel);
  for (const label of ["Implemented", "Verification", "Deviations", "Observations", "Mode", "Diffstat", "Commit"]) {
    assert.match(text, new RegExp(label));
  }
  assert.match(text, /Built it\./);
  assert.match(text, /Touched an extra file/);
  assert.match(text, /The helper is duplicated/);
  assert.match(text, /2 files · \+30 −4/);
  assert.match(text, /provisional/);
  assert.match(text, /orchestrator/);
  assert.doesNotMatch(text, /Errors/);
  assert.doesNotMatch(text, /Triggers/);
  assert.ok(links(panel).includes("#/entry/plan-2026-10-01-follow-up"));
  const commit = byTag(panel, "a").find((a) => a.textContent === "abc1234");
  assert.equal(commit.attrs.href, "https://github.com/acme/demo/commit/abc1234");
  assert.equal(byClass(panel, "prewrap")[0].textContent, "python3 -m unittest: OK");
  // Closing hides the detail again without touching the hash.
  fire(toggle, "click");
  assert.equal(toggle.attrs["aria-expanded"], "false");
});

test("commit is plain text without a commit URL; clean attempts say none", () => {
  const batch = fixtureBatch("done");
  const s = { ...site, commitUrl: "" };
  const d = fakeDoc();
  const root = fakeRoot(d);
  B.render(d, root, ctxFor(batch, { site: s }));
  fire(rowToggles(root)[0], "click");
  const panel = byClass(root, "phase-detail")[0];
  assert.equal(byTag(panel, "a").filter((a) => a.textContent === "abc1234").length, 0);
  assert.ok(byTag(panel, "code").some((c) => c.textContent === "abc1234"));
  const dds = byTag(panel, "dd").map((dd) => collectText(dd).trim());
  assert.equal(dds.filter((t) => t === "none").length, 2); // deviations and observations
});

test("several attempts: selector lists all, newest selected, switching redraws", () => {
  const { root } = draw(fixtureBatch("done"));
  fire(rowToggles(root)[1], "click");
  const panel = byClass(root, "phase-detail")[0];
  const select = byTag(panel, "select")[0];
  const options = byTag(select, "option");
  assert.equal(options.length, 2);
  assert.match(options[0].textContent, /red/);
  assert.match(options[1].textContent, /green/);
  assert.equal(select.value, "1");
  assert.equal(options[1].attrs.selected, "selected");
  select.value = "0";
  fire(select, "change");
  const redPanel = byClass(root, "phase-detail")[0];
  const text = collectText(redPanel);
  assert.match(text, /Errors/);
  assert.match(text, /AssertionError: boom/);
  assert.doesNotMatch(text, /Touched an extra file/);
  assert.doesNotMatch(text, /Commit/);
  // A single attempt gets no selector.
  const one = draw(fixtureBatch("done"));
  fire(rowToggles(one.root)[0], "click");
  assert.equal(byTag(one.root, "select").length, 0);
});

test("Plan and Files sub-tabs", () => {
  const { root } = draw(fixtureBatch("done"));
  fire(rowToggles(root)[0], "click");
  let panel = byClass(root, "phase-detail")[0];
  fire(buttons(panel, "Plan")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  assert.ok(collectHtml(panel).includes("<p>Plan of First.</p>"));
  assert.ok(byClass(panel, "prose").length >= 1);
  fire(buttons(panel, "Files")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  const rows = byTag(panel, "tbody")[0].children;
  assert.equal(rows.length, 2);
  const text = collectText(panel);
  assert.match(text, /scripts\/a\.py/);
  assert.match(text, /\+25 −4/);
  assert.match(text, /planned/);
  assert.match(text, /unplanned/);
  assert.match(text, /binary/);
});

test("Files: no data recorded; a phase without attempts is Not started", () => {
  const { root } = draw(fixtureBatch("plan_only"));
  fire(rowToggles(root)[0], "click");
  let panel = byClass(root, "phase-detail")[0];
  assert.match(collectText(panel), /Not started\./);
  fire(buttons(panel, "Files")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  assert.match(collectText(panel), /No file data recorded\./);
  fire(buttons(panel, "Plan")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  assert.ok(collectHtml(panel).includes("<p>Plan of First.</p>"));
});

test("the phase route renders that row open and the others closed", () => {
  const { root } = draw(fixtureBatch("done"), { route: { phase: "02-second" } });
  const toggles = rowToggles(root);
  assert.deepEqual(toggles.map((b) => b.attrs["aria-expanded"]), ["false", "true"]);
  assert.equal(byClass(root, "phase-detail").length, 1);
  assert.equal(byTag(root, "nav")[0].children.length, 5);
  assert.equal(byClass(root, "active")[0].textContent, "Phases (2)");
});

test("Plan context: every section but the goal, or a notice", () => {
  const batch = fixtureBatch("done");
  batch.context = { goal: "<p>G</p>", decisions: "<ul><li>One</li></ul>", "cross-phase contracts": "<p>C</p>" };
  const { root } = draw(batch, { route: { tab: "context" } });
  assert.deepEqual(byTag(byClass(root, "batch-tab")[0], "h3").map((h) => h.textContent), ["Decisions", "Cross phase contracts"]);
  const html = collectHtml(byClass(root, "batch-tab")[0]);
  assert.deepEqual(html, ["<ul><li>One</li></ul>", "<p>C</p>"]);
  batch.context = {};
  const empty = draw(batch, { route: { tab: "context" } });
  assert.match(collectText(byClass(empty.root, "batch-tab")[0]), /No batch context recorded\./);
  batch.context = { goal: "<p>G</p>" };
  const goalOnly = draw(batch, { route: { tab: "context" } });
  assert.match(collectText(byClass(goalOnly.root, "batch-tab")[0]), /No batch context recorded\./);
});

test("the plan-only batch renders without figures: empty cards, dashes in the table", () => {
  const { root } = draw(fixtureBatch("plan_only"));
  assert.match(collectText(byClass(root, "result")[0]), /0 of 2 phases green/);
  assert.doesNotMatch(collectText(byClass(root, "result")[0]), /merged/);
  const cards = byClass(root, "part");
  assert.equal(cards.length, 2);
  for (const card of cards) assert.match(collectText(card), /No telemetry recorded\./);
  const rows = byClass(root, "phase-row");
  assert.equal(rows.length, 2);
  for (const tr of rows) {
    const cells = byTag(tr, "td");
    assert.equal(collectText(cells[4]).trim(), "–"); // time
    assert.equal(collectText(cells[5]).trim(), "–"); // active
    assert.equal(collectText(cells[6]).trim(), "–"); // turns
    assert.equal(collectText(cells[7]).trim(), "–"); // out
  }
  assert.doesNotThrow(() => draw(fixtureBatch("in_progress")));
});

test("the in-progress batch shows an implementation card and an empty planning card", () => {
  const { root } = draw(fixtureBatch("in_progress"));
  const [plan, impl] = byClass(root, "part");
  assert.match(collectText(plan), /No telemetry recorded\./);
  assert.match(collectText(impl), /Active ≈ 25m calendar 30m/);
});

test("headerFacts counts green, skipped and error phases", () => {
  const f = B.headerFacts(stateBatch());
  assert.deepEqual([f.green, f.skipped, f.error], [1, 1, 1]);
  assert.deepEqual(B.headerFacts(fixtureBatch("done")).green, 2);
});

test("result line: green count, merge state, branch and base", () => {
  const { root } = draw(fixtureBatch("done"));
  const line = byClass(root, "result")[0];
  assert.equal(byClass(line, "result-main")[0].textContent, "2 of 2 phases green");
  const text = collectText(line);
  assert.match(text, /✔ merged/);
  assert.deepEqual(byTag(line, "code").map((c) => c.textContent), ["cfq/047-2026-10-01-demo", "main"]);
  const open = fixtureBatch("in_progress");
  open.merged = false;
  assert.match(collectText(byClass(draw(open).root, "result")[0]), /not merged yet/);
});

test("part cards: values, share, interview depth, phase count, explorers and audit", () => {
  const { root } = draw(fixtureBatch("done"));
  const [plan, impl] = byClass(root, "part");
  assert.match(plan.className, /part-plan/);
  assert.match(impl.className, /part-impl/);
  const planText = collectText(plan);
  assert.match(planText, /Planning/);
  assert.match(planText, /50 %/); // equal output on both sides in the fixture
  assert.match(planText, /Active ≈ 30m/);
  assert.match(planText, /Output 6\.2k 75 turns/);
  assert.match(planText, /Input new 4\.4k/);
  assert.match(planText, /Cache read 38k/);
  assert.match(planText, /thorough interview/);
  assert.match(planText, /2 phases planned/);
  assert.match(planText, /1 explorer\b/);
  assert.match(planText, /audit 5m · 1 finding\b/);
  assert.match(planText, /sonnet/);
  assert.match(planText, /haiku/);
  // the sub line of the planning Active fact is the calendar range, with the labels on the facts
  const range = byClass(byClass(plan, "fact")[0], "s")[0].textContent;
  assert.match(range, /^\d\d\.\d\d\. \d\d:\d\d–(\d\d\.\d\d\. )?\d\d:\d\d$/);
  const implText = collectText(impl);
  assert.match(implText, /Active ≈ 40m calendar 2h 40m/);
  assert.match(implText, /orchestrator/);
  assert.match(implText, /1 worker · 1 explorer/);
  // "Input new" and "Cache read" are explained in their tooltips
  const titles = byClass(plan, "fact").map((f) => f.attrs.title || "");
  assert.ok(titles.some((t) => /Input plus cache creation/.test(t)));
  assert.ok(titles.some((t) => /read from the cache/.test(t)));
});

test("part cards: a part without telemetry says so, the other stays; no audit means no audit line", () => {
  const batch = fixtureBatch("done");
  batch.planning.cost = null;
  const { root } = draw(batch);
  const [plan, impl] = byClass(root, "part");
  assert.match(collectText(plan), /No telemetry recorded\./);
  assert.equal(byClass(plan, "fact").length, 0);
  assert.equal(byClass(impl, "fact").length, 4);
  const noAudit = fixtureBatch("done");
  noAudit.planning.audit = [];
  assert.doesNotMatch(collectText(byClass(draw(noAudit).root, "part")[0]), /audit/);
  const running = fixtureBatch("done");
  running.planning.audit = [{ started: "2026-10-01T07:00:00Z", finished: "", findings: 0 }];
  assert.match(collectText(byClass(draw(running).root, "part")[0]), /audit running/);
});

test("notices: with only info flags there are no warn lines and a no-warnings pill with counts by code", () => {
  const batch = fixtureBatch("done");
  batch.flags = [
    { level: "info", code: "cost-outlier", text: "Output 3.5x the S baseline", phase: "01-first" },
    { level: "info", code: "cost-outlier", text: "Output 2.5x the S baseline", phase: "02-second" },
    { level: "info", code: "observations", text: "1 observation", phase: "02-second" },
  ];
  batch.phases[1].flags = [];
  const { root } = draw(batch);
  const head = byTag(root, "header")[0];
  assert.equal(byClass(head, "flag-warn").length, 0);
  const box = byClass(head, "notices")[0];
  assert.match(collectText(byClass(box, "pill")[0]), /no warnings/);
  const summary = collectText(byClass(box, "disclosure-toggle")[0]);
  assert.match(summary, /2 phases above their size baseline · 1 phase with observations/);
  assert.doesNotMatch(collectText(box), /Output 3\.5x/); // the list opens on demand
  fire(byClass(box, "disclosure-toggle")[0], "click");
  assert.match(collectText(box), /Output 3\.5x the S baseline/);
  assert.ok(links(box).includes("#/batch/047-2026-10-01-demo/phase/01-first"));
  // no flags at all: just the pill
  const clean = fixtureBatch("done");
  clean.flags = [];
  const none = byClass(draw(clean).root, "notices")[0];
  assert.match(collectText(none), /no warnings/);
});

test("notices: a warn flag is listed above the collapsed notes and there is no no-warnings pill", () => {
  const batch = fixtureBatch("done");
  batch.flags = [
    { level: "info", code: "cost-outlier", text: "Output 3.5x the S baseline", phase: "01-first" },
    { level: "warn", code: "red-attempt", text: "Phase is red", phase: "02-second" },
  ];
  const head = byTag(draw(batch).root, "header")[0];
  const warn = byClass(head, "flag-warn")[0];
  assert.ok(warn);
  const kids = head.children;
  const warnList = kids.find((k) => byClass(k, "flag-warn").length && k.tagName === "ul");
  const notices = byClass(head, "notices")[0];
  assert.ok(kids.indexOf(warnList) < kids.indexOf(notices));
  assert.doesNotMatch(collectText(notices), /no warnings/);
  assert.match(collectText(notices), /1 phase above its size baseline/);
});

test("phases table: Time is the latest attempt's clock time, Active the active sums; no active_s shows calendar time only", () => {
  const { root } = draw(fixtureBatch("done"));
  const [one, two] = byClass(root, "phase-row").map((tr) => byTag(tr, "td"));
  assert.match(collectText(one[4]), /^\d\d:\d\d$/);
  assert.equal(collectText(one[5]), "≈ 25m");
  assert.equal(one[5].attrs.title, "calendar 30m");
  // the second phase's latest attempt has active_s null: calendar time (20m + 40m) without a tilde
  assert.equal(collectText(two[5]), "1h 00m");
  assert.equal(two[5].attrs.title, undefined);
  assert.equal(B.phaseRows(fixtureBatch("done"))[1].active, null);
  assert.equal(B.phaseRows(fixtureBatch("done"))[0].active, 1500);
});

test("a null payload renders Batch not found and a link back", () => {
  const { root, crumbs } = draw(null);
  assert.match(collectText(root), /Batch not found\./);
  assert.ok(links(root).includes("#/"));
  assert.equal(crumbs.length, 1);
});

test("global mode builds links under the mirror", () => {
  const batch = fixtureBatch("done");
  const d = fakeDoc();
  const root = fakeRoot(d);
  const crumbs = [];
  B.render(d, root, {
    mode: "global", repo: "demo-1a2b", mirror: "demo-1a2b", site: { mode: "global" }, batch,
    route: { name: "batch", tab: null, batch: batch.name, phase: null, mirror: "demo-1a2b" },
    setCrumbs: (c) => crumbs.push(c),
  });
  assert.ok(links(root).includes("#/demo-1a2b/batch/047-2026-10-01-demo/context"));
  assert.deepEqual(crumbs[0].map((c) => c.href), ["#/", "#/demo-1a2b/", null]);
});

test("safety: free text never reaches innerHTML; only planHtml, goal and context do", () => {
  const evil = "<script>alert(1)</script>";
  const batch = fixtureBatch("done");
  batch.flags = [{ level: "warn", code: "x", text: evil, phase: "01-first" }];
  batch.phases.forEach((p) => {
    p.title = evil;
    p.affectedFiles = [evil];
    p.attempts.forEach((a) => {
      a.summary = evil;
      a.verification = evil;
      a.deviations = [evil];
      a.observations = [evil];
      a.errors = [evil];
      a.question = evil;
      a.mode = evil;
      a.diffstat = { files: 1, insertions: 1, deletions: 1, paths: [{ path: evil, added: 1, deleted: 1 }] };
    });
  });
  const d = fakeDoc();
  const root = fakeRoot(d);
  B.render(d, root, ctxFor(batch));
  for (const toggle of rowToggles(root)) {
    fire(toggle, "click");
    for (const sub of ["Result", "Plan", "Files"]) {
      for (const panel of byClass(root, "phase-detail")) {
        const btn = buttons(panel, sub)[0];
        if (btn) fire(btn, "click");
        const select = byTag(panel, "select")[0];
        if (select) { select.value = "0"; fire(select, "change"); }
      }
    }
  }
  const text = collectText(root);
  assert.match(text, /<script>alert\(1\)<\/script>/);
  const writes = d.innerHtmlWrites.map((w) => w.value);
  assert.ok(writes.length > 0);
  for (const w of writes) assert.doesNotMatch(w, /<script>/);
  // Only the goal and the two plan texts were written as markup (the Plan sub-tab opens per click).
  assert.ok(writes.every((w) => /^<p>(Demo goal|Plan of First|Plan of Second)\.<\/p>$/.test(w)), writes.join("|"));
});

test("extra slot items appear after the built-in ones and render their own body", () => {
  const C = loadPortal().core;
  const B2 = globalThis.CFQ.batch;
  C.register("batchTab", { id: "extra", label: "Extra", order: 99, count: () => 3, render: (doc, root) => root.appendChild(C.el(doc, "p", "extra body")) });
  C.register("phaseTab", { id: "more", label: "More", order: 99, render: (doc, root, ctx, phase, attempt) => root.appendChild(C.el(doc, "p", "more for " + phase.slug + " " + (attempt ? attempt.status : "none"))) });
  C.register("batchPhasesTop", { id: "extra-top", order: 10, render: (doc, root) => root.appendChild(C.el(doc, "p", "timeline above")) });

  const batch = fixtureBatch("done");
  const d = fakeDoc();
  const root = fakeRoot(d);
  B2.render(d, root, { mode: "repo", repo: site.repo, site, batch, setCrumbs() {}, route: { name: "batch", tab: null, batch: batch.name, phase: null } });
  assert.deepEqual(byTag(byTag(root, "nav")[0], "a").map((a) => a.textContent), ["Phases (2)", "Cost", "Plan context", "Notes (5)", "Closing", "Extra (3)"]);
  const body = byClass(root, "batch-tab")[0];
  assert.match(collectText(byClass(body, "top-extra-top")[0]), /timeline above/);
  assert.equal(body.children[body.children.length - 1].className, "tscroll"); // the phase table follows the top slots

  fire(rowToggles(root)[0], "click");
  let panel = byClass(root, "phase-detail")[0];
  assert.deepEqual(byClass(panel, "subtab").map((b) => b.textContent), ["Result", "Plan", "Cost", "Files", "More"]);
  fire(buttons(panel, "More")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  assert.match(collectText(panel), /more for 01-first green/);

  const extra = fakeRoot(d);
  B2.render(d, extra, { mode: "repo", repo: site.repo, site, batch, setCrumbs() {}, route: { name: "batch", tab: "extra", batch: batch.name, phase: null } });
  assert.match(collectText(extra), /extra body/);
  assert.equal(byTag(extra, "table").length, 0);
});

function stateBatch() {
  const batch = fixtureBatch("in_progress");
  const [first, second, third] = batch.phases;
  second.state = "error";
  second.attempts = [{ ...first.attempts[0], status: "red", summary: "", errors: ["boom"], commit: "" }];
  third.state = "skipped";
  third.skipReason = "obsolete";
  third.attempts = [{ ...first.attempts[0], status: "skipped", summary: "obsolete", commit: "", cost: null, tools: {} }];
  return batch;
}

test("phase states: error and skipped render with their own icon and word; the skip reason shows", () => {
  const rows = B.phaseRows(stateBatch());
  assert.deepEqual(rows.map((r) => r.status), ["green", "error", "skipped"]);
  assert.equal(rows[2].skipReason, "obsolete");
  const { root } = draw(stateBatch());
  const [, errorRow, skippedRow] = byClass(root, "phase-row");
  const errorPill = byClass(errorRow, "pill")[0];
  const skippedPill = byClass(skippedRow, "pill")[0];
  assert.match(errorPill.className, /pill-error/);
  assert.match(skippedPill.className, /pill-skipped/);
  assert.match(collectText(errorPill), /error/i);
  assert.match(collectText(skippedPill), /skipped/i);
  assert.notEqual(byClass(errorPill, "icon")[0].textContent, byClass(skippedPill, "icon")[0].textContent);
  assert.match(collectText(skippedRow), /obsolete/);
  assert.doesNotMatch(collectText(errorRow), /obsolete/);
  assert.match(collectText(byClass(root, "result")[0]), /1 of 3 phases green · 1 skipped · 1 error/);
});

test("a skip attempt renders as a row labelled skipped", () => {
  const { root } = draw(stateBatch());
  fire(rowToggles(root)[2], "click");
  const panel = byClass(root, "phase-detail")[0];
  const pill = byClass(panel, "pill")[0];
  assert.match(pill.className, /pill-skipped/);
  assert.match(collectText(pill), /skipped/i);
  assert.match(collectText(panel), /obsolete/);
});

// ---- edit controls --------------------------------------------------------------------------

test("header: an open batch shows the folder and context controls and the hint", () => {
  const { root } = draw(fixtureBatch("in_progress"));
  const head = byTag(root, "header")[0];
  const rows = byClass(head, "edit-controls");
  assert.equal(rows.length, 1);
  assert.deepEqual(byClass(rows[0], "edit-open").map((a) => [a.textContent, a.attrs.href]), [
    ["Open folder", "vscode://file/home/code/git/demo/.claude/cfq/impl/047-2026-10-01-demo"],
  ]);
  assert.deepEqual(byClass(rows[0], "edit-copy").map((b) => b.textContent), ["Copy folder path", "Copy context path"]);
  assert.equal(byClass(rows[0], "edit-hint").length, 1);
  // after the facts list
  const kids = head.children;
  assert.ok(kids.indexOf(rows[0]) > kids.indexOf(byClass(head, "result")[0]));
});

test("header: no context file means no context pair; editor off means no links; a done batch has none", () => {
  const noCtx = fixtureBatch("in_progress");
  delete noCtx.edit.context;
  const a = draw(noCtx).root;
  assert.deepEqual(byClass(a, "edit-copy").filter((b) => /context/.test(b.textContent)), []);
  assert.deepEqual(byClass(a, "edit-copy").map((b) => b.textContent), ["Copy folder path"]);

  const off = fixtureBatch("in_progress");
  delete off.edit.dir.url;
  const b = draw(off).root;
  assert.equal(byClass(b, "edit-open").length, 0);
  assert.equal(byClass(b, "edit-copy").length, 2);

  // an old-shape context url never becomes a link
  const oldCtx = fixtureBatch("in_progress");
  oldCtx.edit.context.url = "vscode://file/old/.batch-context.md";
  const c = draw(oldCtx).root;
  assert.deepEqual(byClass(c, "edit-open").map((a) => a.textContent), ["Open folder"]);

  assert.equal(byClass(draw(fixtureBatch("done")).root, "edit-controls").length, 0);
});

test("Plan sub-tab: a phase with edit shows Open folder above the plan text, also without plan text", () => {
  const { root } = draw(fixtureBatch("plan_only"));
  fire(rowToggles(root)[0], "click");
  let panel = byClass(root, "phase-detail")[0];
  fire(buttons(panel, "Plan")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  const row = byClass(panel, "edit-controls")[0];
  assert.deepEqual(byClass(row, "edit-open").map((a) => [a.textContent, a.attrs.href]),
    [["Open folder", "vscode://file/home/code/git/demo/.claude/cfq/impl/047-2026-10-01-demo"]]);
  assert.deepEqual(byClass(row, "edit-copy").map((b) => b.textContent), ["Copy path"]);
  const siblings = row.parentNode.children;
  assert.ok(siblings.indexOf(row) < siblings.indexOf(byClass(panel, "plan-text")[0]));
  assert.ok(collectHtml(panel).includes("<p>Plan of First.</p>"));

  const empty = fixtureBatch("plan_only");
  empty.phases[0].planHtml = "";
  const e = draw(empty).root;
  fire(rowToggles(e)[0], "click");
  let p2 = byClass(e, "phase-detail")[0];
  fire(buttons(p2, "Plan")[0], "click");
  p2 = byClass(e, "phase-detail")[0];
  assert.equal(byClass(p2, "edit-controls").length, 1);
  assert.match(collectText(p2), /No plan text recorded\./);
});

test("Plan sub-tab: a phase without edit shows no controls", () => {
  const { root } = draw(fixtureBatch("done"));
  fire(rowToggles(root)[0], "click");
  let panel = byClass(root, "phase-detail")[0];
  fire(buttons(panel, "Plan")[0], "click");
  panel = byClass(root, "phase-detail")[0];
  assert.equal(byClass(panel, "edit-controls").length, 0);
  assert.ok(collectHtml(panel).includes("<p>Plan of First.</p>"));
});
