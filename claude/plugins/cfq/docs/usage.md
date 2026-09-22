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

Configurable (see [configuration.md](configuration.md#settings-reference)): `planModels`,
`planExploreModel`, `planExploreModelComplex`, `allowAnyModel`, `grillMode`,
`useMattpocockGrilling`, `usePonytailAudit`, `planBlockedPlugins`.

Handoff: `/clear` → `/model <an implModels entry>` → `/ifq`.

Exact steps: [`skills/plan-for-queue/SKILL.md`](../skills/plan-for-queue/SKILL.md).

## Implement a batch — `/ifq`

Works off one batch from the current repo's queue, phase by phase, committing and pushing every
green phase. Gates hard on the running model — `implModels`, or `orchestratorModels` when
orchestrator mode is on (falls back to `implModels` when empty) — the one check in cfq that aborts
rather than warns. Shows the batch overview and the full queue and asks — start, pick a different
batch, or cancel — before touching anything. By default
(`orchestratorMode`) each phase runs in its own worker sub-agent with a fresh context window
instead of the classic single-session loop, shifting the handoff point from the context-capacity
gate to the rate-limit window. Never two batches in the same session, even once the first finishes
early.

Configurable (see [configuration.md](configuration.md#settings-reference)): `implModels`,
`allowAnyModel`, `orchestratorMode`, `orchestratorModels`, `implExploreModel`,
`implExploreModelComplex`, `stopUsed`, `stopFiveHourPct`, `stopSevenDayPct`,
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

## Dashboard, queue and settings — `/cfq`

First-time setup (see [setup.md](setup.md)), the cross-repo dashboard — a `QUEUES` overview across
every registered repo, a `THIS REPO` phase table, and a `CONFIG` block for the repo `/cfq` runs
in — management of the current repo's `todo/` leftovers, and reading or changing settings.

Configurable: none of its own — it's the interface to every setting listed under the other three
skills; see [configuration.md](configuration.md).

Exact steps: [`skills/code-for-queue/SKILL.md`](../skills/code-for-queue/SKILL.md).

## Reports — `/rfq`

Read-only: surfaces what `/ifq` already did — a compact terminal table across all repos, or the
detailed HTML report for one batch (which phases went green or red, where the implementation
departed from the plan, what broke, telemetry). Never writes anything.

Configurable (see [configuration.md](configuration.md#settings-reference)): `htmlReport`,
`reportDir`.

Exact steps: [`skills/report-for-queue/SKILL.md`](../skills/report-for-queue/SKILL.md).

## See also

- [setup.md](setup.md) — installation and first-time setup
- [configuration.md](configuration.md) — the full settings reference
