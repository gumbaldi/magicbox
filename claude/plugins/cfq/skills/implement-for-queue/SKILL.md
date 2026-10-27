---
name: implement-for-queue
description: >
  Work off parked phase plans from the repo-local queue (`.claude/cfq/` in the repository) one
  batch per session, phase by phase, stopping when the context window gets too full. Use for
  "/ifq", "/implement-for-queue", "implement the queue", "work off the plans", "continue with
  the plans", "next phase".
argument-hint: <batch or phase>
---

# Implement-for-Queue: Work Off a Batch Phase by Phase

Always answer in the user's language. A finding about cfq itself — during this session or in a
follow-up conversation after it — is parked with `bin/cfq note plan --framework` per
`${CLAUDE_PLUGIN_ROOT}/references/queue-entries.md`'s **Plan Entry**, never sent through `SendFeedback`.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Section Map

| Section | Steps | Contents |
|---|---|---|
| PRECHECKS | 1-4 | Preflight, Model Gate, Batch, Start Gate, Lock, Branch, Resume |
| IMPLEMENTATION | 5 | per phase, in the mode's own file: announcement, result, Commit |
| POSTCHECKS | 5-7 | Context Check, Telemetry, Lock, Batch Done |

## Step 1 — Arguments

Text passed with the invocation narrows batch selection in **Batch Selection** — it never replaces
the briefing. Arguments were passed → read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s
**Arguments**: `resume`, `start` (`start <batch>` included), `skip <NN> [reason]` and `unskip <NN>`
are keywords, not a selection hint. Skipping a phase — only ever on the user's
request — is in `${CLAUDE_PLUGIN_ROOT}/references/ifq-phase.md`'s **Skipping a Phase**.

## Step 2 — Plan-Mode Gate

Before **Batch Selection**: a "Plan mode is active" reminder is present in context → call
`ExitPlanMode` now, naming what this session is about to write.

## Step 3 — Preflight: Policy, Batch Selection

Print the `PRECHECKS` header, then one call:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-impl "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```
`status: "NO_REPO"` → abort, report, end. Otherwise, print `inbox.overview` verbatim right here —
always, before Model Gate, the start gate or any lock, read-only, no import, no question, even when
no batch ends up selectable. This one call already resolved the model gate, plugin boundaries and
batch selection together — read its fields below, no further calls needed for those three steps.
**Model Gate**: print as returned. `policy.allowAnyModel: true` → no check. Otherwise the running
model's name (system prompt, environment block) must substring-match an entry of
`policy.implModels` — of `policy.orchestratorModels` when `policy.orchestratorMode` is `true`. No
match → stop immediately, touching nothing; a model-gate mismatch → read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Model Gate Stop** for the stop wording.

