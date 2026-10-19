// Shared core of the portal viewer: routing, data loading, DOM helpers, formatting and the slot
// registry every other portal script plugs into. Plain JS, no libraries, no build step; works from
// file:// in any current browser and under `node --test` (tests/js/*.test.mjs).
//
// Every script under portal/ attaches to one shared namespace object `CFQ` (`window.CFQ` in a
// browser, `globalThis.CFQ` under Node) and exports nothing else. `core.js` loads first, `app.js`
// last; a module touches another one only inside functions, never at load time.
//
// The data comes from repo files, and the viewer must not become an injection path: every value
// reaches the DOM through `textContent` (`el()`, `inlineCode()`), except the HTML fragments
// `cfq_lib/markdown.py` pre-rendered and escaped server-side (`...Html` fields), which go through
// `html()` -- the one function in the whole viewer that assigns `innerHTML`.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  // ---- routes -----------------------------------------------------------------------------------
  // Repo mode: #/  #/todos  #/inbox  #/archive  #/batch/<name>[/<tab>]  #/batch/<name>/phase/<slug>
  //            #/entry/<id>.  Global mode prefixes each with #/<mirror>/ and adds #/ = repo list.
  // Result: {name: "overview"|"batch"|"entry"|"repos", mirror, tab, batch, phase, id}; `tab` is the
  // overview tab (batches|todos|inbox|archive) or the batch tab (phases|cost|context|notes|closing,
  // null when none is named).

  var OVERVIEW_TABS = { todos: "todos", inbox: "inbox", archive: "archive" };
  var BATCH_TABS = ["phases", "cost", "context", "notes", "closing"];

  function decode(part) {
    try { return decodeURIComponent(part); } catch (e) { return part; }
  }

  function parseRoute(hash, mode) {
    var parts = String(hash || "").replace(/^#/, "").split("/").filter(function (p) { return p !== ""; }).map(decode);
    var mirror = null;
    if (mode === "global") {
      if (!parts.length) return { name: "repos", mirror: null, tab: null, batch: null, phase: null, id: null };
      mirror = parts.shift();
    }
    var route = { name: "overview", mirror: mirror, tab: "batches", batch: null, phase: null, id: null };
    if (parts[0] === "batch" && parts.length >= 2) {
      route.name = "batch";
      route.tab = null;
      route.batch = parts[1];
      if (parts[2] === "phase" && parts[3]) route.phase = parts[3];
      else if (BATCH_TABS.indexOf(parts[2]) !== -1) route.tab = parts[2];
    } else if (parts[0] === "entry" && parts.length >= 2) {
      route.name = "entry";
      route.tab = null;
      route.id = parts.slice(1).join("/");
    } else if (parts[0] && OVERVIEW_TABS[parts[0]]) {
      route.tab = OVERVIEW_TABS[parts[0]];
    }
    return route;
  }

  // A path relative to the reports root, without ".js". `site` and `repos` are the same file in
  // both modes; every per-repo file lives under "<mirror>/" in global mode.
  function dataPath(mode, repo, key) {
    if (mode === "global" && repo && key !== "site" && key !== "repos") return repo + "/data/" + key;
    return "data/" + key;
  }

  function href(ctx, path) {
    path = path || "";
    if (ctx && ctx.mode === "global") return "#/" + ctx.mirror + "/" + path;
    return "#/" + path;
  }

  // ---- data loading -----------------------------------------------------------------------------
  // Each data file registers `window.CFQ_DATA["<key>"]`; the key is whatever follows the last
  // "data/" in the path, so repo-local and mirrored files share one key space per file. Cached by
  // full path so two repos' same-named file never serve each other's promise.

  var cache = Object.create(null);

  function dataKeyFromPath(path) {
    var idx = path.lastIndexOf("data/");
    return idx === -1 ? path : path.slice(idx + 5);
  }

  function loadData(path) {
    if (Object.prototype.hasOwnProperty.call(cache, path)) return cache[path];
    var key = dataKeyFromPath(path);
    cache[path] = new Promise(function (resolve) {
      var script = document.createElement("script");
      script.src = path + ".js";
      script.onload = function () {
        var data = window.CFQ_DATA;
        resolve(data && Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null);
      };
      script.onerror = function () { resolve(null); };
      document.head.appendChild(script);
    });
    return cache[path];
  }

  // ---- slots ------------------------------------------------------------------------------------
  // Later phases add behaviour by registering an item under a slot from a file of their own.

  var slots = Object.create(null);
  var seq = 0;

  function register(slot, item) {
    (slots[slot] = slots[slot] || []).push({ item: item, seq: seq++ });
    return item;
  }

  function registered(slot) {
    return (slots[slot] || []).slice().sort(function (a, b) {
      var oa = typeof a.item.order === "number" ? a.item.order : 0;
      var ob = typeof b.item.order === "number" ? b.item.order : 0;
      return oa - ob || a.seq - b.seq;
    }).map(function (e) { return e.item; });
  }

  // ---- DOM helpers: the one place text or markup reaches an element ----------------------------

  function el(doc, tag, text, className) {
    var e = doc.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (className) e.className = className;
    return e;
  }

  // The only `innerHTML` assignment in the viewer: `markup` must be a fragment pre-rendered and
  // escaped by cfq_lib/markdown.py.
  function html(doc, tag, markup, className) {
    var e = doc.createElement(tag);
    e.innerHTML = markup || "";
    if (className) e.className = className;
    return e;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function text(doc, s) {
    return doc.createTextNode(String(s));
  }

  // "a `b` c" -> a span holding text, <code>, text; nothing is parsed as markup.
  function inlineCode(doc, str) {
    var span = doc.createElement("span");
    String(str === undefined || str === null ? "" : str).split("`").forEach(function (piece, i) {
      if (piece === "") return;
      if (i % 2 === 1) span.appendChild(el(doc, "code", piece));
      else span.appendChild(text(doc, piece));
    });
    return span;
  }

  // ---- formatting -------------------------------------------------------------------------------

  function isNum(n) { return typeof n === "number" && isFinite(n); }

  function fmtInt(n, locale) {
    if (!isNum(n)) return "–";
    return Math.round(n).toLocaleString(locale);
  }

  function fmtTokens(n) {
    if (!isNum(n)) return "–";
    var v = Math.round(n);
    if (v < 1000) return String(v);
    var k = Math.round(v / 100) / 10;
    if (v < 1e6 && k < 1000) return String(k) + "k";
    return String(Math.round(v / 1e5) / 10) + "M";
  }

  function fmtDuration(s) {
    if (!isNum(s) || s <= 0) return "–";
    var total = Math.round(s);
    var h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), sec = total % 60;
    var pad = function (x) { return x < 10 ? "0" + x : String(x); };
    return h ? h + ":" + pad(m) + ":" + pad(sec) : m + ":" + pad(sec);
  }

  function defaultFormatter(options) {
    try { return new Intl.DateTimeFormat(undefined, options); } catch (e) { return null; }
  }

  // `fmt` is anything with .format(Date); the default follows the browser's locale and timezone.
  function fmtDateTime(iso, fmt) {
    if (!iso) return "–";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    fmt = fmt || defaultFormatter({ dateStyle: "medium", timeStyle: "short" });
    return fmt ? fmt.format(d) : d.toISOString();
  }

  function fmtDate(iso, fmt) {
    if (!iso) return "–";
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
    // A bare date is a calendar day, not an instant: build it in local time so no timezone shifts it.
    var d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    fmt = fmt || defaultFormatter({ dateStyle: "medium" });
    return fmt ? fmt.format(d) : d.toISOString().slice(0, 10);
  }

  function billableIn(t) {
    return ((t && t.input) || 0) + ((t && t.cache_creation) || 0);
  }

  function addT5(a, b) {
    var out = { turns: 0, input: 0, output: 0, cache_read: 0, cache_creation: 0 };
    Object.keys(out).forEach(function (k) { out[k] = ((a && a[k]) || 0) + ((b && b[k]) || 0); });
    return out;
  }

  // ---- shared widgets ---------------------------------------------------------------------------

  var STATUS = {
    planning: ["✎", "Planning"],
    awaiting_review: ["◔", "Awaiting review"],
    planned: ["○", "Planned"],
    blocked: ["⊘", "Blocked"],
    in_progress: ["▶", "In progress"],
    done: ["✔", "Done"],
    green: ["✔", "Green"],
    red: ["✖", "Red"],
    question: ["?", "Question"],
    open: ["○", "Open"],
  };

  // Status is always icon plus text, never colour alone.
  function statusPill(doc, status) {
    var known = Object.prototype.hasOwnProperty.call(STATUS, status);
    var pill = el(doc, "span", null, "pill" + (known ? " pill-" + status : ""));
    if (!known) {
      pill.textContent = String(status === undefined || status === null ? "" : status);
      return pill;
    }
    var icon = el(doc, "span", STATUS[status][0], "icon");
    icon.setAttribute("aria-hidden", "true");
    pill.appendChild(icon);
    pill.appendChild(el(doc, "span", STATUS[status][1], "label"));
    return pill;
  }

  // `flags` is the queue row's {warn, info} counts or a batch/phase `flags` array of
  // {level, text}; the badge titles list the texts when they are known.
  function flagBadges(doc, flags) {
    var counts = { warn: 0, info: 0 }, texts = { warn: [], info: [] };
    if (Array.isArray(flags)) {
      flags.forEach(function (f) {
        if (!f || !counts.hasOwnProperty(f.level)) return;
        counts[f.level] += 1;
        if (f.text) texts[f.level].push(f.text);
      });
    } else if (flags) {
      counts.warn = flags.warn || 0;
      counts.info = flags.info || 0;
    }
    var wrap = el(doc, "span", null, "flags");
    [["warn", "⚠"], ["info", "ⓘ"]].forEach(function (pair) {
      var level = pair[0];
      if (!counts[level]) return;
      var badge = el(doc, "span", pair[1] + " " + counts[level], "flag flag-" + level);
      badge.setAttribute("title", texts[level].length ? texts[level].join("\n")
        : counts[level] + (level === "warn" ? " warning" : " note") + (counts[level] === 1 ? "" : "s"));
      wrap.appendChild(badge);
    });
    if (!wrap.children.length) {
      wrap.className = "flags none";
      wrap.textContent = "–";
      wrap.setAttribute("title", "no flags");
    }
    return wrap;
  }

  // A fixed-width track with a fill proportional to value/max and the rounded value beside it.
  function tokenBar(doc, value, max) {
    var wrap = el(doc, "span", null, "tokbar");
    if (!isNum(value)) {
      wrap.appendChild(el(doc, "span", "–", "val"));
      return wrap;
    }
    var track = el(doc, "span", null, "track");
    var fill = el(doc, "span", null, "fill");
    var pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    fill.style.width = (Math.round(pct * 10) / 10) + "%";
    track.appendChild(fill);
    wrap.appendChild(track);
    var val = el(doc, "span", fmtTokens(value), "val");
    val.setAttribute("title", fmtInt(value));
    wrap.appendChild(val);
    return wrap;
  }

  // items: [{id, label, href}]; the active one is marked with aria-current.
  function tabs(doc, items, activeId) {
    var nav = el(doc, "nav", null, "tabs");
    nav.setAttribute("aria-label", "Views");
    items.forEach(function (item) {
      var a = el(doc, "a", item.label, "tab" + (item.id === activeId ? " active" : ""));
      a.setAttribute("href", item.href);
      if (item.id === activeId) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
    return nav;
  }

  // A real button; the body renders on first open only.
  function disclosure(doc, labelNode, renderBody) {
    var wrap = el(doc, "div", null, "disclosure");
    var button = el(doc, "button", null, "disclosure-toggle");
    button.setAttribute("type", "button");
    button.setAttribute("aria-expanded", "false");
    button.appendChild(el(doc, "span", "▸", "caret"));
    button.appendChild(typeof labelNode === "string" ? text(doc, labelNode) : labelNode);
    var body = el(doc, "div", null, "disclosure-body");
    body.setAttribute("hidden", "");
    var rendered = false;
    button.addEventListener("click", function () {
      var open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        body.removeAttribute("hidden");
        if (!rendered) { rendered = true; renderBody(doc, body); }
      } else {
        body.setAttribute("hidden", "");
      }
    });
    wrap.appendChild(button);
    wrap.appendChild(body);
    return wrap;
  }

  CFQ.core = {
    parseRoute: parseRoute,
    dataPath: dataPath,
    dataKeyFromPath: dataKeyFromPath,
    href: href,
    loadData: loadData,
    register: register,
    registered: registered,
    el: el,
    html: html,
    text: text,
    inlineCode: inlineCode,
    clear: clear,
    fmtInt: fmtInt,
    fmtTokens: fmtTokens,
    fmtDuration: fmtDuration,
    fmtDateTime: fmtDateTime,
    fmtDate: fmtDate,
    billableIn: billableIn,
    addT5: addT5,
    statusPill: statusPill,
    flagBadges: flagBadges,
    tokenBar: tokenBar,
    tabs: tabs,
    disclosure: disclosure,
  };
})();
