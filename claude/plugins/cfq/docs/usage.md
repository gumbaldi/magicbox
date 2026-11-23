# Usage

What each skill does and produces, and the settings that shape it. See
[configuration.md](configuration.md) for what every setting actually does, and each skill's own
`SKILL.md` for its exact steps.

## Plan a batch — `/pfq`

Interviews you at one of three depths (quick, thorough grilling, or grilling with a written
`CONTEXT.md`/ADR trail), reads the code — delegating multi-file or unclear-scope research to
Explore subagents — and parks phased plan files under the repo-local queue. Never edits code,
builds, or commits, even when a plan-mode approval or an autonomous/auto-run mode would otherwise
let it. Overlapping open batches get an automatic `.dependsOn`; any fixable security or maintenance
finding becomes a `plan/` entry for a later session, never a question.

### Reviewing and editing the plan

Before a batch is released, `/pfq` asks whether to release it, request changes, edit the files
yourself, or discard it. The release question carries a compact gate in its own text: the phase list
and one link to the batch directory. The full digest — the batch context and, per phase, its
context, affected files, change steps and verification command — stays one command away. The batch
stays held until you answer.

The plan lives at `<repo>/.claude/cfq/impl/<batch>/NN-<slug>.md` plus `.batch-context.md`, plain
Markdown; the same plan is readable in the report portal. You may edit these files by hand, at the
gate and afterwards, until `/ifq` starts the phase; `/ifq` lints the batch again at its start.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" brief "<batch-dir>" --review         # print the full plan digest
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" brief "<batch-dir>" --review --gate  # print the compact gate
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" lint "<batch-dir>"             # check your edits
```

A review that was never answered keeps the batch held, with no time limit; the next `/pfq`
offers to resume it, and `bin/cfq batch ready "<batch-dir>"` releases it without a review.

### Waiting for the post-write audit

After the plan files are written, `/pfq` starts an audit in the background and writes an `.audit`
marker into the batch (`bin/cfq batch audit <batch-dir> start`). While the marker exists, `batch review` and
`batch ready` refuse, `/ifq` never offers the batch, and `/pfq` ends its turn with a `⏳ Phase Audit`
line instead of looking finished. When the audit result arrives, `/pfq` removes the marker
(`bin/cfq batch audit <batch-dir> done`) and goes on to the review gate. The duration and finding count land in
`report.json` under `audit`. `auditBarrier: false` writes no marker.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" batch audit "<batch-dir>" start   # hold the batch
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" batch audit "<batch-dir>" done    # release it again
```

### Choosing a model per phase

A phase may carry an optional `## Model` heading, followed by a model name on the next non-empty
line. The planner sets it, and only with a name from `implModels`: a model that may not implement
may not be planned. A phase without the heading runs on the default model, the first entry of
`implModels`. `bin/cfq lint` checks the name.

