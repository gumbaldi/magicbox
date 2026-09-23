# Interaction Policy

Shared rules for `pfq` and `ifq` sessions on gating against harness state and on when
`AskUserQuestion` is (and isn't) the right move. Plugin-level because both skills need it.

## Plan-Mode Gate

If a "Plan mode is active" system-reminder is present in context, call `ExitPlanMode`
immediately — before `pfq`'s **Start Block** / before `ifq`'s **Preflight** call — naming what this
session is about to write (`pfq`: "interview and park plan files for `<repo>`"; `ifq`: "implement
the next open phase of `<batch>`"). Neither skill can function under Plan Mode (`pfq` writes
batch/phase files in **Park**, `ifq` writes code in **Implementation**) — resolve this before the
first write attempt, not as a discovered tool failure.

## No Waiting Questions

Never `AskUserQuestion` (or a prose equivalent) about whether to keep waiting on a subagent or
background task that's still running (Explore delegation, verification delegation). That is not a
user decision — print a status line, then continue automatically once the result lands.
`AskUserQuestion` is reserved for points where the answer changes what gets built or parked. The
rule behind `pfq`'s site list: it asks everything it needs before planning work starts — after
that, only exceptional cases still ask; everything routine gets decided and reported, or parked as
a `plan/` entry. Current sites — `pfq`: start block (interview depth, priority, and — new repo
only — config keep/adjust, one call), grilling rounds, closing question, self-critique's
drop-a-phase/remove-a-named-capability question; `ifq`: start gate (start/pick a different
batch/cancel, per `<plugin-root>/references/ifq-batch-start.md`'s **Start Gate**), scope-creep
parking, branch base (ambiguous dependencies, a newer uncontained cfq branch than the highest
batch, ahead/diverged remote only) — this section adds a rule, not new question sites.

## Active Interview Duty

Before treating an open point as "routine" (`pfq`'s **Interview**) or answering the closing
"anything else open?" check (`pfq`'s **Closing Question**) as satisfied, explicitly enumerate
every decision made autonomously
during the session that involved a real trade-off — not a forced choice, but one where a
different, reasonable reading would produce materially different files or behavior (e.g.
hardcoding a value vs. adding a configurable setting, choosing a data shape, picking a default).
Surface at least those in one batched `AskUserQuestion` before writing anything. Silently deciding
them and only asking "anything else?" afterward does not satisfy **Closing Question** — this section exists
specifically to prevent that.

This section covers decisions the *planner* made autonomously. `plan-for-queue`'s
**Self-Critique of the Phase Cut** and `<plugin-root>/references/plan-self-critique.md` cover the
mirror case — decisions the *user* made from the
planner's own option lists, re-examined before any phase file is written.

## Decision Question Context

Before any `AskUserQuestion` that asks the user to *decide* (not merely confirm), write a short
block in the user's language, in user-visible terms (what the user sees or does), not code
identifiers:

- **What it is about** — the feature or step, and what happens today.
- **The problem** — what goes wrong, or why a decision is needed.
- **Options** — each with its concrete effect for the user and its downside.

Then give the recommendation, marked `➡️`, before asking. Code names may appear in parentheses
after the plain description, never instead of it.

**Exempt:** `pfq`'s start block questions (**Start Block**), and pure confirmations whose options
are proceed/cancel (e.g. "delete this batch?").
