# Queue Check: Overlap with Open Batches

Only read when Step 5 finds at least one open batch for the target repo.

```bash
for f in <repo-root>/.claude/code-for-queue/impl/<batch>/[0-9]*.md; do
  printf '%s\n' "== $f"
  sed -n '/^## Affected Files/,/^## /p' "$f" | sed -n 's/^- `\([^`]*\)`.*/\1/p'
done
```

Read only the "Affected Files" section of each phase file — never the whole file. Intersect the
resulting path set against the files the new work will touch.

- **No overlap** → one sentence, move on. No question.
- **Overlap** → name the affected paths and the batch, then ask one `AskUserQuestion`: set
  `.dependsOn` on that batch · deliberately parallel (note that whichever batch runs first will
  change the file) · fold into the existing batch instead of creating a new one.

A batch waiting on another is rarely worth flagging high — say so when offering the flag in
Step 7.
