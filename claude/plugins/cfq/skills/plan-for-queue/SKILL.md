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
The context carries a JSON object with `"injected": true` and `status` `OK` or `NO_REPO` (the
`/pfq` command ran the preflight while loading) → that object is the preflight result, never
repeat the call, and remember the path as `injected`. `INJECTION_OFF`, `PREFLIGHT_ERROR` or no
object → remember `fallback` and run the preflight once for the whole session:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-plan "$(pwd)"
```
`status: "NO_REPO"` → report and end. Otherwise this result covers every later step too — never
re-derive or re-run `bin/cfq settings`/`scan`/`registry`/`maintenance`/`note` for anything it
already carries — its own `note import`/`note list --overview`/`note list --detail` calls already
produced `inbox.count`/`.imported`/`.overview`/`.detail`.

## Step 2 — Inbox

`inbox.pendingImport` above `0` → run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" note import "<repo-root>"`,
then `note list "<repo-root>" --overview` and `--detail` again, and print those instead of the
injected `inbox.overview`/`inbox.detail` (the entries must live in `plan/` before one can be chosen
for `--from-plan`).

Print `Inbox` as returned, then `inbox.overview` verbatim right after it — always, with or without
arguments, zero entries included (`INBOX  empty`). Arguments were passed with the invocation → don't open the inbox question regardless of
entry count; plan the arguments, leave every inbox entry untouched, but when those arguments refer
to or ask about inbox entries, print `inbox.detail` right after `inbox.overview` first. No
arguments and `inbox.count == 0` → nothing further here. No arguments and `inbox.count > 0` → read
`${CLAUDE_PLUGIN_ROOT}/references/plan-inbox.md` and follow it. `queue.awaitingAudit` non-empty and
no arguments → print one line naming the batch, read `${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md` first and resume
its audit per **The Post-Write Audit** (start, agent, wait, done), then continue at **Maintenance**. No question.

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
Then read **Group A** in one parallel turn: `${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`,
`${CLAUDE_PLUGIN_ROOT}/references/explore-escalation.md`, plus `${CLAUDE_PLUGIN_ROOT}/references/grilling.md`
when the user picked **Thorough grilling** or **Grilling with docs** (follow it for the interview round).

## Step 4 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not. For research spanning multiple files or unclear scope, delegate to
Explore agents instead of reading inline — one for a narrow area, up to three in parallel for
broad scope, each with a specific focus. Model choice is a rule, not a mood — follow
`explore-escalation.md` (read in Group A).

## Step 5 — Interview

Clarify open points as long as different readings would lead to materially different work; decide
and name routine decisions yourself — follow
`interaction-policy.md` (read in Group A); its **Active Interview
Duty** also governs **Closing Question**'s closing check.

## Step 6 — Queue Check

`queue.openBatches` (**Preflight**, no new `bin/cfq scan | jq` call). None → print `Queue Check`
with `➖` and move on. Any batch found → `queue-check.md` (read in Group B) is followed at the start
of **Language and Cut Phases**, right after that read: overlap sets `.dependsOn` automatically,
without a question; print `Queue Check` there.

## Step 7 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans: "Before I write the plans: is
there anything else we should discuss? Something I misunderstood, an edge case, a constraint?"
(one `AskUserQuestion`; when autonomous decisions are listed (`interaction-policy.md`'s **Active
Interview Duty**), the list is in the question text). Proceed once nothing else is open; if something comes up, ask again.

## Step 8 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`. Read **Group B** in one parallel turn:
`${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md`, `${CLAUDE_PLUGIN_ROOT}/references/phase-template.md`,
`${CLAUDE_PLUGIN_ROOT}/references/plan-self-critique.md`, `${CLAUDE_PLUGIN_ROOT}/references/plan-park.md`,
`${CLAUDE_PLUGIN_ROOT}/references/batch-context.md`, plus `${CLAUDE_PLUGIN_ROOT}/references/queue-check.md`
when `queue.openBatches` has entries and `${CLAUDE_PLUGIN_ROOT}/references/language.md` when a phase touches
documentation. Read `language.codeLanguage`/`.docLanguages`/`.docLevel` from **Preflight**'s result (no new
call). `codeLanguage` governs everything a phase specifies without exception — code, comments,
commit messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/` — and this session's own
output too: plan files, `## Decisions`, the batch directory name. A phase touching documentation →
follow `language.md`. Print `Language`. Propose a
split — one phase = one self-testable, individually committable unit — as a status update (phase
list + S/M/L sizes); no dedicated confirmation question gates the write, that gate is
**Self-Critique of the Phase Cut**. Follow `phase-quality.md` (and `phase-template.md` as the
phase-file skeleton), always, before writing any phase's Changes and Verification text — it also steers the
Size letter (rule 5). For each phase, estimate **Size** `S`/`M`/`L` and write the `## Size` heading
— mechanics (letter placement, what parses it, the degrade-to-`M` fallback) in `phase-quality.md` rule 5. Per phase, decide the
optional `## Model` heading per that file's rule 8, from `planningPolicy.implModels`. Print `Phases` once
written — no phase file is written to disk yet, that's **Park**, after **Self-Critique of the
Phase Cut**.

