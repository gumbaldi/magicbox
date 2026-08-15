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

## Output Format

Progress is reported as status lines, not prose. One line per step, printed **as soon as that
step is done** — never collected and dumped at the end. Section headers are printed once, on
entering the section.

```
SECTION HEADER IN CAPS
<icon> <label padded to 16 chars><detail, one short clause>
```

Icons: `✅` done · `⚠️` warning, unavailable, degraded · `❌` failed · `➖` skipped, not
applicable, nothing to do.

Rules:

- The detail says what the check found, not what you are about to do next. `sonnet · implModels:
  sonnet`, not "the model gate is satisfied, I will now look at the batch".
- A step that did not run still gets its line, with `➖` or `⚠️` and the reason — "no security
  data for this repo" is exactly the information the user is after.
- Sub-information belongs on an indented `   └ ` continuation line, never in the detail column.
- Section headers, labels, and status-line content are always English — regardless of the
  language the rest of the conversation is in. Only interactive prose (see below) follows the
  user's language.
- No commentary around the block: no "I will now …", no "done!", no summary sentence that repeats
  what the lines already say.
- The result section is a label/value list under the same padding, not a table.
- Interactive parts are exempt: `AskUserQuestion`, the batch briefing, and any question to the
  user stay in the user's language.
- The data tables of this skill are not status lines and stay exactly as specified below — the
  format applies to what happens around them.

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | 1 | `Scan` | `2 batches with a report` / `➖ no batch has a report (only exists since v0.2)` |
| PRECHECKS | 1 | `Filter` | `➖ no argument · all repos` / `1 match: magicbox → detail view` |
| POSTCHECKS | 3 | `HTML` | `rendered · file:///…` |

## 1. Collect

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh"
```

Print the `PRECHECKS` header on entering this step. Filter every batch with `report: true` — open
and archived alike. For each hit, build the batch path (`<path>/.claude/code-for-queue/<name>`,
or `.../done/<name>` when `archived: true`) and call:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" summary "<batch-dir>"
```

No repo discovery of your own — that lives entirely in `cfq-scan.sh`. Print the `Scan` status
line.

No batch has a report → say so plainly, and mention that reports have existed only since v0.2, so
older batches never got one. Do not render an empty table.

## 2. Terminal Table

From the TSV lines, sorted by date **descending** (newest first — here the latest run is what
matters, unlike the dashboard):

| Repo | Batch | Phases | ✓ | ✗ | Dev. | Date | Cost | Plan |
|---|---|---|---|---|---|---|---|---|
| magicbox | 2026-08-13-cfq-v02 | 6 | 5 | 1 | 2 | 2026-08-14 | 67k | 12k |

**Cost** (field 7) and **Plan** (field 8) are output tokens, rounded to whole thousands with no
decimal (`67k`). Batches without telemetry (reports have existed since v0.2, telemetry only since
v0.3) return `0` here from the TSV — show `–` in the table instead.

Repo column: basename only, resolve the full path once underneath. Visibly mark batches with
`✗ > 0`. Below the table, one `file://` path to the HTML per row.

## 3. Detail

On request for a single batch: read `report.json` and render the phases in prose — status,
summary, deviations, errors, and, if present, the phase's model, effort, and the skills actually
used (`.phases[].telemetry`). For the HTML view, print the `POSTCHECKS` header, then call:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<batch-dir>"
```

(renders fresh, overwrites a stale file) and state the printed path as a `file://` URL, printing
the `HTML` status line. Never open the file yourself — only print the path.

List that repo's open `todo/*.md` entries too — title plus one line, nothing else. Purely
read-only: no checking off, no moving, and never running the entries' `check:` commands. One
sentence pointing to `/cfq` for checking them off. No entries → the section is left out entirely.

## Arguments

No argument → all repos. With an argument, filter by repo name **or** batch name (substring is
enough, case-insensitive); exactly one match → go straight to the detail view instead of the
table. Print the `Filter` status line right after `Scan`, before Step 2's table.

## Boundary

This skill only reads. No deleting, no editing, no retroactively recording phases — reports are
produced exclusively by `ifq`.
