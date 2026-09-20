# ifq: Batch-Done and Closing Reports

## Batch-Done Report Fields

`bin/cfq finish`'s one JSON object, rendered field by field:

- `Language`: `.lang.issues` is the structural count (`missing`/`stray`/`unfiled`); judge
  `.lang.prose.sample` for prose, comments, identifiers and commit messages not in `codeLanguage` —
  any language, never hardcode one to look for. `i18nExcludePatterns` keeps locale/translation
  resources out of the sample by default; a line that lands anyway (custom naming the patterns
  miss) from an evident translation resource isn't a `codeLanguage` violation — expected
  multi-language content, not a policy breach. `.lang.prose.truncated: true` means the sample is
  exactly that, a sample, so the status line says so (`⚠️ 2 issues · sampled`); an empty sample (no
  git repo, unknown ref) is `➖`, not a finding. Either source finding → `⚠️` with the combined
  count, details as `   └ ` lines; nothing found → `✅ no issues`. No repair here — every finding
  becomes a `todo/` entry per **Follow-Up** in `queue-entries.md`.
- `Maintenance` from `.maintenance`: `➖ off` · `➖ not due (<n> commits)` · `⚠️ due (<n> commits) ·
  run /pfq`.
- `Security Diff` from `.security.new` — the difference only, no repeat of the overall count, no
  new planning, no automatic fix; an empty `.security` block (older batch, no planning snapshot)
  → skip without comment.
- `Changelog` from `.changelog` as-is.
- `Telemetry` from `.telemetry`, `Lock` from `.lock`.
- Any `.errors` entries → `⚠️` lines naming the failed step; the sequence still completed.

## Closing Report Fields (full format)

`RESULT · implement-for-queue` header, one label/value line per field:

- `Batch` — batch and repo, phases total, green/red split.
- `Cost` — run `"<plugin-root>/bin/cfq" report summary "<batch-dir>"` (same call
  `report-for-queue` already uses for its table) and render fields 9/7/8/10/11 as turns, output
  tokens total (planning's share named separately), models, efforts. A row carrying fields 12-15
  (only present when the batch ran a worker, i.e. orchestrator mode) additionally names the
  orchestrator's and the workers' turns and output tokens separately — `orchestrator_turns`,
  `orchestrator_output`, `worker_turns`, `worker_output`, in that order, the two pairs summing back
  to fields 9/7 — alongside the existing total. A row without those fields (classic mode, or an
  older report) renders exactly as before, no worker line.
- `Skills` — recommended vs. used, query in **Skills Recommended vs. Used** below.
- `Security` — the difference only, one line.
- `Merge` — current branch, commits ahead of `main`, a ready-to-run command as an indented
  `   └ ` line, printed not run; also a `todo/` card, written without asking by
  `"<plugin-root>/bin/cfq" note merge-todo "<repo-root>" "<branch>"` (per **Follow-Up** in
  `queue-entries.md`), so a forgotten merge is never lost and the card's `check:` line lets `/cfq`
  close it on its own once the merge lands.
- `Report` — `file://` path, only when the Batch-Done step rendered one, else the line is omitted.

## Skills Recommended vs. Used

```bash
"<plugin-root>/bin/cfq" report skills "<batch-dir>"
```
