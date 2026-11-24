# Plan Inbox: Choosing an Entry

The choice question below is only read when `/pfq` was invoked without arguments and **Inbox** finds
at least one entry in `<repo-root>/.claude/cfq/plan/`; **Entries Covered by the Plan** applies to
every session with at least one entry. The compact list itself was already printed verbatim by **Inbox**
(`inbox.overview`) — before the choice question below, print `inbox.detail` verbatim too, so the
user sees what each entry is actually about, not just its title.

Ask one `AskUserQuestion`, "There are N planning requests waiting in the queue. How do you want to
proceed?" (N = `inbox.count`):

- **Start with the oldest** (recommended, name it and its title from the overview above)
- **Choose a different one** (a second `AskUserQuestion`, entries as options, label = filename
  slug, description = date + title from `bin/cfq note list "<repo-root>"` JSON — one call, only in
  this branch)
- **Skip — plan something else** (this session's topic comes from the user instead, exactly as if
  the inbox were empty)

The chosen entry's path is passed to **Park**'s `bin/cfq park` call as `--from-plan
<chosen-entry-path>`, which moves it into `plan/done/` once the batch is parked — when this
session's topic combines more than one inbox entry, pass one `--from-plan <path>` per entry, the
flag repeats. "Skip" passes nothing for the chosen entry; entries the plan covers are handled as
below.

## Entries Covered by the Plan

Applies with and without arguments. An inbox entry counts as covered when the plan's phases fix or
build what the entry describes — not merely touch the same file or topic. Before any plan is
written, the closing question lists the covered entries (title and date from `inbox.overview`) as
"covered — moved to `plan/done/` when parked". An entry the planner is unsure about is listed
separately as "possibly covered" and is consumed only when the user confirms it. The user strikes
or adds entries in the free-text answer. At **Park**, every covered, non-struck entry is passed as
one `--from-plan <path>` argument (paths from `bin/cfq note list "<repo-root>"` JSON or the entry
paths in `inbox.detail`). An entry is never closed silently.
