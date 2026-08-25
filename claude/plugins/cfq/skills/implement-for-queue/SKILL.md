---
name: implement-for-queue
description: >
  Work off parked phase plans from the repo-local queue (<repo>/.claude/cfq/) one
  batch per session, phase by phase, stopping when the context window gets too full. Use for
  "/ifq", "/implement-for-queue", "implement the queue", "work off the plans", "continue with
  the plans", "next phase".
---

# Implement-for-Queue: Work Off a Batch Phase by Phase

Always answer in the user's language.

## Output Format

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Step 0 — Plan-Mode Gate

Before Step 1-3a, check for Plan Mode — read
`${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s **Plan-Mode Gate** section and follow it.

## 1-3a. Preflight: Policy, Batch Selection

Print the `PRECHECKS` header, then one call:
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-ifq-preflight.sh" "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```
`status: "NO_REPO"` → abort, report, end. Otherwise this one call already resolved Steps 1
(model gate), 2 (plugin gate) and 3a (batch selection) together — read its fields below, no
further calls needed for those three steps.

**Model Gate.** The running model's name is in your system prompt's environment block;
`policy.allowAnyModel: true` → skip this check, otherwise it must match one of
`policy.implModels` (substring match: `sonnet` matches `claude-sonnet-5`). No match → **stop
immediately**, touch nothing, report the allowed models, that `/model <x>` then `/ifq` is the way
forward, and that `CFQ_IMPL_MODELS`/`cfq` changes the list. Print the `Model Gate` status line
either way.

**Plugin Boundaries.** `policy.implBlockedPlugins` — those plugins/skills aren't called for the
rest of the session, not even indirectly — per-phase skill recommendations on this list are
ignored. Print the `Plugin Boundaries` status line.

**Batch Selection.** `status` already reflects the filtered outcome — `NO_BATCH` → report "No open
plans for this repo in the queue.", end. `BLOCKED`/`MULTIPLE_IN_PROGRESS`/`selection.planning`
entries each need specific wording (wait list, stop-immediately rule, the still-planning notice) —
cold-path detail: read `references/queues.md`'s **Batch Selection Rules** section on first use each
session and apply it here.

`selection.inProgress` non-null → that batch was auto-selected already (`batch`/`nextPhase`/
`branch`/`resume`/`contextGate` are already resolved for it) — skip the `AskUserQuestion`, print
`Batch` as `resumed <name> · <done>/<done+open> phases done` (prefix `high · ` if flagged),
straight to Step 3b. `selection.inProgress` null and `selection.selectable` has **exactly one**
entry → same pre-resolved fields, no question either — print `Batch` noting it was the only
selectable batch (e.g. `2026-08-18-example · only open batch · 3 phases`), straight to Step 3b.
`selection.selectable` has **zero** entries and `status` isn't `NO_BATCH`/`BLOCKED` → treat as
`NO_BATCH`. **More than one** → `batch`/`nextPhase`/`branch`/`resume`/`contextGate` are `null`; ask
one `AskUserQuestion`, "There are N open plans for this repo. How do you want to proceed?": **Work
through them in order** (show `selection.selectable`, already sorted flagged-first-then-name) or
**Choose a specific plan** (a second `AskUserQuestion`, batches as options, label = topic slug,
description = open phase count + date, prefixed with `high · ` only when flagged). Set the chosen
batch (or the first, for "in order"), re-run the preflight call with `--select <chosen>` to resolve
its fields — **do not acquire the lock yet**. Print the `Batch` status line once chosen; both
questions stay prose. **Never two batches in the same session**, not even once the first finishes
and context is still free — different plans belong in separate context windows.

## 3b. Batch Briefing and Go-Ahead

Nothing is touched, no lock taken, until the user has seen what the batch contains — never read
phase files in full here, that's Step 4's job. Present `batch.briefText` compactly (already the
full per-phase listing — name/priority/phase count/`dependsOn`/one line per phase with size and
context excerpt), then ask exactly one `AskUserQuestion`, "Start implementing this batch?":
- **Start** → acquire the repo lock (`cfq-lock.sh acquire "<repo-root>" "<batch>"`). Exit ≠ 0 (`LOCKED`) →
  **end immediately**, touch nothing, name holder/batch/time, note the 30-minute stale takeover;
  `TAKEOVER` → proceed, `Lock` carries that warning; else `Lock` is just acquired. `branch.mode`
  (from the preflight — already computed, no new call) decides the checkout — full behavior
  (`off`/`continue`/`new`, base-branch question, checkout, changelog init, post-checkout reconfirm)
  in `references/queues.md`'s **Branch and Changelog on Go-Ahead**. `Branch` renders whichever
  happened. `resume` (same preflight
  result) already carries done/open phases, last commit, deviations, red-phase history,
  `.batch-context.md`'s path — no new `cfq-resume.sh` call; if `resume.batchContext.exists`, `Read`
  it now. Print `Resume` — phases done/open, `.batch-context.md` present or not. Then Step 4.
- **A different batch** → back to Step 3a's question with the remaining batches; the declined one
  isn't offered again. Nothing left → report and end. Not offered at all when Step 3a didn't run a
  picker (auto-resumed in-progress batch, or only one selectable batch) — offering one here would
  restart a different batch mid-work; the go-ahead then has only **Start** / **Cancel**.
