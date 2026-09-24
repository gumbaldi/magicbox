// The fixed portal viewer shell (batch 040 phase 02). Plain HTML/CSS/JS: no external libraries,
// no CDN, no build step. Works when opened from disk (file://) in any current browser, and under
// `node --test` for its own pure-function unit tests (tests/js/viewer.test.mjs).
//
// Two kinds of function live here:
//   - pure logic (route parsing, batch grouping, cost-layer arithmetic, DOM-tree assembly given an
//     already-loaded payload) -- exported via `module.exports` when `module` exists, so the same
//     file runs in the browser and under Node with no separate test build.
//   - browser-only glue (inserting <script src> data-file tags, wiring `hashchange`) -- guarded by
//     `typeof window !== "undefined"` / only ever called from within the browser bootstrap, so
//     requiring this file under Node never touches a DOM global that doesn't exist there.
//
// The data comes from repo files, and this viewer must not become an injection path: every value
// that isn't a pre-rendered HTML fragment (`bodyHtml` on a phase/entry payload, already escaped by
// `cfq_lib/markdown.py`) goes in through `textContent`, via the `el()` helper below, never
// `innerHTML`.

(function () {
  "use strict";

  // ---- route parsing ----------------------------------------------------------------------

  function parseRoute(hash) {
    var h = (hash || "").replace(/^#/, "");
    var parts = h.split("/").filter(function (p) { return p !== ""; });
    if (parts.length >= 2 && parts[0] === "batch") {
      return { name: "batch", param: parts.slice(1).join("/") };
    }
    if (parts.length >= 2 && parts[0] === "entry") {
      return { name: "entry", param: parts.slice(1).join("/") };
    }
    return { name: "overview", param: null };
  }

  // ---- overview grouping --------------------------------------------------------------------

  function groupBatches(batches) {
    var groups = { inProgress: [], planned: [], done: [] };
    (batches || []).forEach(function (b) {
      if (b.status === "in_progress") groups.inProgress.push(b);
      else if (b.status === "done") groups.done.push(b);
      else groups.planned.push(b); // planned, blocked, planning
    });
    return groups;
  }

  function plannedReason(b) {
    b = b || {};
    if (b.status === "blocked") {
      var unknown = b.unknownDeps || [];
      if (unknown.length) return "Unknown dependency: " + unknown.join(", ");
      return "Waiting on " + (b.dependsOn || []).join(", ");
    }
    if (b.status === "planning") return "Still being planned";
    return "";
  }

  // ---- cost arithmetic: turns/output/billable_in, never a subtraction -----------------------

  function zeroTotals() {
    return { turns: 0, output: 0, billable_in: 0 };
  }

  function addTotals(dst, src) {
    dst.turns += (src && src.turns) || 0;
    dst.output += (src && src.output) || 0;
    dst.billable_in += (src && src.billable_in) || 0;
    return dst;
  }

  function sumNodeTotals(nodes) {
    var total = zeroTotals();
    (nodes || []).forEach(function (n) { addTotals(total, n.totals); });
    return total;
  }

  // Groups one batch's agents (every phase attempt's `telemetry.agents`, batch 038 phase 04) into
  // the orchestrator/explorer/worker/explorer(under worker) tree the batch page renders. Each
  // agent's own `layer` (already resolved server-side) decides its bucket; a worker's id is
  // namespaced by the phase slug it came from, since agent ids are only unique within one phase's
  // subagent directory, never across phases.
  function buildCostTree(implPhases) {
    var orchestrator = zeroTotals();
    var orchestratorModels = {};
    var orchestratorEfforts = {};
    var explorers = [];
    var workersByKey = {};

    (implPhases || []).forEach(function (rec, idx) {
      var tel = rec && rec.telemetry;
      if (!tel) return;
      var ns = rec.phase || ("phase-" + idx);
      var mainLayer = (tel.layers && tel.layers.main) || tel.totals || {};
      addTotals(orchestrator, mainLayer);
      (mainLayer.models || Object.keys(tel.by_model || {})).forEach(function (m) {
        orchestratorModels[m] = true;
      });
      (mainLayer.efforts || Object.keys(tel.by_effort || {})).forEach(function (e) {
        orchestratorEfforts[e] = true;
      });

      var agents = tel.agents || [];
      agents.forEach(function (a) {
        var key = ns + ":" + a.id;
        var withMeta = Object.assign({}, a, { phase: ns, key: key });
        if (a.layer === "main_explore") explorers.push(withMeta);
        else if (a.layer === "worker") workersByKey[key] = { node: withMeta, explorers: [] };
      });
      agents.forEach(function (a) {
        if (a.layer === "worker_explore" && a.parent) {
          var parentKey = ns + ":" + a.parent;
          var w = workersByKey[parentKey];
          if (w) w.explorers.push(Object.assign({}, a, { phase: ns, key: ns + ":" + a.id }));
        }
      });
    });

    var workers = Object.keys(workersByKey).map(function (k) { return workersByKey[k]; });
    return {
      orchestrator: {
        totals: orchestrator,
        models: Object.keys(orchestratorModels).sort(),
        efforts: Object.keys(orchestratorEfforts).sort(),
      },
      explorers: explorers,
      explorersSum: sumNodeTotals(explorers),
      workers: workers,
      workersSum: sumNodeTotals(workers.map(function (w) { return w.node; })),
    };
  }

  // ---- plan/impl merge: one row per plan phase, every report.json attempt attached ----------

  function mergePhases(planPhases, implPhases) {
    planPhases = planPhases || [];
    implPhases = implPhases || [];
    return planPhases.map(function (p) {
      var attempts = implPhases.filter(function (r) { return r.phase === p.slug; });
      var failed = attempts.slice(0, -1).filter(function (a) { return a.status === "red"; });
      return {
        slug: p.slug,
        title: p.title,
        size: p.size,
        state: p.state,
        bodyHtml: p.bodyHtml,
        attempts: attempts,
        latest: attempts.length ? attempts[attempts.length - 1] : null,
        failed: failed,
      };
    });
  }

  // ---- formatting -----------------------------------------------------------------------------

  function fmtInt(n) {
    if (typeof n !== "number" || !isFinite(n)) return "–";
    return Math.round(n).toLocaleString("en-US");
  }

  // ---- DOM helper: the one place text ever reaches an element, always via textContent -------

  function el(doc, tag, text, className) {
    var e = doc.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (className) e.className = className;
    return e;
  }

  function clearChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  // ---- rendering: overview --------------------------------------------------------------------

  function batchRowInto(doc, b) {
    var row = doc.createElement("div");
    row.className = "batch-row";

    var name = doc.createElement("div");
    name.className = "name";
    var link = doc.createElement("a");
    link.setAttribute("href", "#/batch/" + b.name);
    link.textContent = b.name;
    name.appendChild(link);
    row.appendChild(name);

    if (b.priority) row.appendChild(el(doc, "span", b.priority, "priority-badge"));

    var total = (b.done || 0) + (b.open || 0);
    row.appendChild(el(doc, "span", (b.done || 0) + "/" + total + " phases", "progress"));

    var out = b.cost && b.cost.total ? b.cost.total.output : 0;
    row.appendChild(el(doc, "span", fmtInt(out) + " out", "cost"));

    if (b.deviations) {
      row.appendChild(el(doc, "span", b.deviations + " deviation" + (b.deviations === 1 ? "" : "s"), "deviations"));
    }
    if (b.goal) row.appendChild(el(doc, "div", b.goal, "goal"));

    var reason = plannedReason(b);
    if (reason) row.appendChild(el(doc, "div", reason, "reason"));

    return row;
  }

  function batchGroupInto(doc, title, list, emptyMsg) {
    var section = doc.createElement("section");
    section.className = "queue-group";
    section.appendChild(el(doc, "h2", title + " (" + list.length + ")"));
    if (!list.length) {
      section.appendChild(el(doc, "p", emptyMsg, "muted"));
    } else {
      list.forEach(function (b) { section.appendChild(batchRowInto(doc, b)); });
    }
    return section;
  }

  function entryListInto(doc, title, entries) {
    var section = doc.createElement("section");
    section.className = "queue-group";
    section.appendChild(el(doc, "h2", title + " (" + entries.length + ")"));
    var ul = doc.createElement("ul");
    ul.className = "entry-list";
    entries.forEach(function (e) {
      var li = doc.createElement("li");
      var link = doc.createElement("a");
      link.setAttribute("href", "#/entry/" + e.id);
      link.textContent = e.title || e.id;
      li.appendChild(link);
      li.appendChild(el(doc, "span", e.date || "", "date"));
      if (e.check) li.appendChild(el(doc, "span", "check:", "check"));
      ul.appendChild(li);
    });
    section.appendChild(ul);
    return section;
  }

  function renderOverviewInto(doc, root, queue) {
    queue = queue || { batches: [], entries: [] };
    var batches = queue.batches || [];
    var entries = queue.entries || [];
    var groups = groupBatches(batches);

    root.appendChild(batchGroupInto(doc, "In progress", groups.inProgress, "No batch in progress."));
    root.appendChild(batchGroupInto(doc, "Planned", groups.planned, "Nothing planned."));
    root.appendChild(batchGroupInto(doc, "Done", groups.done, "Nothing done yet."));

    root.appendChild(entryListInto(doc, "Todos", entries.filter(function (e) { return e.kind === "todo"; })));
    root.appendChild(entryListInto(doc, "Plan inbox", entries.filter(function (e) { return e.kind === "plan"; })));
  }

  // ---- rendering: batch -----------------------------------------------------------------------

  function costTreeNodeInto(doc, label, totals, meta) {
    var li = doc.createElement("li");
    var line = doc.createElement("div");
    line.className = "node";
    line.appendChild(el(doc, "span", label, "label"));
    line.appendChild(el(
      doc, "span",
      fmtInt(totals.turns) + " turns · " + fmtInt(totals.billable_in) + " in · " + fmtInt(totals.output) + " out",
      "nums",
    ));
    if (meta) line.appendChild(el(doc, "span", meta, "meta"));
    li.appendChild(line);
    return li;
  }

  function costTreeInto(doc, tree) {
    var rootUl = doc.createElement("ul");
    rootUl.className = "cost-tree";

    var orchMeta = [].concat(tree.orchestrator.models, tree.orchestrator.efforts).filter(Boolean).join(" · ");
    var orchLi = costTreeNodeInto(doc, "Orchestrator", tree.orchestrator.totals, orchMeta);
    var children = doc.createElement("ul");

    if (tree.explorers.length) {
      children.appendChild(costTreeNodeInto(doc, "Explorer (" + tree.explorers.length + ")", tree.explorersSum));
    }
    if (tree.workers.length) {
      var workLi = costTreeNodeInto(doc, "Worker (" + tree.workers.length + ")", tree.workersSum);
      var workerChildren = doc.createElement("ul");
      tree.workers.forEach(function (w) {
        var label = w.node.description || w.node.phase || w.node.id;
        var wLi = costTreeNodeInto(doc, label, w.node.totals);
        if (w.explorers.length) {
          var wexUl = doc.createElement("ul");
          wexUl.appendChild(costTreeNodeInto(doc, "Explorer (" + w.explorers.length + ")", sumNodeTotals(w.explorers)));
          wLi.appendChild(wexUl);
        }
        workerChildren.appendChild(wLi);
      });
      workLi.appendChild(workerChildren);
      children.appendChild(workLi);
    }

    orchLi.appendChild(children);
    rootUl.appendChild(orchLi);
    return rootUl;
  }

  function securityInto(doc, security) {
    var section = doc.createElement("section");
    section.className = "security";
    section.appendChild(el(doc, "h2", "Security"));
    if (!security || !security.available) {
      var hint = security && security.hint;
      section.appendChild(el(doc, "p", "Not available" + (hint ? " — " + hint : ""), "muted"));
      return section;
    }
    var counts = security.counts || {};
    var countKeys = Object.keys(counts).sort();
    if (countKeys.length) {
      var dl = doc.createElement("dl");
      dl.className = "meta";
      countKeys.forEach(function (k) {
        var row = doc.createElement("div");
        row.appendChild(el(doc, "dt", k));
        row.appendChild(el(doc, "dd", fmtInt(counts[k])));
        dl.appendChild(row);
      });
      section.appendChild(dl);
    }
    var findings = security.findings || [];
    if (findings.length) {
      var ul = doc.createElement("ul");
      findings.forEach(function (f) {
        var text = typeof f === "string" ? f : [f.severity, f.title].filter(Boolean).join(" ");
        ul.appendChild(el(doc, "li", text || JSON.stringify(f)));
      });
      section.appendChild(ul);
    } else if (countKeys.length) {
      section.appendChild(el(doc, "p", "No findings.", "muted"));
    }
    return section;
  }

  function phaseBlockInto(doc, p) {
    var details = doc.createElement("details");
    details.className = "phase-plan";
    var summary = doc.createElement("summary");
    summary.textContent = p.slug + " — " + (p.title || "") + " (" + (p.size || "?") + ", " + p.state + ")";
    details.appendChild(summary);

    var body = doc.createElement("div");
    body.className = "body";
    // The one deliberate innerHTML assignment per phase block: `bodyHtml` is the phase file
    // pre-rendered by `cfq_lib/markdown.py` server-side, already escaped there -- every other
    // value on this page goes in through `el()`/`textContent`.
    body.innerHTML = p.bodyHtml || "";
    details.appendChild(body);

    if (p.latest) {
      var implBox = doc.createElement("div");
      implBox.className = "phase-impl";
      implBox.appendChild(el(doc, "p", "Status: " + p.latest.status));
      if (p.latest.summary) implBox.appendChild(el(doc, "p", p.latest.summary));
      if (p.latest.commit) implBox.appendChild(el(doc, "p", "Commit: " + p.latest.commit, "muted"));
      if (p.latest.deviations && p.latest.deviations.length) {
        implBox.appendChild(el(doc, "p", "Deviations: " + p.latest.deviations.join("; ")));
      }
      if (p.failed.length) {
        implBox.appendChild(el(doc, "p", p.failed.length + " failed attempt(s) before this one.", "muted"));
      }
      var totals = p.latest.telemetry && p.latest.telemetry.totals;
      if (totals) {
        implBox.appendChild(el(
          doc, "p", fmtInt(totals.turns) + " turns · " + fmtInt(totals.output) + " out", "cost",
        ));
      }
      details.appendChild(implBox);
    }

    return details;
  }

  function renderBatchInto(doc, root, batchName, plan, impl) {
    plan = plan || {};

    var crumbs = doc.createElement("nav");
    crumbs.className = "crumbs";
    var back = doc.createElement("a");
    back.setAttribute("href", "#/");
    back.textContent = "Overview";
    crumbs.appendChild(back);
    root.appendChild(crumbs);

    root.appendChild(el(doc, "h1", plan.batch || batchName));

    var sections = plan.sections || {};
    ["goal", "decisions", "non-goals", "invariants", "cross-phase contracts"].forEach(function (key) {
      if (sections[key]) {
        var box = doc.createElement("div");
        box.className = "overview";
        box.innerHTML = sections[key]; // pre-rendered by cfq_lib/markdown.py -- same rule as bodyHtml
        root.appendChild(box);
      }
    });

    var merged = mergePhases(plan.phases, impl ? impl.phases : []);
    var phasesSection = doc.createElement("section");
    phasesSection.appendChild(el(doc, "h2", "Phases"));
    merged.forEach(function (p) { phasesSection.appendChild(phaseBlockInto(doc, p)); });
    root.appendChild(phasesSection);

    if (impl) {
      var costSection = doc.createElement("section");
      costSection.appendChild(el(doc, "h2", "Cost"));
      costSection.appendChild(costTreeInto(doc, buildCostTree(impl.phases)));
      root.appendChild(costSection);
      root.appendChild(securityInto(doc, impl.security));
    } else {
      root.appendChild(el(doc, "p", "Not implemented yet — plan only.", "muted"));
    }
  }

  // ---- rendering: entry -------------------------------------------------------------------

  function renderEntryInto(doc, root, entry) {
    if (!entry) {
      root.appendChild(el(doc, "p", "Entry not found.", "muted"));
      return;
    }

    var crumbs = doc.createElement("nav");
    crumbs.className = "crumbs";
    var back = doc.createElement("a");
    back.setAttribute("href", "#/");
    back.textContent = "Overview";
    crumbs.appendChild(back);
    root.appendChild(crumbs);

    root.appendChild(el(doc, "h1", entry.title || entry.id));

    var meta = doc.createElement("dl");
    meta.className = "meta";
    function pair(label, value) {
      var row = doc.createElement("div");
      row.appendChild(el(doc, "dt", label));
      row.appendChild(el(doc, "dd", value));
      meta.appendChild(row);
    }
    pair("Date", entry.date || "–");
    pair("Origin", entry.origin || entry.kind || "–");
    pair("check:", entry.check ? "yes" : "no");
    root.appendChild(meta);

    var body = doc.createElement("div");
    body.className = "entry-body";
    // Pre-rendered by cfq_lib/markdown.py -- the one innerHTML assignment on this page.
    body.innerHTML = entry.bodyHtml || "";
    root.appendChild(body);
  }

  // ---- browser bootstrap: data loading, routing --------------------------------------------
  // Nothing below this line runs under `node --test` -- it's only ever invoked from the
  // `DOMContentLoaded`/`hashchange` listeners registered at the bottom of this file, which are
  // themselves only registered when `window` exists.

  var _dataCache = Object.create(null);

  function loadData(key) {
    if (Object.prototype.hasOwnProperty.call(_dataCache, key)) return _dataCache[key];
    var promise = new Promise(function (resolve) {
      var script = document.createElement("script");
      script.src = "data/" + key + ".js";
      script.onload = function () {
        var data = window.CFQ_DATA;
        resolve(data && Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null);
      };
      script.onerror = function () { resolve(null); };
      document.head.appendChild(script);
    });
    _dataCache[key] = promise;
    return promise;
  }

  function updateSiteTitle() {
    loadData("site").then(function (site) {
      var titleEl = document.getElementById("site-title");
      if (titleEl && site && site.repo) titleEl.textContent = "cfq — " + site.repo;
    });
  }

  function route() {
    var root = document.getElementById("app");
    if (!root) return;
    var r = parseRoute(location.hash);
    clearChildren(root);
    if (r.name === "batch") {
      Promise.all([loadData("batch/" + r.param + "/plan"), loadData("batch/" + r.param + "/impl")])
        .then(function (results) { renderBatchInto(document, root, r.param, results[0], results[1]); });
    } else if (r.name === "entry") {
      loadData("entry/" + r.param).then(function (entry) { renderEntryInto(document, root, entry); });
    } else {
      loadData("queue").then(function (queue) { renderOverviewInto(document, root, queue); });
    }
  }

  if (typeof window !== "undefined") {
    window.addEventListener("hashchange", route);
    window.addEventListener("DOMContentLoaded", function () {
      updateSiteTitle();
      route();
    });
  }

  // ---- exports: pure functions only, exercised directly by tests/js/viewer.test.mjs ---------

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      parseRoute: parseRoute,
      groupBatches: groupBatches,
      plannedReason: plannedReason,
      zeroTotals: zeroTotals,
      addTotals: addTotals,
      sumNodeTotals: sumNodeTotals,
      buildCostTree: buildCostTree,
      mergePhases: mergePhases,
      fmtInt: fmtInt,
      el: el,
      clearChildren: clearChildren,
      renderOverviewInto: renderOverviewInto,
      renderBatchInto: renderBatchInto,
      renderEntryInto: renderEntryInto,
      costTreeInto: costTreeInto,
    };
  }
})();
