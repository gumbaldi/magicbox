// The cross-repo index shown when the portal runs from a `reportDir` mirror (`site.mode ==
// "global"`): one row per repo that has synced, linking to that repo's own overview.
// `app.js` calls `CFQ.repos.render(doc, root, ctx)` with `ctx.repos` the `data/repos.js` list.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var COLUMNS = [
    { label: "Repo", cls: "" },
    { label: "In progress", cls: "n" },
    { label: "Planned", cls: "n" },
    { label: "Done", cls: "n" },
    { label: "Open todos", cls: "n" },
    { label: "Plan inbox", cls: "n" },
  ];

  function render(doc, root, ctx) {
    var C = CFQ.core;
    if (ctx.setCrumbs) ctx.setCrumbs([{ label: "All repos", href: null }]);
    root.appendChild(C.el(doc, "h1", "All repos"));

    var repos = Array.isArray(ctx.repos) ? ctx.repos : [];
    if (!repos.length) {
      root.appendChild(C.el(doc, "p", "No repo has synced into this report directory yet.", "empty"));
      return;
    }

    var scroll = C.el(doc, "div", null, "tscroll");
    var table = C.el(doc, "table", null, "data repos");
    var head = C.el(doc, "tr");
    COLUMNS.forEach(function (col) {
      var th = C.el(doc, "th", col.label, col.cls);
      th.setAttribute("scope", "col");
      head.appendChild(th);
    });
    var thead = C.el(doc, "thead");
    thead.appendChild(head);
    table.appendChild(thead);

    var tbody = C.el(doc, "tbody");
    repos.forEach(function (repo) {
      var counts = repo.counts || {};
      var batches = counts.batches || {};
      var tr = C.el(doc, "tr");
      var name = C.el(doc, "td", null, "repo");
      var a = C.el(doc, "a", repo.name || repo.mirror, "rowlink");
      a.setAttribute("href", "#/" + encodeURIComponent(repo.mirror) + "/");
      name.appendChild(a);
      if (repo.source) {
        var src = C.el(doc, "div", repo.source, "sub faint mono");
        name.appendChild(src);
      }
      tr.appendChild(name);
      [batches.inProgress, batches.planned, batches.done, counts.todos, counts.planEntries].forEach(function (n) {
        tr.appendChild(C.el(doc, "td", C.fmtInt(n || 0), "n"));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    root.appendChild(scroll);
  }

  CFQ.repos = { render: render };
})();
