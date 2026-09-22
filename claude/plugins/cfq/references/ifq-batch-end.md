# ifq: Batch-Done and Closing Reports

## Batch-Done Report Fields

`bin/cfq finish` moves the batch into `impl/done/`, registers the repo, runs the
language/maintenance/security/changelog/telemetry sequence and releases the lock unconditionally (a
`trap`, so a mid-sequence failure can never leave the repo locked), and prints one JSON object whose
`statusLines` array already carries `Language`/`Maintenance`/`Security Diff`/`Changelog`/
`Telemetry`/`Lock` rendered from that same object's fields — print each entry as returned, in
order; `Security Diff` is entirely absent from the array on an older batch with no planning
snapshot to diff against, rather than printed empty. Any `.errors` entry (`"<step>: <message>"`)
already arrives attached as a `sub` line under its matching entry above — the sequence still
completed, no separate error line to compose.

One addition the aggregator cannot make on its own: `Language`'s line covers only the structural
count (`.lang.issues`, `missing`/`stray`/`unfiled`); still judge `.lang.prose.sample` yourself for
prose, comments, identifiers and commit messages not in `codeLanguage` — any language, never
hardcode one to look for. `i18nExcludePatterns` keeps locale/translation resources out of the
sample by default; a line that lands anyway from an evident translation resource isn't a
`codeLanguage` violation. If that judgment finds something the structural count didn't, add one
more `   └ ` sub-line of your own to the printed `Language` line — an addition, never a reword of
what the aggregator already rendered. No repair here either way — every finding becomes a `todo/`
entry per **Follow-Up** in `queue-entries.md`.

Render the HTML report (`bin/cfq report html "<repo-root>/.claude/cfq/impl/done/<batch>"`),
printing `Report` as `rendered`, unless `htmlReport` is `false` — then skip it, printing `➖ off ·
/rfq renders on demand` and no `file://` line in **Closing Reports**.

## Closing Report Fields (full format)

`RESULT · implement-for-queue` header, one label/value line per field:

- `Batch` — batch and repo, phases total, green/red split.
- `Cost` — run `"<plugin-root>/bin/cfq" report summary "<batch-dir>"` (same call
  `report-for-queue` already uses for its table) and render fields 9/7/8/10/11 as turns, output
  tokens total (planning's share named separately), models, efforts. The row's last five fields —
  in that order, regardless of whether the optional worker block below is present — are always
  `total_billable_in`, `planning_turns`, `planning_billable_in`, `explore_turns`, `explore_output`:
  render `total_billable_in` as input tokens for the whole batch, `planning_turns` alongside
  `planning_output` (field 8, already named) as planning's own turn count, `planning_billable_in`
  alongside it as planning's own input share, and `explore_turns`/`explore_output` together as one
  clause naming the Explore sub-agents' own share. A row carrying fields 12-15 (only present when a
  phase actually ran a worker sub-agent, i.e. orchestrator mode) additionally names the
  orchestrator's and the workers' turns and output tokens separately — `orchestrator_turns`,
  `orchestrator_output`, `worker_turns`, `worker_output`, in that order, the two pairs summing back
  to fields 9/7 — alongside the existing total. These four fields are worker-only now: an Explore
  agent's activity within the same phases never counts toward either side of this split, it
  surfaces only in the `explore_turns`/`explore_output` tail fields above. A row without fields
  12-15 (classic mode, or an older report) renders exactly as before, no worker line.
- `Skills` — recommended vs. used, query in **Skills Recommended vs. Used** below.
- `Security` — the difference only, one line.
- `Merge` — current branch, commits ahead of `main`, a ready-to-run command as an indented
  `   └ ` line, printed not run; also a `todo/` card, written without asking by
  `"<plugin-root>/bin/cfq" note merge-todo "<repo-root>" "<branch>"` (per **Follow-Up** in
  `queue-entries.md`), so a forgotten merge is never lost and the card's `check:` line lets `/cfq`
  close it on its own once the merge lands.
- `Report` — `file://` path, only when the Batch-Done step rendered one, else the line is omitted.

**Short format** — `HANDOFF · implement-for-queue` header, three to four lines: phases done, phases
open, the `USED` value, `/clear` → `/ifq`. No cost breakdown, no merge hint. **Red case:** still the
full format, naming the red phase; its `❌` line already appeared in **Implementation**, so this
step only repeats the `5 green, 1 red` split in `Batch`, not the error text.

## Skills Recommended vs. Used

```bash
"<plugin-root>/bin/cfq" report skills "<batch-dir>"
```
