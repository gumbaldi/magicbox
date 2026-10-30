---
name: code-for-queue
description: Show CFQ queues and reports, manage queued work, or change CFQ settings. Use for cfq, queue status, and cfq settings.
---

# CFQ dashboard

Reply in the user's language. `CFQ` below is notation for the absolute `bin/cfq` in this plugin root; find the root by going three directories above this `SKILL.md`. Put that absolute path directly in each shell call so the hook can bind the session. Use the same root for the other Codex CFQ skills.

Run `CFQ dash` once. Read its JSON for all repositories and the current repository. Show the open batches, next phase, dependencies and report portal path. Do not run `dash render`: its prose is tailored to the other harness. A queue lives at `<repo>/.claude/cfq/` for both harnesses.

For a requested setting, use `CFQ settings describe <key>` and `CFQ settings get <key>`. Change it with `CFQ settings set [--repo <repo>] <key> <value>` or `unset`, then read it back. The `codex*` model settings govern Codex; unprefixed model settings govern the other harness. Repository language, queue and workflow settings are shared.

For queue changes, show the target and effect first. Use the matching `CFQ` subcommand for priority, dependencies, archive, delete or note sweep. Never mutate the queue with direct shell file operations. Report exactly what changed. Ask before deleting or archiving a batch.

For a first run, check `CFQ doctor` and `CFQ settings list`; configure the desired Codex model order with `codexPlanModels`, `codexImplModels`, and `codexOrchestratorModels` as needed. Empty Codex model lists use the running model. No Claude setup wizard or Claude plugin dependencies are required.
