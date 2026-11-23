// The cross-repo index shown when the portal runs from a `reportDir` mirror (`site.mode ==
// "global"`): one row per repo that has synced, linking to that repo's own overview, with the
// repo's running or waiting batch, what needs attention and when it was last active.
// `app.js` calls `CFQ.repos.render(doc, root, ctx)` with `ctx.repos` the `data/repos.js` list;
// `ctx.now` (a Date) is only injected by tests.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var NOW_DOT = { in_progress: "run", awaiting_review: "review", planning: "review", blocked: "wait", planned: "wait" };
  var DAY_MS = 86400000;

  function startOfDay(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  }

  // "today", "yesterday", "N days ago" (up to six days), else the local date; "–" without a date.
  function relDate(iso, now) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return "–";
    var days = Math.round((startOfDay(now || new Date()) - startOfDay(d)) / DAY_MS);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 7) return days + " days ago";
    return CFQ.core.fmtDmy(iso);
  }

  function activityOf(repo) {
    var ts = Date.parse(((repo.counts || {}).lastActivity) || "");
    return isNaN(ts) ? null : ts;
  }

  // Most recent activity first; repos without one go last, by name.
  function sortRepos(repos) {
    return repos.slice().sort(function (a, b) {
      var ta = activityOf(a), tb = activityOf(b);
      if (ta !== null && tb !== null && ta !== tb) return tb - ta;
      if (ta !== null && tb === null) return -1;
      if (ta === null && tb !== null) return 1;
      var na = String(a.name || a.mirror), nb = String(b.name || b.mirror);
      return na < nb ? -1 : na > nb ? 1 : 0;
    });
  }

  function nowCell(doc, C, now) {
    var cell = C.el(doc, "div", null, "repo-now");
    if (!now) {
      cell.appendChild(C.el(doc, "span", "idle", "muted"));
      return cell;
    }
    cell.appendChild(C.el(doc, "span", null, "dot " + (NOW_DOT[now.status] || "wait")));
    cell.appendChild(C.el(doc, "span", (now.number || "") + " · " + (now.title || now.batch), "t"));
    var phases = now.phases || {};
    if (phases.total) cell.appendChild(C.el(doc, "span", (phases.done || 0) + "/" + phases.total, "num muted"));
    return cell;
  }

  function pillsCell(doc, C, attention) {
    var cell = C.el(doc, "div", null, "repo-pills");
    var warn = (attention && attention.warn) || 0;
    var plan = (attention && attention.plan) || 0;
    if (warn) cell.appendChild(C.el(doc, "span", "⚠ " + C.fmtInt(warn), "pill warn"));
    if (plan) cell.appendChild(C.el(doc, "span", C.fmtInt(plan) + " review", "pill plan"));
    return cell;
  }

  function render(doc, root, ctx) {
    var C = CFQ.core;
    if (ctx.setCrumbs) ctx.setCrumbs([{ label: "All repos", href: null }]);
    root.appendChild(C.el(doc, "h1", "Repositories"));

    var repos = Array.isArray(ctx.repos) ? ctx.repos : [];
    if (!repos.length) {
      root.appendChild(C.el(doc, "p", "No repo has synced into this report directory yet.", "empty"));
      return;
    }

    var list = C.el(doc, "div", null, "list repos");
    sortRepos(repos).forEach(function (repo) {
      var counts = repo.counts || {};
      var row = C.el(doc, "div", null, "item repo-row");

      var name = C.el(doc, "div", null, "repo");
      var a = C.el(doc, "a", repo.name || repo.mirror, "rowlink");
      a.setAttribute("href", "#/" + encodeURIComponent(repo.mirror) + "/");
      name.appendChild(a);
      if (repo.source) name.appendChild(C.el(doc, "div", repo.source, "sub faint mono"));
      row.appendChild(name);

      row.appendChild(nowCell(doc, C, counts.now));
      row.appendChild(pillsCell(doc, C, counts.attention));

      var meta = C.el(doc, "div", null, "repo-meta muted");
      meta.appendChild(C.el(doc, "span", "last active " + relDate(counts.lastActivity, ctx.now), "when"));
      meta.appendChild(C.el(doc, "span", C.fmtInt(counts.todos || 0) + " todos · " + C.fmtInt(counts.planEntries || 0) + " inbox", "sub"));
      row.appendChild(meta);

      list.appendChild(row);
    });
    root.appendChild(list);
  }

  CFQ.repos = { render: render, relDate: relDate, sortRepos: sortRepos };
})();
