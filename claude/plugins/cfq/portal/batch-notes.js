// The batch page's Notes and Closing tabs. Notes: the todo cards and plan entries this batch wrote,
// the plan entries it implements and the entries its phases parked. Closing: what the `ifq` run
// reported when it finished (language check, maintenance, security, changelog, errors, merge) and
// which skills were used.
//
// Every value reaches the DOM through `textContent` / `inlineCode`; nothing here parses markup.

(function () {
  "use strict";

  var g = typeof window !== "undefined" ? window : globalThis;
  var CFQ = g.CFQ = g.CFQ || {};

  function core() { return CFQ.core; }
  function isNum(n) { return typeof n === "number" && isFinite(n); }

  // "plan/2026-10-01-follow-up.md" -> "plan-2026-10-01-follow-up" (the entry route id).
  function parkedId(file) {
    return "plan-" + String(file || "").split("/").pop().replace(/\.md$/, "");
  }

  // Every parked entry of every attempt, once per (phase, file), in phase order.
  function parkedRows(batch) {
    var rows = [], seen = {};
    ((batch && batch.phases) || []).forEach(function (phase) {
      (phase.attempts || []).forEach(function (a) {
        (a.parkedPlanEntries || []).forEach(function (file) {
          var key = phase.slug + "\n" + file;
          if (seen[key]) return;
          seen[key] = true;
          rows.push({ phase: phase.slug, file: file, id: parkedId(file), name: String(file).split("/").pop() });
        });
      });
    });
    return rows;
  }

  function noteCount(batch) {
    return ((batch && batch.notes) || []).length + ((batch && batch.fromPlan) || []).length + parkedRows(batch).length;
  }

  function link(doc, text, href, className) {
    var a = core().el(doc, "a", text, className);
    a.setAttribute("href", href);
    return a;
  }

  function heading(doc, text) { return core().el(doc, "h3", text); }
  function none(doc) { return core().el(doc, "span", "none", "faint"); }
  function dash(doc) { return core().el(doc, "span", "–", "faint"); }

  function table(doc, cols) {
    var C = core();
    var t = C.el(doc, "table", null, "data notes");
    var thead = C.el(doc, "thead"), tr = C.el(doc, "tr");
    cols.forEach(function (c) {
      var th = C.el(doc, "th", c);
      th.setAttribute("scope", "col");
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    t.appendChild(thead);
    t.appendChild(C.el(doc, "tbody"));
    return t;
  }

  function scroll(doc, t) {
    var wrap = core().el(doc, "div", null, "tscroll");
    wrap.appendChild(t);
    return wrap;
  }

  // ---- Notes tab --------------------------------------------------------------------------------

  function stateNode(doc, note) {
    var C = core();
    if (note.state === "missing") {
      return C.el(doc, "span", note.framework ? "external" : "missing", "faint");
    }
    if (note.state === "open" || note.state === "done") return C.statusPill(doc, note.state);
    return C.el(doc, "span", note.state || "–", "faint");
  }

  function phaseLink(doc, ctx, batch, slug) {
    var C = core();
    if (!slug) return dash(doc);
    return link(doc, slug, C.href(ctx, "batch/" + batch.name + "/phase/" + slug), "mono");
  }

  function renderNotes(doc, root, ctx) {
    var C = core();
    var batch = ctx.batch;
    var notes = (batch && batch.notes) || [];
    var fromPlan = (batch && batch.fromPlan) || [];
    var parked = parkedRows(batch);
    if (!notes.length && !fromPlan.length && !parked.length) {
      root.appendChild(C.el(doc, "p", "No notes recorded for this batch.", "empty"));
      return;
    }

    if (notes.length) {
      var sec = C.el(doc, "section", null, "notes-section");
      sec.appendChild(heading(doc, "Written during this batch"));
      var t = table(doc, ["Kind", "Title", "Phase", "Written", "State"]);
      var body = t.children[1];
      notes.forEach(function (n) {
        var tr = C.el(doc, "tr");
        tr.appendChild(C.el(doc, "td", n.kind === "todo" ? "Todo card" : n.kind === "plan" ? "Plan entry" : n.kind || "–"));
        var title = C.el(doc, "td", null, "title");
        var inline = C.inlineCode(doc, n.title);
        if (n.state === "missing") {
          title.appendChild(inline);
        } else {
          var a = C.el(doc, "a");
          a.setAttribute("href", C.href(ctx, "entry/" + n.id));
          a.appendChild(inline);
          title.appendChild(a);
        }
        tr.appendChild(title);
        var ph = C.el(doc, "td");
        ph.appendChild(phaseLink(doc, ctx, batch, n.phase));
        tr.appendChild(ph);
        tr.appendChild(C.el(doc, "td", C.fmtDateTime(n.at), "date"));
        var st = C.el(doc, "td");
        st.appendChild(stateNode(doc, n));
        tr.appendChild(st);
        body.appendChild(tr);
      });
      sec.appendChild(scroll(doc, t));
      root.appendChild(sec);
    }

    if (fromPlan.length) {
      var sec2 = C.el(doc, "section", null, "notes-section");
      sec2.appendChild(heading(doc, "Implements plan entries"));
      var ul = C.el(doc, "ul", null, "plain-list");
      fromPlan.forEach(function (e) {
        var li = C.el(doc, "li");
        var a2 = C.el(doc, "a");
        a2.setAttribute("href", C.href(ctx, "entry/" + e.id));
        a2.appendChild(C.inlineCode(doc, e.title || e.id));
        li.appendChild(a2);
        ul.appendChild(li);
      });
      sec2.appendChild(ul);
      root.appendChild(sec2);
    }

    if (parked.length) {
      var sec3 = C.el(doc, "section", null, "notes-section");
      sec3.appendChild(heading(doc, "Parked by phases"));
      var ul3 = C.el(doc, "ul", null, "plain-list");
      parked.forEach(function (p) {
        var li = C.el(doc, "li");
        li.appendChild(link(doc, p.name, C.href(ctx, "entry/" + p.id)));
        li.appendChild(C.text(doc, " from "));
        li.appendChild(phaseLink(doc, ctx, batch, p.phase));
        ul3.appendChild(li);
      });
      sec3.appendChild(ul3);
      root.appendChild(sec3);
    }
  }

  // ---- Closing tab ------------------------------------------------------------------------------

  function finding(f) {
    if (typeof f === "string") return f;
    if (!f) return "";
    return (f.severity ? f.severity + ": " : "") + (f.title || f.text || "");
  }

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

  function defRow(doc, dl, label, node) {
    var C = core();
    dl.appendChild(C.el(doc, "dt", label));
    var dd = C.el(doc, "dd");
    dd.appendChild(node);
    dl.appendChild(dd);
  }

  function valueOrDash(doc, v) {
    return v === undefined || v === null || v === "" ? dash(doc) : core().el(doc, "span", v);
  }

  // Skills used across every attempt, each name once, sorted.
  function skillSets(batch) {
    var used = {};
    ((batch && batch.phases) || []).forEach(function (phase) {
      (phase.attempts || []).forEach(function (a) {
        var s = a.skills || {};
        (s.used || []).forEach(function (n) { used[n] = true; });
      });
    });
    return { used: Object.keys(used).sort() };
  }

  function securityNode(doc, closing, batch) {
    var C = core();
    var wrap = C.el(doc, "div");
    var sec = closing.security;
    if (sec) {
      var t = table(doc, ["Planning", "Now", "New"]);
      var tr = C.el(doc, "tr");
      ["planning", "now", "new"].forEach(function (k) {
        tr.appendChild(C.el(doc, "td", isNum(sec[k]) ? C.fmtInt(sec[k]) : "–", "n"));
      });
      t.children[1].appendChild(tr);
      wrap.appendChild(scroll(doc, t));
    } else {
      wrap.appendChild(dash(doc));
    }
    var snap = batch.security;
    if (snap) {
      if (snap.hint) wrap.appendChild(C.el(doc, "p", snap.hint, "muted"));
      var findings = (snap.findings || []).map(finding).filter(Boolean);
      if (findings.length) wrap.appendChild(textList(doc, findings));
    }
    return wrap;
  }

  function renderClosing(doc, root, ctx) {
    var C = core();
    var batch = ctx.batch;
    var closing = batch && batch.closing;
    if (!closing) {
      root.appendChild(C.el(doc, "p", "No closing data recorded.", "empty"));
      return;
    }
    var dl = C.el(doc, "dl", null, "result closing");
    defRow(doc, dl, "Finished", valueOrDash(doc, closing.at ? C.fmtDateTime(closing.at) : null));

    var lang = closing.lang;
    if (lang) {
      var box = C.el(doc, "div");
      var n = isNum(lang.issues) ? lang.issues : (lang.findings || []).length;
      box.appendChild(C.el(doc, "span", n + (n === 1 ? " issue" : " issues")));
      var list = (lang.findings || []).filter(Boolean);
      if (list.length) box.appendChild(textList(doc, list));
      defRow(doc, dl, "Language", box);
    } else {
      defRow(doc, dl, "Language", dash(doc));
    }

    defRow(doc, dl, "Maintenance", valueOrDash(doc, closing.maintenance));
    defRow(doc, dl, "Security", securityNode(doc, closing, batch));
    defRow(doc, dl, "Changelog", valueOrDash(doc, closing.changelog));
    defRow(doc, dl, "Errors", textList(doc, closing.errors));

    var merge = C.el(doc, "span");
    if (batch.branch) merge.appendChild(C.el(doc, "code", batch.branch));
    if (batch.branch && batch.base) merge.appendChild(C.text(doc, " → "));
    if (batch.base) merge.appendChild(C.el(doc, "code", batch.base));
    var state = batch.merged === true ? "✔ merged" : batch.merged === false ? "not merged yet" : null;
    if (state) merge.appendChild(C.el(doc, "span", (batch.branch || batch.base ? " · " : "") + state));
    if (!merge.children.length) merge.appendChild(dash(doc));
    defRow(doc, dl, "Merge", merge);

    var skills = skillSets(batch);
    var sk = C.el(doc, "div");
    sk.appendChild(C.el(doc, "div", "Used", "faint"));
    sk.appendChild(textList(doc, skills.used));
    defRow(doc, dl, "Skills", sk);

    root.appendChild(dl);
  }

  CFQ.batchNotes = {
    parkedRows: parkedRows,
    noteCount: noteCount,
    skillSets: skillSets,
  };

  CFQ.core.register("batchTab", { id: "notes", label: "Notes", order: 40, count: noteCount, render: renderNotes });
  CFQ.core.register("batchTab", { id: "closing", label: "Closing", order: 50, render: renderClosing });
})();
