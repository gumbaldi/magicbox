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
| PRECHECKS | 2 | `Setup` | `➖ already done` / `⚠️ first run · 2 questions follow` |
| PRECHECKS | 3 | `Dash` | `2 repos · 1 with open work` |
| PRECHECKS | 3 | `Plugins` | `✅ mattpocock-skills and ponytail installed · classic grill and audit on` |

## Step 1 — Aggregate

One call, reused by **First-Time Setup** through **Settings** — never re-derive any of the following by hand:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" dash
```

`status: "NO_REPO"` means no repo anywhere has a queue yet — say so, **Management** and **Settings** still work once
this repo has one. `RUNTIME_DEGRADED` → surface `.runtimeDiagnostic` verbatim, treat both plugins
as not installed for this run. `MULTIPLE_IN_PROGRESS` → this repo has more than one batch
locked/in-progress at once, an invariant violation — surface it, never silently pick one.

## Step 2 — First-Time Setup (only if `setupDone` is `false`)

Print the `PRECHECKS` header on entering this step. Print `.plugins.statusLine.text` as returned;
this step's offer flow reads `.plugins`' installed/switch fields directly.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings state get setupDone
```

Not yet run → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and follow its **Global
Part** — the same flow **Setup Wizard** below runs by name. Print its own closing status line (`Setup  ✅
done · <n> changed`) as the `Setup` status line for this step; `➖ already done` when this step
didn't run at all.

## Step 3 — Dashboard (default behavior with no argument)

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" dash render
```

Print its output exactly as returned, in the order the script emits it — `PRECHECKS` header,
`Dash`/`Plugins` status lines, `QUEUES`, `THIS REPO · <name>` (when applicable, open batches only,
plus the expanded next batch), `CONFIG · <name>`, `ACTIONS` (every management action and settings
command **Management** and **Settings** can run, naming each in one line), and finally `NEXT` — the copyable
`cd`/`/model`/`/ifq` sequence, current repo first when several repos have open work, state
described before the call to action that follows it. No reformatting, no rebuilding a table from
`.repos`/`.thisRepo`/`.settings` by hand — this is the same aggregation **Aggregate** fetches as JSON,
formatted by the script instead of the model. (The bare `/cfq` slash command already prints this
block via its own injection before the model runs at all; this step exists for every other way the
skill gets invoked — natural language, or as part of **First-Time Setup**'s flow.)

`QUEUES`' `Reports` column and its `ACTIONS` entry both point at the report portal
(`<repo>/.claude/cfq/reports/index.html`) — the dashboard itself never renders a report.

The dashboard never executes `todo/` `check:` commands — that stays **Management**'s job, on request, in
one `bin/cfq note sweep` call rather than per entry.

## Step 4 — Management (on request, always confirm before writing)

Six actions, exclusively in the current repository: flag/unflag priority, delete a batch, archive
a batch, clean the registry, set/remove a dependency, work off `todo/` entries in one
`bin/cfq note sweep` call rather than per entry. Each follows the
same shared flow — a deterministic check (already available from `.repos`/`.thisRepo`) → present →
confirm → mutate → report under an `ACTION` header. Full per-action detail in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`.

## Step 5 — Settings

Argument `settings` (or a request for "the settings menu") → read
`${CLAUDE_PLUGIN_ROOT}/references/settings-menu.md` and follow it: a guided scope → group → key →
value picker, global or per repo. A free-text change request ("set stopUsed to 100000") skips the
picker and goes straight through the rest of this step, unchanged.

Explaining a setting pairs its `bin/cfq settings describe [<key>]` text with
`${CLAUDE_PLUGIN_ROOT}/references/settings-explain.md`, which adds only the nuance that doesn't
reduce to schema data.

Change requests go through `bin/cfq settings set [--repo <path>] <key> <value>` (or `unset`) — read
each key's value/source straight from `.settings` (**Aggregate**'s call), never re-list. Scope inference,
the global-only rejection, and the `env:repo-legacy` migration note are in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`. After a change, print one status line:
`✅ Setting  maintenanceEvery: 50 → 40 (global)`, or `⚠️ Setting  stopUsed set, but
CFQ_STOP_USED overrides` when an env var shadows the key.

## Step 6 — Setup Wizard

Argument `setup` → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and follow it: its
**Global Part** always, then — inside a repo — its **Repo Part**; outside a repo the global part is
the whole wizard. This is the exact **Global Part** flow **First-Time Setup** already runs automatically on
`setupDone: false` — **First-Time Setup** never chains into the repo part on its own, even inside a repo; only
`/pfq`'s own unknown-repo trigger and this explicit `setup` argument run it. Running this step
again by name re-walks the whole flow, and every question's "keep current"/"keep" option makes an
already-configured value a no-op.
