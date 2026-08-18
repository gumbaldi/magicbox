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
queue.", end. Read `.priority` per batch (missing → not flagged); default order: flagged batches
first, then folder name ascending (date-prefixed; oldest first, ties broken by name).

`cfq-scan.sh`'s output carries `blocked`, `unknownDeps`, `planning` and `inProgress` per batch. The
filters exist — blocked and still-being-planned batches are never offered, more than one
in-progress batch is a stop condition — but the exact wording of each case (wait lists, the
stop-immediately rule, the blocked-and-in-progress corner case) is cold-path detail: read
`references/queues.md`'s **Batch Selection Rules** section on first use each session and apply it
here.

Among the batches that pass the planning/blocked filters, check `inProgress`: **exactly one** →
skip the `AskUserQuestion` below entirely, select it, print the `Batch` status line as `resumed
<name> · <done>/<done+open> phases done` (prefix with `high · ` when the batch is flagged), hand it
straight to Step 3b. **Zero** → the picker below runs unchanged. **More than one** → stop per the
reference above.

Among the batches that pass the planning/blocked filters (with `inProgress` at zero, so the picker
is in play at all): **exactly one** selectable batch → no question either — a list of one cannot
change the outcome. Select it, print the `Batch` status line noting it was the only selectable
batch (e.g. `2026-08-18-example · only open batch · 3 phases`), hand it straight to Step 3b.
**Zero** → the existing "No open plans for this repo in the queue." path, unchanged. **More than
one** → the `AskUserQuestion` below, unchanged.

One `AskUserQuestion`, "There are N open plans for this repo. How do you want to proceed?": **Work
through them in order** (show the computed order) or **Choose a specific plan** (a second
`AskUserQuestion`, batches as options, label = topic slug, description = open phase count + date,
prefixed with `high · ` only when the batch is flagged). Set the chosen batch (or the first, for
"in order") and hand it to Step 3b — **do
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
  `TAKEOVER` → proceed, `Lock` carries that warning; else `Lock` is just acquired. Then
  `cfq-branch.sh plan` decides `off` / `continue` / `new` and, on `new`, `cfq-changelog.sh init`
  runs too (all per `references/queues.md`); `Branch` renders whichever of the three happened.
  Then Step 4.
- **A different batch** → back to Step 3a's question, with the remaining batches; the declined one
  isn't offered again this session. Nothing left → report and end. Not offered at all when Step 3a
  didn't run a picker — auto-resumed in-progress batch, or only one selectable batch — since
  offering one here would restart a different batch while this one sits half-done; the go-ahead
  question then has only **Start** / **Cancel**.
- **Cancel** → report "aborted, nothing touched" and end. No lock was ever held.

## 4. Work Off a Phase

Before reading the phase file, two checks. **(4a) Earlier failed attempt:** if `report.json`
exists, look for an entry for this exact phase with `jq -c --arg p "<phase-slug>" '[.phases[] |
select(.phase == $p and .status == "red")] | last // empty' "<batch-dir>/report.json"`. A hit →
read its `errors`/`summary`, check whether the cause still holds before repeating, and mention it
in the new entry ("second attempt after …"); no hit → skip silently. Print the `Failed Attempt`
status line either way.
**(4b) Size gate.** A `## Size` of `L`, with context already above **half** the
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

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"`. `STOP` → print `POSTCHECKS`, sync telemetry and
release the lock (`cfq-telemetry.sh sync "<repo-root>"`, `cfq-lock.sh release "<repo-root>"`),
printing `Telemetry`/`Lock`, then end — the follow-up session acquires the lock fresh, a
half-finished batch must not stay locked. Print the `HANDOFF · implement-for-queue` short format
from Step 8. `OK` → next phase, same batch. `UNKNOWN` → treat like `STOP`. `stopPct: 0` is
deliberate, not a misconfiguration — `STOP` fires after every phase, one context window each; hand
off without commenting on it.

## 7. Batch Done

No open `*.md` left → print the `POSTCHECKS` header, then run
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-finish.sh" "<repo-root>" "<batch-dir>" "<branch>"`, which moves
the batch into `impl/done/`, registers the repo, runs the language/maintenance/security/changelog/
telemetry sequence and releases the lock unconditionally (a `trap`, so a mid-sequence failure can
never leave the repo locked), and prints one JSON object. Render its fields:
- `Language`: `.lang.issues` from the JSON is the structural count (`missing`/`stray`/`unfiled`);
  judge `.lang.prose.sample` for prose, comments, identifiers and commit messages not in
  `codeLanguage` — any language, never hardcode one to look for. `.lang.prose.truncated: true`
  means the sample is exactly that, a sample, so the status line says so (`⚠️ 2 issues ·
  sampled`); an empty sample (no git repo, unknown ref) is `➖`, not a finding. Either source
  finding → `⚠️` with the combined count, details as `   └ ` lines; nothing found → `✅ no
  issues`. No repair here — every finding becomes a `todo/` entry per `references/queues.md`.
- `Maintenance` from `.maintenance`: `➖ off` · `➖ not due (<n> commits)` · `⚠️ due (<n> commits) ·
  run /pfq`.
- `Security Diff` from `.security.new` — the difference only, no repeat of the overall count, no
  new planning, no automatic fix; an empty `.security` block (older batch, no planning snapshot)
  → skip without comment.
- `Changelog` from `.changelog` as-is.
- `Telemetry` from `.telemetry`, `Lock` from `.lock`.
- Any `.errors` entries → `⚠️` lines naming the failed step; the sequence still completed.

Render the HTML report only when `htmlReport` is `true` (`cfq-report.sh html
"<repo-root>/.claude/code-for-queue/impl/done/<batch>"`), printing `Report` as `rendered`; else `➖ off ·
/rfq renders on demand` and no `file://` line in Step 8. Hand the batch to Step 8 for the closing report.

## 8. Closing Reports

One format, two lengths, both end the session, both a label/value list under the `Output Format`
padding rule — `RESULT · implement-for-queue` (full) or `HANDOFF · implement-for-queue` (short).
**Full format** — `RESULT · implement-for-queue` header: `Batch`
(batch and repo, phases total, green/red split) · `Cost` — run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh"
summary "<batch-dir>"` (same call `report-for-queue` already uses for its table) and render fields
9/7/8/10/11 as turns, output tokens total (planning's share named separately), models, efforts ·
`Skills` (recommended vs. used, query in `references/queues.md`) · `Security` (the difference, one
line) · `Merge` (current branch,
commits ahead of `main`, ready-to-run command as an indented `   └ ` line, printed not run; also a
`todo/` entry per `references/queues.md` without asking, so a forgotten merge is never lost) ·
`Report` (`file://` path, only when Step 7 rendered one — else the line is omitted).

**Short format** — `HANDOFF · implement-for-queue` header, three to four lines: phases done, phases open, the `PCT`
value, `/clear` → `/ifq`. No cost breakdown, no merge hint. **Red case:** still the full format,
naming the red phase; its `❌` line already appeared in `IMPLEMENTATION` (Step 4), so Step 8 only
repeats the `5 green, 1 red` split in `Batch`, not the error text.
