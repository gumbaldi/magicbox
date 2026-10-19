// The page for a single todo card or plan entry, open or archived: breadcrumb, heading, a facts
// list (a row is left out when it has no value) and the pre-rendered body. `app.js` calls
// `CFQ.entry.render(doc, root, ctx)` with `ctx.entry` null when the data file could not be loaded.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  function core() { return CFQ.core; }

  function repoLabel(ctx) {
    if (ctx.mode === "global") return ctx.mirror || ctx.repo || "Overview";
    return String(ctx.repo || "").split("/").filter(Boolean).pop() || "Overview";
  }

  // [label, route inside the overview] of the list an entry belongs to.
  function listFor(entry) {
    if (entry.state !== "open") return ["Archive", "archive"];
    return entry.kind === "plan" ? ["Plan inbox", "inbox"] : ["Todos", "todos"];
  }

  function link(doc, label, href) {
    var a = core().el(doc, "a", label);
    a.setAttribute("href", href);
    return a;
  }

  function stateCell(doc, entry) {
    var C = core();
    if (entry.state === "open") return C.statusPill(doc, "open");
    var pill = C.el(doc, "span", null, "pill pill-done");
    var icon = C.el(doc, "span", "✔", "icon");
    icon.setAttribute("aria-hidden", "true");
    pill.appendChild(icon);
    pill.appendChild(C.el(doc, "span", "Closed", "label"));
    return pill;
  }

  function fact(doc, list, label, valueNode) {
    var C = core();
    list.appendChild(C.el(doc, "dt", label));
    var dd = C.el(doc, "dd");
    dd.appendChild(valueNode);
    list.appendChild(dd);
  }

  function originNode(doc, ctx, origin) {
    var C = core();
    var span = C.el(doc, "span", null, "origin");
    span.appendChild(link(doc, origin.batch, C.href(ctx, "batch/" + encodeURIComponent(origin.batch))));
    if (origin.phase) {
      span.appendChild(C.text(doc, " · phase "));
      span.appendChild(link(doc, origin.phase,
        C.href(ctx, "batch/" + encodeURIComponent(origin.batch) + "/phase/" + encodeURIComponent(origin.phase))));
    }
    return span;
  }

  function render(doc, root, ctx) {
    var C = core();
    var entry = ctx.entry;
    var crumbs = ctx.mode === "global" ? [{ label: "All repos", href: "#/" }] : [];
    crumbs.push({ label: repoLabel(ctx), href: C.href(ctx, "") });

    if (!entry) {
      crumbs.push({ label: "Entry", href: null });
      if (ctx.setCrumbs) ctx.setCrumbs(crumbs);
      root.appendChild(C.el(doc, "p", "Entry not found.", "empty"));
      root.appendChild(link(doc, "Back to the overview", C.href(ctx, "")));
      return;
    }

    var list = listFor(entry);
    crumbs.push({ label: list[0], href: C.href(ctx, list[1]) });
    crumbs.push({ label: entry.kind === "plan" ? "Plan entry" : "Todo card", href: null });
    if (ctx.setCrumbs) ctx.setCrumbs(crumbs);

    var page = C.el(doc, "article", null, "entry-page");
    var h1 = C.el(doc, "h1");
    h1.appendChild(C.inlineCode(doc, entry.title));
    page.appendChild(h1);

    var facts = C.el(doc, "dl", null, "facts");
    fact(doc, facts, "Kind", C.text(doc, entry.kind === "plan" ? "Plan entry" : "Todo card"));
    fact(doc, facts, "State", stateCell(doc, entry));
    if (entry.date) fact(doc, facts, "Date", C.text(doc, C.fmtDate(entry.date)));
    if (entry.check) fact(doc, facts, "Check", C.el(doc, "code", entry.check));
    if (entry.origin && entry.origin.batch) fact(doc, facts, "Origin", originNode(doc, ctx, entry.origin));
    if (entry.parkedInto) {
      fact(doc, facts, "Parked into",
        link(doc, entry.parkedInto, C.href(ctx, "batch/" + encodeURIComponent(entry.parkedInto))));
    }
    if (entry.closed) fact(doc, facts, "Closed", C.text(doc, entry.closed));
    page.appendChild(facts);

    if (entry.bodyHtml) page.appendChild(C.html(doc, "div", entry.bodyHtml, "prose"));
    root.appendChild(page);
  }

  CFQ.entry = { render: render };
})();
