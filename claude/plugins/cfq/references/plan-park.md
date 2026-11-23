# Plan Park: Batch Allocation and the Final Report

Read in Group B of pfq's **Language and Cut Phases**; applies at the **Security and Park** and
**Close and Report** steps.

## Park Mechanics

Topic slug (`codeLanguage`, lowercase, hyphen-separated, ASCII only) plus today's date
(`YYYY-MM-DD`) go to `bin/cfq planning open`. Never compute/pad the batch number by hand — the
command allocates it through `batch allocate`, which reserves it in the local changelog
(`status: parked`) and the queue directory, and returns the final `batch` name.
`BATCH_WIDTH_MIGRATION_BLOCKED` → surface `action` and stop, nothing parked. Number
phase files ascending against the cut from **Self-Critique of the Phase Cut** — a phase it dropped
leaves no gap in the numbering. All phase files go out as `Write` calls in one response, once the cut
and every decision are final; look up anchors before that turn, not between the writes. Each `NN-<slug>.md` starts as a copy of
`<plugin-root>/references/phase-template.md`.

A phase-file `Write` denied by a `PreToolUse` hook ends the session. Print `❌ Park`, then
quote the hook's `stopReason` verbatim on a `   └ ` sub-line (paraphrasing it loses the path
it names) and add the reserved batch directory's path on another sub-line. Never work around
the denial: no `Bash` fallback for phase files, no unlock marker of any kind. Both would
defeat the guard the user configured. What a guard hook has to allow: **Hook contract** in
the plugin's `README.md`.

`bin/cfq park` writes `status.json` (every phase `open`); after renaming, adding or removing a phase
file, re-run `bin/cfq park` so a `status:` lint finding clears.

`bin/cfq park` writes `.priority`/`.dependsOn` (**Queue Check**'s dependencies, if any; `.priority`
only when **Start Block**'s flag answer was high), ensures the git-exclude entry, registers the
repo — idempotent. `--from-plan` may repeat, once per chosen inbox entry — a batch planned from
several entries (**Inbox**) passes every one of them in the same `park` call.

`.planning` is born at `batch allocate`, not at `park` — the marker exists from the moment the
batch directory does. `park` only refreshes it (a heartbeat, safe to re-run any number of times
during this session). `bin/cfq planning close` runs lint, then `batch ready`, which removes the
marker. Once it has, a later `park` call — a correction after that point — leaves it absent and
prints an `already ready` warning on stderr instead of resurrecting it: call `planning close`
(idempotent) again afterwards.

Print four status lines: `Park` (file count and batch dir, also covers the security
snapshot of `planning open`), `Batch Context` (sections written, or `➖ Goal only`), `Git Exclude`, `Registry`.

## Final Report Fields

`RESULT · plan-for-queue` header, then a label/value list under the `Output Format` padding rule:
`Batch` (absolute path) · `Phases` (in order, each with its size) · `Portal` (the `portal` value of `planning close`, omitted when it is null) · `Edit` (plain
Markdown in `Batch`; editable by hand until `/ifq` starts the phase, `/ifq` lints again at its
start) · `Priority` (only when **Start
Block**'s flag answer was high, omit otherwise) · `Waiting on` (the `.dependsOn` edge and its
reason, omit when none) · `Cost` (interview depth plus the script-derived numbers below) ·
`Security` (count, "unavailable"+hint, or "no findings") · `Handoff` (`/clear` → `/model <first
implModels>` → `/ifq`). A maintenance `plan/` entry from **Maintenance** is named in one extra
`Inbox` line, not a second `RESULT` block.

`Cost`'s numbers are never a model estimate. Build the line from the `cost` object of `bin/cfq
planning close` (the output of `telemetry show --session`), field by field, rendering its own top-level fields: `turns`, `billable_in` as "in", `output` as
"out" — the whole session's own sum (the planning session itself plus every sub-agent it spawned,
never only the top-level transcript), `cache_read` named separately, `models`, `efforts`. When
`layers.main_explore.turns` is non-zero, add one further clause naming the Explore sub-agent's own
`turns`/`output` share, read from `layers.main_explore` — that activity is already folded into the
top-level numbers above, this clause only surfaces the split, so a planning session that delegated
research to an Explore agent doesn't have that share stay invisible. Interview depth is the one
part of this line that stays prose, not a script field — it is a fact about this session, not
something the script can see. If `cost` is null or unusable, the whole line
reads `⚠️ unavailable` — never a guessed number in its place.
