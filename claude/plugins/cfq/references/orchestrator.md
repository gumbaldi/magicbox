# Orchestrator Mode

`implement-for-queue`'s second mode: the session spawns one `cfq-phase-worker` sub-agent per phase
instead of implementing in-session, and decides between phases whether the next one starts. Loaded
only when `policy.orchestratorMode` is `true` — off by default until this batch's last phase flips
it. Everything the worker itself does or returns is defined in
`<plugin-root>/agents/cfq-phase-worker.md`; this file is the orchestrator's own loop around it.

## 1. Per phase, before spawning

Re-run `bin/cfq preflight-impl "<repo-root>" --select "<batch>"` to resolve the next open phase,
then `bin/cfq ctx` for the rate-limit gate. A `WARN` carries the same three-option question as
classic mode's `<plugin-root>/references/queues.md`'s **Phase Announcement** — identical wording,
identical options, no second variant. The capacity reason (`stopUsed`) does not apply here: every
worker starts on an empty context window, so no size gate runs and `onePhasePerSession` has no
effect on this loop at all.

## 2. Spawn

`bin/cfq worker brief "<batch-dir>" --phase <NN>` for the resolved phase, then one `cfq-phase-worker`
sub-agent, the briefing JSON as its prompt verbatim, and `policy.orchestratorModels[0]`
(`policy.implModels[0]` when `orchestratorModels` is empty) as its model.

## 3. On return

Pipe the worker's returned report — the JSON object `<plugin-root>/agents/cfq-phase-worker.md`'s
**Report** section defines — into `bin/cfq worker verdict "<batch-dir>"` on stdin.

- `CONTINUE` → render the phase summary (step 5 below), then back to step 1 for the next phase.
- `ASK` → resolve what can be resolved from `.batch-context.md`, the phase file and settings;
  relay only what genuinely can't be resolved as one `AskUserQuestion`. This covers both the
  self-reported `triggers` (`omitted`/`dependency`) and a `status: "question"` report — `verdict`
  already tells them apart, the orchestrator doesn't re-classify.
- `STOP` → the batch ends. `errors` prints unmodified, exactly as classic mode's red case does; run
  `POSTCHECKS` as today.

## 4. Resuming after an answer

Send the answer to the same worker with `SendMessage` so its context survives — it already holds
the phase file and everything it read while implementing. If that fails, spawn a fresh worker with
the answer folded into a new briefing and say so in the status line; the fallback is visible, never
silent.

## 5. Phase summary and batch end

Render the worker's report as `<plugin-root>/references/queues.md`'s existing **Phase Summary**
block (`implemented`/`verification`/`deviations` map onto `Implemented`/`Verification`/`Deviation`
directly), adding one line per entry in `parkedPlanEntries`. Batch end — no open `NN-*.md` left —
runs `bin/cfq finish` exactly as classic mode's Step 11 does.

## 6. Fallback to classic

A spawn that fails outright, or a worker that returns nothing usable (malformed report, no report
at all), does not end the batch: the orchestrator implements that phase itself, in-session, exactly
as classic mode's Step 8 would, and prints one `⚠️` line naming what failed before falling back.
This fallback exists to keep a batch moving on an occasional spawn failure — a *repeated* fallback
within the same batch is worth investigating, not silently absorbing.

## Sub-agent type

A plugin agent at `agents/cfq-phase-worker.md` in plugin `cfq` resolves as `cfq:cfq-phase-worker`
(plugin-namespaced) when spawned via the `Agent` tool — the documented Claude Code convention for
plugin-provided sub-agents, and the form recorded here.

Empirically: both `cfq:cfq-phase-worker` and the bare `cfq-phase-worker` were spawned against this
exact definition from inside the implementing session that just wrote it, and both came back
`Agent type '<name>' not found. Available agents: claude, claude-code-guide, Explore,
general-purpose, Plan, statusline-setup` — the running session's plugin instance is loaded from the
installed plugin cache, not from this checkout, so a newly added `agents/*.md` file is invisible to
`Agent` calls until the plugin is reinstalled or updated from this source. No session working
inside its own plugin's checkout can spawn an agent it just added to that same checkout — this is a
structural limit of testing a plugin agent against itself, not a naming ambiguity. Re-verify the
namespaced form once this plugin version ships and an `/ifq` session runs against the installed
copy; `agents/cfq-phase-worker.md` falling back to the spawning session's own model (its `model:`
field is intentionally absent) is unaffected either way.
