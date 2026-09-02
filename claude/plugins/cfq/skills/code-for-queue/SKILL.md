---
name: code-for-queue
description: >
  Dashboard and settings for the code-for-queue workflow: show every parked queue across all
  repositories — what is still open, how much is done — manage the current repository's queue,
  and change cfq's configuration. Use for "/cfq", "/code-for-queue", "show my queues", "queue
  status", "cfq settings".
argument-hint: <settings|repo>
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
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-dash.sh"
```

`status: "NO_REPO"` means no repo anywhere has a queue yet — say so, Steps C/D still work once
this repo has one. `RUNTIME_DEGRADED` → surface `.runtimeDiagnostic` verbatim, treat both plugins
as not installed for this run. `MULTIPLE_IN_PROGRESS` → this repo has more than one batch
locked/in-progress at once, an invariant violation — surface it, never silently pick one.

## Plugin Status Line (Steps A and B)

From `.plugins`: `.mattpocock`/`.ponytail` (installed) and `.useMattpocockGrilling`/
`.usePonytailAudit` (the switches) — computed once by the aggregator, no separate call.

- Neither installed → `➖ mattpocock-skills/ponytail not installed`.
- Both installed, at least one switch off → `➖ installed · <off list>`, naming only the switch(es)
  that are actually off (`grill: classic off`, `audit off`).
- Both installed, both on → `✅ mattpocock-skills and ponytail installed · classic grill and audit
  on`.
- One installed, one missing → name the missing one and the installed one's switch state, e.g.
  `➖ ponytail not installed · classic grill on`.

## Step A — First-Time Setup (only if `setupDone` is `false`)

Print the `PRECHECKS` header on entering this step.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" state get setupDone
```

If it hasn't run yet, clarify two things **before** anything else — each its own
`AskUserQuestion`:

1. *Grill procedure*: step-by-step (one question per round, recommended) vs. classic (all
   questions of a round at once, saves context — needs `mattpocock-skills`, falls back to
   step-by-step without it). Write the result to `grillMode`.
2. *Optional third-party plugins*: for each plugin `.plugins` reports not installed, **offer** it,
   never install it unasked — what it does, what cfq uses it for, install command and docs are in
   `${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`. Agreement → hand the user the `/plugin` command
   to run and set the matching switch to `true`. Decline → the switch stays `false`; cfq must work
   fully without either plugin, no path may run into a dead end without them.

Afterward set `setupDone` to `true`. Both switches stay changeable later via Step C or the env
vars, even with a plugin installed. Print the `Setup` status line — `➖ already done` when this
step didn't run at all.

## Step B — Dashboard (default behavior with no argument)

Print the `Dash` and `Plugins` status lines, then render:

**`QUEUES`** — one row per `.repos[]` entry:

| Repo | Plan | Todo | Batches | Status |
|---|---|---|---|---|
| kankuri | 1 | 0 | 1/2 | IN_PROGRESS |

`Batches` is open/done **batch** counts (not phases). `Status` is BLOCKED/PLANNING/IN_PROGRESS/OK
per `CLAUDE.md`'s Status Vocabulary — explain the values once, not per row. Empty `.repos` → say
so plainly, no empty table.

**`THIS REPO · <name>`** — only when `.thisRepo` is non-null, one row per batch:

| Batch | Priority | Open/Done | Status |
|---|---|---|---|
| 2026-08-13-cfq-plugin | high | 4/2 | IN_PROGRESS |

For every repo whose overview `Status` is not `BLOCKED` and whose open count is nonzero, print the
copyable sequence once: `cd <repo>` → `/model sonnet` (or the first `implModels` entry) → `/ifq`.

**`CONFIG · <name>`** — only when `.thisRepo` is non-null: from `.settings`, only entries whose
`marker` is not `D`, each as `[<marker>] <key>  <value>`; an entry carrying `maskedValue`
additionally shows `⚠ masks <maskedSource> value '<maskedValue>'`. A header line states the
deviation count and total key count. One closing line offers the full list and the global view —
see `${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`.

The dashboard never executes `todo/` `check:` commands — that stays Step C's job, on request.

## Step C — Management (on request, always confirm before writing)

Six actions, exclusively in the current repository: flag/unflag priority, delete a batch, archive
a batch, clean the registry, set/remove a dependency, work off `todo/` entries. Each follows the
same shared flow — a deterministic check (already available from `.repos`/`.thisRepo`) → present →
confirm → mutate → report under an `ACTION` header. Full per-action detail in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`.

## Step D — Settings

Change requests go through `cfq-settings.sh set [--repo <path>] <key> <value>` (or `unset`) — read
each key's value/source straight from `.settings` (Step 0's call), never re-list. Scope inference,
the global-only rejection, and the `env:repo-legacy` migration note are in
`${CLAUDE_PLUGIN_ROOT}/references/dashboard.md`. After a change, print one status line:
`✅ Setting  maintenanceEvery: 50 → 40 (global)`, or `⚠️ Setting  stopUsed set, but
CFQ_STOP_USED overrides` when an env var shadows the key.
