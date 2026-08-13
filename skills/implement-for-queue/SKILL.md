---
name: implement-for-queue
description: >
  Work off parked phase plans from the repo-local queue (<repo>/.claude/code-for-queue/) one
  batch per session, phase by phase, stopping when the context window gets too full. Use for
  "/ifq", "/implement-for-queue", "implement the queue", "work off the plans", "continue with
  the plans", "next phase".
---

# Implement-for-Queue: Work Off a Batch Phase by Phase

Always answer in the user's language.

## 1. Model Gate

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implModels
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get allowAnyModel
```

The running model's name is in your system prompt's environment block. If `allowAnyModel` is
`true`, skip this check. Otherwise the running model must match one of the entries in
`implModels` (a substring match is enough: `sonnet` matches `claude-sonnet-5`). No match →
**stop immediately**, touch nothing, and report which models are allowed, that `/model <x>`
followed by `/ifq` is the way forward, and that `CFQ_IMPL_MODELS` or `cfq` changes the list.

## 2. Plugin Boundaries

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implBlockedPlugins
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implPreferredPlugins
```

Do not call blocked plugins/skills for the rest of the session — not even indirectly. Check
whether preferred plugins help with the phase at hand; if they don't fit, skip them without
comment. Both lists may be empty.

## 3. Choose a Batch

1. Determine the repo root: `git rev-parse --show-toplevel`. No git repo in the current working
   directory → abort, report that `implement-for-queue` needs a repo. End.
2. Check `<repo-root>/.claude/code-for-queue/` for open batches: directories directly beneath it
   (excluding `done/`) with at least one `*.md` at the top level.
3. No open batches → report: "No open plans for this repo in the queue." End.
4. Open batches exist → read `.priority` for each (file missing → `medium`). Compute the default
   order: priority first (`high` > `medium` > `low`), then folder name ascending (the name
   starts with the date, so it doubles as creation date and — as a tie-break on the same date —
   plan ID; oldest first).
5. `AskUserQuestion`: "There are N open plans for this repo. How do you want to proceed?" with
   the options:
   - **Work through them in order** (show the computed order in the description)
   - **Choose a specific plan** → leads to a second `AskUserQuestion` with the batches as options
     (label = topic slug, description = priority + number of open phases + date).
6. Set the chosen batch (or, for "in order", the first one) as this session's batch.

**Never two batches in the same session** — not even once the first one finishes and context is
still free. Different plans (even from the same repo) belong in separate context windows.

## 4. Work Off a Phase

1. Read the lowest-numbered open `NN-*.md` in full.
2. Implement it — completely, not just the easy parts.
3. Run the verification named in the plan, output filtered.
4. Green → move the file to `<batch>/done/` (`mkdir -p` first), then register the repo:
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"
   ```
   Red → **stop**, report, the file stays open. Do not move on to the next phase.
5. Record the phase in the batch report — after green **and** after red, before anything else happens:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" append "<batch-dir>" '<phase-json>'
   ```

   `deviations` is not optional padding: whenever the implementation departed from the plan, name what
   the plan said, what was built instead, and why. An honest empty array is fine; a glossed-over
   deviation is not. On red, `errors` carries the actual failure output, trimmed to what identifies it.

## 5. Commit & Push (on green, every phase)

Immediately after moving the file to `done/` — automatically, without asking, even if more
phases in the same batch follow. Don't collect these until the end of the batch or before a
`/clear`.

**Never commit/push to `main` automatically.** Check the current branch before committing:

```bash
git branch --show-current
```

- Branch is `main` → create a new branch **first**, then commit:
  1. Determine the highest existing `vX.Y` branch (local + remote):
     `git branch -a | grep -oE 'v[0-9]+\.[0-9]+' | sort -t. -k1,1V -k2,2n | tail -1`
  2. Increment the digit after the dot by 1 (e.g. `v0.48` → `v0.49`). No matching branch found →
     start with `v0.1`.
  3. `git checkout -b v0.<N+1>`, then commit and push with `git push -u origin v0.<N+1>`.
- Branch is already a feature/version branch (e.g. `v0.48`) → commit and push directly on it (the
  remote branch usually already exists, no `-u` needed).

## 6. Context Check After Every Phase

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"
```

- `STOP` → end the session here. Report: phases completed, phases still open, the context value,
  and the instruction to run `/clear`, then `/implement-for-queue` (or `/ifq`) again.
- `OK` → next phase of the same batch.
- `UNKNOWN` → treat like `STOP` (hand off cleanly when in doubt).

`stopPct: 0` is a deliberate setting, not a misconfiguration: the script then reports `STOP` after
every single phase, so each phase gets its own context window. Hand off without commenting on it.

## 7. Batch Done

No open `*.md` left at the top level → move the whole batch directory to
`<repo-root>/.claude/code-for-queue/done/` and report what was implemented overall. Register the
repo once more:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"
```

Then render the report and hand the path over with the closing summary:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<repo-root>/.claude/code-for-queue/done/<batch>"
```

Report the terminal summary yourself (phases, green/red, deviations) and print the `file://` path to
the HTML underneath — the detail lives there, not in the terminal.

No manual bookkeeping is needed anymore — the dashboard (P4) counts live from disk.
