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
    var slot = doc.getElementById ? doc.getElementById("site-title") : null;
    if (slot) slot.textContent = title;
    try { doc.title = title; } catch (e) { /* a document without a settable title */ }
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
