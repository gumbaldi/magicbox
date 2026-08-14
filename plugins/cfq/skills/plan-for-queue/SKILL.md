---
name: plan-for-queue
description: >
  Interview the user, resolve open questions, and write detailed phase plans that get parked in
  the repo-local implementation queue — without implementing anything. Use whenever a feature, a
  series of bugs, a refactoring or a larger rework needs planning, and for "plan this", "how do
  we approach X", "/pfq", "/plan-for-queue". A separate cheaper session implements it later via
  implement-for-queue.
---

# Plan-for-Queue: Interview, Park, Hand Off

Always answer in the user's language. The output of this session is plan files only — no code
edits, no builds, no commits, not even "just this one line."

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
| INTERVIEW | 1 | `Interview Depth` | `Quick` / `Grilling` / `Grilling + Docs` |
| INTERVIEW | 3 | `Plugin Boundaries` | `blocked: superpowers` / `➖ none` |
| INTERVIEW | 5 | `Queue Check` | `➖ no open batches` / `⚠️ overlap with <batch>: <n> files` |
| PLANNING | 7 | `Language` | `en · docs: de · level standard` / `➖ minimal` |
| PLANNING | 7 | `Phases` | `5 phases · 2 M, 3 S` |
| PLANNING | 8 | `Security` | `3 low, 1 medium` / `⚠️ unavailable: <hint>` / `➖ no findings` |
| PLANNING | 9 | `Priority` | `high` |
| POSTCHECKS | 10 | `Park` | `5 files · <batch-dir>` |
| POSTCHECKS | 10 | `Git Exclude` | `already set` / `added` |
| POSTCHECKS | 10 | `Registry` | `registered` |
| POSTCHECKS | 11 | `Lint` | `OK 5 phases` / `❌ <finding>` (fixed, re-checked) |
| POSTCHECKS | 12 | `Maintenance` | `➖ off` / `➖ not due (12 commits)` / `3 findings` |
| POSTCHECKS | 13 | `Telemetry` | `recorded · synced` / `⚠️ sync failed` |

The Step 8 security snapshot is written only after parking; it's covered by the `Park` line.

## Step 0 — Inbox

List `"<repo-root>/.claude/code-for-queue/plan"/*.md`. Existing orders are offered as topics
(filename plus first line); the user picks one or declines. The chosen order file moves to
`plan/done/` once parked. No orders → skip silently, no status line, no mention.

## Step 1 — Interview Depth (unconditional, always, before anything else)

Print the `INTERVIEW` header on entering. Ask this before anything else, every time, even for a
small task or a familiar codebase — never skip, never infer. One `AskUserQuestion` with three
options, the recommendation derived from scope (components touched, how unclear the requirement
is, how far consequences reach) and justified in the option text — don't always mark the same one:

- **Quick interview** — a handful of targeted questions; fits when the scope is manageable.
- **Thorough grilling** — a design tree, round by round, until nothing is left open. Costs
  noticeably more planning tokens; recommended for complex reworks.
- **Grilling with docs** — thorough grilling plus a paper trail: domain terms into a `CONTEXT.md`
  glossary, hard-to-reverse/surprising trade-off decisions into ADRs under `docs/adr/`. Most
  expensive; writes versioned files into the target repo — recommend only for genuinely new
  domain vocabulary or decisions someone would otherwise have to re-derive.

On **Thorough** or **Grilling with docs**, read `references/grilling.md` and follow it. Print the
`Interview Depth` status line once answered.

## Step 2 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not.

## Step 3 — Plugin Boundaries

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planBlockedPlugins`. Blocked plugins are
used neither directly nor indirectly, nor recommended in the phase files this session produces.
Print the `Plugin Boundaries` status line.

## Step 4 — Interview

Clarify open points as long as different readings would lead to materially different work.
Decide and name routine decisions yourself instead of asking.

## Step 5 — Queue Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh" | jq -c '.repos[] | select(.path == "<repo-root>") | .batches[] | select(.archived == false and .open > 0) | {name, priority, open, dependsOn}'
```

Any batch found → read `references/queue-check.md` and follow it. No repo / no open batches →
skip the step without mentioning it. Either way, print the `Queue Check` status line — `➖` when
there was nothing to check.

## Step 6 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans: "Before I write the plans: is
there anything else we should discuss? Something I misunderstood, an edge case, a constraint?"
Proceed only once the user says no; if something comes up, work it in and ask again afterward.

