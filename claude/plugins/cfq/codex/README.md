# CFQ in Codex

## Install

From the Magicbox checkout, run `codex plugin marketplace add ./` and
`codex plugin add cfq@magicbox`, or install `cfq` from the Magicbox source in the ChatGPT desktop
Plugins Directory and restart the app. Enable the plugin for a trusted repo if needed with:

```toml
[plugins."cfq@magicbox"]
enabled = true
```

Codex must trust the plugin's local hooks. The `PreToolUse` hook supplies the current session ID,
transcript path and model to each `bin/cfq` invocation without adding prompt text. Lock acquisition
refuses an unbound session; if it reports `RUNTIME_UNBOUND`, check plugin enablement and hook trust.
The `SubagentStop` hook refreshes worker usage in the shared ledger after the worker exits.

Use `code-for-queue` for the dashboard, `plan-for-queue` to park plans, and
`implement-for-queue` to execute one batch. The same files under `<repo>/.claude/cfq/` are read by
Claude Code. A batch may be planned in one harness and implemented in the other. The lock allows
only one implementation session in a repo at a time; handoff occurs between phases or sessions.

Codex skills and hooks live under `codex/`. Claude Code's `skills/`, `references/` and `hooks/`
are not loaded by the Codex compatibility manifest. Both hosts execute the same `bin/cfq` CLI,
and the neutral `<plugin-root>/references/phase-template.md` is the only shared instructional template.

Codex defaults are `codexPlanModels: [gpt-6.1-sol]` with `codexPlanEffort: high`,
`codexOrchestratorModels: [gpt-6.1-sol]` with `codexOrchestratorEffort: medium`, and
`codexImplModels: [gpt-6-luna]` with `codexWorkerEffort: xhigh`. The explorer uses
`codexExplorerEffort: high`. The four model overrides `codexPlanExploreModel`,
`codexPlanExploreModelComplex`, `codexImplExploreModel`, and `codexImplExploreModelComplex`
all default to `gpt-6-luna`. `codexImplModels` is ordered from cheaper to stronger for optional
escalation. An explicitly empty Codex model list falls back to the running model.

CFQ checks the expected model and effort of a planner or orchestrator session. Codex chooses
those main-session values before the skill starts; a skill cannot switch them. The Codex skills
pass the worker and explorer model and effort explicitly when spawning those subagents. Repository
language, branch, queue and workflow settings are shared. A Claude `## Model` phase hint is
removed from the Codex worker's phase view.

The CLI works in Codex desktop and Codex CLI when the plugin is enabled and its hooks are active.
The report portal stays at `<repo>/.claude/cfq/reports/index.html`.
