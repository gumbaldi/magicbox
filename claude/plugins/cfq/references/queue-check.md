# Queue Check: Overlap with Open Batches

Only read when **Queue Check** finds at least one open batch for the target repo.

```bash
"<plugin-root>/bin/cfq" overlap "<repo-root>"
```

Prints `{"batches": [{"batch": "<name>", "files": ["<path>", ...]}, ...]}` — one entry per open
batch, `files` from each of its open phases' `## Affected Files` section, `[]` when none list one.
Read the JSON and intersect each batch's `files` against the paths the new work will touch — no
shell filter, no `jq`.

- **No overlap** → one sentence, move on. No question.
- **Overlap** → name the affected paths and every overlapping batch in the `Queue Check` status
  line. Collect each overlapping batch's name as a `.dependsOn` entry for **Park**'s `bin/cfq park`
  call — no question, no "parallel"/"fold into" options.
