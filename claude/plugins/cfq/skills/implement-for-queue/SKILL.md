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

Progress is reported as status lines, not prose, one line per step, printed as soon as that step
is done. Section headers print once, on entering the section.

```
SECTION HEADER IN CAPS
<icon> <label padded to 16 chars><detail, one short clause>
```

Icons: `✅` done · `⚠️` warning/unavailable/degraded · `❌` failed · `➖` skipped/not applicable.
Rules: detail = what happened, not what happens next · a step that didn't run still gets its line
with `➖`/`⚠️` and the reason · sub-information → indented `   └ ` line, never the detail column ·
headers/labels/status lines are always English, interactive parts stay in the user's language ·
no commentary around the block.

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | 1 | `Model Gate` | `sonnet · implModels: sonnet` / on abort `❌ … allowed: sonnet · /model sonnet, then /ifq` |
| PRECHECKS | 2 | `Plugin Boundaries` | `blocked: superpowers` / `➖ none` |
| PRECHECKS | 3a | `Batch` | `2026-08-13-cfq-plugin · medium · 1 open phase` |
| PRECHECKS | 3b | `Lock` | `acquired` / `⚠️ takeover after 30 min inactivity` / `❌ held by <session> since <time>` |
| PRECHECKS | 3b | `Branch` | `v0.11-example-topic on v0.10-previous` / `➖ branchPerBatch off` / `⚠️ existing branch checked out` |
| PRECHECKS | 4a | `Failed Attempt` | `➖ none` / `⚠️ P3 second attempt after <reason>` |
| PRECHECKS | 4b | `Size Gate` | `context 5 % · limit 20 %` / `❌ phase L, handoff instead of start` |
| IMPLEMENTATION | 4c | `P<n> <slug>` | `green · 6 deviations`, each deviation as its own `   └ ` line |
| IMPLEMENTATION | 5 | `Commit` | `v0.11-example-topic · 1 commit pushed` |
| POSTCHECKS | 7 | `Language` | `✅ no issues` / `⚠️ 3 issues` |
| POSTCHECKS | 7 | `Maintenance` | `➖ off` / `➖ not due (12 commits)` / `⚠️ due (63 commits) · run /pfq` |
| POSTCHECKS | 6/7 | `Security Diff` | `no new findings` / `⚠️ no planning snapshot · comparison skipped` / `⚠️ unavailable: <hint>` |
| POSTCHECKS | 7 | `Changelog` | `v0.11 done · 4 phases` / `➖ changelogFile empty` |
| POSTCHECKS | 6/7 | `Telemetry` | `synced` / `⚠️ sync failed` |
| POSTCHECKS | 6/7 | `Lock` | `released` |
| POSTCHECKS | 7 | `Report` | `rendered` / `➖ off · /rfq renders on demand` |

## 1. Model Gate

Print the `PRECHECKS` header on entering, then:
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implModels
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get allowAnyModel
```

The running model's name is in your system prompt's environment block; `allowAnyModel: true` →
skip this check, otherwise it must match one of `implModels` (substring match: `sonnet` matches
`claude-sonnet-5`). No match → **stop immediately**, touch nothing, report the allowed models,
that `/model <x>` then `/ifq` is the way forward, and that `CFQ_IMPL_MODELS`/`cfq` changes the
list. Print the `Model Gate` status line either way.

## 2. Plugin Boundaries

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implBlockedPlugins`. Blocked
plugins/skills aren't called for the rest of the session, not even indirectly — per-phase skill
recommendations on this list are ignored. Print the `Plugin Boundaries` status line.

## 3a. Choose a Batch

Repo root via `git rev-parse --show-toplevel`; no git repo → abort, report, end. Check
`<repo-root>/.claude/code-for-queue/impl/` for open batches (directories beneath it, excluding
`done/`, with at least one top-level `*.md`); none → report "No open plans for this repo in the
queue.", end. Read `.priority` per batch (missing → `medium`); default order: priority first
(`high` > `medium` > `low`), then folder name ascending (date-prefixed; oldest first, ties broken
by name). `cfq-scan.sh`'s output carries `blocked`/`unknownDeps` per batch — **blocked batches are
never offered**; if every open batch is blocked, print the wait list (batch → waiting on batch)
and end, never falling back to a blocked one. `unknownDeps` are shown at selection time with `⚠️`
and the unresolvable name but don't block (`/cfq` fixes it) — one sentence, no more.

