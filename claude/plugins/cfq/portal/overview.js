// The repo overview: what is running now, what needs attention, the last ten batches as a planning |
// implementation pair, then tabs: the sortable, filterable batch table (newest first), the Trends
// charts, open todos, the plan inbox and the archive of closed entries. Pure helpers (`defaultOrder`,
// `sortBatches`, `filterBatches`) are separate from the DOM assembly so tests/js/overview.test.mjs
// can exercise them directly.

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

  // The output tokens of one part (`planning` or `implementation`) of a row, null when unknown.
  function partOutput(row, part) {
    var p = row.cost && row.cost[part] && row.cost[part].total;
    return p ? p.output || 0 : null;
  }

  function sortValue(row, key) {
    switch (key) {
      case "name": return row.name;
      case "status": return STATUS_RANK.indexOf(row.status);
      case "finished": return row.finished || null;
      case "planning": case "implementation": return partOutput(row, key);
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

  // Output tokens with the active time beneath; turns, input and cache read go into the tooltip.
  function costCell(doc, t, span, provisional) {
    var C = core();
    var td = cell(doc, "td", "n");
    if (!t) {
      td.appendChild(C.el(doc, "span", "–", "faint"));
      td.setAttribute("title", NO_TELEMETRY);
      return td;
    }
    td.appendChild(C.el(doc, "span", C.fmtTokens(t.output || 0), "out"));
    var tip = C.fmtInt(t.turns || 0) + " turns · " + C.fmtInt(C.billableIn(t)) + " input new · "
      + C.fmtInt(t.cache_read || 0) + " cache read · " + C.fmtInt(t.output || 0) + " output";
    if (provisional) tip += " (provisional: the session has not ended yet)";
    if (span) {
      var a = C.fmtActive(span.active_s, span.wallclock_s);
      var line = C.el(doc, "div", a.text, "faint active");
      if (a.title) tip += " · calendar " + a.title;
      td.appendChild(line);
    }
    td.setAttribute("title", tip);
    return td;
  }

  function batchRow(doc, ctx, row) {
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
    var phaseText = phases.done + "/" + phases.total;
    if (phases.skipped) phaseText += " · " + phases.skipped + " skipped";
    if (phases.error) phaseText += " · " + phases.error + " error";
    phaseCell.appendChild(C.el(doc, "span", phaseText, "mono"));
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

    var planning = row.cost && row.cost.planning && row.cost.planning.total;
    var impl = row.cost && row.cost.implementation && row.cost.implementation.total;
    var time = row.time || {};
    if (!planning && !impl) {
      tr.appendChild(dashCell(doc, "n", NO_TELEMETRY));
      tr.appendChild(dashCell(doc, "n", NO_TELEMETRY));
    } else {
      tr.appendChild(costCell(doc, planning, time.planning, row.settled === false));
      var implCell = costCell(doc, impl, null, row.settled === false);
      var pOut = planning ? planning.output || 0 : 0, iOut = impl ? impl.output || 0 : 0;
      var all = pOut + iOut;
      var share = all > 0 ? Math.round((pOut / all) * 100) : 0;
      var mini = C.el(doc, "div", null, "mini");
      mini.setAttribute("title", "Planning " + share + " % of the output");
      var mp = C.el(doc, "i", null, "p"); mp.style.width = share + "%";
      var mi = C.el(doc, "i", null, "m"); mi.style.width = (100 - share) + "%";
      mini.appendChild(mp);
      mini.appendChild(mi);
      implCell.appendChild(mini);
      tr.appendChild(implCell);
    }

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
    { label: "Planning", key: "planning", cls: "n", title: "Output tokens of the planning session; hover a cell for turns, input and cache read" },
    { label: "Implementation", key: "implementation", cls: "n", title: "Output tokens of the phases; the small bar is the planning share" },
    { label: "Flags", key: "flags" },
    { label: "Merge", key: null },
  ];
  var DESC_FIRST = { finished: 1, planning: 1, implementation: 1, flags: 1 };

  function renderBatches(doc, root, ctx, queue) {
    var C = core();
    var rows = queue.batches || [];

    if (!rows.length) {
      root.appendChild(C.el(doc, "p", "No batches yet. Plan one with /pfq.", "empty"));
      return;
    }

    // The search text lives in CFQ.state.query; the top bar's search field writes it.
    var shared = CFQ.state || (CFQ.state = { query: "", onQuery: null });
    var state = { query: shared.query || "", group: "all", key: null, dir: "asc" };
    var tableHost = C.el(doc, "div", null, "tscroll");

    var toolbar = C.el(doc, "div", null, "toolbar");

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
    // Typing in the top bar's field filters this table.
    shared.onQuery = function () {
      state.query = shared.query || "";
      draw();
    };
    root.appendChild(toolbar);
    root.appendChild(tableHost);

    function draw() {
      C.clear(tableHost);
      var ordered = state.key ? sortBatches(rows, state.key, state.dir) : defaultOrder(rows);
      var visible = filterBatches(ordered, { query: state.query, group: state.group });
      if (!visible.length) {
        tableHost.appendChild(C.el(doc, "p", "No batch matches the filter.", "empty"));
        return;
      }
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
      visible.forEach(function (r) { tbody.appendChild(batchRow(doc, ctx, r)); });
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

  // ---- Now, Needs attention, Last 10 batches ----------------------------------------------------

  function pad2(n) { return n < 10 ? "0" + n : String(n); }

  // "047-2026-10-01-gamma" -> "047"; a name without a leading number stays whole.
  function numberOf(name) {
    var m = /^(\d+)-/.exec(String(name || ""));
    return m ? m[1] : String(name || "");
  }

  function sectionHead(doc, title, aside) {
    var C = core();
    var head = C.el(doc, "div", null, "sec-head");
    head.appendChild(C.el(doc, "h2", title));
    if (aside) head.appendChild(C.el(doc, "span", aside, "aside"));
    return head;
  }

  function batchLink(doc, ctx, name, label, className) {
    var a = core().el(doc, "a", label, className || null);
    a.setAttribute("href", href(ctx, "batch/" + name));
    return a;
  }

  var NOW_DOT = { in_progress: "run", awaiting_review: "review", planning: "review", blocked: "wait", planned: "wait" };

  function nowSub(item) {
    var phases = item.phases || { done: 0, total: 0 };
    switch (item.status) {
      case "in_progress":
        if (!item.current) return "In progress";
        return "Phase " + pad2(item.current.num || 0) + " of " + pad2(phases.total || 0) + " running"
          + (item.current.title ? " · " + item.current.title : "");
      case "awaiting_review":
        return "Waiting for your plan review · " + phases.total + " phases";
      case "planning":
        return "Planning in progress";
      case "blocked":
        return "Queued · waits on " + (item.waitsOn || []).map(numberOf).join(", ");
      default:
        return "Queued · next in line";
    }
  }

  var NOW_PILL = { awaiting_review: ["plan", "review"], planning: ["plan", "planning"], blocked: ["neutral", "blocked"], planned: ["neutral", "next"] };

  function renderNow(doc, root, ctx, queue) {
    var C = core();
    var items = (queue && queue.now) || [];
    var sec = C.el(doc, "section", null, "now");
    sec.appendChild(sectionHead(doc, "Now", "in progress · awaiting review · next in queue"));
    var list = C.el(doc, "div", null, "list");
    if (!items.length) {
      list.appendChild(C.el(doc, "p", "Nothing running. Next: none queued.", "empty-line muted"));
    }
    items.forEach(function (item) {
      var row = C.el(doc, "div", null, "item now-" + item.status);
      row.appendChild(C.el(doc, "span", null, "dot " + (NOW_DOT[item.status] || "wait")));
      var body = C.el(doc, "div");
      var t = C.el(doc, "div", null, "t");
      t.appendChild(batchLink(doc, ctx, item.batch, item.number + " · " + (item.title || item.batch)));
      body.appendChild(t);
      body.appendChild(C.el(doc, "div", nowSub(item), "sub"));
      row.appendChild(body);
      var phases = item.phases || { done: 0, total: 0 };
      if (item.status === "in_progress") {
        var prog = C.el(doc, "div", null, "prog");
        var bar = C.el(doc, "div", null, "bar");
        bar.setAttribute("title", phases.done + " of " + phases.total + " phases done");
        var fill = C.el(doc, "i");
        fill.style.width = (phases.total ? Math.round((phases.done / phases.total) * 100) : 0) + "%";
        bar.appendChild(fill);
        prog.appendChild(bar);
        prog.appendChild(C.el(doc, "span", phases.done + "/" + phases.total, "num muted"));
        row.appendChild(prog);
      } else {
        var pill = NOW_PILL[item.status] || NOW_PILL.planned;
        row.appendChild(C.el(doc, "span", pill[1], "pill " + pill[0]));
      }
      list.appendChild(row);
    });
    sec.appendChild(list);
    root.appendChild(sec);
  }

  var ATTENTION_PILL = {
    "red-attempt": "red", question: "question", reopened: "reopened", "no-commit": "commit",
    "no-telemetry": "telemetry", "undeclared-files": "files", "checks-skipped": "checks",
    "finish-errors": "finish", "lang-issues": "language", "security-new": "security",
    review: "review", "unknown-dependency": "dependency", "audit-running": "audit",
  };

  function phaseTitle(slug) {
    var words = String(slug || "").replace(/^\d+-/, "").replace(/-/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  function renderAttention(doc, root, ctx, queue) {
    var C = core();
    var items = (queue && queue.attention) || [];
    var sec = C.el(doc, "section", null, "attention");
    sec.appendChild(sectionHead(doc, "Needs attention", "real problems only · cost outliers are notes"));
    var list = C.el(doc, "div", null, "list");
    var titles = {};
    ((queue && queue.batches) || []).forEach(function (b) { titles[b.name] = b.title; });
    var shown = 0;
    items.forEach(function (item) {
      if (item.code === "more") return;
      shown += 1;
      var level = item.level === "plan" ? "plan" : "warn";
      var row = C.el(doc, "div", null, "item attn-" + level);
      row.appendChild(C.el(doc, "span", null, "sev " + level));
      var body = C.el(doc, "div");
      var t = C.el(doc, "div", null, "t");
      if (item.phase) {
        t.appendChild(batchLink(doc, ctx, item.batch, numberOf(item.batch)));
        var pa = C.el(doc, "a", " / " + numberOf(item.phase) + " · " + phaseTitle(item.phase));
        pa.setAttribute("href", href(ctx, "batch/" + item.batch + "/phase/" + item.phase));
        t.appendChild(pa);
      } else {
        var name = titles[item.batch] || String(item.batch || "").replace(/^\d+-\d{4}-\d{2}-\d{2}-/, "").replace(/-/g, " ");
        t.appendChild(batchLink(doc, ctx, item.batch, numberOf(item.batch) + " · " + name));
      }
      body.appendChild(t);
      body.appendChild(C.el(doc, "div", item.text, "sub"));
      row.appendChild(body);
      row.appendChild(C.el(doc, "span", ATTENTION_PILL[item.code] || item.code, "pill " + level));
      list.appendChild(row);
    });
    if (!shown) list.appendChild(C.el(doc, "p", "Nothing needs attention.", "empty-line muted"));
    items.forEach(function (item) {
      if (item.code === "more") list.appendChild(C.el(doc, "p", item.text, "empty-line muted more"));
    });
    sec.appendChild(list);
    root.appendChild(sec);
  }

  // Models of a byModel map, the one with the most output first.
  function modelsByOutput(byModel) {
    return Object.keys(byModel || {}).sort(function (a, b) {
      return ((byModel[b] && byModel[b].output) || 0) - ((byModel[a] && byModel[a].output) || 0) || (a < b ? -1 : 1);
    });
  }

  function activeFact(part) {
    var C = core();
    var a = C.fmtActive(part.active_s, part.wallclock_s);
    return { k: "Active", v: a.text, s: a.title ? "calendar " + a.title : null };
  }

  function renderRecent(doc, root, queue) {
    var C = core();
    var recent = queue && queue.recent;
    if (!recent || !recent.batches || !recent.batches.length || !recent.planning || !recent.implementation) return;
    var p = recent.planning, m = recent.implementation;
    var pOut = (p.total && p.total.output) || 0, mOut = (m.total && m.total.output) || 0;
    var all = pOut + mOut;
    var pShare = all > 0 ? Math.round((pOut / all) * 100) : 0;
    var sec = C.el(doc, "section", null, "recent");
    sec.appendChild(sectionHead(doc, "Last " + recent.batches.length + " batches", "finished · output tokens"));
    var split = C.el(doc, "div", null, "split");
    split.appendChild(C.partCard(doc, {
      kind: "plan", title: "Planning", share: pShare + " %",
      facts: [
        { k: "Output", v: C.fmtTokens(pOut), title: C.fmtInt(pOut) },
        { k: "Turns", v: C.fmtInt((p.total && p.total.turns) || 0) },
        activeFact(p),
        { k: "Median / batch", v: C.fmtTokens(p.medianOutput || 0) },
      ],
      models: modelsByOutput(p.byModel),
    }));
    split.appendChild(C.partCard(doc, {
      kind: "impl", title: "Implementation", share: (all > 0 ? 100 - pShare : 0) + " %",
      facts: [
        { k: "Output", v: C.fmtTokens(mOut), title: C.fmtInt(mOut) },
        { k: "Turns", v: C.fmtInt((m.total && m.total.turns) || 0) },
        activeFact(m),
        { k: "Median / phase", v: C.fmtTokens(m.outputPerPhase || 0), s: (m.phases || 0) + " phases" },
      ],
      models: modelsByOutput(m.byModel),
    }));
    sec.appendChild(split);
    var bar = C.el(doc, "div", null, "sharebar");
    bar.setAttribute("aria-label", "Planning " + pShare + " percent, implementation " + (all > 0 ? 100 - pShare : 0) + " percent");
    var bp = C.el(doc, "i", null, "p"); bp.style.width = pShare + "%";
    var bm = C.el(doc, "i", null, "m"); bm.style.width = (all > 0 ? 100 - pShare : 0) + "%";
    bar.appendChild(bp);
    bar.appendChild(bm);
    sec.appendChild(bar);
    root.appendChild(sec);
  }

  // The Trends tab: every registered `overviewPanel`, one under the other.
  function renderTrends(doc, root, ctx) {
    var C = core();
    var panels = C.registered("overviewPanel");
    if (!panels.length) {
      root.appendChild(C.el(doc, "p", "No charts available.", "empty"));
      return;
    }
    var host = C.el(doc, "div", null, "panels stacked");
    panels.forEach(function (panel) {
      var box = C.el(doc, "section", null, "panel panel-" + panel.id);
      try { panel.render(doc, box, ctx); } catch (e) { box.textContent = "This panel could not be rendered."; }
      host.appendChild(box);
    });
    root.appendChild(host);
  }

  function render(doc, root, ctx) {
    var C = core();
    var queue = ctx.queue;
    if (CFQ.state) CFQ.state.onQuery = null;
    if (ctx.mode === "global" && ctx.setCrumbs) {
      ctx.setCrumbs([{ label: "All repos", href: "#/" }, { label: ctx.mirror || ctx.repo || "", href: null }]);
    } else if (ctx.setCrumbs) {
      ctx.setCrumbs([]);
    }
    if (!queue) {
      root.appendChild(C.el(doc, "p", "No queue data found for this repo. Run `cfq portal sync`.", "empty"));
      return;
    }

    renderNow(doc, root, ctx, queue);
    renderAttention(doc, root, ctx, queue);
    renderRecent(doc, root, queue);

    var tab = (ctx.route && ctx.route.tab) || "batches";
    var counts = entryCounts(queue);
    root.appendChild(C.tabs(doc, [
      { id: "batches", label: "Batches", href: href(ctx, "") },
      { id: "trends", label: "Trends", href: href(ctx, "trends") },
      { id: "todos", label: "Todos (" + counts.todos + ")", href: href(ctx, "todos") },
      { id: "inbox", label: "Plan inbox (" + counts.inbox + ")", href: href(ctx, "inbox") },
      { id: "archive", label: "Archive (" + counts.archive + ")", href: href(ctx, "archive") },
    ], tab));

    if (tab === "batches") renderBatches(doc, root, ctx, queue);
    else if (tab === "trends") renderTrends(doc, root, ctx);
    else renderEntries(doc, root, ctx, queue, tab);
  }

  CFQ.overview = {
    defaultOrder: defaultOrder,
    sortBatches: sortBatches,
    filterBatches: filterBatches,
    entriesFor: entriesFor,
    render: render,
  };
})();
