# ifq: Per-Phase Mechanics

## Phase Announcement

Runs after the Size Gate, before any code is written, every phase. The announcement is
`bin/cfq brief "<batch-dir>" --phase <NN>`'s output, rendered as returned, no rewording —
deterministic, extracted from the phase file, so it cannot drift in wording between phases. This
is the classic-mode announcement specifically: the call refuses (`MODE_MISMATCH`, exit 2) while
`orchestratorMode` is on for the repo, since that mode's own phase announcement goes through
`bin/cfq worker brief` instead — see `<plugin-root>/references/orchestrator.md` section 6 for the
one documented `--classic-fallback` override.

```
PHASE 02 · ifq-per-phase-go-gate · Size L
  Goal     <first two non-empty lines of ## Context>
  Files    bin/cfq, implement-for-queue/SKILL.md, ifq-phase.md, test-settings.sh
  Check    <first command line from ## Verification>
```

Implementation starts right after — there is no per-phase go-ahead beyond this announcement. What
still stops a session: the Size Gate's `HANDOFF` verdict (before this step runs), `stopUsed` after
the phase (the Context Check), and `onePhasePerSession` ending the session after exactly one phase
regardless. The `WARN` variant below is the one case that still asks before proceeding.

**`WARN` variant.** When `contextGate.verdict` is `WARN`, one warning line precedes the
announcement, naming the reason and the concrete numbers from `contextGate.note` in the user's
language — e.g.:

```
⚠️ Five-hour budget at 89% (threshold 70%) — this is a warning, not a blocker; the phase runs
normally if you start it.

PHASE 02 · ifq-per-phase-go-gate · Size L
  Goal     <first two non-empty lines of ## Context>
  Files    bin/cfq, implement-for-queue/SKILL.md, ifq-phase.md, test-settings.sh
  Check    <first command line from ## Verification>
```

Then one `AskUserQuestion`, three options: **Go** — "proceed, implement this phase now", its
description naming the budget state so the user sees what they are accepting — and **must not**
claim the attempt will fail. **Handoff** — "end the session cleanly instead of implementing",
reusing the Context Check's `STOP` sequence (telemetry sync, lock release, the `HANDOFF ·
implement-for-queue` short report). **Cancel** — "release the lock and end the session, nothing
touched", runs `bin/cfq lock release "<repo-root>"`, reports "cancelled before implementation,
nothing touched", and ends; it never leaves the lock held. No option may be phrased as futile —
every option offered here must actually do what it says. This same warning line is reused verbatim
at the Batch Briefing step, above the batch briefing — one wording, two call sites, never two
drifting variants.

## Context Gate Reason Semantics

`stopUsed: 0` is deliberate, not a misconfiguration — `STOP` fires after every phase for the
capacity reason, one context window each. A rate limit produces a `WARN`, which never overrides a
capacity `STOP` and never ends a session on its own — a rate-limit stop never wins over the
`stopUsed: 0` bypass. `stopUsed: -1` is equally deliberate — `STOP` never fires **for the capacity
reason**; the rate-limit reason has its own switches. `stopFiveHourPct: -1` and `stopSevenDayPct:
-1` are each just as deliberate — warns for nothing for that reason either; a payload without
`rate_limits` (API-level billing) means the check simply doesn't apply. `onePhasePerSession: true`
(the default) means every session implements exactly one phase after the batch starts — it
outranks `WARN`: with one-phase-per-session on, the session ends after a phase either way, and the
budget warning changes nothing.

## Phase Summary

Printed after implementation, before the closing `bin/cfq phase commit` (green) or `phase record`
(red) call:

```
PHASE 02 DONE
✅ Implemented     <one clause: what was built>
✅ Verification    <command, and its result>
⚠️ Deviation       <one line per deviation>
```

`Implemented` and `Verification` are the model's own prose — no script can know what actually
happened. `Deviation` repeats, verbatim, whatever goes into that phase's `report.json`
`deviations` entry: one source, two renderings, never worded differently for the two audiences. No
deviations → the `Deviation` line is omitted entirely, not printed empty.

## File-Scope Deviation

Mandatory, every phase, on green — not conditional on suspicion, not skippable when the phase
"obviously" stayed in scope.

The phase's changes aren't committed yet at this point (commits happen in the following Commit &
Push step), so this compares the working tree, never a prior commit. Pipeline: take the changed and
untracked paths from `git status --porcelain` (covers files the phase created, not only modified
ones), resolve them to absolute paths against the repo root, and subtract the phase's `## Affected
Files` entries, extracted the same way `cfq_queue_overlap.py`'s `extract_affected_files` does (a
port of `sed -n '/^## Affected Files/,/^## /p' "<phase-file>" | sed -n 's/^- \`\([^\`]*\)\`.*/\1/p'`).
Ignore anything under `<repo-root>/.claude/cfq/` — the queue's own bookkeeping is not a code
deviation and is git-excluded anyway.

A non-empty difference becomes one `deviations` entry naming the file(s) and why they had to be
touched — plan said X, the change also required Y, because Z. This is the same `deviations` array
already passed to `bin/cfq phase commit` — no new field, no new call. An empty array is correct
only when the comparison actually came back empty; omitting a difference the comparison found is a
defect, not brevity.

Nothing new is shown: `## Phase Summary`'s existing `⚠️ Deviation` line already repeats the
`report.json` entry verbatim, one source and two renderings — no second rendering here.

