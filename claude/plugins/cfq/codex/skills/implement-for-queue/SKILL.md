---
name: implement-for-queue
description: Implement one shared CFQ queue batch phase by phase with Codex workers, verification, commits and handoff. Use for ifq, implement for queue, or continuing a queued plan.
---

# Implement for queue

Reply in the user's language. `CFQ` below is notation for the absolute `bin/cfq` three directories above this `SKILL.md`; put that path directly in each shell call so the hook can bind the session. Work on one batch per parent session. Both harnesses use the same queue under `<repo>/.claude/cfq/` and the same phase status. A different harness may continue at the next open phase in a new session.

## Start

1. Run `CFQ preflight-impl <repo-root>` once (`--intent start`, `--intent resume`, or `--select <batch>` when requested). Stop on `NO_REPO`, `NO_BATCH`, `BLOCKED`, `MULTIPLE_IN_PROGRESS`, missing required tools, or unclean lint. The Codex policy fields already exclude Claude plugin and effort checks. If the current model does not match a nonempty `policy.implModels` or `policy.orchestratorModels`, stop before touching the batch.
2. Print the preflight's inbox overview and status lines. Run `CFQ brief <batch-dir> --overview`, show the selected batch, dependencies, phase statuses and branch. Respect `startGate.fire`: ask the user to start or choose another selectable batch when true, unless the user has already explicitly requested to implement that batch in this conversation. Do not silently change batches.
3. Acquire `CFQ lock acquire <repo-root> <batch-name>`. A `LOCKED` result ends the session. The Codex hook supplies the session identity to `CFQ`; if the hook is disabled, lock acquisition fails closed. Run `CFQ branch plan <repo-root> <batch-name>` for the read-only branch decision. For `off`, keep the current branch; for `continue`, use the existing batch branch; for `new`, inspect the proposed `baseRef` and `uncontained` branches, then use `git switch -c cfq/<batch-name> <baseRef>` and `CFQ changelog init <repo-root> cfq/<batch-name> <base> <batch-name>`. Stop and ask on a dirty, divergent or unsafe branch state. Read `.batch-context.md` and the preflight's resume snapshot before phase edits.

## Phase loop

For each `nextPhase`, call `CFQ worker brief <batch-dir> --phase <NN>`. Show the returned `announcement`. Spawn exactly one Codex `worker` subagent at a time, using the returned `model` when available. Give it only the returned `prompt` and the Codex worker instructions in `<plugin-root>/codex/references/worker.md`; the prompt names `.worker-brief.json`, which the worker reads itself. Do not paste the briefing JSON into the spawn prompt. A model override can require a fresh context; use the available subagent mechanism and report if a requested model cannot be selected.

Pass the worker's JSON report to `CFQ worker verdict <batch-dir>` on stdin. `CONTINUE` starts the next open phase. `ASK` relays the unresolved direction question to the user, then gives the answer to that worker or starts a fresh one with the answer. `ESCALATE` uses `escalation.next` once: write the returned handover object to a temporary file, rerun `worker brief` with `--model-override` and `--handover-file`, and start a stronger worker. `STOP` ends the phase loop and reports the red result. Display the verdict's `statusLines` and the worker's verification, commit and deviations. The worker commits a green phase itself; the parent does not edit its code.

If worker spawning is unavailable, implement that phase in this session using the same brief and `<plugin-root>/codex/references/worker.md` contract, then call `worker verdict`. Respect any context warning from `CFQ ctx`: hand off before another phase when the capacity gate says stop.

When no phase remains, run `CFQ finish <repo-root> <batch-dir> <branch>`. Release the lock with `CFQ lock release <repo-root> --batch <batch-name>` on every normal or error exit where this session owns it. Report completed/open phases, branch, last commit, push status and the shared report portal. Do not start a second batch in the same session.
