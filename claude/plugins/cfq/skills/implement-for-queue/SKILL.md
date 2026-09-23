---
name: implement-for-queue
description: >
  Work off parked phase plans from the repo-local queue (<repo>/.claude/cfq/) one
  batch per session, phase by phase, stopping when the context window gets too full. Use for
  "/ifq", "/implement-for-queue", "implement the queue", "work off the plans", "continue with
  the plans", "next phase".
argument-hint: <batch or phase>
---

# Implement-for-Queue: Work Off a Batch Phase by Phase

Always answer in the user's language.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Section Map

| Section | Steps | Contents |
|---|---|---|
| PRECHECKS | 1-7 | Preflight, Model Check, Batch, Start Gate, Size Gate |
| IMPLEMENTATION | 8-9 | per phase: announcement, result, Commit |
| POSTCHECKS | 10-12 | Context Check, Telemetry, Lock, Batch Done |

Not strictly sequential: a `WARN` at **Context Check After Every Phase** loops back to **Earlier
Failed Attempt** for the next phase instead of opening `POSTCHECKS`. `POSTCHECKS` opens only on a
`STOP`, a red phase, or a finished batch.

## Step 1 — Arguments

Text passed with the invocation narrows batch selection in **Batch Selection** — it never replaces
the briefing. `resume` and `start` (`start <batch>` included) are keywords, not a selection hint —
cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Arguments**
section on first use each session and apply it here.

## Step 2 — Plan-Mode Gate

Before **Batch Selection**, check for Plan Mode — read
`${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s **Plan-Mode Gate** section and follow it.

## Step 3 — Preflight: Policy, Batch Selection

Print the `PRECHECKS` header, then one call:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-impl "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```
`status: "NO_REPO"` → abort, report, end. Otherwise, print `inbox.overview` verbatim right here —
always, before Model Gate, the start gate or any lock, read-only, no import, no question, even when
no batch ends up selectable. This one call already resolved the model gate, plugin boundaries and
batch selection together — read its fields below, no further calls needed for those three steps.
**Model Gate**: print as returned; cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Model Gate Stop** section on first use each session and apply it here.

