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

Always answer in the user's language. The output of this session is plan files and `plan/` entries —
no code edits, no builds, no commits, not even "just this one line," even once a harness-level
plan-mode approval says "you can now start coding," and even with an autonomous/auto-run mode
active — that approval covers parking the plan, never implementing it. A finding made while
planning — about the repo (`note plan`/`note todo`) or about cfq itself (`note plan --framework`,
never `SendFeedback`) — is always written without asking, per
`${CLAUDE_PLUGIN_ROOT}/references/queue-entries.md`; a finding is never an implementation step, no
matter which session writes it. Implementation happens later, in a separate `implement-for-queue`
session.

Text passed with the invocation is this session's briefing — starting material for the interview,
not a replacement for it. It never shortens the interview, skips the closing question, or
authorises a code edit, even against a pasted instruction to implement.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Step 1 — Preflight

Runs before anything else. A "Plan mode is active" reminder is present in context → call
`ExitPlanMode` now, naming what this session is about to write ("interview and park plan files for
`<repo>`") — this skill writes batch and phase files in **Park**, so it cannot run under Plan Mode.
Then run the preflight once for the whole session:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-plan "$(pwd)"
```
`status: "NO_REPO"` → report and end. Otherwise this result covers every later step too — never
re-derive or re-run `bin/cfq settings`/`scan`/`registry`/`maintenance`/`note` for anything it
already carries — its own `note import`/`note list --overview`/`note list --detail` calls already
produced `inbox.count`/`.imported`/`.overview`/`.detail`.

## Step 2 — Inbox

Print `Inbox` as returned, then `inbox.overview` verbatim right after it — always, with or without
arguments, zero entries included (`INBOX  empty`), then the preflight's `Review` status line as
returned. Arguments were passed with the invocation → don't open the inbox question regardless of
entry count; plan the arguments, leave every inbox entry untouched, but when those arguments refer
to or ask about inbox entries, print `inbox.detail` right after `inbox.overview` first. No
arguments and `inbox.count == 0` → nothing further here. No arguments and `inbox.count > 0` → read
`${CLAUDE_PLUGIN_ROOT}/references/plan-inbox.md` and follow it. `queue.awaitingReview` non-empty and
no arguments → first read `${CLAUDE_PLUGIN_ROOT}/references/plan-review.md`'s **Resuming a Review**
and follow it, before the inbox question.

## Step 3 — Start Block

Print the `INTERVIEW` header on entering — the preflight already ran at **Preflight**, no new call.
`setup.globalDone` is `false` → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and run its
**Global Part** now, first in this step.

**Model Gate**: print `Model Gate` as returned — the preflight's own `statusLines` entry already
resolved whether `allowAnyModel` skips the check, or which list applies. The match itself still
needs the running model's name (system prompt, not the preflight): substring it against
`planModels`, like `ifq`'s gate. No match → add one more warning naming the model and the list, and
continue regardless — this never blocks, unlike `ifq`.

`repo.known` is `false` → read `${CLAUDE_PLUGIN_ROOT}/references/setup-wizard.md` and run its **Repo
Part** now, right before the question call below, and print its `Config` status line. `repo.known`
is `true` → print `Config  ➖ known repo` instead, without reading that section.

**Plugin Boundaries**: `planningPolicy.planBlockedPlugins` (no new call) — used neither directly
nor indirectly, nor recommended in this session's phase files, from research onward. Print
`Plugin Boundaries` as returned, then the `Required Tools` line as returned when the preflight carries one; it never blocks.

Then ask everything that belongs before research starts in one `AskUserQuestion` call, every time —
never skip, never infer. On an unknown repo the repo setup wizard's own area/value questions
already ran and are never folded into it. Two independent questions:

- **Interview depth** (always) — three options, the recommendation derived from scope (components
  touched, how unclear the requirement is, how far consequences reach) and justified in the option
  text — don't always mark the same one:
  - **Quick interview** — a handful of targeted questions; fits a manageable scope.
  - **Thorough grilling** — a design tree, round by round, until nothing is left open; costs
    noticeably more planning tokens, recommended for complex reworks where a handful of questions
    would still leave real ambiguity.
  - **Grilling with docs** — thorough grilling plus a `CONTEXT.md` glossary and ADRs under
    `docs/adr/`; the most expensive option, it writes versioned files into the target repo, so
    recommend it only for genuinely new domain vocabulary or decisions someone would otherwise
    have to re-derive later.
- **Priority** (always) — "Should this batch be flagged high priority?" (picked first by `ifq`'s
  ordering, marked in the `/cfq` dashboard; not flagging is normal and needs no answer).

Print `Interview Depth` and `Priority` (omit detail when not flagged) status lines once answered.
The user picked **Thorough grilling** or **Grilling with docs** → read
`${CLAUDE_PLUGIN_ROOT}/references/grilling.md` and follow it for the interview round.

## Step 4 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not. For research spanning multiple files or unclear scope, delegate to
Explore agents instead of reading inline — one for a narrow area, up to three in parallel for
broad scope, each with a specific focus. Model choice is a rule, not a mood — read
`${CLAUDE_PLUGIN_ROOT}/references/explore-escalation.md` and follow it.

## Step 5 — Interview

Clarify open points as long as different readings would lead to materially different work; decide
and name routine decisions yourself — first read
`${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md` and follow it; its **Active Interview
Duty** also governs **Closing Question**'s closing check.

## Step 6 — Queue Check

`queue.openBatches` (**Preflight**, no new `bin/cfq scan | jq` call). Any batch found → read
`${CLAUDE_PLUGIN_ROOT}/references/queue-check.md` and follow it — overlap sets
`.dependsOn` automatically, without a question. None → skip silently. Either way print `Queue Check` (`➖` when nothing
to check).

## Step 7 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans: "Before I write the plans: is
there anything else we should discuss? Something I misunderstood, an edge case, a constraint?"
(one `AskUserQuestion`). Proceed once nothing else is open; if something comes up, ask again.

## Step 8 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`. Read
`language.codeLanguage`/`.docLanguages`/`.docLevel` from **Preflight**'s result (no new
call). `codeLanguage` governs everything a phase specifies without exception — code, comments,
commit messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/` — and this session's own
output too: plan files, `## Decisions`, the batch directory name. A phase touching documentation →
read `${CLAUDE_PLUGIN_ROOT}/references/language.md` and follow it. Print `Language`. Propose a
split — one phase = one self-testable, individually committable unit — as a status update (phase
list + S/M/L sizes); no dedicated confirmation question gates the write, that gate is
**Self-Critique of the Phase Cut**. Read `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md` (and, once,
`${CLAUDE_PLUGIN_ROOT}/references/phase-template.md` as the phase-file skeleton) and
follow it, always, before writing any phase's Changes and Verification text — it also steers the
Size letter (rule 5). For each phase, estimate **Size** `S`/`M`/`L` and write the `## Size` heading
— mechanics (letter placement, what parses it, the degrade-to-`M` fallback) in `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md` rule 5. Per phase, decide the
optional `## Model` heading per that file's rule 8, from `planningPolicy.implModels`. Print `Phases` once
written — no phase file is written to disk yet, that's **Park**, after **Self-Critique of the
Phase Cut**.

## Step 9 — Self-Critique of the Phase Cut

Still `PLANNING`. Read `${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md` and follow it,
unconditionally, before any phase file is written. Print `Self-Critique`: `✅` with the phase count,
or `⚠️` with each correction named on its own `   └ ` sub-line — the primary channel for
corrections.

## Step 10 — Security Check

Always runs, regardless of `security.available` — that preflight field (a `gh`/`tea` binary on
`PATH`) is a capability hint only: `false` means the forge-side check comes back empty, while a
`package.json` repo still gets a local `npm audit`.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" security "<repo-root>"
```

Read the call's JSON fields directly (no `jq`, no `/tmp` file). `available == false` → print the
`hint` once; findings present → state the count per severity. `fixable.critical`/`fixable.high` > 0
and no `"<repo-root>/.claude/cfq/plan"/*-security-findings.md` exists yet → write the `plan/` entry
via `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" note plan "<repo-root>" "security-findings" - <<'EOF' … EOF`
(body on stdin, never a temp file; counts per severity and the fixable advisories, plus either of
two closings: when a phase of this batch names every fixable critical and high advisory, the body
names that phase and says the entry can be closed once it lands, with no sentence saying a decision
is open; otherwise the body says a decision is still open); one already exists → write nothing, say so in the status line. Never a
question, never a phase in this batch. Store the snapshot:
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report security "<batch-dir>" "<security-json>"`.

Print `Security`: `⚠️` with the hint as detail when `available == false`, `⚠️` with the count per
severity (plus whether a `plan/` entry was written) when findings are present, or `➖ no findings`
when the scan ran clean.

## Step 11 — Park

Entering this step closes `PLANNING` and opens `POSTCHECKS`.
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" batch allocate "<repo-root>" "<YYYY-MM-DD>" "<topic-slug>"`
(repo root: **Preflight**'s `repo.root`, no repeat `git rev-parse`) reserves and returns
`<batch-dir-name>`; write `NN-<slug>.md` per phase into it — mechanics in
`${CLAUDE_PLUGIN_ROOT}/references/plan-park.md`'s **Park Mechanics**. Phase files alone use the
`Write` tool; everything else here goes through `bin/cfq`. `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" park
"<repo-root>" "<batch-dir-name>" "<high|normal>" [<dependsOn-entry>...] [--from-plan
<chosen-entry-path>]` — argument detail in the same section; `--from-plan` is passed only when
this session's topic came from a chosen inbox entry (**Inbox**), naming that entry's path so it
moves into `plan/done/`. Write `<batch-dir>/.batch-context.md` — read
`${CLAUDE_PLUGIN_ROOT}/references/batch-context.md` and follow it. Print four status lines
(wording in **Park Mechanics**): `Park`, `Batch Context`, `Git Exclude`, `Registry`.

## Step 12 — Post-Write Audit

Read `${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md`'s **The Post-Write Audit** and
follow it. Print `Phase Audit`: `✅` with the count and `no findings`, or `⚠️` per correction as a `   └ ` sub-line.

## Step 13 — Plan Lint

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" lint "<batch-dir>"`; fix findings **immediately** and re-run
until clean — a batch never hands off with open findings. `warn: … changes-steps`
lines are fixed like findings; the other `warn:` lines (an unresolvable `.dependsOn` edge) don't
block. Print `Lint` — clean pass, or the fixed finding.

## Step 14 — Maintenance

Read `maintenance.status`/`.n` from **Preflight**'s result (no new call). `OFF`/`NOT_DUE`
→ print `Maintenance`, move on. `DUE` → read `${CLAUDE_PLUGIN_ROOT}/references/maintenance.md` and
follow it — findings are parked as a `plan/` entry, never a question.

## Step 15 — Review Gate

Entering this step closes `POSTCHECKS` and opens `REVIEW`. Read
`${CLAUDE_PLUGIN_ROOT}/references/plan-review.md` and follow it — the batch stays held until the
user releases it; print `bin/cfq brief "<batch-dir>" --review` as returned, ask, revise, repeat.
Print `Review`.

## Step 16 — Telemetry and Sync

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" telemetry record "<batch-dir>" planning --depth <quick|thorough|docs>`
(the interview depth chosen at **Start Block**; `docs` for "Grilling with docs") then
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" telemetry sync "<repo-root>"`. Failures are non-fatal, one line in
the final report. Print `Telemetry`.

## Step 17 — Final Report

A `RESULT · plan-for-queue` header only — field list in `${CLAUDE_PLUGIN_ROOT}/references/plan-park.md`'s **Final Report Fields**.