**Plugin Boundaries.** `policy.implBlockedPlugins` — those plugins/skills aren't called for the
rest of the session, not even indirectly — per-phase skill recommendations on this list are
ignored. Print `Plugin Boundaries` as returned (the preflight's own line).

**Required Tools.** Print the `Required Tools` line as returned when present; `requiredTools.missing` non-empty → stop immediately, touching nothing.

**Batch Selection.** `status` already reflects the filtered outcome — `NO_BATCH` → report "No open plans for this repo in the queue.", end. `status` is `OK` → print `Batch`, the preflight's own `statusLines` entry exactly as returned. Any other `status` → read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Batch Selection Rules**, which words every such outcome.

## Step 4 — Batch Briefing and Start

Nothing is touched, no lock taken, until the briefing has been shown — never read
phase files in full here, that's **Implementation**'s job. `contextGate.verdict` is `WARN` or
`batch.consistency == "divergent"` at the briefing → read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Briefing Warnings**.

### Batch Briefing

`bin/cfq brief <batch-dir> --overview` renders the batch overview the start gate shows — the
aligned-monospace batch-overview block: header, phase count with done/red breakdown, the labelled,
untruncated `.batch-context.md` block (`Goal`, `Decisions`, `Invariants`, `Cross-Phase Contracts`,
`Non-Goals`, each only when present), then the phase table with a `done`/`open`/`red` status
column, each row followed by that phase's own `## Context` excerpt and a `→ <file>` pointer
(`done/<file>` for a finished phase), a closing `Plans` line naming the batch directory so a hand
edit knows exactly where to reach in, and a `Portal` line when the report portal is on. A phase
file without `## Size` counts as `M`; one without `## Context` shows its title alone — an
incomplete plan is worth showing, not worth aborting over.

### Start Gate

Fires before the lock — a declined batch must leave nothing to release, not even a lock. What is
printed, in order: the briefing warnings **Briefing Warnings** already defines, then `bin/cfq
brief "<batch-dir>" --overview` (the aligned-monospace batch-overview block from **Batch
Briefing**), then `selection.queueText` (already resolved by the preflight, no new call), each
rendered exactly as returned — no rewording, nothing between them but a blank line.

**The question** may take a second call, because `AskUserQuestion` caps at four options and a repo
may hold more than two other open batches — but only when another batch is actually selectable:

- Other selectable batches = entries of `selection.selectable` other than the batch just briefed
  (the same set the second call below offers).
- At least one other selectable batch → first call, three options: **Start** (recommended, listed
  first) — proceed to **Lock Acquisition** for the batch just briefed; **Pick a different batch** —
  opens the second call below; **Cancel** — end the session, nothing touched, no lock taken, no
  branch checked out. Print `Start Gate` as `➖ cancelled by user` and stop.
- None → first call has only two options: **Start** (recommended, listed first), same effect as
  above, and **Cancel**, same effect as above. No middle option, no second call possible; the
  question text says the batch is ready and asks whether to start it — it does not mention picking
  another batch.
- Second call, only when the user picked the middle option (so only reachable in the
  at-least-one-other case): one option per entry in
  `selection.selectable` other than the batch already briefed, each labelled with its number and
  slug and described with its `open` (phase count) and `goal`. Blocked and planning batches are
  **not** offered — they are already visible in `queueText` with their own reason and stay
  non-selectable. More than four such entries → offer the first three, in the same
  flagged-first-then-name order `selectable` already carries, and say in the question text that
  the rest are in the listing above and reachable by typing the number as free text. A free-text
  answer naming a batch that is not in `selection.selectable` is reported against `queueText`'s
  own reason for that batch and the question is asked once more; a second miss ends the session
  without touching anything, mirroring `${CLAUDE_PLUGIN_ROOT}/references/ifq-branch.md`'s **Branch and Changelog on Go-Ahead** free-text
  resolution for the base-branch question — point at that paragraph, don't repeat it.
- `startGate.offerSkip` is `true` → the first call gains a further option, **Skip this phase**,
  placed after **Start**: it asks nothing more, runs `bin/cfq phase skip "<batch-dir>" <NN>
  --reason "skipped at start gate after failed attempt"` for `nextPhase`, prints the returned status
  line, re-runs the preflight with `--select <batch>` and continues with the next phase without
  asking the gate again. The option exists only when the next phase is `error`; with `resume` or
  `start` the gate does not fire and the phase is retried.
- On a different batch being chosen, re-run `bin/cfq preflight-impl "<repo-root>" --select
  <batch>` and continue from **Batch Briefing** with the new result — the gate does not fire a
  second time for the freshly chosen batch, because choosing it *was* the confirmation.

**When it fires**: `startGate.fire` is `true` — already resolved by the preflight from `--intent`
and whether a batch is in progress (**Arguments** above). Without either keyword this is always
`true`, with no exception — a resumed in-progress batch, a batch named
explicitly as an argument, and orchestrator mode are all still included. `--intent resume` also
comes back `true` (reason `resume-nothing-in-progress`) when nothing is in progress — `resume`
never starts something new silently, it falls back to the normal gate instead.

**When it does not fire**: `startGate.fire` is `false` — `--intent start` always, or `--intent
resume` with a batch already in progress. Print the preflight's own `Start Gate` status line (in
`statusLines`, already worded `skipped · resume · <batch>` / `skipped · start · <batch>`) and go
straight to **Lock Acquisition** — the briefing warnings and the batch overview above are still
printed either way, so the user sees what is starting even without being asked.

