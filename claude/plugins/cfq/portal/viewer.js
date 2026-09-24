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
  // `mode` ("repo", the default, or "global") comes from the already-loaded `site.js` payload --
  // the same hash means different things in the two modes (batch 040 phase 03's global index),
  // so the parser needs to be told which one is live rather than guessing from the hash alone.
  // Repo mode is byte-identical to phase 02: every existing call site (and test) that omits
  // `mode` keeps its exact prior behaviour.

  function parseRoute(hash, mode) {
    mode = mode || "repo";
    var h = (hash || "").replace(/^#/, "");
    var parts = h.split("/").filter(function (p) { return p !== ""; });

    if (mode === "global") {
      if (!parts.length) return { name: "repos", param: null };
      var repo = parts[0];
      var rest = parts.slice(1);
      if (rest.length >= 2 && rest[0] === "batch") {
        return { name: "repo-batch", param: { repo: repo, batch: rest.slice(1).join("/") } };
      }
      if (rest.length >= 2 && rest[0] === "entry") {
        return { name: "repo-entry", param: { repo: repo, id: rest.slice(1).join("/") } };
      }
      return { name: "repo-overview", param: repo };
    }

    if (parts.length >= 2 && parts[0] === "batch") {
      return { name: "batch", param: parts.slice(1).join("/") };
    }
    if (parts.length >= 2 && parts[0] === "entry") {
      return { name: "entry", param: parts.slice(1).join("/") };
    }
    return { name: "overview", param: null };
  }

  // ---- data paths: repo-local vs global-mirrored ------------------------------------------
  // Repo mode always reads "data/<key>.js". Global mode reads the same per-repo files out of
  // "<repo>/data/<key>.js" (batch 040 phase 03's mirror layout) for every key except the
  // global-only "site"/"repos" files, which stay at "data/<key>.js" (repo=null/falsy selects
  // that branch either way, so a global caller with no repo yet -- the repos list itself --
  // needs no special case).

  function dataPath(mode, repo, key) {
    if (mode === "global" && repo) return repo + "/data/" + key;
    return "data/" + key;
  }

  // The key registered on `window.CFQ_DATA` is always the bit after the last "data/" segment --
  // true for both "data/queue" (-> "queue") and "myrepo/data/queue" (-> "queue"), since the data
  // file itself doesn't know or care whether it was written to a repo-local or a mirrored root.
  function dataKeyFromPath(path) {
    var idx = path.lastIndexOf("data/");
    return idx === -1 ? path : path.slice(idx + 5);
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

  // ---- rendering: overview building blocks (batch rows, groups, entry lists) ----------------

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

  // ---- rendering: global repos list ------------------------------------------------------

  function repoRowInto(doc, r) {
    r = r || {};
    var row = doc.createElement("div");
    row.className = "repo-row";

    var link = doc.createElement("a");
    link.setAttribute("href", "#/" + r.mirror + "/");
    link.textContent = r.name || r.mirror;
    row.appendChild(link);

    var counts = r.counts || {};
    var batches = counts.batches || {};
    row.appendChild(el(
      doc, "span",
      (batches.inProgress || 0) + " in progress · " + (batches.planned || 0) + " planned · "
        + (batches.done || 0) + " done",
      "counts",
    ));
    if (counts.todos) row.appendChild(el(doc, "span", counts.todos + " todos", "todos"));
    if (counts.planEntries) row.appendChild(el(doc, "span", counts.planEntries + " plan inbox", "plan-entries"));

    return row;
  }

  function renderReposInto(doc, root, repos) {
    repos = repos || [];
    var section = doc.createElement("section");
    section.className = "queue-group";
    section.appendChild(el(doc, "h2", "Repositories (" + repos.length + ")"));
    if (!repos.length) {
      section.appendChild(el(doc, "p", "No repo has synced into this reportDir yet.", "muted"));
    } else {
      repos.forEach(function (r) { section.appendChild(repoRowInto(doc, r)); });
    }
    root.appendChild(section);
  }

  // ---- rendering: overview ----------------------------------------------------------------
  // `crumbHref`, when given, prepends a nav back to it (global mode's repo-overview page,
  // linking back to the cross-repo repos list). Omitted (repo mode, unchanged from phase 02),
  // no crumb is rendered -- the overview stays the top-level page.

  function renderOverviewInto(doc, root, queue, crumbHref) {
    queue = queue || { batches: [], entries: [] };
    if (crumbHref) {
      var crumbs = doc.createElement("nav");
      crumbs.className = "crumbs";
      var back = doc.createElement("a");
      back.setAttribute("href", crumbHref);
      back.textContent = "All repos";
      crumbs.appendChild(back);
      root.appendChild(crumbs);
    }
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

  function renderBatchInto(doc, root, batchName, plan, impl, crumbHref) {
    plan = plan || {};

    var crumbs = doc.createElement("nav");
    crumbs.className = "crumbs";
    var back = doc.createElement("a");
    back.setAttribute("href", crumbHref || "#/");
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

  function renderEntryInto(doc, root, entry, crumbHref) {
    if (!entry) {
      root.appendChild(el(doc, "p", "Entry not found.", "muted"));
      return;
    }

    var crumbs = doc.createElement("nav");
    crumbs.className = "crumbs";
    var back = doc.createElement("a");
    back.setAttribute("href", crumbHref || "#/");
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

  // `path` is relative to the reports root, without ".js" (e.g. "data/queue" in repo mode,
  // "myrepo/data/queue" in global mode) -- built by `dataPath()` above. Cached by that full path,
  // not by the short `window.CFQ_DATA` key alone, so navigating between two repos' same-named
  // file (e.g. both have a "queue" key) in one global-mode page session never serves the wrong
  // repo's cached promise.
  function loadData(path) {
    if (Object.prototype.hasOwnProperty.call(_dataCache, path)) return _dataCache[path];
    var jsKey = dataKeyFromPath(path);
    var promise = new Promise(function (resolve) {
      var script = document.createElement("script");
      script.src = path + ".js";
      script.onload = function () {
        var data = window.CFQ_DATA;
        resolve(data && Object.prototype.hasOwnProperty.call(data, jsKey) ? data[jsKey] : null);
      };
      script.onerror = function () { resolve(null); };
      document.head.appendChild(script);
    });
    _dataCache[path] = promise;
    return promise;
  }

  function updateSiteTitle() {
    loadData(dataPath("repo", null, "site")).then(function (site) {
      var titleEl = document.getElementById("site-title");
      if (!titleEl || !site) return;
      if (site.mode === "global") titleEl.textContent = "cfq — all repos";
      else if (site.repo) titleEl.textContent = "cfq — " + site.repo;
    });
  }

  function route() {
    var root = document.getElementById("app");
    if (!root) return;
    // The site payload's own "data/site" path is the same in both modes -- only its content
    // (`mode: "repo"|"global"`) decides how the rest of the hash is read.
    loadData(dataPath("repo", null, "site")).then(function (site) {
      var mode = (site && site.mode) || "repo";
      var r = parseRoute(location.hash, mode);
      clearChildren(root);

      if (mode === "global") {
        if (r.name === "repo-overview") {
          loadData(dataPath("global", r.param, "queue")).then(function (queue) {
            renderOverviewInto(document, root, queue, "#/");
          });
        } else if (r.name === "repo-batch") {
          var repo = r.param.repo, batch = r.param.batch;
          Promise.all([
            loadData(dataPath("global", repo, "batch/" + batch + "/plan")),
            loadData(dataPath("global", repo, "batch/" + batch + "/impl")),
          ]).then(function (results) {
            renderBatchInto(document, root, batch, results[0], results[1], "#/" + repo + "/");
          });
        } else if (r.name === "repo-entry") {
          var entryRepo = r.param.repo, id = r.param.id;
          loadData(dataPath("global", entryRepo, "entry/" + id)).then(function (entry) {
            renderEntryInto(document, root, entry, "#/" + entryRepo + "/");
          });
        } else {
          loadData(dataPath("global", null, "repos")).then(function (repos) {
            renderReposInto(document, root, repos);
          });
        }
        return;
      }

      if (r.name === "batch") {
        Promise.all([
          loadData(dataPath("repo", null, "batch/" + r.param + "/plan")),
          loadData(dataPath("repo", null, "batch/" + r.param + "/impl")),
        ]).then(function (results) { renderBatchInto(document, root, r.param, results[0], results[1]); });
      } else if (r.name === "entry") {
        loadData(dataPath("repo", null, "entry/" + r.param)).then(function (entry) {
          renderEntryInto(document, root, entry);
        });
      } else {
        loadData(dataPath("repo", null, "queue")).then(function (queue) { renderOverviewInto(document, root, queue); });
      }
    });
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
      dataPath: dataPath,
      dataKeyFromPath: dataKeyFromPath,
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
      renderReposInto: renderReposInto,
      renderOverviewInto: renderOverviewInto,
      renderBatchInto: renderBatchInto,
      renderEntryInto: renderEntryInto,
      costTreeInto: costTreeInto,
    };
  }
})();
