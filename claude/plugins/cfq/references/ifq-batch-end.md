# ifq: Batch-Done and Closing Reports

## Batch-Done Report Fields

`bin/cfq finish` moves the batch into `impl/done/`, registers the repo, runs the
language/maintenance/security/changelog/telemetry sequence, syncs the portal, and releases the lock
unconditionally (a `trap`, so a mid-sequence failure can never leave the repo locked), and prints
one JSON object whose `statusLines` array already carries `Language`/`Maintenance`/`Security Diff`/
`Changelog`/`Branch`/`Telemetry`/`Report`/`Lock` rendered from that same object's fields — print each entry
as returned, in order; `Security Diff` is entirely absent from the array on an older batch with no
planning snapshot to diff against, rather than printed empty. `Skipped` (phases skipped and the inbox
entries written for them, `➖ none` when nothing was skipped) is printed as returned like the rest.
Any `.errors` entry
(`"<step>: <message>"`) already arrives attached as a `sub` line under its matching entry above —
the sequence still completed, no separate error line to compose.

One addition the aggregator cannot make on its own: `Language`'s line covers only the structural
count (`.lang.issues`, `missing`/`stray`/`unfiled`); still judge `.lang.prose.sample` yourself for
prose, comments, identifiers and commit messages not in `codeLanguage` — any language, never
hardcode one to look for. `i18nExcludePatterns` keeps locale/translation resources out of the
sample by default; a line that lands anyway from an evident translation resource isn't a
`codeLanguage` violation. If that judgment finds something the structural count didn't, add one
more `   └ ` sub-line of your own to the printed `Language` line — an addition, never a reword of
what the aggregator already rendered. No repair here either way — every finding becomes a `todo/`
entry per **Follow-Up** in `queue-entries.md`, and this call passes `--batch <batch-name>`.

`Report` names the batch's own route inside the report portal (`file://<repo-root>/.claude/cfq/
reports/index.html#/batch/<batch>`) — the portal sync itself already ran as this same `finish`
call's own side effect (`cfq_lib/portal_hook.py`), so this line only reports where it landed, no
separate render step to run. `htmlReport: false` renders it `➖ off · bin/cfq portal sync renders on demand`
instead, with no `file://` line in **Closing Reports**.

## Closing Report Fields (full format)

`RESULT · implement-for-queue` header, one label/value line per field. The report states no push or
merge status other than the one on the `Branch` line, and any further git fact it names is read by a
command run in this step; preflight values such as `remoteState` and `pushable` describe the start
of the session, never the end.

- `Batch` — batch and repo, phases total, green/red split, and the skipped phases next to it
  (`5 green, 1 red, 2 skipped`) when there are any.
- `Cost` — run `"<plugin-root>/bin/cfq" report summary "<batch-dir>"` (JSON) and render
  `totals.turns` as turns, `totals.output` as out and `totals.billable_in` as in, then `models` and
  `efforts`. Then one clause per layer with non-zero `turns`, in this order: `planning`,
  `orchestrator`, `worker`, `explorer`, `worker explorer` (the keys of `layers`), each as
  `<name> <turns> turns · <out> out`. The five layers add up to `totals`; `planning` is the planning
  session including its own explorers and is never part of `orchestrator`. A classic-mode batch has
  no `worker` or `worker explorer` clause, because both are zero.
- `Deviations` — from `deviations`: `<unique count> distinct · <count> total`, then one line per
  entry of `unique` as `×<count> <text>` (omit `×1`), at most 8 lines and `(+<k> more)` for the
  rest. Omitted when `deviations.count` is 0.
- `Security` — the difference only, one line.
- `Review` — the `Review` status line's detail, and the parked entry's path when there is one;
  omitted when `batchReview` is `off`.
- `Branch` — the Batch-Done step's own `Branch` line, verbatim: the branch this batch's commits are
  on, the branch it was cut from and the push state.
- `Report` — the Batch-Done step's own `Report` line, verbatim: the portal's `file://` route to
  this batch, or omitted when `htmlReport` turned the sync off.

**Short format** — `HANDOFF · implement-for-queue` header, three to four lines: phases done, phases
open, the `USED` value, `/clear` → `/ifq`. No cost breakdown, no `Branch` line. **Red case:** still the
full format, naming the red phase; its `❌` line already appeared in **Implementation**, so this
step only repeats the `5 green, 1 red` split in `Batch`, not the error text.
