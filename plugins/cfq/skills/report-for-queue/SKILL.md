---
name: report-for-queue
description: >
  Show implementation reports for queue batches — which phases went green, which failed, where the
  implementation departed from the plan, and what broke. Renders a compact table in the terminal and a
  detailed HTML report on request. Use for "/rfq", "/report-for-queue", "show the reports", "how did
  the last batch go", "what went wrong in the implementation".
---

# Report-for-Queue: Show What Happened

Always answer in the user's language.

## 1. Collect

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh"
```

Filter every batch with `report: true` — open and archived alike. For each hit, build the batch
path (`<path>/.claude/code-for-queue/<name>`, or `.../done/<name>` when `archived: true`) and call:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" summary "<batch-dir>"
```

No repo discovery of your own — that lives entirely in `cfq-scan.sh`.

No batch has a report → say so plainly, and mention that reports have existed only since v0.2, so
older batches never got one. Do not render an empty table.

## 2. Terminal Table

From the TSV lines, sorted by date **descending** (newest first — here the latest run is what
matters, unlike the dashboard):

| Repo | Batch | Phases | ✓ | ✗ | Dev. | Date | Cost | Plan |
|---|---|---|---|---|---|---|---|---|
| codeforqueue | 2026-08-13-cfq-v02 | 6 | 5 | 1 | 2 | 2026-08-14 | 67k | 12k |

**Cost** (field 7) and **Plan** (field 8) are output tokens, rounded to whole thousands with no
decimal (`67k`). Batches without telemetry (reports have existed since v0.2, telemetry only since
v0.3) return `0` here from the TSV — show `–` in the table instead.

Repo column: basename only, resolve the full path once underneath. Visibly mark batches with
`✗ > 0`. Below the table, one `file://` path to the HTML per row.

## 3. Detail

On request for a single batch: read `report.json` and render the phases in prose — status,
summary, deviations, errors, and, if present, the phase's model, effort, and the skills actually
used (`.phases[].telemetry`). For the HTML view, call:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<batch-dir>"
```

(renders fresh, overwrites a stale file) and state the printed path as a `file://` URL. Never open
the file yourself — only print the path.

## Arguments

No argument → all repos. With an argument, filter by repo name **or** batch name (substring is
enough, case-insensitive); exactly one match → go straight to the detail view instead of the
table.

## Boundary

This skill only reads. No deleting, no editing, no retroactively recording phases — reports are
produced exclusively by `ifq`.
