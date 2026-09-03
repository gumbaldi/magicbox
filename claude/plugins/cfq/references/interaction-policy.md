# Interaction Policy

Shared rules for `pfq` and `ifq` sessions on gating against harness state and on when
`AskUserQuestion` is (and isn't) the right move. Plugin-level because both skills need it.

## Plan-Mode Gate

If a "Plan mode is active" system-reminder is present in context, call `ExitPlanMode`
immediately — before `pfq`'s Step 4 / before `ifq`'s Step 3 preflight call — naming what this
session is about to write (`pfq`: "interview and park plan files for `<repo>`"; `ifq`: "implement
the next open phase of `<batch>`"). Neither skill can function under Plan Mode (`pfq` writes
batch/phase files in Step 15, `ifq` writes code in Step 8) — resolve this before the first write
attempt, not as a discovered tool failure.

## No Waiting Questions

Never `AskUserQuestion` (or a prose equivalent) about whether to keep waiting on a subagent or
background task that's still running (Explore delegation, verification delegation). That is not a
user decision — print a status line, then continue automatically once the result lands.
`AskUserQuestion` is reserved for points where the answer changes what gets built or parked; every
existing question site in both skills already qualifies (batch selection, scope-creep parking,
branch base, interview depth, security phase, grilling rounds, closing question) — this section
adds a rule, not new question sites.

## Active Interview Duty

Before treating an open point as "routine" (`pfq` Step 7) or answering the closing "anything else
open?" check (`pfq` Step 9) as satisfied, explicitly enumerate every decision made autonomously
during the session that involved a real trade-off — not a forced choice, but one where a
different, reasonable reading would produce materially different files or behavior (e.g.
hardcoding a value vs. adding a configurable setting, choosing a data shape, picking a default).
Surface at least those in one batched `AskUserQuestion` before writing anything. Silently deciding
them and only asking "anything else?" afterward does not satisfy Step 9 — this section exists
specifically to prevent that.

This section covers decisions the *planner* made autonomously. `plan-for-queue`'s Step 11 and
`references/plan-self-critique.md` cover the mirror case — decisions the *user* made from the
planner's own option lists, re-examined before any phase file is written.