This does not stop the session, does not ask, and does not block the commit. If the deviation
reveals that the plan itself was wrong rather than merely incomplete, that's scope creep and goes
through the existing parking question (`plan/<YYYY-MM-DD>-<slug>.md`), unchanged.

## Stop Rule

A gate, not a status line — checked after a phase goes green, before auto-advancing to the next
open phase in the same session. Exactly three triggers, nothing else:

- (a) verification came back red, or was not run
- (b) a change the plan specifies was deliberately left out
- (c) a new dependency or a new script was introduced that the plan does not name

Any of the three firing → do not auto-advance; state which trigger fired and ask once
(`AskUserQuestion`) whether to continue anyway. None firing → continue as today, no question.
Everything that is not one of the three is a note in the report, never a stop — do not add a fourth
trigger by interpretation.

## Phase Commit Trailers

Write the human-written subject/body (plus `Co-Authored-By`, as before) to a temp message file and
hand it, unmodified, to `bin/cfq phase commit "<batch-dir>" "<phase-json-file>" "<message-file>"` —
the trailers are added internally, the model never calls `changelog commit-message` itself and
never hand-writes or hand-formats a `CFQ-*` trailer. For a numbered batch (`batchNumber` from the
Batch Briefing/Resume Snapshot data is non-null) `phase commit` appends `CFQ-Batch-Number`,
`CFQ-Batch`, `CFQ-Phase`, `CFQ-Phase-Status` to the existing trailer block via `git
interpret-trailers`, leaving the human-written subject/body untouched. A legacy (unnumbered) batch
passes the message through unchanged — never invent a `CFQ-Batch-Number` for one.

The phase JSON's `phase` field is the full phase slug — the same value that ends up in the trailer,
in the `report.json` entry, and in `bin/cfq report last-failure`'s lookup — one identifier
everywhere, never the bare number.

## Research and Verification Delegation

In orchestrator mode both delegations below happen inside the spawned `cfq-phase-worker`, on the
same rules — not dropped, just relocated; see `<plugin-root>/agents/cfq-phase-worker.md`.

Two, and only two, places in phase implementation may run on an Explore subagent instead of the
implementing session's own model — never a blanket "delegate whatever seems slow". Model choice is
a rule, not a mood — cheap model to locate, expensive to judge; read
`<plugin-root>/references/explore-escalation.md` and follow it. Both keys
(`implExploreModel`/`.implExploreModelComplex`) come from the preflight's `policy` object, no
`bin/cfq settings get` call here:

- **Pre-implementation research.** Before writing any code, a phase that touches several files or
  whose scope isn't fully clear from the phase file alone may send an Explore subagent to locate
  the relevant code, existing patterns, and callers, and return a distilled summary. This mirrors
  `plan-for-queue`'s own research step exactly — same reasoning, same escalation rule. A narrow,
  single-file phase needs no subagent; reading the phase file is enough.
- **Verification output filtering, green case only.** Running the phase's verification command
  (tests, build, lint) can itself be delegated to an `implExploreModel` subagent when the raw output
  would be long — it runs the command and reports back pass/fail plus which command ran, nothing
  more. This is a locate-shaped task (pass/fail, which command), so it always stays on the cheap
  model even where the pre-implementation research above escalated.

**Never delegate a red result.** The moment verification fails, the subagent (if one was used for
that run) returns the complete, unfiltered failure output — full stack trace, full diff, everything
— because the implementing model needs the whole picture to fix the bug. A red phase is exactly the
case where summarizing loses the detail that matters; this is the one asymmetry in the rule, not an
oversight. If verification wasn't delegated at all, this doesn't apply — the failure is already in
context.

**Never delegate implementation, test writing, or documentation.** Writing or editing any file
under the phase's scope always happens in the implementing session itself — a subagent producing
code the parent must then read back in full to verify or commit is strictly more expensive than the
parent writing it directly. See the plugin `CLAUDE.md`'s "Subagents are for exploration and
mechanical test execution" section for the full reasoning and the measurement anyone changing this
should re-run first.

## Reusing a Warm Explore Agent

Only applies when a second phase runs in the same session, i.e. when `onePhasePerSession` is
`false`. Under the default (`true`) this never applies and nothing below happens.

When the next phase's `## Affected Files` overlaps the files an Explore agent of this session has
already read, continue that agent with `SendMessage` instead of starting a new one — its context
still holds those files. Continue it only if nothing has changed underneath it:

```bash
git diff --name-only <sha-when-the-agent-started>..HEAD
```

If that output intersects the files the agent read, its knowledge is stale — start a fresh agent.
One `git` call decides this; do not reason about what an agent "probably still knows".

This never applies to implementation, test writing or documentation, which stay off subagents
entirely.
