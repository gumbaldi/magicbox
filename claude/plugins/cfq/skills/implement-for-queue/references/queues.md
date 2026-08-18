# Batch Briefing and Queue Entry Formats

## Batch Selection Rules (Step 3a)

`cfq-scan.sh`'s output carries `blocked`, `unknownDeps`, `planning`, and `inProgress` per batch —
the filters and stop conditions Step 3a applies before any picker runs.

**Blocked** batches (`.dependsOn` names a batch not yet in `impl/done/`) are never offered. If
every open batch is blocked, print the wait list (batch → waiting on batch) and end — never fall
back to a blocked one. `unknownDeps` (an unresolvable `.dependsOn` name) is shown at selection time
with `⚠️` and the unresolvable name but doesn't block (`/cfq` fixes it) — one sentence, no more.

**Planning** — a batch `/pfq` is still writing (`.planning` marker not yet cleared by its lint
step) — is never offered either, separately from the `dependsOn` wait list: "Batch `<name>` is
still being planned — try again once `/pfq` finishes." One line per such batch, no more.

**In-progress invariant.** Among the batches that pass the planning/blocked filters, more than one
`inProgress` batch violates the one-in-progress-batch-per-repo invariant: **stop immediately**,
touch nothing, name every in-progress batch found, and say this must be resolved via `/cfq` Step C
(archive or reprioritize one) before `/ifq` can proceed — never silently pick one, never fall
through to the picker. A batch that is both `blocked` and `inProgress` is excluded from this check
by the blocked filter (it doesn't reach here) and surfaces only through the wait-list path —
auto-resuming it would restart work whose dependency reappeared after the batch was started, so it
waits like any other blocked batch.

## Batch Briefing Extraction (Step 3b)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-brief.sh" "<batch-dir>"
```

Present it compactly: batch name, priority, phase count, and `.dependsOn` if the file exists, then
one line per phase — number and title, size in brackets, the context excerpt. No prose around it,
no repetition of the plan, no commentary on the phases. A phase file without `## Size`
counts as `M`; one without `## Context` shows its title alone — an incomplete plan is
worth showing, not worth aborting over.

## Branch and Changelog on Go-Ahead (Step 3b)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-branch.sh" plan "<repo-root>" "<batch>"
```

Returns one JSON object; `mode` says what to do:

- **`off`** (`branchPerBatch` is `false`) → `Branch: ➖ branchPerBatch off`, skip everything below.
- **`continue`** (a branch for this batch already exists) → `git checkout "<branch>"`, don't bump
  the version, don't write a changelog entry (the batch is already recorded).
- **`new`** → `base` is already `main` when `candidates` is empty; non-empty → one
  `AskUserQuestion` listing every entry in `candidates` plus `main`, asking which one the new
  branch builds on. Recommended (first, labelled `(Recommended)`): the currently checked-out
  branch if it's in the list, otherwise the highest `vX.Y` among them. Each option's description
  names how many commits it is ahead of `main` (`git rev-list --count main..<branch>`). Then:

```bash
git checkout "<base>"
git checkout -b "<version>-<slug>"
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-changelog.sh" init "<repo-root>" "<version>" "<version>-<slug>" "<base>" "<batch>"
```

A dirty working tree at this point is an error, not something to work around: report it and end
without touching anything.

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
