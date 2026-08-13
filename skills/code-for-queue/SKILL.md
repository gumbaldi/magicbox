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

## Step A — First-Time Setup (only if `setupDone` is `false`)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get setupDone
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
   | `ponytail` | optional cleanup audit at the end of a planning session | `/plugin marketplace add DietrichGebert/ponytail`, then `/plugin install ponytail@ponytail` | `github.com/DietrichGebert/ponytail`, at runtime `/ponytail-help` |

   Check availability yourself beforehand (the skill list in context, or
   `ls -d ~/.claude/plugins/cache/*/mattpocock-skills ~/.claude/plugins/cache/*/ponytail 2>/dev/null`)
   and only offer what's missing. Agreement → **hand the user the `/plugin` command to run**
   (plugins can't be installed from within a skill) and set the matching switch
   (`useMattpocockGrilling` / `usePonytailAudit`) to `true`. Decline → the switch stays `false`,
   the feature is disabled, and that's noted once in a sentence. **cfq must work fully without
   either plugin** — no path may run into a dead end without them.

Afterward set `setupDone` to `true`. Both switches remain changeable at any time via Step C or
the env vars — even with a plugin installed, it can be switched off again here.

## Step B — Dashboard (default behavior with no argument)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh"
```

Render a Markdown table from the JSON, sorted by repo, then within it by priority
(`high` > `medium` > `low`), then by batch name:

| Repo | Batch | Prio | Open | Done | Progress |
|---|---|---|---|---|---|
| kankuri | 2026-08-13-cfq-plugin | medium | 4 | 2 | ▓▓▓░░░░░ 33% |

- Repo column: basename only, resolve the full path once underneath.
- Archived batches (`archived: true`) in their own, collapsed list below the table — they
  shouldn't crowd out open work, but the work already done should stay visible.
- End with a summary line: number of repos with open work, total open phases, total done phases.
- For every repo with open batches, print the copyable sequence:
  `cd <repo>` → `/model sonnet` (or the first model from `implModels`) → `/ifq`.
- No open batches → say so plainly instead of showing an empty table.

**Other repos are read-only.** Step C only applies to the repo `cfq` is currently running in.

## Step C — Management (on request, always confirm before writing)

Four actions, exclusively in the current repository (`git rev-parse --show-toplevel`):

1. **Change priority** — rewrite a batch's `.priority`.
2. **Delete a batch** — remove the directory. Name the batch and the number of files that will
   be lost beforehand, and get explicit confirmation.
3. **Archive a batch** — move to `<repo>/.claude/code-for-queue/done/<batch>/` without working it
   off. Open phases then count as done-but-not-implemented; say so in the confirmation text.
4. **Clean the registry** — `cfq-registry.sh prune`, list the removed paths.

No pulling things back out of `done/` and no editing phase files — that's `pfq`'s job.

## Step D — Settings

Show `cfq-settings.sh list`, with an explanation per key and a marker for which values are
currently overridden by an env var (a `set` then only takes effect after removing the variable —
point that out). Change requests go through `cfq-settings.sh set <key> <value>`. **All** keys
are changeable here, including `planBlockedPlugins` / `implBlockedPlugins` (strict prohibition)
and `planPreferredPlugins` / `implPreferredPlugins` (a pure recommendation to the planning or
implementing skill). `stopPct` accepts `0`-`99`; `0` is a valid, deliberate value meaning "hand
off after every phase", not an error — don't flag it as a misconfiguration.
