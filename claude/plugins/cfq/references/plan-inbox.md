# Plan Inbox: Choosing an Entry

Only read when Step 3 finds at least one entry in `<repo-root>/.claude/cfq/plan/`.

One `AskUserQuestion`, "There are N planning requests waiting in the queue. How do you want to
proceed?":

- **Start with the oldest** (recommended, name it and its first line)
- **Choose a different one** (a second `AskUserQuestion`, entries as options, label = filename
  slug, description = date + first line)
- **Skip — plan something else** (this session's topic comes from the user instead, exactly as if
  the inbox were empty)

The chosen order file moves to `plan/done/` once parked; "Skip" leaves every inbox entry
untouched.
