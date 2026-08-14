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

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | 1 | `Model Gate` | `sonnet · implModels: sonnet` / on abort `❌ … allowed: sonnet · /model sonnet, then /ifq` |
| PRECHECKS | 2 | `Plugin Boundaries` | `blocked: superpowers` / `➖ none` |
| PRECHECKS | 3a | `Batch` | `2026-08-13-cfq-plugin · medium · 1 open phase` |
| PRECHECKS | 3b | `Lock` | `acquired` / `⚠️ takeover after 30 min inactivity` / `❌ held by <session> since <time>` |
| PRECHECKS | 4a | `Failed Attempt` | `➖ none` / `⚠️ P3 second attempt after <reason>` |
| PRECHECKS | 4b | `Size Gate` | `context 5 % · limit 20 %` / `❌ phase L, handoff instead of start` |
| IMPLEMENTATION | 4c | `P<n> <slug>` | `green · 6 deviations`, each deviation as its own `   └ ` line |
| IMPLEMENTATION | 5 | `Commit` | `v0.2 · 1 commit pushed` / `⚠️ branch v0.3 created` |
| POSTCHECKS | 6/7 | `Security Diff` | `no new findings` / `⚠️ no planning snapshot · comparison skipped` / `⚠️ unavailable: <hint>` |
| POSTCHECKS | 6/7 | `Telemetry` | `synced` / `⚠️ sync failed` |
| POSTCHECKS | 6/7 | `Lock` | `released` |
| POSTCHECKS | 7 | `Report` | `rendered` |

## 1. Model Gate

Print the `PRECHECKS` header on entering this step.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implModels
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get allowAnyModel
```

The running model's name is in your system prompt's environment block. If `allowAnyModel` is
`true`, skip this check. Otherwise the running model must match one of the entries in
`implModels` (a substring match is enough: `sonnet` matches `claude-sonnet-5`). No match →
**stop immediately**, touch nothing, and report which models are allowed, that `/model <x>`
followed by `/ifq` is the way forward, and that `CFQ_IMPL_MODELS` or `cfq` changes the list. Print
the `Model Gate` status line either way (see Output Format's section map).

## 2. Plugin Boundaries

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implBlockedPlugins
```

Do not call blocked plugins/skills for the rest of the session — not even indirectly. Skill
recommendations now live **per phase** in the plan itself, are non-binding, and any
recommendation that's on `implBlockedPlugins` is ignored. Print the `Plugin Boundaries` status line.

## 3a. Choose a Batch

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
6. Set the chosen batch (or, for "in order", the first one) as this session's batch and hand it to
   Step 3b — **do not acquire the lock yet.** Nothing is locked and nothing is read in full until
   the user has approved the batch. Print the `Batch` status line once it is chosen.

Steps 5 and 6 above (`AskUserQuestion` and its follow-up) stay prose — only the `Batch` status
line at the end is part of the status-line format.

**Never two batches in the same session** — not even once the first one finishes and context is
still free. Different plans (even from the same repo) belong in separate context windows.

## 3b. Batch Briefing and Go-Ahead

Nothing is touched and no lock is taken until the user has seen what the batch contains. Read the
batch metadata and one line per phase — **never the phase files in full**, that is Step 4's job and
its context budget:

```bash
cat "<batch-dir>/.priority" 2>/dev/null || echo medium
cat "<batch-dir>/.dependsOn" 2>/dev/null
for f in "<batch-dir>"/[0-9]*.md; do
  awk '
    /^# / && !t            { sub(/^# +/, ""); t = $0; next }
    /^## (Größe|Size)/     { g = 1; next }
    g && NF                { size = $1; g = 0; next }
    /^## (Kontext|Context)/ { k = 1; next }
    k && NF                { ctx = ctx $0 " "; if (++n >= 2) k = 0; next }
    END { printf "%s\t%s\t%s\n", t, (size ? size : "M"), substr(ctx, 1, 220) }
  ' "$f"
done
```

Present it compactly: batch name, priority, phase count, and `.dependsOn` if the file exists, then
one line per phase — number and title, size in brackets, the context excerpt. No prose around it, no
repetition of the plan, no commentary on the phases.

Then exactly one `AskUserQuestion`, "Start implementing this batch?", with three options:

- **Start** → acquire the repo lock, then go to Step 4:

  ```bash
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" acquire "<repo-root>" "<batch>"
  ```

  Exit ≠ 0 (output starts with `LOCKED`) → **end immediately**, touch nothing, name the holder,
  batch and time, and note that a dead session is auto-taken-over after 30 minutes of inactivity.
  Output starts with `TAKEOVER` → proceed, printing the `Lock` status line with the takeover
  warning. Otherwise print `Lock` as acquired.
- **A different batch** → back to Step 3a, point 5, with the remaining batches; the declined one is
  not offered again in this session. Nothing left to offer → report and end the session.
- **Cancel** → report "aborted, nothing touched" and end the session. No lock was ever held, so
  there is nothing to release.

A phase file without `## Größe`/`## Size` counts as `M`; one without `## Kontext`/`## Context` shows
its title alone. An incomplete plan is worth showing, not worth aborting over.

## 4. Work Off a Phase

Before reading the phase file, two checks:

**(4a) Earlier failed attempt.** If `report.json` exists, look for an entry for this exact phase:

