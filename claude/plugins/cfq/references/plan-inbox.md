# Plan Inbox: Choosing an Entry

Only read when `/pfq` was invoked without arguments and **Inbox** finds at least one entry in
`<repo-root>/.claude/cfq/plan/`. The compact list itself was already printed verbatim by **Inbox**
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
flag repeats. "Skip" passes nothing, and every inbox entry stays untouched.
