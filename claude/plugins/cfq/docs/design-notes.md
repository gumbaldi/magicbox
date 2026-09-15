# Design Notes

Why cfq's skills behave the way they do. Not loaded by any skill — history and rationale that used
to sit inline in skill/reference/agent prose, where every implementing session paid for it on every
turn. New rationale belongs here, not back in skill text.

## ifq: why a blocked-and-in-progress batch still waits

A batch that is both blocked and in-progress could in principle auto-resume, since it already has
work started. It doesn't: auto-resuming would restart work whose dependency reappeared after the
batch was started, so it waits like any other blocked batch instead.

## ifq: why the WARN phase-announcement options changed

The three-option WARN prompt (Go/Handoff/Cancel) replaced an earlier version whose effective choice
was "start anyway, but it will hand off immediately without implementing" versus "cancel" — two
ways of not implementing, dressed up as a real choice. Handoff is the honest name for what used to
be the forced outcome of "start anyway".

## ifq: why the Stop Rule has only three triggers

A fourth trigger used to sit here — files changed that `## Affected Files` does not list. It fired
only after the phase had already gone green, which made the question it raised unanswerable in
practice: the work was done, the change was evidently necessary, and the only sensible answer was
"yes, continue". That made it a confirmation prompt, not a gate. **File-Scope Deviation** replaces
it: the same mechanical comparison, made mandatory and recorded instead of interrupted for.

## ifq: why cross-references are broken by step renumbering

Cross-references used to name steps by number (`Step 5`, `Step 9`). Every renumbering broke at
least one: Step 3 once claimed to have "resolved Steps 1, 2 and 3a"; Step 8 once pointed at "Step 5"
for a call that had moved to Step 9. Cross-references now name the step instead (`**Size Gate**`,
`**Batch Done**`), so a renumbering can't silently leave a stale reference behind. The `Section Map`
table is the one place step numbers still appear on purpose — it *is* the numbering.
