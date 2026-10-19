// The repo overview: a KPI strip plus a dense, sortable, filterable batch table (newest first),
// with tabs for open todos, the plan inbox and the archive of closed entries. Pure helpers
// (`kpis`, `defaultOrder`, `sortBatches`, `filterBatches`) are separate from the DOM assembly so
// tests/js/overview.test.mjs can exercise them directly.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  function core() { return CFQ.core; }

  // ---- pure logic -------------------------------------------------------------------------------

  var ACTIVE_ORDER = ["in_progress", "awaiting_review", "blocked", "planned", "planning"];
  var STATUS_RANK = ACTIVE_ORDER.concat(["done"]);

  function isActive(row) { return row.status !== "done"; }

  function byNameDesc(a, b) { return a.name < b.name ? 1 : a.name > b.name ? -1 : 0; }

  // The eight KPI tiles, from `queue.totals` only.
  function kpis(queue) {
    var t = (queue && queue.totals) || {};
    var b = t.batches || {};
    var flags = t.flags || {};
    var cost = t.cost || {};
    var C = core();
    return [
      { id: "inProgress", label: "In progress", value: b.inProgress || 0 },
      { id: "planned", label: "Planned", value: b.planned || 0 },
      { id: "done", label: "Done", value: b.done || 0 },
      { id: "todos", label: "Open todos", value: t.todos || 0 },
      { id: "planEntries", label: "Plan inbox", value: t.planEntries || 0 },
      { id: "flags", label: "Flags", value: flags.warn || 0, sub: (flags.info || 0) + " info" },
      { id: "deviations", label: "Deviations", value: t.deviations || 0 },
      {
        id: "tokens",
        label: "Tokens",
        value: C.fmtTokens(C.billableIn(cost)) + " / " + C.fmtTokens(cost.output || 0),
        sub: C.fmtInt(cost.turns || 0) + " turns",
        title: C.fmtInt(C.billableIn(cost)) + " in / " + C.fmtInt(cost.output || 0) + " out",
      },
    ];
  }

  // Active batches first (by status, newest name first), then done by finish time, newest first.
  function defaultOrder(rows) {
    var active = rows.filter(isActive).sort(function (a, b) {
      return ACTIVE_ORDER.indexOf(a.status) - ACTIVE_ORDER.indexOf(b.status) || byNameDesc(a, b);
    });
    var done = rows.filter(function (r) { return !isActive(r); }).sort(function (a, b) {
      var fa = a.finished || "", fb = b.finished || "";
      return fa < fb ? 1 : fa > fb ? -1 : byNameDesc(a, b);
    });
    return active.concat(done);
  }

  function costValue(row, key) {
    var total = row.cost && row.cost.total;
    if (!total) return null;
    if (key === "turns") return total.turns || 0;
    if (key === "in") return core().billableIn(total);
    return total.output || 0;
  }

  function sortValue(row, key) {
    switch (key) {
      case "name": return row.name;
      case "status": return STATUS_RANK.indexOf(row.status);
      case "finished": return row.finished || null;
      case "turns": case "in": case "out": return costValue(row, key);
      case "deviations": return row.deviations || 0;
      case "flags": return ((row.flags && row.flags.warn) || 0) * 1e6 + ((row.flags && row.flags.info) || 0);
      default: return row.name;
    }
  }

  // Rows without a value for the key (no telemetry, not finished) sort last in either direction.
  function sortBatches(rows, key, dir) {
    var sign = dir === "desc" ? -1 : 1;
    return rows.slice().sort(function (a, b) {
      var va = sortValue(a, key), vb = sortValue(b, key);
      if (va === null && vb === null) return byNameDesc(a, b);
      if (va === null) return 1;
      if (vb === null) return -1;
      if (va < vb) return -sign;
      if (va > vb) return sign;
      return byNameDesc(a, b);
    });
  }

  function plain(markup) {
    return String(markup || "").replace(/<[^>]*>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'");
  }

  function filterBatches(rows, filter) {
    var query = String((filter && filter.query) || "").trim().toLowerCase();
    var group = (filter && filter.group) || "all";
    return rows.filter(function (r) {
      if (group === "active" && !isActive(r)) return false;
      if (group === "done" && isActive(r)) return false;
      if (group === "flagged" && !(r.flags && r.flags.warn > 0)) return false;
      if (!query) return true;
      var n = r.number === undefined || r.number === null ? "" : String(r.number);
      var hay = [n, n && n.length < 3 ? ("000" + n).slice(-3) : n, r.title || "", plain(r.goalHtml).replace(/\s+/g, " ")]
        .join("\n").toLowerCase();
      return hay.indexOf(query) !== -1;
    });
  }

  function entriesFor(queue, tab) {
    var list = (queue && queue.entries) || [];
    return list.filter(function (e) {
      if (tab === "todos") return e.kind === "todo" && e.state === "open";
      if (tab === "inbox") return e.kind === "plan" && e.state === "open";
      return e.state === "done";
    }).sort(function (a, b) {
      var da = a.date || "", db = b.date || "";
      return da < db ? 1 : da > db ? -1 : a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
    });
  }

  function entryCounts(queue) {
    return {
      todos: entriesFor(queue, "todos").length,
      inbox: entriesFor(queue, "inbox").length,
      archive: entriesFor(queue, "archive").length,
    };
  }

  // ---- DOM assembly -----------------------------------------------------------------------------

  var NO_TELEMETRY = "no telemetry recorded";

  function cell(doc, tag, className) {
    var c = doc.createElement(tag || "td");
    if (className) c.className = className;
    return c;
  }

  function dashCell(doc, className, title) {
    var c = core().el(doc, "td", "–", (className || "") + " faint");
    if (title) c.setAttribute("title", title);
    return c;
  }

  function blockReason(row) {
    if (row.status === "blocked") {
      if ((row.unknownDeps || []).length) return "Unknown dependency: " + row.unknownDeps.join(", ");
      return "Waiting on " + (row.dependsOn || []).join(", ");
    }
    return "";
  }

  function batchRow(doc, ctx, row, maxIn, maxOut) {
    var C = core();
    var tr = C.el(doc, "tr", null, "row status-" + row.status);
    var link = href(ctx, "batch/" + row.name);

    tr.appendChild(C.el(doc, "td", row.number === undefined || row.number === null ? "–" : row.number, "num faint"));

    var nameCell = cell(doc, "td", "batch");
    var a = C.el(doc, "a", row.title || row.name, "rowlink");
    a.setAttribute("href", link);
    nameCell.appendChild(a);
    if (row.priority) {
      nameCell.appendChild(C.el(doc, "span", row.priority, "priority"));
    }
    nameCell.appendChild(C.el(doc, "div", C.fmtDate(row.date), "sub"));
    var reason = blockReason(row);
    if (reason) nameCell.appendChild(C.el(doc, "div", reason, "sub reason"));
    if (row.goalHtml) nameCell.appendChild(C.html(doc, "div", row.goalHtml, "goal"));
    tr.appendChild(nameCell);

    var statusCell = cell(doc, "td");
    statusCell.appendChild(C.statusPill(doc, row.status));
    tr.appendChild(statusCell);

    var phases = row.phases || { done: 0, total: 0 };
    var phaseCell = cell(doc, "td", "phases");
    phaseCell.appendChild(C.el(doc, "span", phases.done + "/" + phases.total, "mono"));
    var bar = C.el(doc, "span", null, "progress");
    bar.setAttribute("title", phases.done + " of " + phases.total + " phases done");
    var fill = C.el(doc, "span", null, "fill");
    fill.style.width = (phases.total ? Math.round((phases.done / phases.total) * 100) : 0) + "%";
    bar.appendChild(fill);
    phaseCell.appendChild(bar);
    tr.appendChild(phaseCell);

    var when = row.status === "done" ? row.finished : row.started;
    var whenCell = C.el(doc, "td", C.fmtDate(when), "date" + (row.status === "done" ? "" : " faint"));
    whenCell.setAttribute("title", (row.status === "done" ? "Finished " : "Started ") + C.fmtDateTime(when));
    tr.appendChild(whenCell);

    var total = row.cost && row.cost.total;
    if (!total) {
      tr.appendChild(dashCell(doc, "n", NO_TELEMETRY));
      tr.appendChild(dashCell(doc, "n", NO_TELEMETRY));
      tr.appendChild(dashCell(doc, "n", NO_TELEMETRY));
    } else {
      var turns = C.el(doc, "td", C.fmtInt(total.turns), "n");
      turns.setAttribute("title", row.settled === false ? "provisional: the session has not ended yet" : C.fmtInt(total.turns) + " turns");
      tr.appendChild(turns);
      var inCell = cell(doc, "td", "n");
      inCell.appendChild(C.tokenBar(doc, C.billableIn(total), maxIn));
      tr.appendChild(inCell);
      var outCell = cell(doc, "td", "n");
      outCell.appendChild(C.tokenBar(doc, total.output || 0, maxOut));
      tr.appendChild(outCell);
    }

    if (row.deviations) tr.appendChild(C.el(doc, "td", row.deviations, "n"));
    else tr.appendChild(dashCell(doc, "n", "no deviations"));

    var flagCell = cell(doc, "td");
    flagCell.appendChild(C.flagBadges(doc, row.flags));
    tr.appendChild(flagCell);

    var merge = row.merged === true ? "merged" : row.merged === false ? "open" : null;
    if (merge) {
      var m = C.el(doc, "td", merge, "merge merge-" + merge);
      m.setAttribute("title", merge === "merged" ? "merge card closed" : "merge card still open");
      tr.appendChild(m);
    } else {
      tr.appendChild(dashCell(doc, "merge", "no merge state"));
    }

    // The title link is stretched over the row by CSS; a click anywhere else on the row follows it too.
    tr.addEventListener("click", function (ev) {
      var t = ev && ev.target;
      if (t && t.closest && t.closest("a, button")) return;
      if (typeof location !== "undefined") location.hash = link;
    });
    return tr;
  }

  function href(ctx, path) { return core().href(ctx, path); }

  var COLUMNS = [
    { label: "#", key: null, cls: "num" },
    { label: "Batch", key: "name", cls: "batch" },
    { label: "Status", key: "status" },
    { label: "Phases", key: null },
    { label: "Finished", key: "finished", title: "Finish date; start date while the batch is active" },
    { label: "Turns", key: "turns", cls: "n" },
    { label: "In", key: "in", cls: "n", title: "Input tokens: input + cache creation" },
    { label: "Out", key: "out", cls: "n", title: "Output tokens" },
    { label: "Dev", key: "deviations", cls: "n", title: "Deviations from the plan" },
    { label: "Flags", key: "flags" },
    { label: "Merge", key: null },
  ];
  var DESC_FIRST = { finished: 1, turns: 1, in: 1, out: 1, deviations: 1, flags: 1 };

  function renderBatches(doc, root, ctx, queue) {
    var C = core();
    var rows = queue.batches || [];

    var panels = C.registered("overviewPanel");
    if (panels.length) {
      var host = C.el(doc, "div", null, "panels");
      panels.forEach(function (panel) {
        var box = C.el(doc, "section", null, "panel panel-" + panel.id);
        try { panel.render(doc, box, ctx); } catch (e) { box.textContent = "This panel could not be rendered."; }
        host.appendChild(box);
      });
      root.appendChild(host);
    }

    if (!rows.length) {
      root.appendChild(C.el(doc, "p", "No batches yet. Plan one with /pfq.", "empty"));
      return;
    }

    var state = { query: "", group: "all", key: null, dir: "asc" };
    var tableHost = C.el(doc, "div", null, "tscroll");

    var toolbar = C.el(doc, "div", null, "toolbar");
    var search = C.el(doc, "input", null, "search");
    search.setAttribute("type", "search");
    search.setAttribute("placeholder", "Filter by number, title or goal   ( / )");
    search.setAttribute("aria-label", "Filter batches");
    toolbar.appendChild(search);

    var chips = [];
    [["all", "All"], ["active", "Active"], ["done", "Done"], ["flagged", "Flagged"]].forEach(function (c) {
      var count = filterBatches(rows, { group: c[0] }).length;
      var chip = C.el(doc, "button", c[1] + " (" + count + ")", "chip");
      chip.setAttribute("type", "button");
      chip.setAttribute("aria-pressed", c[0] === state.group ? "true" : "false");
      chip.addEventListener("click", function () {
        state.group = c[0];
        chips.forEach(function (x) { x.node.setAttribute("aria-pressed", x.id === state.group ? "true" : "false"); });
        draw();
      });
      chips.push({ id: c[0], node: chip });
      toolbar.appendChild(chip);
    });
    search.addEventListener("input", function () { state.query = search.value || ""; draw(); });
    root.appendChild(toolbar);
    root.appendChild(tableHost);

    // `/` focuses the search field; one handler per document, replaced on every render.
    if (doc.addEventListener) {
      if (doc.__cfqSlash && doc.removeEventListener) doc.removeEventListener("keydown", doc.__cfqSlash);
      doc.__cfqSlash = function (ev) {
        var t = ev && ev.target, tag = t && t.tagName ? String(t.tagName).toLowerCase() : "";
        if (!ev || ev.key !== "/" || tag === "input" || tag === "textarea" || tag === "select") return;
        if (ev.preventDefault) ev.preventDefault();
        search.focus();
      };
      doc.addEventListener("keydown", doc.__cfqSlash);
    }

    function draw() {
      C.clear(tableHost);
      var ordered = state.key ? sortBatches(rows, state.key, state.dir) : defaultOrder(rows);
      var visible = filterBatches(ordered, { query: state.query, group: state.group });
      if (!visible.length) {
        tableHost.appendChild(C.el(doc, "p", "No batch matches the filter.", "empty"));
        return;
      }
      var maxIn = 0, maxOut = 0;
      visible.forEach(function (r) {
        if (r.cost && r.cost.total) {
          maxIn = Math.max(maxIn, C.billableIn(r.cost.total));
          maxOut = Math.max(maxOut, r.cost.total.output || 0);
        }
      });

      var table = C.el(doc, "table", null, "data batches");
      var head = doc.createElement("tr");
      COLUMNS.forEach(function (col) {
        var th = cell(doc, "th", col.cls);
        if (col.title) th.setAttribute("title", col.title);
        if (col.key) {
          var active = state.key === col.key;
          th.setAttribute("aria-sort", active ? (state.dir === "desc" ? "descending" : "ascending") : "none");
          var btn = C.el(doc, "button", col.label + (active ? (state.dir === "desc" ? " ▼" : " ▲") : ""), "sort");
          btn.setAttribute("type", "button");
          btn.addEventListener("click", function () {
            if (state.key === col.key) state.dir = state.dir === "asc" ? "desc" : "asc";
            else { state.key = col.key; state.dir = DESC_FIRST[col.key] ? "desc" : "asc"; }
            draw();
          });
          th.appendChild(btn);
        } else {
          th.textContent = col.label;
        }
        head.appendChild(th);
      });
      var thead = doc.createElement("thead");
      thead.appendChild(head);
      table.appendChild(thead);
      var tbody = doc.createElement("tbody");
      visible.forEach(function (r) { tbody.appendChild(batchRow(doc, ctx, r, maxIn, maxOut)); });
      table.appendChild(tbody);
      tableHost.appendChild(table);
    }
    draw();
  }

  function originCell(doc, ctx, origin) {
    var C = core();
    var td = cell(doc, "td", "origin");
    if (!origin || !origin.batch) {
      td.className += " faint";
      td.textContent = "–";
      td.setAttribute("title", "no recorded origin");
      return td;
    }
    var a = C.el(doc, "a", origin.batch);
    a.setAttribute("href", href(ctx, "batch/" + origin.batch));
    td.appendChild(a);
    if (origin.phase) {
      td.appendChild(C.text(doc, " · "));
      var p = C.el(doc, "a", origin.phase);
      p.setAttribute("href", href(ctx, "batch/" + origin.batch + "/phase/" + origin.phase));
      td.appendChild(p);
    }
    return td;
  }

  function renderEntries(doc, root, ctx, queue, tab) {
    var C = core();
    var list = entriesFor(queue, tab);
    var empty = { todos: "No open todos.", inbox: "The plan inbox is empty.", archive: "Nothing archived yet." };
    if (!list.length) {
      root.appendChild(C.el(doc, "p", empty[tab], "empty"));
      return;
    }
    var archive = tab === "archive";
    var heads = ["Date", "Title", "Check", "Origin"].concat(archive ? ["Kind", "Closed", "Parked into"] : []);
    var table = C.el(doc, "table", null, "data entries");
    var thead = doc.createElement("thead");
    var hr = doc.createElement("tr");
    heads.forEach(function (h) { hr.appendChild(C.el(doc, "th", h)); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tbody = doc.createElement("tbody");
    list.forEach(function (e) {
      var tr = C.el(doc, "tr", null, "row");
      tr.appendChild(C.el(doc, "td", C.fmtDate(e.date), "date"));
      var title = cell(doc, "td", "title");
      var a = doc.createElement("a");
      a.setAttribute("href", href(ctx, "entry/" + e.id));
      a.appendChild(C.inlineCode(doc, e.title || e.id));
      title.appendChild(a);
      tr.appendChild(title);
      var check = cell(doc, "td", "check");
      if (typeof e.check === "string" && e.check) {
        check.appendChild(C.el(doc, "code", e.check));
        check.setAttribute("title", e.check);
      } else if (e.check) {
        check.textContent = "yes";
      } else {
        check.className += " faint";
        check.textContent = "–";
      }
      tr.appendChild(check);
      tr.appendChild(originCell(doc, ctx, e.origin));
      if (archive) {
        tr.appendChild(C.el(doc, "td", e.kind));
        var closed = /^\d{4}-\d{2}-\d{2}$/.test(String(e.closed || "")) ? C.fmtDate(e.closed) : (e.closed || "–");
        tr.appendChild(C.el(doc, "td", closed, e.closed ? "" : "faint"));
        var parked = cell(doc, "td");
        if (e.parkedInto) {
          var pa = C.el(doc, "a", e.parkedInto);
          pa.setAttribute("href", href(ctx, "batch/" + e.parkedInto));
          parked.appendChild(pa);
        } else {
          parked.className = "faint";
          parked.textContent = "–";
        }
        tr.appendChild(parked);
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    var scroll = C.el(doc, "div", null, "tscroll");
    scroll.appendChild(table);
    root.appendChild(scroll);
  }

  function render(doc, root, ctx) {
    var C = core();
    var queue = ctx.queue;
    if (ctx.mode === "global" && ctx.setCrumbs) {
      ctx.setCrumbs([{ label: "All repos", href: "#/" }, { label: ctx.mirror || ctx.repo || "", href: null }]);
    } else if (ctx.setCrumbs) {
      ctx.setCrumbs([]);
    }
    if (!queue) {
      root.appendChild(C.el(doc, "p", "No queue data found for this repo. Run `cfq portal sync`.", "empty"));
      return;
    }

    var strip = C.el(doc, "div", null, "kpis");
    kpis(queue).forEach(function (k) {
      var tile = C.el(doc, "div", null, "kpi kpi-" + k.id);
      if (k.title) tile.setAttribute("title", k.title);
      tile.appendChild(C.el(doc, "div", k.label, "label"));
      tile.appendChild(C.el(doc, "div", typeof k.value === "number" ? C.fmtInt(k.value) : k.value, "value"));
      if (k.sub) tile.appendChild(C.el(doc, "div", k.sub, "sub"));
      strip.appendChild(tile);
    });
    root.appendChild(strip);

    var tab = (ctx.route && ctx.route.tab) || "batches";
    var counts = entryCounts(queue);
    root.appendChild(C.tabs(doc, [
      { id: "batches", label: "Batches", href: href(ctx, "") },
      { id: "todos", label: "Todos (" + counts.todos + ")", href: href(ctx, "todos") },
      { id: "inbox", label: "Plan inbox (" + counts.inbox + ")", href: href(ctx, "inbox") },
      { id: "archive", label: "Archive (" + counts.archive + ")", href: href(ctx, "archive") },
    ], tab));

    if (tab === "batches") renderBatches(doc, root, ctx, queue);
    else renderEntries(doc, root, ctx, queue, tab);
  }

  CFQ.overview = {
    kpis: kpis,
    defaultOrder: defaultOrder,
    sortBatches: sortBatches,
    filterBatches: filterBatches,
    entriesFor: entriesFor,
    render: render,
  };
})();
