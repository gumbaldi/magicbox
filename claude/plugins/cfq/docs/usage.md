# Usage

What each of the four skills does, step by step, and where its behavior is configurable. See
[configuration.md](configuration.md) for what every setting named below actually does.

## Plan a batch — `/pfq`

Interviews you, resolves open questions, and parks phased plans in the repo-local queue. Never
edits code.

```
/pfq
```

1. If `.claude/cfq/plan/` has requests waiting (dropped there by a previous `/ifq`
   session), pfq offers to start with the oldest one, choose a different one, or skip and plan
   something else instead.
2. Checks the running model against `planModels` — a mismatch only warns, it never blocks.
3. Asks for an interview depth: quick targeted questions, thorough grilling (a design-tree
   interview, round by round), or grilling with a written paper trail (a `CONTEXT.md` glossary and
   ADRs for hard-to-reverse decisions).
4. Reads the code — for anything spanning multiple files, it delegates to Explore subagents
   running on `planExploreModel` rather than reading everything in the main session.
5. Clarifies open points, proposes a phase split, checks for security findings, and offers a
   high-priority flag (optional — not flagging is the normal case).
6. Parks the batch as numbered phase files under `.claude/cfq/impl/<date>-<topic>/`. If this ever
   reports `BATCH_LEDGER_MISMATCH` (a queue directory with no matching changelog entry),
   `bin/cfq batch reconcile <repo-root>` reports the gap and `--fix` closes it — it never deletes
   anything, and never touches a reserved number whose directory never got created.

Configurable: `planModels`, `planExploreModel`, `allowAnyModel`, `grillMode`,
`useMattpocockGrilling`, `planBlockedPlugins`.

Handoff: `/clear` → `/model <an implModels entry>` → `/ifq`.

## Implement a batch — `/ifq`

Works off one batch from the current repo's queue, phase by phase, committing and pushing every
green phase.

```
/ifq
```

1. Gates on the model — **aborts** if the running model isn't in `implModels` (unless
   `allowAnyModel` is set); this is the one hard gate in cfq, everywhere else a mismatch only
   warns.
2. Picks a batch: work through the open ones flagged-first, or choose a specific one. Skips
   any batch still blocked by `.dependsOn`.
3. Shows the batch briefing and asks for a go-ahead before touching anything — no lock is taken
   before that.
4. Implements one phase at a time — for a phase spanning multiple files or unclear scope, it may
   delegate pre-implementation research (and, on green/red, mechanical test-run output filtering)
   to Explore subagents running on `implExploreModel`; implementation itself always stays in the
   main session. Before touching any file, it announces the phase and asks for a go-ahead:

   ```
   PHASE 02 · ifq-per-phase-go-gate · Size L
     Goal     Deterministic phase announcement, extracted from the phase file itself.
     Files    bin/cfq, SKILL.md, queues.md
     Check    bash tests/test-brief-park.sh
   ```

   Runs the phase's own verification, commits and pushes on every green phase immediately, then
   prints what actually happened:

   ```
   PHASE 02 DONE
   ✅ Implemented     Added --phase to the brief noun, extended its test.
   ✅ Verification    bash tests/test-brief-park.sh — PASS
   ```

   Before starting the next phase in the same session, it checks four fixed triggers (files
   changed beyond the plan's list, verification red or skipped, a planned change left out, an
   unnamed new dependency) — any of them stops the automatic advance and asks once whether to
   continue.
5. Hands the session off once the capacity threshold (`stopUsed`) fires (`HANDOFF`/`STOP`), or
   finishes the batch and moves it to `impl/done/`. Crossing a rate-limit threshold
   (`stopFiveHourPct` / `stopSevenDayPct`), or failing to read context usage at all, only produces
   a `WARN` — the next phase is still offered, with the warning attached to the go-ahead question,
   and you choose whether to continue or hand off.

Configurable: `implModels`, `allowAnyModel`, `implExploreModel`, `stopUsed`, `stopFiveHourPct`,
`stopSevenDayPct`, `branchPerBatch`, `changelogFile`, `implBlockedPlugins`, `maintenanceEvery`.

## Dashboard, queue and settings — `/cfq`

```
/cfq
```

First-time setup (see [setup.md](setup.md)), the cross-repo dashboard — a `QUEUES` overview table
across every registered repo plus a `THIS REPO` phase-level table and a `CONFIG` block (only the
settings that deviate from default, each tagged `[D]`/`[G]`/`[R]`/`[E]` for default/global/repo/env)
for the repo `/cfq` runs in — management of the current repo's `todo/` leftovers, and reading or
changing settings (see [configuration.md](configuration.md)).

## Reports — `/rfq`

Read-only: surfaces what `/ifq` already did. Never writes anything.

```
/rfq
```

A compact terminal table across all repos, or the detailed HTML report for one batch: which phases
went green or red, where the implementation departed from the plan, what broke, telemetry.

## See also

- [setup.md](setup.md) — installation and first-time setup
- [configuration.md](configuration.md) — the full settings reference
