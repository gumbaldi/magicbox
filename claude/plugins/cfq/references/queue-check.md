# Queue Check: Overlap with Open Batches

Only read when Step 8 finds at least one open batch for the target repo.

```bash
"<plugin-root>/bin/cfq" overlap "<repo-root>"
```

Prints `{"batches": [{"batch": "<name>", "files": ["<path>", ...]}, ...]}` — one entry per open
batch, `files` from each of its open phases' `## Affected Files` section, `[]` when none list one.
Read the JSON and intersect each batch's `files` against the paths the new work will touch — no
shell filter, no `jq`.

- **No overlap** → one sentence, move on. No question.
- **Overlap** → name the affected paths and the batch, then ask one `AskUserQuestion`: set
  `.dependsOn` on that batch · deliberately parallel (note that whichever batch runs first will
  change the file) · fold into the existing batch instead of creating a new one.

A batch waiting on another is rarely worth flagging high — say so when offering the flag in
Step 10.
