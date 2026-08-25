---
name: code-for-queue
description: >
  Dashboard and settings for the code-for-queue workflow: show every parked queue across all
  repositories — what is still open, how much is done — manage the current repository's queue,
  and change cfq's configuration. Use for "/cfq", "/code-for-queue", "show my queues", "queue
  status", "cfq settings".
---

# Code-for-Queue: Dashboard, Settings, First-Time Setup

Always answer in the user's language.

## Output Format

Progress is reported as status lines, not prose. One line per step, printed **as soon as that
step is done** — never collected and dumped at the end. Section headers are printed once, on
entering the section.

```
SECTION HEADER IN CAPS
<icon> <label padded to 16 chars><detail, one short clause>
```

Icons: `✅` done · `⚠️` warning, unavailable, degraded · `❌` failed · `➖` skipped, not
applicable, nothing to do.

Rules:

- The detail says what the check found, not what you are about to do next. `sonnet · implModels:
  sonnet`, not "the model gate is satisfied, I will now look at the batch".
- A step that did not run still gets its line, with `➖` or `⚠️` and the reason — "no security
  data for this repo" is exactly the information the user is after.
- Sub-information belongs on an indented `   └ ` continuation line, never in the detail column.
- Section headers, labels, and status-line content are always English — regardless of the
  language the rest of the conversation is in. Only interactive prose (see below) follows the
  user's language.
- No commentary around the block: no "I will now …", no "done!", no summary sentence that repeats
  what the lines already say.
- The result section is a label/value list under the same padding, not a table.
- Interactive parts are exempt: `AskUserQuestion`, the batch briefing, and any question to the
  user stay in the user's language.
- The data tables of this skill are not status lines and stay exactly as specified below — the
  format applies to what happens around them.

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | A | `Setup` | `➖ already done` / `⚠️ first run · 2 questions follow` |
| PRECHECKS | B | `Scan` | `4 repos · 3 with open work` / `➖ no open batches` |
| PRECHECKS | B | `Plugins` | `✅ mattpocock-skills and ponytail installed · classic grill and audit on` |

## Plugin Status Line (shared by Steps A and B)

Both steps need the same live check — computed once here so the two never drift out of sync:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-runtime.sh" plugins
```

then locally `jq` for whether `mattpocock-skills` (→ classic grill, `useMattpocockGrilling`) and
`ponytail` (→ maintenance audit, `usePonytailAudit`) are present in the returned `.plugins` array.
Step B additionally reads each matching switch (`cfq-settings.sh get useMattpocockGrilling` /
`... get usePonytailAudit`) to render the `Plugins` status line:

- Neither plugin installed → `➖ mattpocock-skills/ponytail not installed`.
- Both installed, at least one switch off → `➖ installed · <off list>`, naming only the switch(es)
  that are actually off (`grill: classic off`, `audit off`), comma-joined when both are off.
- Both installed, both switches on → `✅ mattpocock-skills and ponytail installed · classic grill
  and audit on`.
- One plugin installed, the other missing → name the missing one and the installed one's switch
  state in the same clause, e.g. `➖ ponytail not installed · classic grill on`.

## Step A — First-Time Setup (only if `setupDone` is `false`)

Print the `PRECHECKS` header on entering this step.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" state get setupDone
```

If it hasn't run yet, clarify two things **before** anything else — each its own
`AskUserQuestion`:

1. *Grill procedure*: "step-by-step (one question per round, more pleasant)" — recommended —
   versus "classic (all questions of a round at once, saves context)". For the classic mode,
   state clearly that it needs the `mattpocock-skills` plugin and automatically falls back to
   the step-by-step procedure without it. Write the result to `grillMode`.

