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
  // Repo mode: #/  #/trends  #/todos  #/inbox  #/archive  #/batch/<name>[/<tab>]  #/batch/<name>/phase/<slug>
  //            #/entry/<id>.  Global mode prefixes each with #/<mirror>/ and adds #/ = repo list.
  // Result: {name: "overview"|"batch"|"entry"|"repos", mirror, tab, batch, phase, id}; `tab` is the
  // overview tab (batches|trends|todos|inbox|archive) or the batch tab (phases|cost|context|notes|closing,
  // null when none is named).

  var OVERVIEW_TABS = { trends: "trends", todos: "todos", inbox: "inbox", archive: "archive" };
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

  // Short spans for the summary views: "45s", "11m", "1h 05m", "3d 4h"; "–" for a missing value.
  function fmtSpan(s) {
    if (!isNum(s) || s < 0) return "–";
    var total = Math.round(s);
    if (total < 60) return total + "s";
    var mins = Math.floor(total / 60);
    if (mins < 60) return mins + "m";
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours + "h " + (mins % 60 < 10 ? "0" : "") + (mins % 60) + "m";
    return Math.floor(hours / 24) + "d " + (hours % 24) + "h";
  }

  // Active working time with the calendar time beside it: {text: "≈ 11m", title: "37m"}. A record
  // without `active_s` (older telemetry) shows the calendar time alone and no title.
  function fmtActive(activeS, wallclockS) {
    if (!isNum(activeS)) return { text: fmtSpan(wallclockS), title: null };
    return { text: "≈ " + fmtSpan(activeS), title: isNum(wallclockS) ? fmtSpan(wallclockS) : null };
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

  // Local wall-clock time "HH:MM" and local date "DD.MM.YYYY" of an instant; "–" for a missing or
  // unparsable value. Both follow the browser's timezone, like fmtDateTime.
  function fmtClock(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return "–";
    var pad = function (x) { return x < 10 ? "0" + x : String(x); };
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function fmtDmy(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return "–";
    var pad = function (x) { return x < 10 ? "0" + x : String(x); };
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear();
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
    error: ["!", "Error"],
    skipped: ["↷", "Skipped"],
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

  // One side of the planning | implementation split: a swatch, title and share in the head, a row of
  // facts ({k, v, s, title}: label, value, optional sub line and tooltip) and one chip per model
  // family (names with the same family collapse into one chip). `kind` is "plan" or "impl".
  // `notes` (plain strings) follow the chips in the same row; `empty` replaces the facts with that
  // sentence when the part has no data.
  function partCard(doc, opts) {
    var card = el(doc, "div", null, "part part-" + opts.kind);
    var head = el(doc, "div", null, "part-head");
    head.appendChild(el(doc, "span", null, "swatch sw-" + opts.kind));
    head.appendChild(el(doc, "h3", opts.title));
    if (opts.share) head.appendChild(el(doc, "span", opts.share, "share"));
    card.appendChild(head);
    if (opts.empty) {
      card.appendChild(el(doc, "p", opts.empty, "empty-line muted"));
      return card;
    }
    var facts = el(doc, "div", null, "facts");
    (opts.facts || []).forEach(function (f) {
      var box = el(doc, "div", null, "fact");
      if (f.title) box.setAttribute("title", f.title);
      box.appendChild(el(doc, "div", f.k, "k"));
      box.appendChild(el(doc, "div", f.v, "v"));
      if (f.s) box.appendChild(el(doc, "div", f.s, "s"));
      facts.appendChild(box);
    });
    card.appendChild(facts);
    var models = opts.models || [];
    var notes = opts.notes || [];
    if (models.length || notes.length) {
      var slots = CFQ.charts && CFQ.charts.modelSlots ? CFQ.charts.modelSlots(models) : {};
      var meta = el(doc, "div", null, "meta");
      var seen = {};
      models.forEach(function (m) {
        var slot = slots[m] || "m-other";
        var label = slot === "m-other" ? m : slot.replace(/^m-/, "");
        if (seen[label]) return;
        seen[label] = true;
        var chip = el(doc, "span", null, "mchip");
        chip.appendChild(el(doc, "span", null, "mdot " + slot));
        chip.appendChild(text(doc, label));
        meta.appendChild(chip);
      });
      notes.forEach(function (n) { meta.appendChild(el(doc, "span", n)); });
      card.appendChild(meta);
    }
    return card;
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

  // ---- edit controls ----------------------------------------------------------------------------
  // "Open folder" link and "copy path" button for one editable item, driven by the `edit` object
  // `portal sync` writes: a file's is {path: <OS path>, dir: {path, url: <editor link, absent when
  // the editor is off>}}. The path is only ever set as text; `dir.url` becomes the link's href as
  // written. A file-level `url` (data of an older cfq) is never used.

  var EDIT_HINT = "Changes appear after the next sync (`bin/cfq portal sync <repo-root>`, or when /ifq starts).";

  // Legacy copy: a hidden textarea plus execCommand. Returns whether the browser reported success.
  function legacyCopy(doc, str) {
    if (typeof doc.execCommand !== "function" || !doc.body) return false;
    var area = doc.createElement("textarea");
    area.value = str;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    doc.body.appendChild(area);
    var ok = false;
    try {
      if (area.select) area.select();
      ok = !!doc.execCommand("copy");
    } catch (e) { ok = false; }
    doc.body.removeChild(area);
    return ok;
  }

  function copyButton(doc, str, label) {
    var button = el(doc, "button", label, "edit-copy");
    button.setAttribute("type", "button");
    var shown = null;
    function done(ok) {
      if (ok) {
        button.textContent = "Copied";
        var timer = setTimeout(function () { button.textContent = label; }, 1500);
        if (timer && timer.unref) timer.unref();
      } else if (!shown) {
        // Nothing could copy: show the path so it can be selected by hand.
        shown = el(doc, "code", str, "edit-path");
        if (button.parentNode) button.parentNode.insertBefore(shown, button.nextSibling);
      }
    }
    button.addEventListener("click", function () {
      var nav = g.navigator;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
        try {
          nav.clipboard.writeText(str).then(function () { done(true); }, function () { done(legacyCopy(doc, str)); });
          return;
        } catch (e) { /* fall through to the legacy path */ }
      }
      done(legacyCopy(doc, str));
    });
    return button;
  }

  // pairs: [[edit, {open, copy}], ...]; a pair without an edit object is skipped, no pair at all
  // gives null. One row, one hint.
  function editControlRow(doc, pairs) {
    var row = el(doc, "div", null, "edit-controls");
    var count = 0;
    pairs.forEach(function (pair) {
      var edit = pair[0], labels = pair[1] || {};
      if (!edit || (!edit.path && !edit.url)) return;
      count += 1;
      if (edit.url) {
        var a = el(doc, "a", labels.open || "Open in editor", "edit-open");
        a.setAttribute("href", edit.url);
        row.appendChild(a);
      }
      if (edit.path) row.appendChild(copyButton(doc, String(edit.path), labels.copy || "Copy path"));
    });
    if (!count) return null;
    var hint = el(doc, "span", null, "edit-hint faint");
    hint.appendChild(inlineCode(doc, EDIT_HINT));
    row.appendChild(hint);
    return row;
  }

  // One file item: a link to its folder and a copy button for its own path.
  function fileEditControls(doc, edit, labels) {
    if (!edit) return null;
    var dir = edit.dir || {};
    return editControlRow(doc, [
      [{ url: dir.url }, { open: labels.open }],
      [{ path: edit.path }, { copy: labels.copy }],
    ]);
  }

  // State the top bar and the overview share: the search text, and the overview's redraw hook
  // (`onQuery`, set while the overview is on screen, cleared by the router for every other view).
  CFQ.state = CFQ.state || { query: "", onQuery: null };

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
    fmtSpan: fmtSpan,
    fmtActive: fmtActive,
    fmtClock: fmtClock,
    fmtDmy: fmtDmy,
    fmtDateTime: fmtDateTime,
    fmtDate: fmtDate,
    billableIn: billableIn,
    addT5: addT5,
    statusPill: statusPill,
    flagBadges: flagBadges,
    tokenBar: tokenBar,
    tabs: tabs,
    partCard: partCard,
    disclosure: disclosure,
    fileEditControls: fileEditControls,
    editControlRow: editControlRow,
  };
})();
