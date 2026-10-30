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

Model lists are separate: `codexPlanModels`, `codexImplModels`, and `codexOrchestratorModels`.
`codexImplModels` is ordered from cheaper to stronger for escalation. Empty lists fall back to
the running model. Repository language, branch, queue and workflow settings are shared. A
Claude-only `## Model` phase hint is ignored by Codex workers.

Optional explorer overrides are `codexPlanExploreModel`, `codexPlanExploreModelComplex`,
`codexImplExploreModel`, and `codexImplExploreModelComplex`; empty values also use the running
model.

The CLI works in Codex desktop and Codex CLI when the plugin is enabled and its hooks are active.
The report portal stays at `<repo>/.claude/cfq/reports/index.html`.
