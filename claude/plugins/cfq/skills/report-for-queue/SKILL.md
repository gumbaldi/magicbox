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

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

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

## Section Map

| Section | Step | Label | Example detail |
|---|---|---|---|
| PRECHECKS | 1 | `Scan` | `2 batches with a report` / `➖ no batch has a report (only exists since v0.2)` |
| PRECHECKS | 1 | `Filter` | `➖ no argument · all repos` / `1 match: magicbox → detail view` |
| POSTCHECKS | 3 | `HTML` | `rendered · file:///…` |

## 1. Collect

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report index [--repo <substr>] [--batch <substr>] [--any <substr>]
```

Print the `PRECHECKS` header on entering this step. One call: `index` already discovers every
`report: true` batch (open and archived alike) via its own internal `bin/cfq scan` call, computes
each batch's `GREEN`/`RED`/`MIXED` status, and returns the sorted (newest-first), filtered array —
no separate scan, no per-batch `summary` loop, no filtering after the fact. Print the `Scan` status
line. `--any` is for a single argument that could name either a repo or a batch — see `## Arguments`
below.

No batch has a report (`index` returns `[]`) → say so plainly, and mention that reports have
existed only since v0.2, so older batches never got one. Exactly one match → skip Step 2 entirely
and go straight to Step 3's detail view.

## 2. Terminal Table

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report index [--repo <substr>] [--batch <substr>] [--any <substr>] --text
```

Same filters as Step 1 — another cheap single-scan call, this time rendered. Print its output
exactly as returned (the table plus one `file://` line per row, already pointing into the collected
tree when `reportDir` is configured) — no rebuilding the table from Step 1's JSON by hand.

## 3. Detail

On request for a single batch, print the `POSTCHECKS` header, then call:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report detail "<batch-dir>"
```

and render its `phases` in prose — status, summary, deviations, errors, and, if present, the
phase's model, effort, and the skills actually used (`.phases[].telemetry`); verification excerpts
are already bounded, render as-is. `found: false` → say plainly there is no report for this batch.

For the HTML view:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report html "<batch-dir>"
```

(renders fresh, overwrites a stale file) and state the printed path as a `file://` URL, printing
the `HTML` status line. Never open the file yourself — only print the path.

`detail`'s `todos` array already carries that repo's open `todo/*.md` entries — render title plus
one line, nothing else. Purely read-only: no checking off, no moving, and never running the
entries' `check:` commands. One sentence pointing to `/cfq` for checking them off. Empty array →
the section is left out entirely.

## Arguments

No argument → all repos, `index` called without flags. With an argument that clearly names a repo
or a batch, pass it as `--repo`/`--batch` — narrowing independently when both are given (AND, not
OR). An argument that could name either → `--any <arg>` instead: `index` matches it against repo
path or batch name and dedupes internally, one call, never two calls merged by Claude after the
fact. Print the `Filter` status line right after `Scan`, before Step 2's table.

## Boundary

This skill only reads. No deleting, no editing, no retroactively recording phases — reports are
produced exclusively by `ifq`.
