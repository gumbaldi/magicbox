// Router and bootstrap: resolves the hash to a route, loads the payloads that route needs through
// an injected `load(path)` and hands them to the matching view module (`CFQ.overview`, `CFQ.batch`,
// `CFQ.entry`, `CFQ.repos`). A view module that did not load renders a message instead of
// throwing, so the shell works while later modules are still missing. Loads last.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  var VIEWS = { overview: "overview", batch: "batch", entry: "entry", repos: "repos" };
  var PAYLOAD_KEY = { overview: "queue", batch: "batch", entry: "entry", repos: "repos" };

  // The data file a route needs, relative to the reports root.
  function dataKeyFor(route) {
    if (route.name === "overview") return "queue";
    if (route.name === "batch") return "batch/" + route.batch;
    if (route.name === "entry") return "entry/" + route.id;
    return "repos";
  }

  function makeSetCrumbs(doc) {
    return function setCrumbs(items) {
      var slot = doc.getElementById ? doc.getElementById("crumbs") : null;
      if (!slot) return;
      var C = CFQ.core;
      C.clear(slot);
      (items || []).forEach(function (item, i) {
        if (i > 0) slot.appendChild(C.el(doc, "span", "›", "sep"));
        if (item.href) {
          var a = C.el(doc, "a", item.label);
          a.setAttribute("href", item.href);
          slot.appendChild(a);
        } else {
          slot.appendChild(C.el(doc, "span", item.label, "current"));
        }
      });
    };
  }

  function applySiteChrome(doc, site) {
    var title = site && site.mode === "global" ? "cfq – all repos"
      : site && site.repo ? "cfq – " + String(site.repo).split("/").filter(Boolean).pop() : "cfq";
    try { doc.title = title; } catch (e) { /* a document without a settable title */ }
  }

  // ---- top bar: repository switcher, breadcrumbs (setCrumbs), search ------------------------------

  var current = null; // the ctx of the view on screen; the search field reads it on Enter

  function repoName(ctx) {
    return String(ctx.repo || "").split("/").filter(Boolean).pop() || "";
  }

  // Global mode: a <select> over data/repos.js that navigates to the chosen repo's overview. Repo
  // mode: the repo name as plain text.
  function renderSwitcher(doc, ctx, repos) {
    var slot = doc.getElementById ? doc.getElementById("repo-switch") : null;
    if (!slot) return;
    var C = CFQ.core;
    C.clear(slot);
    if (ctx.mode !== "global") {
      slot.appendChild(C.el(doc, "span", repoName(ctx), "repo"));
      return;
    }
    var select = C.el(doc, "select", null, "repo");
    select.setAttribute("aria-label", "Repository");
    var list = Array.isArray(repos) ? repos : [];
    if (!ctx.mirror) {
      var all = C.el(doc, "option", "All repos");
      all.setAttribute("value", "");
      select.appendChild(all);
    }
    list.forEach(function (repo) {
      var opt = C.el(doc, "option", repo.name || repo.mirror);
      opt.setAttribute("value", repo.mirror);
      if (repo.mirror === ctx.mirror) opt.setAttribute("selected", "selected");
      select.appendChild(opt);
    });
    select.value = ctx.mirror || "";
    select.addEventListener("change", function () {
      g.location.hash = select.value ? "#/" + encodeURIComponent(select.value) + "/" : "#/";
    });
    slot.appendChild(select);
  }

  // The search field: typing filters the overview's batch table, Enter on any other page opens the
  // overview with the query kept in CFQ.state.query. Wired once per element.
  function wireSearch(doc) {
    var search = doc.getElementById ? doc.getElementById("search") : null;
    if (!search) return;
    search.value = CFQ.state.query || "";
    if (search.__cfqBound) return;
    search.__cfqBound = true;
    search.addEventListener("input", function () {
      CFQ.state.query = search.value || "";
      if (typeof CFQ.state.onQuery === "function") CFQ.state.onQuery();
    });
    search.addEventListener("keydown", function (ev) {
      if (!ev || ev.key !== "Enter") return;
      if (!current || (current.route && current.route.name === "overview")) return;
      if (current.mode === "global" && !current.mirror) return;
      g.location.hash = CFQ.core.href(current, "");
    });
  }

  // `/` focuses the search field; one handler per document, replaced on every render.
  function wireSlash(doc) {
    if (!doc.addEventListener) return;
    if (doc.__cfqSlash && doc.removeEventListener) doc.removeEventListener("keydown", doc.__cfqSlash);
    doc.__cfqSlash = function (ev) {
      var t = ev && ev.target, tag = t && t.tagName ? String(t.tagName).toLowerCase() : "";
      if (!ev || ev.key !== "/" || tag === "input" || tag === "textarea" || tag === "select") return;
      var search = doc.getElementById ? doc.getElementById("search") : null;
      if (!search) return;
      if (ev.preventDefault) ev.preventDefault();
      search.focus();
    };
    doc.addEventListener("keydown", doc.__cfqSlash);
  }

  var token = 0;

  // Resolves once the view is drawn (or superseded by a newer render).
  function render(doc, root, hash, load) {
    var C = CFQ.core;
    var mine = ++token;
    return load(C.dataPath("repo", null, "site")).then(function (site) {
      if (mine !== token) return;
      var mode = site && site.mode === "global" ? "global" : "repo";
      var route = C.parseRoute(hash, mode);
      var mirror = route.mirror || null;
      var key = dataKeyFor(route);
      return load(C.dataPath(mode, mirror, key)).then(function (payload) {
        if (mine !== token) return;
        // The switcher needs the repo list on every page of a mirror; the repo index has it already.
        if (mode !== "global") return [payload, null];
        if (route.name === "repos") return [payload, payload];
        return load(C.dataPath(mode, null, "repos")).then(function (repos) { return [payload, repos]; });
      }).then(function (loaded) {
        if (mine !== token) return;
        var payload = loaded[0], repos = loaded[1];
        applySiteChrome(doc, site);
        var ctx = {
          mode: mode,
          repo: (site && site.repo) || mirror || "",
          mirror: mirror,
          route: route,
          site: site,
          setCrumbs: makeSetCrumbs(doc),
        };
        ctx[PAYLOAD_KEY[route.name]] = payload === undefined ? null : payload;
        current = ctx;
        CFQ.state.onQuery = null;
        renderSwitcher(doc, ctx, repos);
        wireSearch(doc);
        wireSlash(doc);
        C.clear(root);
        ctx.setCrumbs([]);
        var view = CFQ[VIEWS[route.name]];
        if (!view || typeof view.render !== "function") {
          root.appendChild(C.el(doc, "p", "This view is not available.", "empty"));
          return;
        }
        try {
          view.render(doc, root, ctx);
        } catch (err) {
          root.appendChild(C.el(doc, "p", "This view could not be rendered: " + (err && err.message), "empty"));
          if (typeof console !== "undefined") console.error(err);
        }
      });
    });
  }

  CFQ.app = { render: render, dataKeyFor: dataKeyFor };

  // ---- browser bootstrap (never runs under Node) -------------------------------------------------

  if (typeof window !== "undefined" && window.document) {
    var first = true;
    var go = function () {
      var root = document.getElementById("app");
      if (!root) return;
      render(document, root, location.hash, CFQ.core.loadData);
      if (!first && window.scrollTo) window.scrollTo(0, 0);
      first = false;
    };
    window.addEventListener("hashchange", go);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go);
    else go();
  }
})();