**The one case it does not fire regardless of `--intent`**: `selection.selectable` is empty and
there is no in-progress batch, i.e. the session is already ending via
`NO_BATCH`/`BLOCKED`/`MULTIPLE_IN_PROGRESS`. Those paths end before a batch is ever resolved
(`startGate: null`), so there is nothing left to confirm.

Print `Start Gate` either way: `✅ confirmed · <batch>` (Start chosen), `✅ switched to <batch>`
(a different batch chosen on the second call), `➖ cancelled by user` (Cancel, or a second
free-text miss on the second call) — or, when `startGate.fire` was `false`, the preflight's own
line from `statusLines`, printed exactly as returned rather than composed here.

`lint.clean` is `false` → print `Lint` with its findings and end, nothing touched — read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-start.md`'s **Lint Gate**.

Acquire the repo lock (`bin/cfq lock acquire "<repo-root>" "<batch>"`).

### Lock Acquisition

Exit ≠ 0 (`LOCKED`) → **end immediately**, touch nothing, name holder/batch/time, note the
30-minute stale takeover; `TAKEOVER` → proceed, `Lock` carries that warning; else `Lock` is just
acquired.

### Branch

`branch.mode` (from the preflight — already computed, no new call) is `off` → print `Branch` as
`➖ branchPerBatch off`, nothing else. `branch.mode` is anything other than `off` → read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-branch.md`: full behavior (`continue`/`new`, base-branch
question, checkout, changelog init, changelog commit, post-checkout reconfirm) based on `origin`'s
current state. `Branch` renders whichever happened.

### Resume Snapshot

`bin/cfq preflight-impl`'s `resume` field carries what `bin/cfq resume` itself returns for the
resolved batch, minus its own `branch` sub-object (redundant with the preflight's top-level
`branch`, computed by that same underlying call — see the `resume` noun's own script header
comment for the full, still-current field-by-field contract: `phasesOpen`/`phasesDone`, `lastCommit`/
`lastCommitSource`, `deviations`, `redPhases`, `batchContext.exists`/`.path`). One JSON object,
deterministic — no summarization, only facts read from disk, `report.json`, and git.

`resume` (same preflight result) already carries done/open phases, last commit, deviations,
red-phase history, `.batch-context.md`'s path — no new `bin/cfq resume` call; if
`resume.batchContext.exists`, `Read` it now. Print `Resume` — phases done/open, `.batch-context.md`
present or not.

## Step 5 — Mode Switch

`policy.orchestratorMode` is `true` → read `${CLAUDE_PLUGIN_ROOT}/references/orchestrator.md` and
follow it; `false` → read `${CLAUDE_PLUGIN_ROOT}/references/ifq-classic.md` and follow it. `POSTCHECKS`
opens only on a `STOP`, a red phase, or a finished batch.

## Step 6 — Batch Done

The batch has no open phase left (`nextPhase: null`) → print the `POSTCHECKS` header (this closes
`IMPLEMENTATION`). `policy.batchReview` is `off` → print `➖ Review  off`; anything else → read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-review.md` and follow it. Then run
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" finish "<repo-root>" "<batch-dir>" "<branch>"` and read
`${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-end.md`'s **Batch-Done Report Fields**. Hand the batch to
**Closing Reports** for the closing report.

## Step 7 — Closing Reports

One format, two lengths, both end the session, both a label/value list under the `Output Format`
padding rule — `RESULT · implement-for-queue` (full) or `HANDOFF · implement-for-queue` (short).
**Short format** — `HANDOFF · implement-for-queue` header, three to four lines: phases done, phases
open, the `USED` value, `/clear` → `/ifq`. No cost breakdown, no merge hint. The batch has no open
phase left → read `${CLAUDE_PLUGIN_ROOT}/references/ifq-batch-end.md`'s **Closing Report Fields** for
the full format. The closing report names no push or merge state beyond the `Branch` line.
