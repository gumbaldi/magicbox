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

Only walked when `branchPerBatch` is not `false`.

Continuation check — a branch ending in `-<slug>` (batch dir name, leading `YYYY-MM-DD-` removed)
already exists locally or on the remote:

```bash
slug="<batch dir name with the leading YYYY-MM-DD- removed>"
git branch -a --format='%(refname:short)' | sed 's#^origin/##' | sort -u | grep -E -- "-${slug}$"
```

A hit → check it out, don't bump the version, don't write a changelog entry (the batch is already
recorded), skip everything below.

Version — same expression Step 5 already used before this phase, `grep -oE` only ever captures the
`vX.Y` prefix so the new `-<slug>` suffix doesn't confuse it:

```bash
git branch -a | grep -oE 'v[0-9]+\.[0-9]+' | sort -t. -k1,1V -k2,2n | tail -1
```

Increment the digit after the dot (`v0.48` → `v0.49`); nothing found → `v0.1`. The major is never
incremented automatically.

Base — every branch ahead of `main`:

```bash
for b in $(git branch --format='%(refname:short)'); do
  [ "$b" = main ] && continue
  [ "$(git rev-list --count main.."$b")" -gt 0 ] && echo "$b"
done
```

Empty → base is `main`, silently. Non-empty → one `AskUserQuestion` listing all of these branches
plus `main`, asking which one the new branch builds on. Recommended (first, labelled
`(Recommended)`): the currently checked-out branch if it's in the list, otherwise the highest
`vX.Y` among them. Each option's description names how many commits it is ahead of `main`.

Create it, without pushing — the push happens with the first commit:

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

## Planungsauftrag (`plan/<YYYY-MM-DD>-<slug>.md`)

H1 title, then:

- `## Fund` — what was noticed
- `## Fundort` — files and locations, absolute paths
- `## Warum nicht hier` — why it's out of scope for the current phase
- `## Herkunft` — batch and phase it came from

## Nacharbeit (`todo/<YYYY-MM-DD>-<slug>.md`)

H1 title, one or two sentences describing what to do, optionally a `check: <shell-command>` line
(exit `0` means done). For the merge case: `check: git branch --merged main | grep -q <branch>`.
Plus `## Herkunft`, same as above.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`, written in `codeLanguage`.
