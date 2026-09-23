# Design Notes

Why cfq's skills behave the way they do. Not loaded by any skill — history and rationale that used
to sit inline in skill/reference/agent prose, where every implementing session paid for it on every
turn. New rationale belongs here, not back in skill text.

## ifq: why a blocked-and-in-progress batch still waits

A batch that is both blocked and in-progress could in principle auto-resume, since it already has
work started. It doesn't: auto-resuming would restart work whose dependency reappeared after the
batch was started, so it waits like any other blocked batch instead.

## ifq: why the start gate was added

`SKILL.md` used to state plainly that invoking `/ifq` is itself the intent to start a batch, no
confirmation question — a deliberate choice, made to keep the session moving without an extra
round trip on every run. It was reversed on the user's request: the session now shows the batch
overview and the full queue and asks before touching anything, because "just start" gave no
chance to pick a different batch, or to notice a wrong one was about to be worked, before the lock
and branch were already committed to. A future reader finding the gate should not read it as
leftover caution to be trimmed back to the old behaviour — it replaced a decision that was tried
and explicitly walked back.

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

## pfq: why Self-Critique of the Phase Cut exists

Observed in batch `009`: six phases were cut, the user said "write the plans", and only
afterwards, asked unprompted, did re-examining the cut within one turn produce a differentiated
answer — three phases clearly justified, one only a precondition, one delivering a different
benefit than assumed, one weak enough to drop. The batch went from six phases to five. Under the
rule this incident produced, the drop would still have prompted one question; the two narrowings
would have been made silently and reported. The specific failure mode: a phase enters the batch
because the user picked it from an option list the planner itself wrote, and a step that only asks
the user to review the plan cannot catch that — the user is reviewing a proposal built from their
own earlier answer.

## pfq/ifq: why decision questions explain their context first

In a `pfq` session (2026-09-23), the planner explained its hypothesis in a dense paragraph written
in code identifiers, then asked only "what should happen?". The user answered: "Ich verstehe den
context nicht. Wenn ich Entscheidungen treffen soll brauche ich mehr Details: worum geht es, was
ist das Problem, wie kann man es lösen." `interaction-policy.md`'s **Decision Question Context**
exists so a decision question always states what it's about, what the problem is, and what each
option costs, in the user's own terms, before asking — not just in `pfq`, since `ifq`'s branch and
self-critique questions have the same shape.

## pfq: why Phase Quality's five rules exist

One `/ifq` phase burned far more tokens than the task itself required — not the logic, the
debugging: a raw `bash -x` trace dumped whole into context, and a dozen one-off shell smoke tests
instead of one test file. The five rules in `references/phase-quality.md` turn that incident into a
standing checkpoint, not a one-time lesson repeated only in a post-mortem.
