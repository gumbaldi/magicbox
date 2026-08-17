# Batch Briefing and Queue Entry Formats

## Batch Briefing Extraction (Step 3b)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-brief.sh" "<batch-dir>"
```

Present it compactly: batch name, priority, phase count, and `.dependsOn` if the file exists, then
one line per phase — number and title, size in brackets, the context excerpt. No prose around it,
no repetition of the plan, no commentary on the phases. A phase file without `## Größe`/`## Size`
counts as `M`; one without `## Kontext`/`## Context` shows its title alone — an incomplete plan is
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

## Planungsauftrag / Plan Entry (`plan/<YYYY-MM-DD>-<slug>.md`)

H1 title, then:

- `## Fund` / `## Finding` — what was noticed
- `## Fundort` / `## Location` — files and locations, absolute paths
- `## Warum nicht hier` / `## Why Not Here` — why it's out of scope for the current phase
- `## Herkunft` / `## Origin` — batch and phase it came from

## Nacharbeit / Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

H1 title, one or two sentences describing what to do, optionally a `check: <shell-command>` line
(exit `0` means done). For the merge case: `check: git branch --merged main | grep -q <branch>`.
Plus `## Herkunft` / `## Origin`, same as above.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`, written in `codeLanguage` — use the heading
variant matching that language.
