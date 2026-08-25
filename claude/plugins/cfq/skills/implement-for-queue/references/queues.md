# Batch Briefing and Queue Entry Formats

## Batch Selection Rules (Step 1-3a)

`cfq-ifq-preflight.sh`'s `selection` object carries `blocked`, `planning`, `inProgress`, and
`multipleInProgress` — the filters and stop conditions Step 1-3a applies before any picker runs.
The preflight itself already excludes blocked/planning/other-in-progress batches from
`selection.selectable`; this section only covers the wording each case needs.

**Blocked** batches (`selection.blocked`, each `{name, dependsOn, unknownDeps}`) are never offered.
If `status` is `BLOCKED`, print the wait list (batch → waiting on `dependsOn`) and end — never fall
back to a blocked one. `unknownDeps` (an unresolvable `.dependsOn` name) is shown at selection time
with `⚠️` and the unresolvable name but doesn't block (`/cfq` fixes it) — one sentence, no more.

**Planning** — a batch `/pfq` is still writing (`.planning` marker not yet cleared by its lint
step) — is never offered either, separately from the `dependsOn` wait list: for every name in
`selection.planning`, "Batch `<name>` is still being planned — try again once `/pfq` finishes."
One line per such batch, no more.

**In-progress invariant.** `status: "MULTIPLE_IN_PROGRESS"` (`selection.multipleInProgress`
non-empty) means more than one batch violates the one-in-progress-batch-per-repo invariant: **stop
immediately**, touch nothing, name every batch in the list, and say this must be resolved via
`/cfq` Step C (archive or reprioritize one) before `/ifq` can proceed — never silently pick one,
never fall through to the picker. A batch that is both blocked and in-progress is excluded from
this check by the blocked filter (it doesn't reach `selection.selectable`/`.inProgress` at all) and
surfaces only through the wait-list path — auto-resuming it would restart work whose dependency
reappeared after the batch was started, so it waits like any other blocked batch.

## Batch Briefing (Step 3b)

`batch.briefText` in the preflight result already holds `cfq-brief.sh`'s output for the resolved
batch — batch name, priority, phase count, `.dependsOn` if present, then one line per phase (number
and title, size in brackets, context excerpt). Present it as-is, compactly: no prose around it, no
repetition of the plan, no commentary on the phases. A phase file without `## Size` counts as `M`;
one without `## Context` shows its title alone — an incomplete plan is worth showing, not worth
aborting over.

## Branch and Changelog on Go-Ahead (Step 3b)

The preflight's `branch` field (already computed pre-mutation — see **Resume Snapshot** above) is
the same JSON `cfq-branch.sh plan "<repo-root>" "<batch>"` itself returns: `batch`/`batchNumber`
echo the batch's own stable identity (`batchNumber` is `null` for a legacy unnumbered batch);
`mode` says what to do. Always use the `branch` field directly for checkout — never reconstruct a
branch string from a number/slug:

`cfq-branch.sh plan` is remote-aware: it fetches `origin` once (best-effort — no `origin`, or the
fetch fails offline/sandboxed, and everything falls back to local-only behavior unchanged) before
deciding, so a stale local `main`/branch never gets silently proposed as a base. Two additive
fields ride along with every response: `remoteChecked` (bool) and `remoteWarning` (string or
`null`, set only when local has commits `origin` doesn't and that gap can't be auto-resolved).

- **`off`** (`branchPerBatch` is `false`) → `Branch: ➖ branchPerBatch off`, skip everything below.
- **`continue`** (a branch for this batch already exists) → `git checkout "<branch>"`, don't write
  a changelog entry (the batch is already recorded). Local purely behind its own
  `origin/<branch>` is fast-forwarded automatically before checkout. `remoteWarning` non-null here
  (local ahead of/diverged from `origin/<branch>`) doesn't block — `git checkout "<branch>"` still
  runs, but the `Branch` status line surfaces the warning as a `⚠️` note.
- **`new`** → `base` is already `main` when `candidates` is empty; local `main` purely behind
  `origin/main` is fast-forwarded first, same as the `continue` case. Non-empty `candidates` → one
  `AskUserQuestion` listing every entry in `candidates` plus `main`, deduplicated (`main` itself
  ends up in `candidates` when it's the one that's ahead of `origin/main` — see below), asking
  which one the new branch builds on. Recommended (first, labelled `(Recommended)`): the currently
  checked-out branch if it's in the list, otherwise the first candidate. Each option's description
  names how many commits it is ahead of `main` (`git rev-list --count main..<branch>`) — except the
  branch `remoteWarning` is about: its option is phrased "use local `<branch>` anyway (ahead of
  origin, deliberate)" and the question's context includes `remoteWarning` verbatim, so the choice
  to override is explicit rather than an unremarked list entry. Then:

