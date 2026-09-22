# Plan Park: Batch Allocation and the Final Report

Only read at pfq's **Park** and **Final Report** steps.

## Park Mechanics

Topic slug (`codeLanguage`, lowercase, hyphen-separated, ASCII only) plus today's date
(`YYYY-MM-DD`) go to the allocation call. Never compute/pad the batch number by hand — the helper
reserves it in the local changelog (`status: parked`) and the queue directory, returning the final
`batch` name. `BATCH_WIDTH_MIGRATION_BLOCKED` → surface `action` and stop, nothing parked. Number
phase files ascending against the cut from **Self-Critique of the Phase Cut** — a phase it dropped
leaves no gap in the numbering.

`bin/cfq park` writes `.priority`/`.dependsOn` (**Queue Check**'s dependencies, if any; `.priority`
only when **Start Block**'s flag answer was high), ensures the git-exclude entry, registers the
repo — idempotent.

Print four status lines: `Park` (file count and batch dir, also covers **Security Check**'s
snapshot), `Batch Context` (sections written, or `➖ Goal only`), `Git Exclude`, `Registry`.

## Final Report Fields

The `RESULT · plan-for-queue` header is preceded by the batch overview block — `bin/cfq brief
"<batch-dir>" --overview`, printed exactly as returned, no rewording, one blank line between it
and the header. Above the header, not below: the overview is what the user reads to check the plan
just written, the `RESULT` list that follows is only the handoff metadata. This is printed at
**Final Report**, after **Plan Lint** has gone clean — a batch whose lint still has findings is not
yet the plan the user gets, and the `.planning` marker is only removed once lint passes; the block
is never printed earlier, at **Park**.

`RESULT · plan-for-queue` header, then a label/value list under the `Output Format` padding rule:
`Batch` (absolute path) · `Phases` (in order, each with its size) · `Priority` (only when **Start
Block**'s flag answer was high, omit otherwise) · `Waiting on` (the `.dependsOn` edge and its
reason, omit when none) · `Cost` (interview depth, turns, tokens, model, effort) · `Security`
(count, "unavailable"+hint, or "no findings") · `Handoff` (`/clear` → `/model <first implModels>` →
`/ifq`). A maintenance `plan/` entry from **Maintenance** is named in one extra `Inbox` line, not a
second `RESULT` block. Phase file structure is unchanged from the template — see
`<plugin-root>/references/phase-quality.md`'s closing section.