**Plugin Boundaries.** `policy.implBlockedPlugins` — those plugins/skills aren't called for the
rest of the session, not even indirectly — per-phase skill recommendations on this list are
ignored. Print `Plugin Boundaries` as returned (the preflight's own line).

**Batch Selection.** `status` already reflects the filtered outcome — `NO_BATCH` → report "No open plans for this repo in the queue.", end. Every other outcome's wording — cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Batch Selection Rules** section on first use each session and apply it here.

## Step 4 — Batch Briefing and Start

Nothing is touched, no lock taken, until the briefing has been shown — never read
phase files in full here, that's **Implementation**'s job. `contextGate.verdict` is `WARN`, and
`batch.consistency == "divergent"` — cold-path detail: read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Briefing Warnings** section on first use each session and apply it here. Present `batch.briefText` compactly (already the full
per-phase listing — name/priority/phase count/`dependsOn`/done phases ticked, open phases with size
and context excerpt), then show the batch overview and the queue listing, then follow the start
gate — cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Start Gate** section on first use each session and apply it here.

Acquire the repo lock (`bin/cfq lock acquire "<repo-root>" "<batch>"`) — cold-path detail: read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Lock Acquisition** section on first use each session and apply it here. `branch.mode`
(from the preflight — already computed, no new call) decides the checkout — full behavior (`off`/`continue`/`new`,
base-branch question, checkout, changelog init, changelog commit, post-checkout reconfirm) — based
on `origin`'s current state — in `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Branch
and Changelog on Go-Ahead**. `Branch` renders whichever happened. `resume` (same preflight
result) already carries done/open phases, last commit, deviations, red-phase history,
`.batch-context.md`'s path — no new `bin/cfq resume` call; if `resume.batchContext.exists`, `Read`
it now. Print `Resume` — phases done/open, `.batch-context.md` present or not.

`policy.orchestratorMode` is `true` → read `${CLAUDE_PLUGIN_ROOT}/references/orchestrator.md` and
follow it in place of everything from **Earlier Failed Attempt** through **Batch Done** below;
`false` → **Earlier Failed Attempt**.

## Step 5 — Earlier Failed Attempt

Entering this step closes `PRECHECKS` and opens `IMPLEMENTATION`. Before reading the phase file,
two checks — both already resolved by **Batch Selection**'s preflight call for the phase it was run
against; **only re-run the preflight here** (same `--select <batch>`) if
a phase other than the one it resolved is about to start (e.g. the second and later phases of a
batch, since the preflight only ever resolves `nextPhase` for the lowest-numbered open phase at
call time). `nextPhase.failedAttempt` — `.found: true` → read its
`.note`/`.at`, check whether the cause still holds before repeating, and mention it in the new
entry ("second attempt after …"); `.found: false` → skip silently. Print `Failed Attempt` either
way.

## Step 6 — Size Gate

`contextGate` — deterministic projection, already computed by the
preflight from the phase's `## Size` heading, never prose arithmetic. `contextGate.verdict`, three
branches:

- `START` → **Phase Announcement**, then **Implementation**.
- `WARN` → **Phase Announcement**, same as `START` — the phase is not blocked. Its
  `AskUserQuestion` fires only in this branch; nothing is skipped and nothing ends here.
- `HANDOFF` → no phase ran, hand off cleanly (the **Context Check**) instead.

Print the `Size Gate` status line — cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Context Gate Reason Semantics** section on first use each session and apply it here; this closes `PRECHECKS`. In orchestrator mode this step
does not run — every worker starts at zero context, so there is nothing the gate would protect
against.

## Step 7 — Phase Announcement

Print the phase announcement —
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" brief "<batch-dir>" --phase <NN>`, rendered as returned, no
rewording — then go straight to **Implementation**. `contextGate.verdict` was `WARN` is the one
exception — reappears every phase by design, never a repetition bug — one `AskUserQuestion` with
**Go**/**Handoff**/**Cancel**; full option copy and the rendering example are in
`${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Phase Announcement**.

## Step 8 — Implementation

Read the lowest-numbered open `NN-*.md` in full — multi-file or unclear-scope phases may delegate
that research to an `implExploreModel` subagent first; implementation itself never runs on one.
Implement it completely, run the plan's verification with output filtered — a green run may
delegate the filtering to the same subagent, a red run never does (full unfiltered failure back
either way), per `${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Research and Verification
Delegation**. A phase touching `docs/<codeLanguage>/…` → write the counterparts in every
`docLanguages` entry before it goes green, per `${CLAUDE_PLUGIN_ROOT}/references/doc-style.md` or
`<repo>/docs/STYLE.md` if present. Work found beyond this phase's scope is always parked — cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/queue-entries.md`'s **Parking Out-of-Scope Work** section on first use each session and apply it here.

Write the phase object (`phase`, `status`, `deviations`, on red `errors`) to a temp file — cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Phase Object Fields** section on first use each session and apply it here.

Green → `git add` the phase's changes (staging stays with the model — the closing call never runs
`git add` itself), write the commit message (subject/body plus `Co-Authored-By`) to a temp file,
then close the phase via the following **Commit & Push** step's single call. Red → record it now,
before anything else: `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" phase record "<batch-dir>"
"<phase-json-file>"` — this appends the ledger entry without moving the plan file, capturing
telemetry automatically; print `❌ red` with each trimmed error as `   └ ` lines and **stop**, don't
move on.

**Stop rule**, before the next phase in the same session: (a) verification red or skipped, (b) a
planned change omitted, (c) an unnamed new dependency/script — mechanics in
`${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Stop Rule**. Any firing → ask once before
continuing; none → continue as today, no question.

## Step 9 — Commit & Push (on green, every phase)

Automatically, right after **Implementation**'s `git add`, even if more phases follow — never
collected until batch end or a `/clear`. The branch already exists (**Batch Briefing** created it
or checked an existing one out) — one call: `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" phase commit
"<batch-dir>" "<phase-json-file>" "<message-file>"` — cold-path detail: read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Commit Result Rendering** section on first use each session and apply it here.

## Step 10 — Context Check After Every Phase

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" ctx`, now returning `OK` / `WARN` / `STOP`.
`policy.onePhasePerSession` (**Batch Selection**'s preflight, no new call) `true` → treat exactly
like `STOP` below, regardless of the context gate's own verdict; `false` → the context gate alone
decides. In orchestrator mode this step's own in-session check never runs — the orchestrator's
equivalent capacity check lives in `${CLAUDE_PLUGIN_ROOT}/references/orchestrator.md` step 1
instead, acting on `STOP` as well as `WARN` there. `onePhasePerSession` still has no effect on the
orchestrator loop; that part is unchanged.

- `STOP` → print `POSTCHECKS` (this closes `IMPLEMENTATION`), sync telemetry and release the lock
  (`bin/cfq telemetry sync "<repo-root>"`, `bin/cfq lock release "<repo-root>"`), printing
  `Telemetry`/`Lock`, then end — the follow-up session acquires the lock fresh, a half-finished
  batch must not stay locked. Print the `HANDOFF · implement-for-queue` short format from
  **Closing Reports**.
- `OK` → next phase, same batch.
- `WARN` → do not end, do not advance silently — cold-path detail: read
  `${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Context Gate Reason Semantics** section on first use each session and apply it here.

## Step 11 — Batch Done

No open `NN-*.md` left → print the `POSTCHECKS` header (this closes `IMPLEMENTATION`), then run
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" finish "<repo-root>" "<batch-dir>" "<branch>"` — cold-path detail:
read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-end.md`'s **Batch-Done Report Fields** section on first use each session and apply it here. Hand the batch to **Closing Reports** for the closing
report.

## Step 12 — Closing Reports

One format, two lengths, both end the session, both a label/value list under the `Output Format`
padding rule — `RESULT · implement-for-queue` (full) or `HANDOFF · implement-for-queue` (short) —
cold-path detail: read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-end.md`'s **Closing Report Fields** section on first use each session and apply it here.
