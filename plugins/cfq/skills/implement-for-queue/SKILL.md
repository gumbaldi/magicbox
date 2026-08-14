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
```

Do not call blocked plugins/skills for the rest of the session — not even indirectly. Skill
recommendations now live **per phase** in the plan itself, are non-binding, and any
recommendation that's on `implBlockedPlugins` is ignored.

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

   The scan output (`cfq-scan.sh`) carries `blocked` and `unknownDeps` per batch. **Blocked
   batches are never offered.** If every open batch is blocked, print the wait list (one line per
   batch: batch → waiting on batch) and end the session — do not fall back to a blocked batch.
   `unknownDeps` are shown at selection time with `⚠️` and the unresolvable name, but don't block
   (Decision 9); one sentence that `/cfq` fixes it.
5. `AskUserQuestion`: "There are N open plans for this repo. How do you want to proceed?" with
   the options:
   - **Work through them in order** (show the computed order in the description)
   - **Choose a specific plan** → leads to a second `AskUserQuestion` with the batches as options
     (label = topic slug, description = priority + number of open phases + date).
6. Set the chosen batch (or, for "in order", the first one) as this session's batch, then acquire
   the repo lock **before** the first phase:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" acquire "<repo-root>" "<batch>"
   ```

   Exit ≠ 0 (output starts with `LOCKED`) → **end immediately**, touch nothing, name the holder,
   batch and time, and note that a dead session is auto-taken-over after 30 minutes of inactivity.
   Output starts with `TAKEOVER` → proceed, mentioning the takeover in one line.

**Never two batches in the same session** — not even once the first one finishes and context is
still free. Different plans (even from the same repo) belong in separate context windows.

## 4. Work Off a Phase

Before reading the phase file, two checks:

**a) Earlier failed attempt.** If `report.json` exists, look for an entry for this exact phase:

```bash
jq -c --arg p "<phase-slug>" '[.phases[] | select(.phase == $p and .status == "red")] | last // empty' \
  "<batch-dir>/report.json"
```

A hit → read its `errors` and `summary` as context and don't blindly repeat the phase: check
first whether the original cause still holds. Mention this in the new report entry ("second
attempt after ..."). No hit → skip this check without mentioning it.

**b) Size gate.** If the phase carries a `## Size` (or `## Größe`) heading of `L` and the current
context value is already above **half** the `stopPct` threshold, don't start the phase — hand off
cleanly as in Step 6 instead, so it doesn't tear off mid-limit. `S` and `M` always start; a
missing size counts as `M`.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get stopPct
```

At `stopPct: 0` the gate doesn't apply — a handoff already happens after every phase there.

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

   `append` captures the phase's telemetry automatically — no extra call and no token estimate of
   your own is needed. `deviations` is not optional padding: whenever the implementation departed
   from the plan, name what the plan said, what was built instead, and why. An honest empty array
   is fine; a glossed-over deviation is not. On red, `errors` carries the actual failure output,
   trimmed to what identifies it.

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

- `STOP` → sync telemetry and release the lock, then end the session here:
  ```bash
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" sync "<repo-root>"
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" release "<repo-root>"
  ```
  The lock is released on handoff — the follow-up session is a new session and acquires it fresh;
  a half-finished batch must not stay locked forever. Report: phases completed, phases still open,
  the context value, and the instruction to run `/clear`, then `/implement-for-queue` (or `/ifq`)
  again.
- `OK` → next phase of the same batch.
- `UNKNOWN` → treat like `STOP` (hand off cleanly when in doubt).

`stopPct: 0` is a deliberate setting, not a misconfiguration: the script then reports `STOP` after
every single phase, so each phase gets its own context window. Hand off without commenting on it.

## 7. Batch Done

No open `*.md` left at the top level → move the whole batch directory to
`<repo-root>/.claude/code-for-queue/done/`. Register the repo once more:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"
```

Fresh security snapshot, compared against the one taken at planning time:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-security.sh" "<repo-root>" > /tmp/cfq-sec-end.json
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" security "<batch-dir>" "$(cat /tmp/cfq-sec-end.json)"
jq -c '{planung: .security[0].counts, jetzt: .security[-1].counts}' "<batch-dir>/report.json"
```

Report only the **difference** from the planning-time snapshot — newly appeared findings per
severity. No repeat of the overall count, no new planning, no automatic fix. Missing planning
snapshot (a batch from an older version) → skip the comparison without comment.

Sync telemetry and release the lock:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" sync "<repo-root>"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" release "<repo-root>"
```

Render the HTML report:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<repo-root>/.claude/code-for-queue/done/<batch>"
```

Hand the batch to Step 8 for the closing report.

## 8. Closing Reports

One format, two lengths. Both end the session.

**Full format (batch done):**

1. Batch and repo, phases total, green/red, number of deviations.
2. One cost line: turns, output tokens, models and effort levels used, from the telemetry blocks;
   plus the planning cost from `.planning`, if present.
3. **Skills used**, from `.phases[].telemetry.by_skill` — and, where the plan recommended any,
   whether they were actually used:
   ```bash
   jq -c '{empfohlen: [.phases[].telemetry.skills_recommended // []] | flatten | unique,
           benutzt:   [.phases[].telemetry.by_skill // {} | keys[]] | unique | map(select(. != "-"))}' \
     "<batch-dir>/report.json"
   ```
4. Security difference in one line.
5. **Merge hint**: current branch, number of commits against `main`, and the ready-to-run command
   — print it, **don't** run it:
   ```bash
   git branch --show-current
   git rev-list --count main..HEAD
   ```
   From that: `gh pr create --base main --head <branch>` or
   `git checkout main && git merge --no-ff <branch>`.
6. `file://` path to the HTML report. The details live there, not in the terminal.

**Short format (context handoff):** three to four lines — phases done, phases open, the `PCT`
value, and `/clear` → `/ifq`. No cost breakdown, no merge hint.

**Red case:** the report still gets printed, in full format, naming the red phase and noting that
the next run will pick it up again with the failed-attempt context.

No manual bookkeeping is needed anymore — the dashboard (P4) counts live from disk.
