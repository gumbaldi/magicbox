# Plan Self-Critique: Does the Cut Still Earn Its Place

`Step 6` asks the **user** what is still open. Step 7 proposes the phase cut and, until this file
existed, wrote the files right after — nothing asked the **planner** whether the phases it just cut
actually serve the batch goal. This was observed in batch `009`: six phases were cut, the user said
"write the plans", and only afterwards, asked unprompted, did re-examining the cut within one turn
produce a differentiated answer — three phases clearly justified, one only a precondition, one
delivering a different benefit than assumed, one weak enough to drop. The batch went from six phases
to five.

The specific failure mode this catches: a phase enters the batch because the user picked it from an
`AskUserQuestion` option list the planner itself wrote, and the planner then treats the answer as
settled. A step that only asks the user to review the plan cannot catch that — the user is reviewing
a proposal built from their own earlier answer. This is the mirror image of
`interaction-policy.md`'s **Active Interview Duty**, which covers decisions the *planner* made
autonomously; this file covers decisions the *user* made from the planner's own option lists.

This file governs whether a phase should **exist**. `phase-quality.md` governs what a phase's
**text** must contain once it does. Keep the two separate.

## Scope

Read unconditionally at Step 7a, every session, regardless of phase count or interview depth. A
two-phase batch still gets two short verdicts — this step is never skipped as "too small to
bother".

## The Three Categories

Judge every open phase against all three:

1. **Purposeful, no over-engineering** — the phase does the smallest thing that achieves its part
   of the goal. This subsumes token efficiency of the planned change: rather than a free-standing
   verdict (which would get answered "yes" every time), point at `phase-quality.md` rules 3
   (debugging stays out of the main context), 4 (smoke tests are bundled, not serialized) and 5
   (size reflects verify-the-reuse work) — three specific rules can actually be checked.
2. **Fits the existing environment** — no logic errors, no hand-off problems between phases, no
   dead code left behind, no feature cut off half-finished by a later phase. This category requires
   reading the phase files against one another, not each in isolation.
3. **Serves the batch goal** — the phase advances the goal named in `.batch-context.md`'s `##
   Goal`. This is the category that catches the option-list failure above: a phase that is in the
   batch only because it was picked from a list the planner wrote fails here.

## The Citation Requirement

The central rule, not a footnote: every verdict — pass or fail — names something concrete. A file
path, another phase's number, a quoted line from the phase file, a specific `phase-quality.md`
rule. A verdict that cannot cite anything **counts as a fail**. This, not the category count, is
what stops the step degenerating into a rubber stamp.

## The Batch Line

After the per-phase verdicts, one judgement on the cut as a whole: do the phases compose, is the
order right, does any phase depend on something a later phase produces. Categories 2 and 3 above
are statements about individual phases that per-phase judging alone cannot make about the whole.

## On a Fail

Every failing category becomes one `AskUserQuestion` with a named recommendation and its reasoning.
Options drawn from: drop the phase · narrow its scope · merge it with another phase · reorder ·
leave as is. Batch several fails into one call rather than asking serially. Nothing is written
until the user has answered — the planner does not silently re-cut.

## Recording

A phase dropped at this step goes into `.batch-context.md`'s `## Non-Goals` with its reason, so a
later `/ifq` resume — which reads that file — cannot quietly resurrect it.

## Rendered Example

```
Self-Critique
  01 audit-log-schema      pass — cites phase 02's read path
  02 audit-log-writer      pass — cites the batch goal directly
  03 audit-log-dashboard   fail (serves the batch goal) — this batch's goal is "make writes
                           auditable", not "visualize them"; 03 was picked from Step 5's option
                           list, not derived from the goal
  batch                    03 aside, 01→02 compose cleanly, no ordering issue
```

→ one `AskUserQuestion`: "Phase 03 doesn't serve this batch's goal (see above) — drop it, narrow it
to just the audit-log table view, or leave it as is?"
