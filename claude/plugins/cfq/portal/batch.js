// The batch page: a header with the batch's key figures, a tab bar and the phases as a table whose
// rows unfold into a detail panel (result, plan text, files). The tab bar, the per-phase sub-tabs
// and the area above the phase table are filled from the slot registry in core.js (`batchTab`,
// `phaseTab`, `batchPhasesTop`), so a later script adds a tab by registering an item from a file of
// its own. This file registers the Phases and Plan context tabs and the Result, Plan and Files
// sub-tabs. Pure helpers (`phaseRows`, `fileRows`, `headerFacts`, ...) are separate from the DOM
// assembly so tests/js/batch.test.mjs can exercise them directly.
//
// Every value reaches the DOM through `textContent`; `html()` is used only for the pre-rendered,
// escaped fragments (`planHtml`, `context` sections, the goal).

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  function core() { return CFQ.core; }

  // ---- pure logic -------------------------------------------------------------------------------

  function isNum(n) { return typeof n === "number" && isFinite(n); }

  function latestAttempt(phase) {
    var list = (phase && phase.attempts) || [];
    return list.length ? list[list.length - 1] : null;
  }

  function attemptTotal(attempt) {
    return (attempt && attempt.cost && attempt.cost.total) || null;
  }

  // One row per plan phase. turns/in/out and duration are summed over all attempts (a retried
  // phase paid for every attempt); null when no attempt recorded any.
  function phaseRows(batch) {
    var C = core();
    return ((batch && batch.phases) || []).map(function (phase) {
      var attempts = phase.attempts || [];
      var latest = latestAttempt(phase);
      var turns = null, inTok = null, out = null, duration = null;
      attempts.forEach(function (a) {
        var t = attemptTotal(a);
        if (t) {
          turns = (turns || 0) + (t.turns || 0);
          inTok = (inTok || 0) + C.billableIn(t);
          out = (out || 0) + (t.output || 0);
        }
        var w = a.time && a.time.wallclock_s;
        if (isNum(w)) duration = (duration || 0) + w;
      });
      return {
        phase: phase,
        slug: phase.slug,
        num: phase.num,
        title: phase.title,
        size: phase.size,
        latest: latest,
        failed: attempts.slice(0, -1).filter(function (a) { return a.status === "red"; }).length,
        turns: turns,
        in: inTok,
        out: out,
        worked: latest && latest.time ? latest.time.from || null : null,
        duration: duration,
        devCount: latest ? (latest.deviations || []).length : 0,
        // an error or skipped phase shows its own state, not the status of its latest attempt
        status: phase.state === "error" || phase.state === "skipped" ? phase.state : (latest ? latest.status : "open"),
        skipReason: phase.state === "skipped" ? phase.skipReason || "" : "",
        flags: phase.flags || [],
      };
    });
  }

  // `p` made repo-relative: against `repo` when known, otherwise by matching the end of an absolute
  // path against a path the plan or the diffstat already gave in relative form.
  function relPath(p, repo, known) {
    p = String(p || "");
    if (p.charAt(0) !== "/") return p;
    if (repo) {
      var prefix = String(repo).replace(/\/+$/, "") + "/";
      if (p.indexOf(prefix) === 0) return p.slice(prefix.length);
    }
    for (var i = 0; i < known.length; i++) {
      if (known[i] && p.length > known[i].length && p.slice(-known[i].length - 1) === "/" + known[i]) return known[i];
    }
    return p;
  }

  // Planned and changed files side by side: `planned` (in both), `unplanned` (changed, not in the
  // plan), `untouched` (planned, not changed). Without a diffstat the attempt's `filesTouched`
  // stands in (no counts); with neither there is nothing to show.
  function fileRows(phase, attempt, repo) {
    var planned = (phase && phase.affectedFiles) || [];
    var stat = attempt && attempt.diffstat;
    var rows = [];
    if (stat && Array.isArray(stat.paths)) {
      var seen = {};
      stat.paths.forEach(function (p) {
        var path = relPath(p.path, repo, planned);
        seen[path] = true;
        rows.push({
          path: path,
          added: isNum(p.added) ? p.added : null,
          deleted: isNum(p.deleted) ? p.deleted : null,
          kind: planned.indexOf(path) !== -1 ? "planned" : "unplanned",
        });
      });
      planned.forEach(function (path) {
        if (!seen[path]) rows.push({ path: path, added: null, deleted: null, kind: "untouched" });
      });
      return rows;
    }
    var touched = (attempt && attempt.filesTouched) || [];
    return touched.map(function (p) {
      var path = relPath(p, repo, planned);
      return { path: path, added: null, deleted: null, kind: planned.indexOf(path) !== -1 ? "planned" : "unplanned" };
    });
  }

  function shortSha(sha) { return String(sha || "").slice(0, 7); }

  function commitHref(site, sha) {
    if (!sha || !site || !site.commitUrl) return null;
    return site.commitUrl + sha;
  }

  // The header's facts. Cost figures are null without telemetry, elapsed without both timestamps.
  function headerFacts(batch) {
    var C = core();
    batch = batch || {};
    var phases = batch.phases || [];
    var total = batch.cost && batch.cost.total;
    var elapsed = null;
    if (batch.started && batch.finished) {
      var a = new Date(batch.started).getTime(), b = new Date(batch.finished).getTime();
      if (isFinite(a) && isFinite(b) && b >= a) elapsed = (b - a) / 1000;
    }
    return {
      started: batch.started || null,
      finished: batch.finished || null,
      elapsed: elapsed,
      phases: { done: phases.filter(function (p) { return p.state === "done"; }).length, total: phases.length },
      turns: total ? total.turns || 0 : null,
      in: total ? C.billableIn(total) : null,
      out: total ? total.output || 0 : null,
      branch: batch.branch || null,
      base: batch.base || null,
      merged: batch.merged === true || batch.merged === false ? batch.merged : null,
    };
  }

  // "047-2026-10-01-demo-batch" -> {number: "047", title: "demo batch"}; legacy names keep theirs.
  function nameParts(name) {
    var m = /^(\d+)-\d{4}-\d{2}-\d{2}-(.+)$/.exec(String(name || ""));
    if (m) return { number: m[1], title: m[2].replace(/-/g, " ") };
    var d = /^\d{4}-\d{2}-\d{2}-(.+)$/.exec(String(name || ""));
    return { number: "", title: (d ? d[1] : String(name || "")).replace(/-/g, " ") };
  }

  function parkedId(file) {
    var base = String(file || "").split("/").pop().replace(/\.md$/, "");
    return "plan-" + base;
  }

  function capitalize(s) {
    s = String(s || "").replace(/[-_]+/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ---- small DOM helpers ------------------------------------------------------------------------

  function dash(doc, tag, className, title) {
    var c = core().el(doc, tag || "td", "–", (className || "") + " faint");
    if (title) c.setAttribute("title", title);
    return c;
  }

  function dateCell(doc, iso) {
    var C = core();
    if (!iso) return dash(doc, "td", "date");
    var c = C.el(doc, "td", C.fmtDateTime(iso), "date");
    return c;
  }

  function numCell(doc, value, text, title) {
    var C = core();
    if (!isNum(value)) return dash(doc, "td", "n");
    var c = C.el(doc, "td", text, "n");
    if (title) c.setAttribute("title", title);
    return c;
  }

  function link(doc, text, hrefValue, className) {
    var a = core().el(doc, "a", text, className);
    a.setAttribute("href", hrefValue);
    return a;
  }

  function none(doc) { return core().el(doc, "span", "none", "faint"); }

  function textList(doc, items) {
    var C = core();
    if (!items || !items.length) return none(doc);
    var ul = C.el(doc, "ul", null, "plain-list");
    items.forEach(function (s) {
      var li = C.el(doc, "li");
      li.appendChild(C.inlineCode(doc, s));
      ul.appendChild(li);
    });
    return ul;
  }

  // ---- header -----------------------------------------------------------------------------------

  function fact(doc, label, node) {
    var C = core();
    var span = C.el(doc, "span", null, "fact");
    span.appendChild(C.el(doc, "span", label, "fact-label"));
    span.appendChild(node);
    return span;
  }

  function factText(doc, text, title) {
    var C = core();
    var s = text === null || text === undefined ? C.el(doc, "span", "–", "fact-value faint") : C.el(doc, "span", text, "fact-value");
    if (title) s.setAttribute("title", title);
    return s;
  }

  function renderHeader(doc, root, ctx, batch) {
    var C = core();
    var parts = nameParts(batch.name);
    var head = C.el(doc, "header", null, "batch-head");

    var titleRow = C.el(doc, "div", null, "batch-title");
    var h1 = C.el(doc, "h1", parts.number ? parts.number + " · " + parts.title : parts.title);
    h1.setAttribute("title", batch.name);
    titleRow.appendChild(h1);
    titleRow.appendChild(C.statusPill(doc, batch.status));
    if (batch.priority) titleRow.appendChild(C.el(doc, "span", batch.priority, "priority"));
    head.appendChild(titleRow);

    var deps = batch.dependsOn || [];
    if (deps.length) {
      var depLine = C.el(doc, "p", null, "batch-deps muted");
      depLine.appendChild(C.text(doc, "Depends on "));
      deps.forEach(function (dep, i) {
        if (i > 0) depLine.appendChild(C.text(doc, ", "));
        depLine.appendChild(link(doc, dep, C.href(ctx, "batch/" + dep)));
      });
      head.appendChild(depLine);
    }

    var goal = batch.context && batch.context.goal;
    if (goal) head.appendChild(C.html(doc, "div", goal, "goal prose"));

    var f = headerFacts(batch);
    var facts = C.el(doc, "p", null, "facts");
    facts.appendChild(fact(doc, "Started", factText(doc, f.started ? C.fmtDateTime(f.started) : null)));
    facts.appendChild(fact(doc, "Finished", factText(doc, f.finished ? C.fmtDateTime(f.finished) : null)));
    facts.appendChild(fact(doc, "Elapsed", factText(doc, f.elapsed === null ? null : C.fmtDuration(f.elapsed))));
    var skipped = (batch.phases || []).filter(function (p) { return p.state === "skipped"; }).length;
    facts.appendChild(fact(doc, "Phases", factText(doc, f.phases.done + "/" + f.phases.total + (skipped ? " · " + skipped + " skipped" : ""))));
    facts.appendChild(fact(doc, "Turns", factText(doc, f.turns === null ? null : C.fmtInt(f.turns))));
    facts.appendChild(fact(doc, "In", factText(doc, f.in === null ? null : C.fmtTokens(f.in), f.in === null ? "" : C.fmtInt(f.in))));
    facts.appendChild(fact(doc, "Out", factText(doc, f.out === null ? null : C.fmtTokens(f.out), f.out === null ? "" : C.fmtInt(f.out))));
    var branch = f.branch ? C.el(doc, "code", f.branch) : factText(doc, null);
    facts.appendChild(fact(doc, "Branch", branch));
    facts.appendChild(fact(doc, "Base", f.base ? C.el(doc, "code", f.base) : factText(doc, null)));
    facts.appendChild(fact(doc, "Merged", factText(doc, f.merged === null ? null : f.merged ? "✔ merged" : "not merged yet")));
    head.appendChild(facts);

    var flags = batch.flags || [];
    var warns = flags.filter(function (x) { return x.level === "warn"; });
    var infos = flags.filter(function (x) { return x.level === "info"; });
    if (warns.length) {
      var ul = C.el(doc, "ul", null, "batch-flags");
      warns.forEach(function (flag) {
        var li = C.el(doc, "li", null, "flag-line");
        li.appendChild(C.el(doc, "span", "⚠", "flag flag-warn"));
        li.appendChild(C.text(doc, " "));
        li.appendChild(C.inlineCode(doc, flag.text));
        if (flag.phase) {
          li.appendChild(C.text(doc, " "));
          li.appendChild(link(doc, flag.phase, C.href(ctx, "batch/" + batch.name + "/phase/" + flag.phase), "flag-phase"));
        }
        ul.appendChild(li);
      });
      head.appendChild(ul);
    }
    if (infos.length) {
      head.appendChild(C.disclosure(doc, infos.length + (infos.length === 1 ? " note" : " notes"), function (d, body) {
        var list = C.el(d, "ul", null, "batch-flags");
        infos.forEach(function (flag) {
          var li = C.el(d, "li", null, "flag-line");
          li.appendChild(C.el(d, "span", "ⓘ", "flag flag-info"));
          li.appendChild(C.text(d, " "));
          li.appendChild(C.inlineCode(d, flag.text));
          if (flag.phase) {
            li.appendChild(C.text(d, " "));
            li.appendChild(link(d, flag.phase, C.href(ctx, "batch/" + batch.name + "/phase/" + flag.phase), "flag-phase"));
          }
          list.appendChild(li);
        });
        body.appendChild(list);
      }));
    }

    root.appendChild(head);
  }

  // ---- phase detail: sub-tabs -------------------------------------------------------------------

  function defRow(doc, dl, label, node) {
    var C = core();
    dl.appendChild(C.el(doc, "dt", label));
    var dd = C.el(doc, "dd");
    dd.appendChild(node);
    dl.appendChild(dd);
  }

  function prewrap(doc, str) {
    return core().el(doc, "div", str, "prewrap");
  }

  function diffstatText(stat) {
    var n = stat.files || 0;
    return n + (n === 1 ? " file" : " files") + " · +" + (stat.insertions || 0) + " −" + (stat.deletions || 0);
  }

  function renderResult(doc, root, ctx, phase, attempt) {
    var C = core();
    if (!attempt) {
      root.appendChild(C.el(doc, "p", "Not started.", "empty"));
      return;
    }
    var dl = C.el(doc, "dl", null, "result");

    var status = C.el(doc, "span");
    status.appendChild(C.statusPill(doc, attempt.status));
    if (attempt.reopened) status.appendChild(C.el(doc, "span", " reopened", "faint"));
    defRow(doc, dl, "Status", status);

    defRow(doc, dl, "Implemented", attempt.summary ? C.inlineCode(doc, attempt.summary) : none(doc));
    defRow(doc, dl, "Verification", attempt.verification ? prewrap(doc, attempt.verification) : none(doc));
    defRow(doc, dl, "Deviations", textList(doc, attempt.deviations));
    defRow(doc, dl, "Observations", textList(doc, attempt.observations));

    var errors = attempt.errors || [];
    if (errors.length) {
      var box = C.el(doc, "div");
      errors.forEach(function (e) { box.appendChild(prewrap(doc, e)); });
      defRow(doc, dl, "Errors", box);
    }
    if (attempt.question) defRow(doc, dl, "Question", C.inlineCode(doc, attempt.question));

    var triggers = attempt.triggers || [];
    if (triggers.length) defRow(doc, dl, "Triggers", C.el(doc, "span", triggers.join(", ")));

    var parked = attempt.parkedPlanEntries || [];
    if (parked.length) {
      var ul = C.el(doc, "ul", null, "plain-list");
      parked.forEach(function (file) {
        var li = C.el(doc, "li");
        li.appendChild(link(doc, String(file).split("/").pop(), C.href(ctx, "entry/" + parkedId(file))));
        ul.appendChild(li);
      });
      defRow(doc, dl, "Parked entries", ul);
    }

    if (attempt.commit) {
      var url = commitHref(ctx.site, attempt.commit);
      var sha;
      if (url) {
        sha = link(doc, shortSha(attempt.commit), url, "mono");
      } else {
        sha = C.el(doc, "code", shortSha(attempt.commit));
      }
      sha.setAttribute("title", attempt.commit);
      defRow(doc, dl, "Commit", sha);
    }
    if (attempt.diffstat) defRow(doc, dl, "Diffstat", C.el(doc, "span", diffstatText(attempt.diffstat), "mono"));
    defRow(doc, dl, "Mode", attempt.mode ? C.el(doc, "span", attempt.mode) : C.el(doc, "span", "–", "faint"));
    if (attempt.settled === false) {
      var prov = C.el(doc, "span", "provisional", "provisional");
      prov.setAttribute("title", "The telemetry of this attempt is recomputed once its session has ended");
      defRow(doc, dl, "Telemetry", prov);
    }
    root.appendChild(dl);
  }

  function renderPlan(doc, root, ctx, phase) {
    var C = core();
    if (!phase.planHtml) {
      root.appendChild(C.el(doc, "p", "No plan text recorded.", "empty"));
      return;
    }
    root.appendChild(C.html(doc, "div", phase.planHtml, "prose plan-text"));
  }

  var KIND_LABEL = { planned: "planned", unplanned: "unplanned", untouched: "untouched" };
  var KIND_HINT = {
    planned: "Changed and named in the plan",
    unplanned: "Changed but not named in the plan",
    untouched: "Named in the plan but not changed",
  };

  function renderFiles(doc, root, ctx, phase, attempt) {
    var C = core();
    var rows = fileRows(phase, attempt, ctx.site && ctx.site.repo);
    if (!rows.length) {
      root.appendChild(C.el(doc, "p", "No file data recorded.", "empty"));
      return;
    }
    var hasStat = !!(attempt && attempt.diffstat);
    var table = C.el(doc, "table", null, "data files");
    var thead = C.el(doc, "thead");
    var hr = C.el(doc, "tr");
    [["File", ""], ["Change", "n"], ["Kind", ""]].forEach(function (h) { hr.appendChild(C.el(doc, "th", h[0], h[1])); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = C.el(doc, "tbody");
    rows.forEach(function (row) {
      var tr = C.el(doc, "tr", null, "file-" + row.kind);
      var pathCell = C.el(doc, "td", null, "path");
      pathCell.appendChild(C.el(doc, "code", row.path));
      tr.appendChild(pathCell);
      if (isNum(row.added) || isNum(row.deleted)) {
        tr.appendChild(C.el(doc, "td", "+" + (row.added || 0) + " −" + (row.deleted || 0), "n"));
      } else if (hasStat && row.kind !== "untouched") {
        tr.appendChild(C.el(doc, "td", "binary", "n faint"));
      } else {
        tr.appendChild(dash(doc, "td", "n"));
      }
      var kindCell = C.el(doc, "td");
      var mark = C.el(doc, "span", KIND_LABEL[row.kind], "kind kind-" + row.kind);
      mark.setAttribute("title", KIND_HINT[row.kind]);
      kindCell.appendChild(mark);
      tr.appendChild(kindCell);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var scroll = C.el(doc, "div", null, "tscroll");
    scroll.appendChild(table);
    root.appendChild(scroll);
  }

  function attemptLabel(C, a, i, n) {
    return "Attempt " + (i + 1) + " of " + n + " · " + a.status + " · " + C.fmtDateTime(a.time && a.time.from);
  }

  // The panel under an open row. Re-renders itself in place when the sub-tab or the attempt changes.
  function renderDetail(doc, root, ctx, phase) {
    var C = core();
    var attempts = phase.attempts || [];
    var state = { tab: null, attempt: attempts.length ? attempts.length - 1 : -1 };
    var panel = C.el(doc, "div", null, "phase-detail");
    root.appendChild(panel);

    function draw() {
      C.clear(panel);
      var tabs = C.registered("phaseTab");
      if (!tabs.length) return;
      var active = tabs.filter(function (t) { return t.id === state.tab; })[0] || tabs.filter(function (t) { return t.id === "result"; })[0] || tabs[0];
      state.tab = active.id;
      var attempt = state.attempt >= 0 ? attempts[state.attempt] : null;

      var bar = C.el(doc, "div", null, "detail-bar");
      var strip = C.el(doc, "div", null, "subtabs");
      strip.setAttribute("role", "tablist");
      tabs.forEach(function (t) {
        var b = C.el(doc, "button", t.label, "subtab" + (t.id === active.id ? " active" : ""));
        b.setAttribute("type", "button");
        b.setAttribute("role", "tab");
        b.setAttribute("aria-selected", t.id === active.id ? "true" : "false");
        b.addEventListener("click", function () { state.tab = t.id; draw(); });
        strip.appendChild(b);
      });
      bar.appendChild(strip);

      if (attempts.length > 1) {
        var wrap = C.el(doc, "label", null, "attempt-select");
        wrap.appendChild(C.el(doc, "span", "Attempt", "faint"));
        var select = C.el(doc, "select");
        select.setAttribute("aria-label", "Attempt of " + phase.slug);
        attempts.forEach(function (a, i) {
          var opt = C.el(doc, "option", attemptLabel(C, a, i, attempts.length));
          opt.setAttribute("value", String(i));
          if (i === state.attempt) opt.setAttribute("selected", "selected");
          select.appendChild(opt);
        });
        select.value = String(state.attempt);
        select.addEventListener("change", function (ev) {
          var v = Number((ev && ev.target ? ev.target : select).value);
          if (isFinite(v) && attempts[v]) { state.attempt = v; draw(); }
        });
        wrap.appendChild(select);
        bar.appendChild(wrap);
      }
      panel.appendChild(bar);

      var body = C.el(doc, "div", null, "detail-body");
      body.setAttribute("role", "tabpanel");
      panel.appendChild(body);
      active.render(doc, body, ctx, phase, attempt);
    }
    draw();
  }

  // ---- Phases tab -------------------------------------------------------------------------------

  var COLUMNS = [
    ["#", "n"], ["Phase", ""], ["Size", ""], ["Status", ""], ["Worked", ""], ["Duration", "n"],
    ["Turns", "n"], ["Out", "n"], ["Dev", "n"], ["Flags", ""],
  ];

  function phaseRow(doc, ctx, row, maxOut, open, tbody) {
    var C = core();
    var tr = C.el(doc, "tr", null, "phase-row status-" + row.status);
    tr.appendChild(C.el(doc, "td", row.num === undefined || row.num === null ? "–" : row.num, "num n"));

    var titleCell = C.el(doc, "td", null, "phase");
    var toggle = C.el(doc, "button", null, "disclosure-toggle");
    toggle.setAttribute("type", "button");
    toggle.setAttribute("aria-expanded", "false");
    toggle.appendChild(C.el(doc, "span", "▸", "caret"));
    var titleEl = C.el(doc, "span", null, "phase-title");
    titleEl.appendChild(C.inlineCode(doc, row.title || row.slug));
    toggle.appendChild(titleEl);
    titleCell.appendChild(toggle);
    titleCell.appendChild(C.el(doc, "div", row.slug, "sub mono"));
    tr.appendChild(titleCell);

    tr.appendChild(row.size ? C.el(doc, "td", row.size, "size") : dash(doc, "td", "size"));

    var statusCell = C.el(doc, "td");
    statusCell.appendChild(C.statusPill(doc, row.status));
    if (row.failed) statusCell.appendChild(C.el(doc, "div", row.failed + " earlier red", "sub faint"));
    if (row.skipReason) statusCell.appendChild(C.el(doc, "div", row.skipReason, "sub faint skip-reason"));
    tr.appendChild(statusCell);

    tr.appendChild(dateCell(doc, row.worked));
    tr.appendChild(numCell(doc, row.duration, C.fmtDuration(row.duration), row.duration === null ? "" : C.fmtInt(row.duration) + " s"));
    tr.appendChild(numCell(doc, row.turns, C.fmtInt(row.turns)));
    var outCell = C.el(doc, "td", null, "n");
    outCell.appendChild(C.tokenBar(doc, row.out, maxOut));
    tr.appendChild(outCell);
    tr.appendChild(row.latest ? C.el(doc, "td", C.fmtInt(row.devCount), "n") : dash(doc, "td", "n"));
    var flagCell = C.el(doc, "td");
    flagCell.appendChild(C.flagBadges(doc, row.flags));
    tr.appendChild(flagCell);
    tbody.appendChild(tr);

    var detailRow = C.el(doc, "tr", null, "detail-row");
    detailRow.setAttribute("hidden", "");
    var detailCell = C.el(doc, "td");
    detailCell.setAttribute("colspan", String(COLUMNS.length));
    detailRow.appendChild(detailCell);
    tbody.appendChild(detailRow);

    var rendered = false;
    function setOpen(on) {
      toggle.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) {
        detailRow.removeAttribute("hidden");
        if (!rendered) { rendered = true; renderDetail(doc, detailCell, ctx, row.phase); }
      } else {
        detailRow.setAttribute("hidden", "");
      }
    }
    toggle.addEventListener("click", function () { setOpen(toggle.getAttribute("aria-expanded") !== "true"); });
    if (open) setOpen(true);
  }

  function renderPhasesTab(doc, root, ctx) {
    var C = core();
    var batch = ctx.batch;

    C.registered("batchPhasesTop").forEach(function (item) {
      var host = C.el(doc, "div", null, "phases-top top-" + item.id);
      root.appendChild(host);
      item.render(doc, host, ctx);
    });

    var rows = phaseRows(batch);
    if (!rows.length) {
      root.appendChild(C.el(doc, "p", "No phases recorded.", "empty"));
      return;
    }
    var maxOut = rows.reduce(function (m, r) { return isNum(r.out) && r.out > m ? r.out : m; }, 0);
    var openSlug = ctx.route && ctx.route.phase;

    var table = C.el(doc, "table", null, "data phases");
    var thead = C.el(doc, "thead");
    var hr = C.el(doc, "tr");
    COLUMNS.forEach(function (c) { hr.appendChild(C.el(doc, "th", c[0], c[1])); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = C.el(doc, "tbody");
    rows.forEach(function (row) { phaseRow(doc, ctx, row, maxOut, row.slug === openSlug, tbody); });
    table.appendChild(tbody);
    var scroll = C.el(doc, "div", null, "tscroll");
    scroll.appendChild(table);
    root.appendChild(scroll);
  }

  // ---- Plan context tab -------------------------------------------------------------------------

  function renderContextTab(doc, root, ctx) {
    var C = core();
    var context = (ctx.batch && ctx.batch.context) || {};
    var keys = Object.keys(context).filter(function (k) { return k.toLowerCase() !== "goal" && context[k]; });
    if (!keys.length) {
      root.appendChild(C.el(doc, "p", "No batch context recorded.", "empty"));
      return;
    }
    keys.forEach(function (key) {
      var section = C.el(doc, "section", null, "context-section");
      section.appendChild(C.el(doc, "h3", capitalize(key)));
      section.appendChild(C.html(doc, "div", context[key], "prose"));
      root.appendChild(section);
    });
  }

  // ---- page -------------------------------------------------------------------------------------

  function repoLabel(ctx) {
    if (ctx.mode === "global") return ctx.mirror || ctx.repo || "Overview";
    return String(ctx.repo || "").split("/").filter(Boolean).pop() || "Overview";
  }

  function render(doc, root, ctx) {
    var C = core();
    var batch = ctx.batch;
    var crumbs = ctx.mode === "global" ? [{ label: "All repos", href: "#/" }] : [];
    crumbs.push({ label: repoLabel(ctx), href: C.href(ctx, "") });

    if (!batch) {
      crumbs.push({ label: (ctx.route && ctx.route.batch) || "Batch", href: null });
      if (ctx.setCrumbs) ctx.setCrumbs(crumbs);
      root.appendChild(C.el(doc, "p", "Batch not found.", "empty"));
      root.appendChild(link(doc, "Back to the batch overview", C.href(ctx, "")));
      return;
    }
    crumbs.push({ label: batch.name, href: null });
    if (ctx.setCrumbs) ctx.setCrumbs(crumbs);

    renderHeader(doc, root, ctx, batch);

    var tabs = C.registered("batchTab");
    var wanted = ctx.route && ctx.route.tab;
    var active = tabs.filter(function (t) { return t.id === wanted; })[0]
      || tabs.filter(function (t) { return t.id === "phases"; })[0] || tabs[0];
    if (!active) return;
    root.appendChild(C.tabs(doc, tabs.map(function (t) {
      var n = typeof t.count === "function" ? t.count(batch) : null;
      return {
        id: t.id,
        label: isNum(n) ? t.label + " (" + n + ")" : t.label,
        href: C.href(ctx, "batch/" + batch.name + "/" + t.id),
      };
    }), active.id));

    var body = C.el(doc, "div", null, "batch-tab tab-" + active.id);
    root.appendChild(body);
    active.render(doc, body, ctx);
  }

  CFQ.batch = {
    phaseRows: phaseRows,
    fileRows: fileRows,
    shortSha: shortSha,
    commitHref: commitHref,
    headerFacts: headerFacts,
    render: render,
  };

  CFQ.core.register("batchTab", {
    id: "phases", label: "Phases", order: 10,
    count: function (batch) { return ((batch && batch.phases) || []).length; },
    render: renderPhasesTab,
  });
  CFQ.core.register("batchTab", { id: "context", label: "Plan context", order: 30, render: renderContextTab });
  CFQ.core.register("phaseTab", { id: "result", label: "Result", order: 10, render: renderResult });
  CFQ.core.register("phaseTab", { id: "plan", label: "Plan", order: 20, render: renderPlan });
  CFQ.core.register("phaseTab", { id: "files", label: "Files", order: 40, render: renderFiles });
})();
