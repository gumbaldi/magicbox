---
name: report-for-queue
description: >
  Show implementation reports for queue batches — which phases went green, which failed, where the
  implementation departed from the plan, and what broke. Renders a compact table in the terminal and a
  detailed HTML report on request. Use for "/rfq", "/report-for-queue", "show the reports", "how did
  the last batch go", "what went wrong in the implementation".
argument-hint: <repo or batch>
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
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" index [--repo <substr>] [--batch <substr>]
```

Print the `PRECHECKS` header on entering this step. One call: `index` already discovers every
`report: true` batch (open and archived alike) via its own internal `cfq-scan.sh` call, computes
each batch's `GREEN`/`RED`/`MIXED` status, and returns the sorted (newest-first), filtered array —
no separate scan, no per-batch `summary` loop, no filtering after the fact. Print the `Scan` status
line.

No batch has a report (`index` returns `[]`) → say so plainly, and mention that reports have
existed only since v0.2, so older batches never got one. Do not render an empty table.

## 2. Terminal Table

Render `index`'s array directly — already sorted newest-first, already carrying a computed
`status`:

| Repo | Batch | Status | Dev. | Date | Cost |
|---|---|---|---|---|---|
| magicbox | 2026-08-13-cfq-v02 | RED | 2 | 2026-08-14 | 67k |

**Cost** is `.cost.outputTokens`, rounded to whole thousands with no decimal (`67k`); `0` (no
telemetry — reports have existed since v0.2, telemetry only since v0.3) renders as `–` instead.
Repo column: basename of `.repo` only. Visibly mark `RED`/`MIXED` rows. Below the table, one
`file://` path to the HTML per row. With `reportDir` configured those paths point into the
collected tree (`<reportDir>/<repo>/<batch>.html`) instead of the batch directory, and
`<reportDir>/index.html` is the entry point into all of them.

## 3. Detail

On request for a single batch, print the `POSTCHECKS` header, then call:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" detail "<batch-dir>"
```

and render its `phases` in prose — status, summary, deviations, errors, and, if present, the
phase's model, effort, and the skills actually used (`.phases[].telemetry`); verification excerpts
are already bounded, render as-is. `found: false` → say plainly there is no report for this batch.

For the HTML view:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" html "<batch-dir>"
```

(renders fresh, overwrites a stale file) and state the printed path as a `file://` URL, printing
the `HTML` status line. Never open the file yourself — only print the path.

`detail`'s `todos` array already carries that repo's open `todo/*.md` entries — render title plus
one line, nothing else. Purely read-only: no checking off, no moving, and never running the
entries' `check:` commands. One sentence pointing to `/cfq` for checking them off. Empty array →
the section is left out entirely.

## Arguments

No argument → all repos, `index` called without flags. With an argument, `--repo` and `--batch`
each narrow independently (both given → both must match, AND not OR) — an argument that could name
either a repo or a batch is passed through as two separate calls, `index --repo <arg>` and `index
--batch <arg>`, merged and deduplicated by `(repo, batch)`, never filtered by Claude after the
fact. Both calls stay cheap (each is `index`'s single internal `cfq-scan.sh` call). Exactly one
match in the merged set → go straight to the detail view instead of the table. Print the `Filter`
status line right after `Scan`, before Step 2's table.

## Boundary

This skill only reads. No deleting, no editing, no retroactively recording phases — reports are
produced exclusively by `ifq`.