One `AskUserQuestion`, "There are N open plans for this repo. How do you want to proceed?": **Work
through them in order** (show the computed order) or **Choose a specific plan** (a second
`AskUserQuestion`, batches as options, label = topic slug, description = priority + open phase
count + date). Set the chosen batch (or the first, for "in order") and hand it to Step 3b — **do
not acquire the lock yet**. Print the `Batch` status line once chosen; both questions stay prose.
**Never two batches in the same session**, not even once the first finishes and context is still
free — different plans, even from the same repo, belong in separate context windows.

## 3b. Batch Briefing and Go-Ahead

Nothing is touched, no lock taken, until the user has seen what the batch contains — never read
phase files in full here, that's Step 4's job. Extract the briefing data per
`references/queues.md` and present it compactly, then ask exactly one `AskUserQuestion`, "Start
implementing this batch?":
- **Start** → acquire the repo lock (`cfq-lock.sh acquire "<repo-root>" "<batch>"`). Exit ≠ 0 (`LOCKED`) →
  **end immediately**, touch nothing, name holder/batch/time, note the 30-minute stale takeover;
  `TAKEOVER` → proceed, `Lock` carries that warning; else `Lock` is just acquired. Unless `branchPerBatch`
  is `false` (`Branch: ➖ branchPerBatch off`, skip to Step 4): an existing branch for this batch → check
  it out, `Branch` notes the existing checkout, no version bump, no changelog entry; else determine
  version/base, `git checkout -b <version>-<slug>`, `cfq-changelog.sh init` (all per
  `references/queues.md`), `Branch` shows branch and base. Then Step 4.
- **A different batch** → back to Step 3a's question, with the remaining batches; the declined one isn't
  offered again this session. Nothing left → report and end.
- **Cancel** → report "aborted, nothing touched" and end. No lock was ever held.

## 4. Work Off a Phase

Before reading the phase file, two checks. **(4a) Earlier failed attempt:** if `report.json`
exists, look for an entry for this exact phase with `jq -c --arg p "<phase-slug>" '[.phases[] |
select(.phase == $p and .status == "red")] | last // empty' "<batch-dir>/report.json"`. A hit →
read its `errors`/`summary`, check whether the cause still holds before repeating, and mention it
in the new entry ("second attempt after …"); no hit → skip silently. Print the `Failed Attempt`
status line either way.
**(4b) Size gate.** A `## Size`/`## Größe` of `L`, with context already above **half** the
`stopPct` threshold → don't start, hand off cleanly (Step 6) instead. `S`/`M` always start, a
missing size counts as `M`; at `stopPct: 0` the gate doesn't apply since a handoff already happens
after every phase.
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get stopPct
```
Print the `Size Gate` status line; this closes `PRECHECKS`, next comes `IMPLEMENTATION`.
**(4c) Implementation.** Read the lowest-numbered open `NN-*.md` in full, implement it completely,
run the plan's verification with output filtered. A phase touching `docs/<codeLanguage>/…` →
write the counterparts in every `docLanguages` entry before it goes green, per
`${CLAUDE_PLUGIN_ROOT}/references/doc-style.md` or `<repo>/docs/STYLE.md` if present. Work found
beyond this phase's scope → one `AskUserQuestion` on parking it: yes writes
`plan/<YYYY-MM-DD>-<slug>.md` per `references/queues.md`, no stays a sentence in the report, no
second attempt. Green → move the file to `<batch>/done/` (`mkdir -p` first), register the repo
(`cfq-registry.sh add "<repo-root>"`); red → **stop**, report, the file stays open, don't move on.
Record the phase either way, before anything else, with
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" append "<batch-dir>" '<phase-json>'` — this captures
telemetry automatically. `deviations` is not optional padding — name what the plan said, what was
built, and why; an honest empty array is fine, a glossed-over deviation is not. On red, `errors`
carries the actual failure output, trimmed to what identifies it. Print the `P<n> <slug>` status
line now — `✅ green` or `❌ red`, each deviation (or the trimmed error) as its own `   └ ` line.

## 5. Commit & Push (on green, every phase)

