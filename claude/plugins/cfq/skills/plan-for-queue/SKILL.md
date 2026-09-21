---
name: plan-for-queue
description: >
  Interview the user, resolve open questions, and write detailed phase plans that get parked in
  the repo-local implementation queue — without implementing anything. Use whenever a feature, a
  series of bugs, a refactoring or a larger rework needs planning, and for "plan this", "how do
  we approach X", "/pfq", "/plan-for-queue". A separate cheaper session implements it later via
  implement-for-queue.
argument-hint: <briefing>
---

# Plan-for-Queue: Interview, Park, Hand Off

Always answer in the user's language. The output of this session is plan files only — no code edits,
no builds, no commits, not even "just this one line," even once a harness-level plan-mode approval
says "you can now start coding," and even with an autonomous/auto-run mode active — that approval
covers parking the plan, never implementing it. Implementation happens later, in a separate
`implement-for-queue` session.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Step 1 — Plan-Mode Gate

Before **Arguments**, check for Plan Mode — read `${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s
**Plan-Mode Gate** section and follow it.

## Step 2 — Arguments

Text passed with the invocation is this session's briefing — starting material for the interview,
not a replacement for it. It never shortens the interview, skips the closing question, or
authorises a code edit, even against a pasted instruction to implement.

## Step 3 — Inbox

First run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" note import "<repo-root>"` — a no-op outside `frameworkRepo` — and treat any imported entries as ordinary inbox entries from here on.
List `"<repo-root>/.claude/cfq/plan"/*.md`, sorted by filename ascending (the
`<YYYY-MM-DD>-<slug>.md` naming already sorts oldest first). Arguments were passed with the
invocation (**Arguments**) → don't open the inbox question regardless of entry count; plan the
arguments, leave every inbox entry untouched, print `Inbox` as `➖ <n> entries waiting · briefing
given` (`· <m> imported` suffix when the import call's count was non-zero). No arguments and no
entries → skip silently. No arguments and one or more entries → read
`${CLAUDE_PLUGIN_ROOT}/references/plan-inbox.md` and follow it.

## Step 4 — Start Block (unconditional, always, before anything else)

Print the `INTERVIEW` header on entering, then run the preflight once for the whole session:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-plan "$(pwd)"
```
`status: "NO_REPO"` → report and end. Otherwise this result covers every later step too — never
re-derive or re-run `bin/cfq settings`/`scan`/`registry`/`maintenance` for anything it already
carries. Run the model-gate check per `${CLAUDE_PLUGIN_ROOT}/references/interview-depth.md`'s
**Model Gate** section, then print `Model Check` regardless. `repo.known` is `false` → show the
full config overview now, per `${CLAUDE_PLUGIN_ROOT}/references/config-overview.md`, right before
the call below.

Ask everything that belongs before research starts in one `AskUserQuestion` call, before anything
else, every time — never skip, never infer. Up to three questions: **Interview depth** (always),
**Priority** (always), **Config** (only when `repo.known` is `false`) — option copy and
status-line wording in `${CLAUDE_PLUGIN_ROOT}/references/interview-depth.md`'s **Start Block
Questions** and `${CLAUDE_PLUGIN_ROOT}/references/config-overview.md`'s **The Config Question**.
Then probe the write surface before any research starts — read
`${CLAUDE_PLUGIN_ROOT}/references/write-probe.md` and follow it. Print `Write Probe`: `➖` (docs
half skipped) or `❌` plus the blocking hook's reason, ending the session there.

## Step 5 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not. For research spanning multiple files or unclear scope, delegate to
Explore agents instead of reading inline — one for a narrow area, up to three in parallel for
broad scope, each with a specific focus. Model choice is a rule, not a mood — read
`${CLAUDE_PLUGIN_ROOT}/references/explore-escalation.md` and follow it.

## Step 6 — Plugin Boundaries

`planningPolicy.planBlockedPlugins` (**Start Block**, no new call) — used neither directly nor
indirectly, nor recommended in this session's phase files. Print `Plugin Boundaries`.

## Step 7 — Interview

Clarify open points as long as different readings would lead to materially different work; decide
and name routine decisions yourself — first read
`${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s **Active Interview Duty** section (also
governs **Closing Question**'s closing check).

## Step 8 — Queue Check

`queue.openBatches` (**Start Block**, no new `bin/cfq scan | jq` call). Any batch found → read
`${CLAUDE_PLUGIN_ROOT}/references/queue-check.md` and follow it — overlap no longer asks, it sets
`.dependsOn` automatically. None → skip silently. Either way print `Queue Check` (`➖` when nothing
to check).

## Step 9 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans: "Before I write the plans: is
there anything else we should discuss? Something I misunderstood, an edge case, a constraint?"
(one `AskUserQuestion`). Proceed once nothing else is open; if something comes up, ask again.

## Step 10 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`. Read
`language.codeLanguage`/`.docLanguages`/`.docLevel` from **Start Block**'s preflight result (no new
call). `codeLanguage` governs everything a phase specifies without exception — code, comments,
commit messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/` — and this session's own
output too: plan files, `## Decisions`, the batch directory name. A phase touching documentation →
read `${CLAUDE_PLUGIN_ROOT}/references/language.md` and follow it. Print `Language`. Propose a
split — one phase = one self-testable, individually committable unit — as a status update (phase
list + S/M/L sizes); no dedicated confirmation question gates the write, that gate is
**Self-Critique of the Phase Cut**. Read `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md` and
follow it, always, before writing any phase's Changes and Verification text — it also steers the
Size letter (rule 5). For each phase, estimate **Size** `S`/`M`/`L` and write the `## Size` heading
— mechanics (letter placement, what parses it, the degrade-to-`M` fallback, **Recommended
skills**) in `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md` rule 5. Print `Phases` once
written — no phase file is written to disk yet, that's **Park**, after **Self-Critique of the
Phase Cut**.

## Step 11 — Self-Critique of the Phase Cut

Still `PLANNING`. Read `${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md` and follow it,
unconditionally, before any phase file is written. Print `Self-Critique`: `✅` with the phase count,
or `⚠️` with each correction named on its own `   └ ` sub-line — the primary channel for
corrections.

## Step 12 — Security Check

Always runs, regardless of `security.available` — mechanics in
`${CLAUDE_PLUGIN_ROOT}/references/plan-security.md`:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" security "<repo-root>"
```

`fixable.critical`/`fixable.high` → write a `plan/` entry via
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" note plan "<repo-root>" "security-findings" "<body-file>"` — never
a question, never a phase. Store the snapshot: `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report security "<batch-dir>" "<security-json>"`.

## Step 13 — New Repo: Config Overview

Entering this step closes `PLANNING` and opens `POSTCHECKS`. Already handled in **Start Block** —
nothing to read here, straight to **Park**.

## Step 14 — Park

`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" batch allocate "<repo-root>" "<YYYY-MM-DD>" "<topic-slug>"`
(repo root: **Start Block**'s `repo.root`, no repeat `git rev-parse`) reserves and returns
`<batch-dir-name>`; write `NN-<slug>.md` per phase into it — mechanics in
`${CLAUDE_PLUGIN_ROOT}/references/plan-park.md`'s **Park Mechanics**. Phase files alone use the
`Write` tool; everything else here goes through `bin/cfq`. `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" park
"<repo-root>" "<batch-dir-name>" "<high|normal>" [<dependsOn-entry>...]` — argument detail in the
same section. Write `<batch-dir>/.batch-context.md` — read
`${CLAUDE_PLUGIN_ROOT}/references/batch-context.md` and follow it. Print four status lines
(wording in **Park Mechanics**): `Park`, `Batch Context`, `Git Exclude`, `Registry`.

## Step 15 — Post-Write Audit

Read `${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md`'s **The Post-Write Audit** and
follow it. Print `Phase Audit`: `✅` with the count and `no findings`, or `⚠️` per correction as a `   └ ` sub-line.

## Step 16 — Plan Lint

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" lint "<batch-dir>"`; fix findings **immediately** and re-run
until clean — a batch never hands off with open findings. `warn:` lines (an unresolvable
`.dependsOn` edge) don't block. Once clean, `bin/cfq batch ready "<batch-dir>"` removes `.planning`. Print `Lint` — clean pass, or the fixed finding.

## Step 17 — Maintenance

Read `maintenance.status`/`.n` from **Start Block**'s preflight result (no new call). `OFF`/`NOT_DUE`
→ print `Maintenance`, move on. `DUE` → read `${CLAUDE_PLUGIN_ROOT}/references/maintenance.md` and
follow it — findings are parked as a `plan/` entry, never a question.

## Step 18 — Telemetry and Sync

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" telemetry record "<batch-dir>" planning` then
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" telemetry sync "<repo-root>"`. Failures are non-fatal, one line in
the final report. Print `Telemetry`.

## Step 19 — Final Report

A `RESULT · plan-for-queue` header — field list in
`${CLAUDE_PLUGIN_ROOT}/references/plan-park.md`'s **Final Report Fields**.