```bash
jq -c --arg p "<phase-slug>" '[.phases[] | select(.phase == $p and .status == "red")] | last // empty' \
  "<batch-dir>/report.json"
```

A hit → read its `errors` and `summary` as context and don't blindly repeat the phase: check
first whether the original cause still holds. Mention this in the new report entry ("second
attempt after ..."). No hit → skip this check without mentioning it. Either way, print the
`Failed Attempt` status line.

**(4b) Size gate.** If the phase carries a `## Size` (or `## Größe`) heading of `L` and the current
context value is already above **half** the `stopPct` threshold, don't start the phase — hand off
cleanly as in Step 6 instead, so it doesn't tear off mid-limit. `S` and `M` always start; a
missing size counts as `M`.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get stopPct
```

At `stopPct: 0` the gate doesn't apply — a handoff already happens after every phase there. Print
the `Size Gate` status line. This closes `PRECHECKS`; the next line printed is the `IMPLEMENTATION`
header.

**(4c) Implementation.**

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

   Print the `P<n> <slug>` status line now — `✅` and `green` on a green phase, `❌` and `red` on a
   red one, each deviation (or the trimmed error) as its own `   └ ` continuation line.

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

Print the `Commit` status line — the branch and number of commits pushed, with a `⚠️` note if a
new branch was created.

## 6. Context Check After Every Phase

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"
```

- `STOP` → print the `POSTCHECKS` header, then sync telemetry and release the lock, printing the
  `Telemetry` and `Lock` status lines, then end the session here:
  ```bash
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" sync "<repo-root>"
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" release "<repo-root>"
  ```
  The lock is released on handoff — the follow-up session is a new session and acquires it fresh;
  a half-finished batch must not stay locked forever. Print the `HANDOFF` short format from Step 8
  (phases completed, phases still open, the context value, and `/clear` → `/ifq`).
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
jq -c '{planning: .security[0].counts, now: .security[-1].counts}' "<batch-dir>/report.json"
```

Report only the **difference** from the planning-time snapshot — newly appeared findings per
severity. No repeat of the overall count, no new planning, no automatic fix. Missing planning
snapshot (a batch from an older version) → skip the comparison without comment. Print the
`POSTCHECKS` header on entering this step, then the `Security Diff` status line.

Sync telemetry and release the lock, printing the `Telemetry` and `Lock` status lines:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" sync "<repo-root>"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lock.sh" release "<repo-root>"
```

Render the HTML report, printing the `Report` status line:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<repo-root>/.claude/code-for-queue/done/<batch>"
```

Hand the batch to Step 8 for the closing report.

## 8. Closing Reports

One format, two lengths. Both end the session. Both are a label/value list under the `Output
Format` padding rule, not a table — this is the `RESULT` (full) or `HANDOFF` (short) section.

**Full format (batch done)** — `RESULT` header, then:

1. `Batch` — batch and repo, phases total, green/red split:
   `2026-08-13-cfq-plugin (codeforqueue) · 6/6 phases · 5 green, 1 red`
2. `Cost` — one line: turns, output tokens, models and effort levels used, from the telemetry
   blocks; plus the planning cost from `.planning`, if present:
   `40 turns · 35,229 tok · claude-sonnet-5 · high · planning 12k`
3. `Skills` — from `.phases[].telemetry.by_skill`, and, where the plan recommended any, whether
   they were actually used:
   ```bash
   jq -c '{recommended: [.phases[].telemetry.skills_recommended // []] | flatten | unique,
           used:        [.phases[].telemetry.by_skill // {} | keys[]] | unique | map(select(. != "-"))}' \
     "<batch-dir>/report.json"
   ```
   `recommended: – · used: cfq:implement-for-queue`
4. `Security` — the difference in one line: `no new findings` / severities that newly appeared.
5. `Merge` — current branch, number of commits against `main`, and the ready-to-run command as an
   indented `   └ ` line — print it, **don't** run it:
   ```bash
   git branch --show-current
   git rev-list --count main..HEAD
   ```
   `v0.2, 13 commits ahead of main` then `   └ gh pr create --base main --head v0.2` (or
   `git checkout main && git merge --no-ff v0.2` if no `gh` remote).
6. `Report` — `file://` path to the HTML report. The details live there, not in the terminal.

Example:

```
RESULT
Batch      2026-08-13-cfq-plugin (codeforqueue) · 6/6 phases · 5 green, 1 red
Cost       40 turns · 35,229 tok · claude-sonnet-5 · high · planning 12k
Skills     recommended: – · used: cfq:implement-for-queue
Security   no new findings
Merge      v0.2, 13 commits ahead of main
           └ gh pr create --base main --head v0.2
Report     file:///…/done/2026-08-13-cfq-plugin/report.html
```

**Short format (context handoff)** — `HANDOFF` header, three to four lines: phases done, phases
open, the `PCT` value, and `/clear` → `/ifq`. No cost breakdown, no merge hint.

```
HANDOFF
Phases     3 done · 3 open
Context    52 % · limit 40 %
Next       /clear → /ifq
```

**Red case:** the report still gets printed, in full format, naming the red phase and noting that
the next run will pick it up again with the failed-attempt context. The red phase's line already
appeared with `❌` in `IMPLEMENTATION` (Step 4); Step 8 does not repeat the error text, only the
`5 green, 1 red` split in `Batch`.

No manual bookkeeping is needed anymore — the dashboard (P4) counts live from disk.