## Step 7 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`; the confirmation dialogue stays prose.
Read once per session: `cfq-settings.sh get codeLanguage`, `docLanguages`, `docLevel`.
`codeLanguage` governs everything a phase specifies without exception — code, comments, commit
messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/`. A phase touching
documentation → read `references/language.md` and follow it. Print the `Language` status line
once read.

Propose a split and get it confirmed — one phase = one self-testable, individually committable
unit; three honest phases beat seven artificial ones. For each phase, estimate **Size** `S`/`M`/`L`
(`S` one file and one test, `M` several files or a new script, `L` a new script **with** a new
test or a skill rework — steers whether `ifq` even starts a phase) and optional **Recommended
skills** (only where it helps, half-sentence reason each, never from `implBlockedPlugins`; no
recommendation is the normal case). Print the `Phases` status line once confirmed — phase count
and size mix.

## Step 8 — Security Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-security.sh" "<repo-root>" > /tmp/cfq-sec.json
jq -c '{available, sources, counts, fixable}' /tmp/cfq-sec.json
```

`available == false` → print the `hint` once, never mention it again. Findings present → state the
count per severity. Only when `fixable.critical`/`fixable.high` > 0: one `AskUserQuestion` asking
whether a security phase should join the batch (suggested first, since it's independent).
Anything below that stays a warning line, no further planning. Store the snapshot after parking
with `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" security "<batch-dir>" "$(cat
/tmp/cfq-sec.json)"` so `ifq` can diff it later. Print the `Security` status line — count per
severity, or `➖ no findings`.

## Step 9 — Priority (unconditional, always)

Ask this for every batch, every time, even a two-phase batch or an obvious urgency — never skip,
never infer, never fold into another question. One `AskUserQuestion` with `low`/`medium`/`high`;
`medium` is the default, but derive it honestly — a hotfix batch is `high`, say so in the option
text rather than reflexively picking `medium`. Written to `.priority` in Step 10; nothing is
parked before this is asked. Print the `Priority` status line once answered.

## Step 10 — Park

Entering this step closes `PLANNING` and opens `POSTCHECKS`.
- Repo root: `git rev-parse --show-toplevel`. No repo → report and abort.
- Batch directory `<repo-root>/.claude/code-for-queue/impl/<YYYY-MM-DD>-<topic-slug>/`;
  `NN-<slug>.md` per phase, numbered ascending; `.priority` with the Step 9 value, nothing else.
- Step 5 concluded a dependency → write `.dependsOn`, one batch name per line; no dependency →
  don't create the file.
- Ensure `**/.claude/code-for-queue/` is in `<repo-root>/.git/info/exclude` (local only, never the
  versioned `.gitignore`), then `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"`.
- Grilling path: write decisions as a `## Decisions` table into the **first** phase file, no
  separate ADR directory.

Print three status lines: `Park` (file count and batch dir, also covers the Step 8 snapshot),
`Git Exclude`, `Registry`.

## Step 11 — Plan Lint

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lint.sh" "<batch-dir>"`. Findings are fixed
**immediately** and the lint re-run until it's clean — a batch never goes into handoff with open
lint findings. `warn:` lines (an unresolvable `.dependsOn` edge) are mentioned but don't block.
Print the `Lint` status line — clean pass, or the fixed finding on re-check.

## Step 12 — Maintenance

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-maintenance.sh" due "<repo-root>"`. `OFF` or `NOT_DUE <n>`
→ print the `Maintenance` status line and move on, nothing is loaded. `DUE <n>` → read
`references/maintenance.md` and follow it.

## Step 13 — Telemetry and Sync

Run `cfq-telemetry.sh record "<batch-dir>" planning` then `cfq-telemetry.sh sync "<repo-root>"`
(both via `${CLAUDE_PLUGIN_ROOT}/scripts/`). Failures of either call are non-fatal and get one
line in the final report, not a comment. Print the `Telemetry` status line.

## Step 14 — Final Report

A `RESULT` header, then a label/value list under the `Output Format` padding rule: `Batch`
(absolute path) · `Phases` (in order, each with its size) · `Priority` (Step 9's value) ·
`Waiting on` (the `.dependsOn` edge and its reason, omit the line entirely when there is none) ·
`Cost` (interview depth, turns, tokens, model, effort) · `Security` (count, "unavailable"+hint, or
"no findings") · `Handoff` (`/clear` → `/model <first implModels>` → `/ifq`).

If a cleanup batch came out of Step 12, print a second `RESULT` block the same way, noting it can
be worked off independently — no repetition of the plan contents, that's what the files are for.

## Phase File Structure

Unchanged from the template: Context · Affected Files (always absolute paths) · Changes
(copy-ready) · Reuse · Dependencies · Verification (with output filtering). Plus the conventions:
absolute paths, no project-specific proper nouns in test data, token hygiene in the verification
section, and the verification must check the real path the user actually takes.
