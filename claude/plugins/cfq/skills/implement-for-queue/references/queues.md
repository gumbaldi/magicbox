# Batch Briefing and Queue Entry Formats

## Batch Briefing Extraction (Step 3b)

```bash
cat "<batch-dir>/.priority" 2>/dev/null || echo medium
cat "<batch-dir>/.dependsOn" 2>/dev/null
for f in "<batch-dir>"/[0-9]*.md; do
  awk '
    /^# / && !t            { sub(/^# +/, ""); t = $0; next }
    /^## (Größe|Size)/     { g = 1; next }
    g && NF                { size = $1; g = 0; next }
    /^## (Kontext|Context)/ { k = 1; next }
    k && NF                { ctx = ctx $0 " "; if (++n >= 2) k = 0; next }
    END { printf "%s\t%s\t%s\n", t, (size ? size : "M"), substr(ctx, 1, 220) }
  ' "$f"
done
```

Present it compactly: batch name, priority, phase count, and `.dependsOn` if the file exists, then
one line per phase — number and title, size in brackets, the context excerpt. No prose around it,
no repetition of the plan, no commentary on the phases. A phase file without `## Größe`/`## Size`
counts as `M`; one without `## Kontext`/`## Context` shows its title alone — an incomplete plan is
worth showing, not worth aborting over.

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
