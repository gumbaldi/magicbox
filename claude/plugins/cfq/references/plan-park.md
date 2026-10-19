# Plan Park: Batch Allocation and the Final Report

Only read at pfq's **Park** and **Final Report** steps.

## Park Mechanics

Topic slug (`codeLanguage`, lowercase, hyphen-separated, ASCII only) plus today's date
(`YYYY-MM-DD`) go to the allocation call. Never compute/pad the batch number by hand — the helper
reserves it in the local changelog (`status: parked`) and the queue directory, returning the final
`batch` name. `BATCH_WIDTH_MIGRATION_BLOCKED` → surface `action` and stop, nothing parked. Number
phase files ascending against the cut from **Self-Critique of the Phase Cut** — a phase it dropped
leaves no gap in the numbering.

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
during this session). `batch ready` runs at **Review Gate**
(`<plugin-root>/references/plan-review.md`), not at **Plan Lint**: **Review Gate** replaces
`.planning` with `.review`, and a `park` call while `.review` exists refreshes nothing and warns
about nothing. Once `batch ready` has removed the marker, a later `park` call — a correction after
that point — leaves it absent and prints an `already ready` warning on stderr instead of
resurrecting it: re-run `bin/cfq lint` until clean and `batch ready` (idempotent) again before
**Final Report**.

Print four status lines: `Park` (file count and batch dir, also covers **Security Check**'s
snapshot), `Batch Context` (sections written, or `➖ Goal only`), `Git Exclude`, `Registry`.

## Final Report Fields

`RESULT · plan-for-queue` header, then a label/value list under the `Output Format` padding rule:
`Batch` (absolute path) · `Phases` (in order, each with its size) · `Review` (`released`, with the revision count when above
zero) · `Edit` (plain Markdown in `Batch`; editable by hand until `/ifq` starts the phase, `/ifq`
lints again at its start) · `Portal` (the route from the digest's own `Portal` footer line, omit
when the digest printed none) · `Priority` (only when **Start
Block**'s flag answer was high, omit otherwise) · `Waiting on` (the `.dependsOn` edge and its
reason, omit when none) · `Cost` (interview depth plus the script-derived numbers below) ·
`Security` (count, "unavailable"+hint, or "no findings") · `Handoff` (`/clear` → `/model <first
implModels>` → `/ifq`). A maintenance `plan/` entry from **Maintenance** is named in one extra
`Inbox` line, not a second `RESULT` block. Phase file structure is unchanged from the template —
see `<plugin-root>/references/phase-quality.md`'s closing section.

`Cost`'s numbers are never a model estimate. Run `bin/cfq telemetry show "<repo-root>" --session`
and render its own top-level fields, field by field: `turns`, `billable_in` as "in", `output` as
"out" — the whole session's own sum (the planning session itself plus every sub-agent it spawned,
never only the top-level transcript), `cache_read` named separately, `models`, `efforts`. When
`layers.main_explore.turns` is non-zero, add one further clause naming the Explore sub-agent's own
`turns`/`output` share, read from `layers.main_explore` — that activity is already folded into the
top-level numbers above, this clause only surfaces the split, so a planning session that delegated
research to an Explore agent doesn't have that share stay invisible. Interview depth is the one
part of this line that stays prose, not a script field — it is a fact about this session, not
something the script can see. If the call itself fails or returns nothing usable, the whole line
reads `⚠️ unavailable` — never a guessed number in its place.
