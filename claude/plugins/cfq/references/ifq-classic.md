# ifq: Classic Per-Phase Loop

This is the per-phase loop of a session whose `policy.orchestratorMode` is `false`, and of the
orchestrator's in-session fallback for a single phase. Its steps run after the lock, branch and
resume block of `implement-for-queue/SKILL.md` and end in **Batch Done** there.

Not strictly sequential: a `WARN` at **Context Check After Every Phase** loops back to **Earlier
Failed Attempt** for the next phase instead of opening `POSTCHECKS`.

## Contents

- Earlier Failed Attempt
- Size Gate
- Phase Announcement
- Implementation
- Commit & Push
- Context Check After Every Phase

## Earlier Failed Attempt

Entering this step closes `PRECHECKS` and opens `IMPLEMENTATION`. Before reading the phase file,
two checks — both already resolved by **Batch Selection**'s preflight call for the phase it was run
against; **only re-run the preflight here** (same `--select <batch>`) if
a phase other than the one it resolved is about to start (e.g. the second and later phases of a
batch, since the preflight only ever resolves `nextPhase` for the lowest-numbered `open` or `error`
phase at call time). `nextPhase.status == "error"` is the trigger: `nextPhase.failedAttempt` —
`.found: true` → read its `.note`/`.at`, check whether the cause still holds before repeating, and mention it in the new
entry ("second attempt after …"); `.found: false` → skip silently. Print `Failed Attempt` either
way.

## Size Gate

`contextGate` — deterministic projection, already computed by the
preflight from the phase's `## Size` heading, never prose arithmetic. `contextGate.verdict`, three
branches:

- `START` → **Phase Announcement**, then **Implementation**.
- `WARN` → **Phase Announcement**, same as `START` — the phase is not blocked. Its
  `AskUserQuestion` fires only in this branch; nothing is skipped and nothing ends here.
- `HANDOFF` → no phase ran, hand off cleanly (the **Context Check**) instead.

Print the `Size Gate` status line — read `<plugin-root>/references/ifq-phase.md`'s **Context Gate Reason Semantics**; this closes `PRECHECKS`. In orchestrator mode this step
does not run — every worker starts at zero context, so there is nothing the gate would protect
against.

## Phase Announcement

Print the phase announcement —
`"<plugin-root>/bin/cfq" brief "<batch-dir>" --phase <NN>`, rendered as returned, no
rewording — then go straight to **Implementation**. `contextGate.verdict` was `WARN` is the one
exception — reappears every phase by design, never a repetition bug — one `AskUserQuestion` with
**Go**/**Handoff**/**Cancel**; full option copy and the rendering example are in
`<plugin-root>/references/ifq-phase.md`'s **Phase Announcement**.

## Implementation

Read `nextPhase`'s plan file (path from the preflight) in full — multi-file or unclear-scope phases may delegate
that research to an `implExploreModel` subagent first; implementation itself never runs on one.
Implement it completely, run the plan's verification with output filtered — a green run may
delegate the filtering to the same subagent, a red run never does (full unfiltered failure back
either way), per `<plugin-root>/references/ifq-phase.md`'s **Research and Verification
Delegation**. A phase touching `docs/<codeLanguage>/…` → write the counterparts in every
`docLanguages` entry before it goes green, per `<plugin-root>/references/doc-style.md` or
`<repo>/docs/STYLE.md` if present. Work found beyond this phase's scope is always parked — read `<plugin-root>/references/queue-entries.md`'s **Parking Out-of-Scope Work**.

Write the phase object (`phase`, `status`, `deviations`, on red `errors`) to a temp file — read `<plugin-root>/references/ifq-phase.md`'s **Phase Object Fields**.

Green → `git add` the phase's changes (staging stays with the model — the closing call never runs
`git add` itself), write the commit message (subject/body plus `Co-Authored-By`) to a temp file,
then close the phase via the following **Commit & Push** step's single call. Red → record it now,
before anything else: `"<plugin-root>/bin/cfq" phase record "<batch-dir>"
"<phase-json-file>"` — this appends the ledger entry without moving the plan file, capturing
telemetry automatically; print `❌ red` with each trimmed error as `   └ ` lines and **stop**, don't
move on.

**Stop rule**, before the next phase in the same session: (a) verification red or skipped, (b) a
planned change omitted, (c) an unnamed new dependency/script — mechanics in
`<plugin-root>/references/ifq-phase.md`'s **Stop Rule**. Any firing → ask once before
continuing; none → continue, no question.

## Commit & Push

Automatically, right after **Implementation**'s `git add`, even if more phases follow — never
collected until batch end or a `/clear`. The branch already exists (**Batch Briefing** created it
or checked an existing one out) — one call: `"<plugin-root>/bin/cfq" phase commit
"<batch-dir>" "<phase-json-file>" "<message-file>"` — read
`<plugin-root>/references/ifq-phase.md`'s **Commit Result Rendering**.

## Context Check After Every Phase

Run `"<plugin-root>/bin/cfq" ctx`, which returns `OK` / `WARN` / `STOP`.
`policy.onePhasePerSession` (**Batch Selection**'s preflight, no new call) `true` → treat exactly
like `STOP` below, regardless of the context gate's own verdict; `false` → the context gate alone
decides. In orchestrator mode this step's own in-session check never runs — the orchestrator's
equivalent capacity check lives in `<plugin-root>/references/orchestrator.md` step 1
instead, acting on `STOP` as well as `WARN` there. `onePhasePerSession` has no effect on the
orchestrator loop.

- `STOP` → print `POSTCHECKS` (this closes `IMPLEMENTATION`), sync telemetry and release the lock
  (`bin/cfq telemetry sync "<repo-root>"`, `bin/cfq lock release "<repo-root>" --batch "<batch>"`),
  printing `Telemetry`/`Lock`, then end — the follow-up session acquires the lock fresh, a
  half-finished batch must not stay locked. Print the `HANDOFF · implement-for-queue` short format
  from **Closing Reports**.
- `OK` → next phase, same batch.
- `WARN` → do not end, do not advance silently — read
  `<plugin-root>/references/ifq-phase.md`'s **Context Gate Reason Semantics**.