- **Cancel** → report "aborted, nothing touched" and end. No lock was ever held.

## 4. Work Off a Phase

Before reading the phase file, two checks — both already resolved by Step 1-3a's preflight call
for the phase it was run against; **only re-run the preflight here** (same `--select <batch>`) if
a phase other than the one it resolved is about to start (e.g. the second and later phases of a
batch, since the preflight only ever resolves `nextPhase` for the lowest-numbered open phase at
call time). **(4a) Earlier failed attempt:** `nextPhase.failedAttempt` — `.found: true` → read its
`.note`/`.at`, check whether the cause still holds before repeating, and mention it in the new
entry ("second attempt after …"); `.found: false` → skip silently. Print `Failed Attempt` either
way. **(4b) Size gate.** `contextGate` — deterministic projection, already computed by the
preflight from the phase's `## Size` heading, never prose arithmetic. `contextGate.verdict`:
`START` → (4c); `HANDOFF` → no phase ran, hand off cleanly (Step 6) instead. Print the `Size Gate`
status line as `USED=<contextGate.used|?> SIZE=<contextGate.size> LIMIT=<contextGate.limit>
<contextGate.verdict> (<contextGate.note>)`; this closes `PRECHECKS`.
**(4b2) Go Gate.** Print one status line — phase number/title (from the phase file's own heading),
`## Size` letter, `Affected Files` — then one `AskUserQuestion`: **Go** (proceed to 4c) / **Cancel**
(release the lock, end the session, nothing touched). Field mapping and option copy in
`references/queues.md`'s **Pre-Implementation Go Gate**.
**(4c) Implementation.** Read the lowest-numbered open `NN-*.md` in full — multi-file or
unclear-scope phases may delegate that research to an `implExploreModel` subagent first;
implementation itself never runs on one. Implement it completely, run the plan's verification with
output filtered — a green run may delegate the filtering to the same subagent, a red run never does
(full unfiltered failure back either way), per `references/queues.md`'s **Research and Verification
Delegation**. A phase touching `docs/<codeLanguage>/…` →
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
an existing one out) — commit, message in `codeLanguage`, composed via `cfq-changelog.sh
commit-message` (`references/queues.md`'s **Phase Commit Trailers**), and push: `-u origin
<branch>` on this session's first push, a plain `git push` after that. Then backfill the commit
hash via
`git rev-parse HEAD` and `cfq-report.sh set-commit "<batch-dir>" "<phase-slug>" "<sha>"` — without
it, `cfq-resume.sh`'s commit fields stay empty for every phase from here on. Print the `Commit`
status line — branch and commits pushed.

## 6. Context Check After Every Phase

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/ctx-usage.sh"`. `policy.onePhasePerSession` (Step 1-3a's
preflight, no new call) `true` → treat exactly like `STOP` below, regardless of the context gate's
own verdict; `false` → the context gate alone decides. `STOP` → print `POSTCHECKS`, sync telemetry
and release the lock (`cfq-telemetry.sh sync "<repo-root>"`, `cfq-lock.sh release "<repo-root>"`),
printing `Telemetry`/`Lock`, then end — the follow-up session acquires the lock fresh, a
half-finished batch must not stay locked. Print the `HANDOFF · implement-for-queue` short format
from Step 8. `OK` → next phase, same batch. `UNKNOWN` → treat like `STOP`. `stopUsed: 0` is
deliberate, not a misconfiguration — `STOP` fires after every phase, one context window each; hand
off without commenting on it. `stopUsed: -1` is equally deliberate — `STOP` never fires for this
reason. `onePhasePerSession: true` (the default) is the finer of two gates: the batch-level Step 3b
go-ahead is coarse, this and (4b2)'s per-phase Go question are fine — together nothing is ever
implemented without an explicit confirmation naming what's about to change.

## 7. Batch Done

No open `NN-*.md` left → print the `POSTCHECKS` header, then run
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-finish.sh" "<repo-root>" "<batch-dir>" "<branch>"`, which moves
the batch into `impl/done/`, registers the repo, runs the language/maintenance/security/changelog/
telemetry sequence and releases the lock unconditionally (a `trap`, so a mid-sequence failure can
never leave the repo locked), and prints one JSON object. Render its fields:
- `Language`: `.lang.issues` from the JSON is the structural count (`missing`/`stray`/`unfiled`);
  judge `.lang.prose.sample` for prose, comments, identifiers and commit messages not in
  `codeLanguage` — any language, never hardcode one to look for. `i18nExcludePatterns` keeps
  locale/translation resources out of the sample by default; a line that lands anyway (custom
  naming the patterns miss) from an evident translation resource isn't a `codeLanguage` violation —
  expected multi-language content, not a policy breach. `.lang.prose.truncated: true`
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
"<repo-root>/.claude/cfq/impl/done/<batch>"`), printing `Report` as `rendered`; else `➖ off ·
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

**Short format** — `HANDOFF · implement-for-queue` header, three to four lines: phases done, phases open, the `USED`
value, `/clear` → `/ifq`. No cost breakdown, no merge hint. **Red case:** still the full format,
naming the red phase; its `❌` line already appeared in `IMPLEMENTATION` (Step 4), so Step 8 only
repeats the `5 green, 1 red` split in `Batch`, not the error text.