## Step 9 — Self-Critique of the Phase Cut

Still `PLANNING`. Follow the self-critique reference (already read in Group B, do not read it again),
unconditionally, before any phase file is written. Print `Self-Critique`: `✅` with the phase count,
or `⚠️` with each correction named on its own `   └ ` sub-line — the primary channel for
corrections.

## Step 10 — Security and Park

Entering this step closes `PLANNING` and opens `POSTCHECKS`.
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" planning open "<repo-root>" "<YYYY-MM-DD>" "<topic-slug>"
```
(repo root: **Preflight**'s `repo.root`, no repeat `git rev-parse`) runs the security check
whatever `security.available` says (a capability hint only: without a forge binary the forge side
comes back empty, a `package.json` repo still gets a local `npm audit`), reserves the batch and
stores the security snapshot. Read its JSON directly (no `jq`, no `/tmp` file) and print its
`statusLines` entry `Security` verbatim. `status` is not `OK` → surface `action`/`detail` and stop,
nothing parked. `securityEntry.needed` true and `securityEntry.exists` false → write the `plan/`
entry via `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" note plan "<repo-root>" "security-findings" - <<'EOF' … EOF`
(body on stdin, never a temp file; counts per severity and the fixable advisories, plus either of
two closings: when a phase of this batch names every fixable critical and high advisory, the body
names that phase and says the entry can be closed once it lands, with no sentence saying a decision
is open; otherwise the body says a decision is still open); otherwise write nothing. Never a
question, never a phase in this batch.

Write `NN-<slug>.md` per phase into `batchDir` — all phase files in one response (anchors are looked up before that turn, not between the writes), mechanics in
`plan-park.md`'s **Park Mechanics** (read in Group B). Phase files alone use the
`Write` tool; everything else here goes through `bin/cfq`. Write `<batch-dir>/.batch-context.md` —
follow `batch-context.md` (read in Group B). Then `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" park
"<repo-root>" "<batch-dir-name>" "<high|normal>" [<dependsOn-entry>...] [--from-plan
<chosen-entry-path>]` — argument detail in the same section; `--from-plan` is passed only when
this session's topic came from a chosen inbox entry (**Inbox**), naming that entry's path so it
moves into `plan/done/`. Print four status lines (wording in **Park Mechanics**): `Park`,
`Batch Context`, `Git Exclude`, `Registry`.

## Step 11 — Post-Write Audit

Follow **The Post-Write Audit** of the self-critique reference (already read in Group B, do not read it again). Print `Phase Audit`: `✅` with the count and `no findings`, or `⚠️` per correction as a `   └ ` sub-line.

## Step 12 — Maintenance

Read `maintenance.status`/`.n` from **Preflight**'s result (no new call). `OFF`/`NOT_DUE`
→ print `Maintenance`, move on. `DUE` → read `${CLAUDE_PLUGIN_ROOT}/references/maintenance.md` and
follow it — findings are parked as a `plan/` entry, never a question. It runs before the close
call, because that call records the session's telemetry.

## Step 13 — Close and Report

Entering this step closes `POSTCHECKS`.
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" planning close "<batch-dir>" --depth <quick|thorough|docs>
```
(the interview depth chosen at **Start Block**; `docs` for "Grilling with docs") runs lint,
releases the batch, records and syncs the planning telemetry and builds the portal link. Print its
`statusLines` entries verbatim, in order. `LINT_FAILED` → fix every finding in one turn (all
corrections of one run in one response; several `Edit` calls on one file are applied in the order sent) and call it again; `warn:` lines are fixed when they are
`changes-steps`, the others don't block. A telemetry failure is one line in the report, never a
stop.

Then the `RESULT · plan-for-queue` block — field list in
`plan-park.md`'s **Final Report Fields** (read in Group B). A correction asked for
after the report is made in the plan files, then `bin/cfq park` if a phase file was added, renamed
or removed, then `planning close` again (idempotent).