Configurable (see [configuration.md](configuration.md#settings-reference)): `planModels`,
`planExploreModel`, `planExploreModelComplex`, `allowAnyModel`, `grillMode`,
`useMattpocockGrilling`, `usePonytailAudit`, `planBlockedPlugins`.

Handoff: `/clear` → `/model <an implModels entry>` → `/ifq`.

Exact steps: [`skills/plan-for-queue/SKILL.md`](../skills/plan-for-queue/SKILL.md).

## Implement a batch — `/ifq`

Works off one batch from the current repo's queue, phase by phase, committing and pushing every
green phase. Gates hard on the running model — `implModels`, or `orchestratorModels` when
orchestrator mode is on (falls back to `implModels` when empty) — the one check in cfq that aborts
rather than warns. Shows the batch overview and the full queue and asks — start or cancel, plus
pick a different batch when another one is selectable — before touching anything. The overview
shows the full batch context, and each phase announcement and the review digest open with the phase's plain-words Summary, followed by its change steps. By default
(`orchestratorMode`) each phase runs in its own worker sub-agent with a fresh context window
instead of the classic single-session loop, shifting the handoff point from the context-capacity
gate to the rate-limit window. Never two batches in the same session, even once the first finishes
early.

A repository that must change a file with every commit, such as a build version, sets
`phaseCommitCommand`: `phase commit` runs that command before every phase commit, and a non-zero
exit turns the phase red (see [configuration.md](configuration.md#settings-reference)).

```bash
/ifq                 # ask which batch, then the start gate before touching anything
/ifq resume           # continue the in-progress batch; skips the start gate
/ifq start             # take the in-progress batch, or the next one in order; skips the start gate
/ifq start <batch>    # same as `start`, naming which batch
/ifq skip <NN> [reason]  # skip phase <NN> of the batch, then carry on
/ifq unskip <NN>      # bring a skipped phase back
```

Configurable (see [configuration.md](configuration.md#settings-reference)): `implModels`,
`allowAnyModel`, `orchestratorMode`, `orchestratorModels`, `implExploreModel`,
`implExploreModelComplex`, `batchReview`, `batchReviewFindings`, `stopUsed`, `stopFiveHourPct`, `stopSevenDayPct`,
`onePhasePerSession`, `branchPerBatch`, `changelogFile`, `implBlockedPlugins`, `maintenanceEvery`.

The classic-mode phase announcement (`bin/cfq brief --phase`) refuses to run while orchestrator
mode is on (`MODE_MISMATCH`, exit 2) — the documented spawn-failure fallback in
[`references/orchestrator.md`](../references/orchestrator.md) passes `--classic-fallback` to
override it; turning orchestrator mode off — per repo, globally, or for one shell — is the way to
implement every phase in the session itself outside that fallback:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings set --repo "$(git rev-parse --show-toplevel)" orchestratorMode false
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings set orchestratorMode false
CFQ_ORCHESTRATOR_MODE=0   # one shell session
```

Exact steps: [`skills/implement-for-queue/SKILL.md`](../skills/implement-for-queue/SKILL.md)
(classic mode) and [`references/orchestrator.md`](../references/orchestrator.md) (orchestrator
mode, the default).

### Escalation and the batch review

`⚠️ Escalation` appears when a worker judged its phase harder than planned and handed it to the
next stronger model from `implModels`. That model continues on the working tree with a handover
note; no question is asked. A phase is escalated once per session, and a worker that cannot
escalate further asks you instead. A phase that failed on a smaller model than the default is
retried on the default model on the next `/ifq` run.

With `batchReview` set, a `Review` line closes the batch after its last phase is green and a
`/code-review` has run over the whole batch. It has three outcomes:

- `✅ Review  low · no findings` — nothing found.
- `✅ Review  low · 3 findings · 2 fixed · 1 parked` — small findings were fixed in one commit,
  the rest went to a `plan/` entry, as `batchReviewFindings` decides.
- `➖ Review  skipped · <reason>` — the review did not run (context too full, no base branch to
  diff against, or `code-review` not available) and the batch finishes anyway.

### Phase states and skipping a phase

Every batch carries a `status.json` that records the state of each phase. The batch directory
mirrors it: `done` phase files lie in `done/`, `skipped` ones in `skipped/`, `open` and `error` ones
in the batch directory itself. If the two ever disagree, `status.json` wins.

| State | Meaning | For the next `/ifq` |
|---|---|---|
| `open` | not implemented yet | the lowest-numbered `open` or `error` phase is the next one |
| `done` | implemented, committed and pushed | settled, never offered again |
| `error` | the last attempt ended red | retried; it blocks the batch like an open phase until it passes or you skip it |
| `skipped` | you decided not to implement it | settled, never offered, the batch moves past it |

A skip is only ever your decision, never the model's. It works on an `open` or `error` phase, never
on a `done` one, and the reason is optional:

```bash
/ifq skip 04 obsolete after the API change   # skip phase 04, then carry on with the next one
/ifq unskip 04                               # restore it to what it was before (open or error)
```

An informal request in the middle of a session ("skip phase 04") does the same. When the next phase
is an `error` one, the start gate also offers **Skip this phase**. After a skip the session goes on
normally with the briefing, the start gate and the next phase; a skip alone does not start a batch.

A batch whose remaining phases are all `done` or `skipped` finishes normally and unblocks the
batches that depend on it. At the finish, `/ifq` writes one `plan/` inbox entry per skipped phase,
carrying your reason and the plan text, so the work is not lost. The skip is also a ledger entry in
`report.json`, so the report, the portal and the changelog show it; the batch outcome ignores it
and the skipped phases are reported as their own count.

## Dashboard, queue and settings — `/cfq`

First-time setup (see [setup.md](setup.md)), the cross-repo dashboard — a `QUEUES` overview across
every registered repo, a `THIS REPO` phase table, and a `CONFIG` block for the repo `/cfq` runs
in — management of the current repo's `todo/` leftovers, and reading or changing settings.

Configurable: none of its own — it's the interface to every setting listed under the other three
skills; see [configuration.md](configuration.md).

Exact steps: [`skills/code-for-queue/SKILL.md`](../skills/code-for-queue/SKILL.md).

## Reports

The report portal lives at `<repo>/.claude/cfq/reports/index.html` and shows every batch with its
phases, deviations, flags and cost; the README's [Report portal](../README.md#report-portal)
section describes each view. The overview opens with **Now** (running batches and their current
phase), **Needs attention** (warnings and batches waiting on a review or the audit) and the **Last 10
batches**, planning and implementation side by side; the **Trends** tab holds the cost and size
charts. A batch page opens with a result band and one card each for planning and implementation;
its **Cost** tab splits tokens by planning and implementation, then by model, agent and phase, and
marks a phase whose cost is far above the rolling baseline of its size with an info note. Times
show calendar time and, where measured, active time. `/ifq` prints the link of the finished batch at its end, and `/cfq`
names the portal path under `view reports`. Open batches, their unfinished phases and open inbox
entries carry "Open folder" and "Copy path" controls, so a plan can be edited before `/ifq`
picks it up.

Configurable (see [configuration.md](configuration.md#settings-reference)): `htmlReport`,
`reportDir`, `editor`, `hostPlatform`, `wslDistro`.

## See also

- [setup.md](setup.md) — installation and first-time setup
- [configuration.md](configuration.md) — the full settings reference
