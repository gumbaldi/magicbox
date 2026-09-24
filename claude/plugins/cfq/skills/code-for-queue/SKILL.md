---
name: code-for-queue
description: >
  Dashboard and settings for the code-for-queue workflow: show every parked queue across all
  repositories — what is still open, how much is done — manage the current repository's queue,
  and change cfq's configuration. Use for "/cfq", "/code-for-queue", "show my queues", "queue
  status", "cfq settings".
argument-hint: <settings|setup|repo>
---

# Code-for-Queue: Dashboard, Settings, First-Time Setup

Always answer in the user's language.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | A | `Setup` | `➖ already done` / `⚠️ first run · 2 questions follow` |
| PRECHECKS | B | `Dash` | `2 repos · 1 with open work` |
| PRECHECKS | B | `Plugins` | `✅ mattpocock-skills and ponytail installed · classic grill and audit on` |

## Step 0 — Aggregate

One call, reused by Steps A through D — never re-derive any of the following by hand:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" dash
```

`status: "NO_REPO"` means no repo anywhere has a queue yet — say so, Steps C/D still work once
this repo has one. `RUNTIME_DEGRADED` → surface `.runtimeDiagnostic` verbatim, treat both plugins
as not installed for this run. `MULTIPLE_IN_PROGRESS` → this repo has more than one batch
locked/in-progress at once, an invariant violation — surface it, never silently pick one.

## Plugin Status Line (Step A)

`cfq dash render` (Step B) computes this identically inside the script — this section is Step A's
own copy, needed there because Step A's offer flow reacts to `.plugins` directly rather than
printing the rendered block.

From `.plugins`: `.mattpocock`/`.ponytail` (installed), `.useMattpocockGrilling`/
`.usePonytailAudit` (the switches), and `.ponytailMode` (`off`/`lite`/`full`/`ultra`/`unknown`) —
computed once by the aggregator, no separate call.

- Neither installed → `➖ mattpocock-skills/ponytail not installed`.
- Both installed, at least one switch off → `➖ installed · <off list>`, naming only the switch(es)
  that are actually off (`grill: classic off`, `ponytail audit: off`).
- Both installed, both on → `✅ mattpocock-skills and ponytail installed · classic grill on ·
  ponytail audit: on`.
- One installed, one missing → name the missing one and the installed one's switch state, e.g.
  `➖ ponytail not installed · classic grill on`.
- Ponytail installed and `.ponytailMode` is not `off` → append `· ponytail default mode: <mode> ·
  cfq expects off` and force the icon to `⚠️`, regardless of which of the four cases above
  applies — cfq expects ponytail dormant outside the maintenance audit.
  `.ponytailMode == "off"` → no clause appended, no icon change, no warning — `off` is the
  expected, configured state.

## Step A — First-Time Setup (only if `setupDone` is `false`)

Print the `PRECHECKS` header on entering this step.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings state get setupDone
```

Not yet run → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and follow its **Global
Part** — the same flow Step E below runs by name. Print its own closing status line (`Setup  ✅
done · <n> changed`) as the `Setup` status line for this step; `➖ already done` when this step
didn't run at all.

## Step B — Dashboard (default behavior with no argument)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" dash render
```

Print its output exactly as returned, in the order the script emits it — `PRECHECKS` header,
`Dash`/`Plugins` status lines, `QUEUES`, `THIS REPO · <name>` (when applicable, open batches only,
plus the expanded next batch), `CONFIG · <name>`, `ACTIONS` (every management action and settings
command Step C/D can run, naming each in one line), and finally `NEXT` — the copyable
`cd`/`/model`/`/ifq` sequence, current repo first when several repos have open work, state
described before the call to action that follows it. No reformatting, no rebuilding a table from
`.repos`/`.thisRepo`/`.settings` by hand — this is the same aggregation **Aggregate** fetches as JSON,
formatted by the script instead of the model. (The bare `/cfq` slash command already prints this
block via its own injection before the model runs at all; this step exists for every other way the
skill gets invoked — natural language, or as part of Step A's flow.)

`QUEUES`' `Reports` column and its `ACTIONS` entry both point at `/rfq` (`report-for-queue`) for
reading what a finished batch produced — the dashboard itself never renders a report.

The dashboard never executes `todo/` `check:` commands — that stays Step C's job, on request, in
one `bin/cfq note sweep` call rather than per card.

## Step C — Management (on request, always confirm before writing)

Six actions, exclusively in the current repository: flag/unflag priority, delete a batch, archive
a batch, clean the registry, set/remove a dependency, work off `todo/` entries in one
`bin/cfq note sweep` call rather than per card. Each follows the
same shared flow — a deterministic check (already available from `.repos`/`.thisRepo`) → present →
confirm → mutate → report under an `ACTION` header. Full per-action detail in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`.

## Step D — Settings

Argument `settings` (or a request for "the settings menu") → read
`${CLAUDE_PLUGIN_ROOT}/references/settings-menu.md` and follow it: a guided scope → group → key →
value picker, global or per repo. A free-text change request ("set stopUsed to 100000") skips the
picker and goes straight through the rest of this step, unchanged.

Change requests go through `bin/cfq settings set [--repo <path>] <key> <value>` (or `unset`) — read
each key's value/source straight from `.settings` (**Aggregate**'s call), never re-list. Scope inference,
the global-only rejection, and the `env:repo-legacy` migration note are in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`. After a change, print one status line:
`✅ Setting  maintenanceEvery: 50 → 40 (global)`, or `⚠️ Setting  stopUsed set, but
CFQ_STOP_USED overrides` when an env var shadows the key.

## Step E — Setup Wizard

Argument `setup` → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and follow it: its
**Global Part** always, then — inside a repo — its **Repo Part**; outside a repo the global part is
the whole wizard. This is the exact **Global Part** flow Step A already runs automatically on
`setupDone: false` — Step A never chains into the repo part on its own, even inside a repo; only
`/pfq`'s own unknown-repo trigger and this explicit `setup` argument run it. Running this step
again by name re-walks the whole flow, and every question's "keep current"/"keep" option makes an
already-configured value a no-op.
