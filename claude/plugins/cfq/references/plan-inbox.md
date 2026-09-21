# Plan Inbox: Choosing an Entry

Only read when `/pfq` was invoked without arguments and **Inbox** finds at least one entry in
`<repo-root>/.claude/cfq/plan/`.

First render the entries as a short list — one line per entry with date, title and excerpt — from:

```bash
"<plugin-root>/bin/cfq" note list "<repo-root>" --text
```

Show that list, then ask one `AskUserQuestion`, "There are N planning requests waiting in the
queue. How do you want to proceed?":

- **Start with the oldest** (recommended, name it and its title/excerpt from the list above)
- **Choose a different one** (a second `AskUserQuestion`, entries as options, label = filename
  slug, description = date + title/excerpt from the same list)
- **Skip — plan something else** (this session's topic comes from the user instead, exactly as if
  the inbox were empty)

The chosen entry's path is passed to **Park**'s `bin/cfq park` call as `--from-plan
<chosen-entry-path>`, which moves it into `plan/done/` once the batch is parked. "Skip" passes
nothing, and every inbox entry stays untouched.
