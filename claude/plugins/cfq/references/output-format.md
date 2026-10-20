# Output Format

Shared status-line format for `pfq` and `ifq` sessions. Progress is reported as status lines, not
prose, one line per step, printed as soon as that step is done. Section headers print once, on
entering the section.

```
SECTION HEADER IN CAPS
<icon> <label padded to 16 chars><detail, one short clause>
```

Icons: `✅` done · `⚠️` warning/unavailable/degraded · `❌` failed · `➖` skipped/not applicable.
Rules: detail = what happened, not what happens next · a step that didn't run still gets its line
with `➖`/`⚠️` and the reason · sub-information → indented `   └ ` line, never the detail column ·
headers/labels/status lines are always English, and so are values — including the `RESULT` block's
label/value list (`none`, not `nichts`); only `AskUserQuestion` copy, the batch briefing and
interview prose follow the user's language · padding is plain space characters, never HTML entities
such as `&nbsp;`, which render as visible text rather than whitespace in a terminal · the result
section is a label/value list under the same padding, not a table · no commentary around the block.

## Rendered vs. composed lines

Some steps have a script (`cfq_ifq_preflight.py`, `cfq_pfq_preflight.py`, `cfq_finish.py`,
`cfq_phase.py`, `cfq_worker.py`) that already resolved every fact its line needs; that script returns a
`statusLines` array, each entry `{"label", "icon", "detail", "sub", "text"}` — `text` already run
through `cfq_lib/text.py`'s `status_line`/`sub_line` (the single definition of the 16-character
padding). Printing one of these means printing its `text` verbatim, entry by entry, in array
order — no re-padding, no re-wording, no re-ordering, and never merging two entries into one.

Which lines this covers: `Model Gate`/`Plugin Boundaries`/`Batch` (`cfq_ifq_preflight.py`),
`Model Gate`/`Inbox`/`Review`/`Plugin Boundaries` (`cfq_pfq_preflight.py`), `Language`/`Maintenance`/
`Security Diff`/`Changelog`/`Telemetry`/`Lock` (`cfq_finish.py`), `Commit`/`Cost` (`cfq_phase.py commit`), `Cost` (`cfq_worker.py verdict`), `Skip`/`Unskip` (`cfq_phase.py`), `Skipped` (`cfq_finish.py`).
`Model Gate` renders only the deterministic half — which list applies, or that
`allowAnyModel` skips the check entirely; the actual substring match against the running model
(only known to the session itself, from its own system prompt) stays skill-composed, unchanged.

Everything else still has no script behind it and stays composed by the model, following the
prose rules above: `Failed Attempt`, `Escalation`, `Size Gate`, `Language` on the `pfq` side,
`Phases`, `Self-Critique`, `Park`, `Phase Audit`, `Lint`, the Start Gate's own `Start Gate`
line, the review gate's own `Review` line (released / discarded) — the preflight's `Review`
line is rendered, the gate's is composed by the model — and the batch review's `Review` line.