```bash
git checkout "<base>"
git checkout -b "<branch>"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-changelog.sh" init "<repo-root>" "<branch>" "<base>" "<batch>"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-branch.sh" plan "<repo-root>" "<batch>"
```

The `new`-mode `cfq-branch.sh plan` re-run above is the one and only place this batch's mutation
step calls it directly — solely to reconfirm the branch now exists post-checkout; `continue`/`off`
never call it again, the preflight's answer already stands. A dirty working tree at this point is
an error, not something to work around: report it and end without touching anything.

## Pre-Implementation Go Gate (Step 4b2)

Runs after the size gate, before any code is written, every phase — the fine-grained counterpart
to Step 3b's one coarse per-batch go-ahead. The status line uses fields already on hand, no new
data model: phase number and title from the phase file's own top-level context (its filename's
`NN-<slug>` plus the first line of its `## Context` section, or the slug alone if `## Context` is
missing), the `## Size` letter, and the `## Affected Files` list verbatim (absolute paths, one per
line or comma-joined if short). Example:

```
P02 ifq-per-phase-go-gate [L]
Affected: cfq-settings.sh, cfq-ifq-preflight.sh, implement-for-queue/SKILL.md, queues.md, test-settings.sh
```

Then one `AskUserQuestion`, two options: **Go** — "proceed, implement this phase now" — and
**Cancel** — "release the lock and end the session, nothing touched". `Cancel` runs
`cfq-lock.sh release "<repo-root>"`, reports "cancelled before implementation, nothing touched",
and ends; it never leaves the lock held. `Go` proceeds straight to (4c).

## Phase Commit Trailers (Step 5)

Write the human-written subject/body (plus `Co-Authored-By`, as before) to a temp message file,
then run it through:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-changelog.sh" commit-message "<repo-root>" "<batch>" "<phase-slug>" green "<message-file>"
```

Commit with `git commit -F -` on its output. For a numbered batch (`batchNumber` from Step 3b's
`Branch`/`Resume` data is non-null) this appends `CFQ-Batch-Number`, `CFQ-Batch`, `CFQ-Phase`,
`CFQ-Phase-Status` to the existing trailer block via `git interpret-trailers`, leaving the
human-written subject/body untouched. A legacy (unnumbered) batch passes the message through
unchanged — never invent a `CFQ-Batch-Number` for one. Claude never hand-writes or hand-formats a
`CFQ-*` trailer.

## Skills Recommended vs. Used (Step 8)

```bash
jq -c '{recommended: [.phases[].telemetry.skills_recommended // []] | flatten | unique,
        used:        [.phases[].telemetry.by_skill // {} | keys[]] | unique | map(select(. != "-"))}' \
  "<batch-dir>/report.json"
```

## Plan Entry (`plan/<YYYY-MM-DD>-<slug>.md`)

H1 title, then:

- `## Finding` — what was noticed
- `## Location` — files and locations, absolute paths
- `## Why Not Here` — why it's out of scope for the current phase
- `## Origin` — batch and phase it came from

## Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

H1 title, one or two sentences describing what to do, optionally a `check: <shell-command>` line
(exit `0` means done). For the merge case: `check: git branch --merged main | grep -q <branch>`.
Plus `## Origin`, same as above.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`. The headings are always English; only the prose
inside them follows `codeLanguage`.

## Resume Snapshot (Step 1-3a preflight)

`cfq-ifq-preflight.sh`'s `resume` field carries what `cfq-resume.sh` itself returns for the
resolved batch, minus its own `branch` sub-object (redundant with the preflight's top-level
`branch`, computed by that same underlying call — see `cfq-resume.sh`'s own header comment for the
full, still-current field-by-field contract: `phasesOpen`/`phasesDone`, `lastCommit`/
`lastCommitSource`, `deviations`, `redPhases`, `batchContext.exists`/`.path`). One JSON object,
deterministic — no summarization, only facts read from disk, `report.json`, and git. `cfq-resume.sh`
itself is unchanged; only who calls it and what's kept from its output moved.

## Research and Verification Delegation (Step 4c)

Two, and only two, places in Step 4c may run on an Explore subagent
(`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get implExploreModel`, default `haiku`) instead of
the implementing session's own model — never a blanket "delegate whatever seems slow":

- **Pre-implementation research.** Before writing any code, a phase that touches several files or
  whose scope isn't fully clear from the phase file alone may send an Explore subagent to locate
  the relevant code, existing patterns, and callers, and return a distilled summary. This mirrors
  `plan-for-queue` Step 2 exactly — same reasoning, same default model. A narrow, single-file phase
  needs no subagent; reading the phase file is enough.
- **Verification output filtering, green case only.** Running the phase's verification command
  (tests, build, lint) can itself be delegated to an `implExploreModel` subagent when the raw output
  would be long — it runs the command and reports back pass/fail plus which command ran, nothing
  more. This keeps noisy log output out of the expensive model's context on the common path.

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