2. *Optional third-party plugins*: for each plugin not installed, **offer** it, never install it
   unasked. Precede the question with a short, honest description: what it does, what cfq uses
   it for, and where the docs are.

   | Plugin | What cfq uses it for | Installation | Docs |
   |---|---|---|---|
   | `mattpocock-skills` | classic grill mode (`grillMode: classic`) | `/plugin install mattpocock-skills@claude-plugins-official` — if the marketplace is missing: `/plugin marketplace add anthropics/claude-plugins-official` | `github.com/anthropics/claude-plugins-official`, locally the `SKILL.md` under `skills/productivity/grilling/` in the plugin cache |
   | `ponytail` | one of several tasks in the maintenance run: an optional cleanup audit | `/plugin marketplace add DietrichGebert/ponytail`, then `/plugin install ponytail@ponytail` | `github.com/DietrichGebert/ponytail`, at runtime `/ponytail-help` |

   Check availability yourself beforehand using the installed/not-installed half of the **Plugin
   Status Line** check above (the skill list in context, or the same `cfq-runtime.sh plugins` +
   `jq` call) and only offer what's missing — an already-installed plugin starts enabled (its
   switch now defaults to `true`) without asking here. Agreement → **hand the user the `/plugin`
   command to run** (plugins can't be installed from within a skill) and set the matching switch
   (`useMattpocockGrilling` / `usePonytailAudit`) to `true`. Decline → the switch stays `false`,
   the feature is disabled, and that's noted once in a sentence. **cfq must work fully without
   either plugin** — no path may run into a dead end without them.

Afterward set `setupDone` to `true` (`cfq-settings.sh state set setupDone true`). Both switches remain changeable at any time via Step C or
the env vars — even with a plugin installed, it can be switched off again here. Print the `Setup`
status line — `➖ already done` when this step didn't run at all.

## Step B — Dashboard (default behavior with no argument)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh" --format=md
```

Compute the `Plugins` status line per the shared **Plugin Status Line** rule above. Print the
`Scan` and `Plugins` status lines, then render the returned Markdown table essentially
verbatim — sorting, priority marking and the `Status` column (`BLOCKED`/`PLANNING`/`IN_PROGRESS`/
`OK`, per `CLAUDE.md`'s Status Vocabulary) are already computed by the script, not rebuilt from
JSON by hand:

| Repo | Batch | Priority | Open/Done | Status |
|---|---|---|---|---|
| kankuri | 2026-08-13-cfq-plugin | high | 4/2 | IN_PROGRESS |

- Explain the `Status` values once, not per row: `BLOCKED` batches aren't offered by `ifq`;
  `PLANNING` means still being written; `IN_PROGRESS` has an active lock.
- Table empty (no rows beyond the header) → say so plainly instead of showing an empty table.
- For every repo with at least one row whose `Status` is not `BLOCKED` and whose `Open/Done` first
  number is nonzero, print the copyable sequence: `cd <repo>` → `/model sonnet` (or the first
  model from `implModels`) → `/ifq` — once per repo, not per batch.
- The dashboard never executes `check:` commands. This stays an explicit rule so a future rework
  doesn't drop it by accident.
- `cfq-scan.sh`'s per-repo `plan`/`todo` counters and the `unknownDeps` edge warning are not part
  of the `--format=md` row projection (batch rows only) — reach for `cfq-scan.sh` (no flag, JSON)
  ad hoc if a user specifically asks about either.

**Other repos are read-only.** Step C only applies to the repo `cfq` is currently running in.

## Step C — Management (on request, always confirm before writing)

Every action below follows the same shared flow: a deterministic script computes the proposed
action (file count, dependency existence, blocked status — already available from `cfq-scan.sh`'s
`blocked`/`unknownDeps` fields, no new script needed for that part) → Claude presents it → the user
confirms → the existing mutation script executes → the structured result is shown. No new script
per action.

Six actions, exclusively in the current repository (`git rev-parse --show-toplevel`):

1. **Flag/unflag high priority** — write or delete `.priority`.
2. **Delete a batch** — remove the directory. Name the batch and the number of files that will
   be lost beforehand, and get explicit confirmation.
3. **Archive a batch** — move to `<repo>/.claude/cfq/impl/done/<batch>/` without working it
   off. Open phases then count as done-but-not-implemented; say so in the confirmation text.
4. **Clean the registry** — `cfq-registry.sh prune`, list the removed paths.
5. **Set/remove a dependency** — write or delete `.dependsOn` in the chosen batch. Before writing,
   check whether the named batch exists (open or in `done/`); if not, warn but write anyway on
   request — the edge is fail-soft by design. As with the other actions: current repo only,
   always with confirmation.
6. **Work off todos** — same current-repo-only rule:
   1. List every entry under `todo/*.md`: title plus the one or two sentences describing what to
      do.
   2. For an entry with a `check:` line, **show** the command, then run it. Exit `0` → done, move
      the file to `todo/done/`, and print a status line under the `ACTION` header naming the
      reason (`✅ Todo   merge-v0.2: check green · moved to done`). Exit ≠ 0 → the entry stays
      open, with one line explaining why.
   3. Entries without a `check:` line are only shown, and only checked off on explicit
      confirmation.
   4. Never create or edit an entry here — those are written by `ifq` (P6).

No pulling things back out of `done/` and no editing phase files — that's `pfq`'s job.

The confirmation question stays prose. After execution, print one line per action under an
`ACTION` header — the label names the action (`Priority`, `Registry`, `Dependency`, etc.), the
detail the before/after or a `⚠️` note:

```
ACTION
✅ Priority        2026-08-13-cfq-plugin: flagged high
✅ Registry        3 dead paths removed
⚠️ Dependency      2026-08-10-auth does not exist · edge written anyway
```

## Step D — Settings

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" list --repo "$(git rev-parse --show-toplevel)" --sources
```

One call gives every key's effective value and which tier supplied it (`env:process`,
`env:repo-legacy`, `repo`, `global`, `default`) for both the global store and this repo at once.
Pair each row with its explanation from `cfq-settings.sh describe [<key>]` — that schema call is
the single source for per-key prose, not a hand-maintained table; `${CLAUDE_PLUGIN_ROOT}/references/settings-explain.md`
adds only the nuance that doesn't reduce to schema data. This value list is not a status line and
stays as specified.

Change requests go through `cfq-settings.sh set [--repo <path>] <key> <value>` (or `unset`). **All**
keys are changeable here, including `planBlockedPlugins` / `implBlockedPlugins` (strict
prohibition) — there is no exception left. A key whose `scope` is global-only (`scanRoots`,
`securityTimeoutSeconds`, `securityFindingsCap`) rejects `--repo`; say so and fall back to a global
`set`. `0` is a valid, deliberate value for `stopUsed` meaning "hand off after every phase";
`-1` is equally valid, meaning "never hand off for this reason" — neither is a misconfiguration,
don't flag either.

Infer `--global` vs. `--repo` from the user's own phrasing where it's unambiguous ("for this repo",
"just here" → `--repo`; "everywhere", "by default" → global) — only ask via `AskUserQuestion` when
genuinely ambiguous, not on every request. If `--sources` reported any `env:repo-legacy` entries
(the value comes from the old per-repo `env` block in `<repo>/.claude/settings.json`, not a
`CFQ_*` shell variable), print one note pointing at `cfq-settings.sh migrate <repo-root>` to carry
that override into the repo settings file — once per session, not once per key.

After a `set`/`unset` call, print one status line: `✅ Setting  maintenanceEvery: 50 → 40 (global)`,
or, when an env var shadows the key, `⚠️ Setting  stopUsed set, but CFQ_STOP_USED overrides`. A
rejected out-of-scope `--repo` attempt prints `❌ Setting  scanRoots is global-only, use set
scanRoots <value> without --repo`.