Automatically, right after moving the file to `done/`, even if more phases follow — never
collected until batch end or a `/clear`. The branch already exists (Step 3b created it or checked
an existing one out) — commit, message in `codeLanguage`, and push: `-u origin <branch>` on this
session's first push, a plain `git push` after that. Print the `Commit` status line — branch and
commits pushed.

## 6. Context Check After Every Phase

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"`. `STOP` → print `POSTCHECKS`, sync telemetry
and release the lock (`cfq-telemetry.sh sync "<repo-root>"`, `cfq-lock.sh release "<repo-root>"`),
printing `Telemetry`/`Lock`, then end — the follow-up session acquires the lock fresh, a
half-finished batch must not stay locked. Print the `HANDOFF` short format from Step 8. `OK` →
next phase, same batch. `UNKNOWN` → treat like `STOP`. `stopPct: 0` is deliberate, not a
misconfiguration — `STOP` fires after every phase, one context window each; hand off without
commenting on it.

## 7. Batch Done

No open `*.md` left → move the batch directory to `<repo-root>/.claude/code-for-queue/impl/done/`,
register the repo again (`cfq-registry.sh add "<repo-root>"`). Run
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lang.sh" "<repo-root>" --changed main`: structural findings
(`missing`/`stray`/`unfiled`) plus a content read of the same changed files — prose in the
required language, comments/identifiers/commit messages in `codeLanguage`. A finding → `⚠️` with
the count, details as `   └ ` lines; nothing found → `✅ no issues`. No repair here — findings
become `todo/` entries per `references/queues.md`. Print the `Language` status line.
Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-maintenance.sh" due "<repo-root>"` — report only, never
run, never stamp: `➖ off` · `➖ not due (12 commits)` · `⚠️ due (63 commits) · run /pfq`. Print the
`Maintenance` status line. Fresh security snapshot, diffed against the planning-time one:
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-security.sh" "<repo-root>" > /tmp/cfq-sec-end.json
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" security "<batch-dir>" "$(cat /tmp/cfq-sec-end.json)"
jq -c '{planning: .security[0].counts, now: .security[-1].counts}' "<batch-dir>/report.json"
```
Report only the **difference** — newly appeared findings per severity, no repeat of the overall
count, no new planning, no automatic fix. Missing planning snapshot (older batch) → skip without
comment. Print the `POSTCHECKS` header on entering this step, then the `Security Diff` line.
Complete the changelog with `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-changelog.sh" finish "<repo-root>" "<branch>"
"<batch-dir>"` — a no-op when `changelogFile` is empty, the script handles that itself; print `Changelog` —
version and phase count done, or `➖ changelogFile empty`. Sync telemetry and release the lock
(`cfq-telemetry.sh sync "<repo-root>"`, `cfq-lock.sh release "<repo-root>"`), printing `Telemetry`/`Lock`.
Render the HTML report only when `htmlReport` is `true` (`cfq-report.sh html
"<repo-root>/.claude/code-for-queue/impl/done/<batch>"`), printing `Report` as `rendered`; else `➖ off ·
/rfq renders on demand` and no `file://` line in Step 8. Hand the batch to Step 8 for the closing report.

## 8. Closing Reports

One format, two lengths, both end the session, both a label/value list under the `Output Format`
padding rule — `RESULT` (full) or `HANDOFF` (short). **Full format** — `RESULT` header: `Batch`
(batch and repo, phases total, green/red split) · `Cost` (turns, tokens, model/effort from
telemetry, plus planning cost from `.planning` if present) · `Skills` (recommended vs. used, query
in `references/queues.md`) · `Security` (the difference, one line) · `Merge` (current branch,
commits ahead of `main`, ready-to-run command as an indented `   └ ` line, printed not run; also a
`todo/` entry per `references/queues.md` without asking, so a forgotten merge is never lost) ·
`Report` (`file://` path, only when Step 7 rendered one — else the line is omitted).

**Short format** — `HANDOFF` header, three to four lines: phases done, phases open, the `PCT`
value, `/clear` → `/ifq`. No cost breakdown, no merge hint. **Red case:** still the full format,
naming the red phase; its `❌` line already appeared in `IMPLEMENTATION` (Step 4), so Step 8 only
repeats the `5 green, 1 red` split in `Batch`, not the error text.
