# Interaction Policy

Shared rules for `pfq` and `ifq` sessions on gating against harness state and on when
`AskUserQuestion` is (and isn't) the right move. Plugin-level because both skills need it.

## Plan-Mode Gate

If a "Plan mode is active" system-reminder is present in context, call `ExitPlanMode`
immediately — before `pfq`'s and `ifq`'s **Preflight** call — naming what this
session is about to write (`pfq`: "interview and park plan files for `<repo>`"; `ifq`: "implement
the next open phase of `<batch>`"). Neither skill can function under Plan Mode (`pfq` writes
batch/phase files in **Park**, `ifq` writes code in `<plugin-root>/references/ifq-classic.md`'s **Implementation**) — resolve this before the
first write attempt, not as a discovered tool failure.

## No Waiting Questions

Never `AskUserQuestion` (or a prose equivalent) about whether to keep waiting on a subagent or
background task that's still running (Explore delegation, verification delegation). That is not a
user decision — print a status line, then continue automatically once the result lands.
`AskUserQuestion` is reserved for points where the answer changes what gets built or parked. The
rule behind `pfq`'s site list: it asks everything it needs before planning work starts — after
that, only exceptional cases still ask; everything routine gets decided and reported, or parked as
a `plan/` entry. Current sites — `pfq`: start block (interview depth, priority, one call; on an
unknown repo, the repo setup wizard's own area/value questions run first, before that call),
grilling rounds, closing question, self-critique's
drop-a-phase/remove-a-named-capability question; `ifq`: start gate (start/cancel, plus skip this phase when the next phase failed, plus pick a
different batch when another one is selectable, per
`implement-for-queue/SKILL.md`'s **Start Gate**, skipped only by the `resume`/`start`
keywords), scope-creep parking, branch base (every new batch branch, with one
confirmation when the chosen base leaves unmerged batch branches behind, plus ahead/diverged
remote on `continue`) — this section adds a rule, not new question sites.

## Challenge Duty

Applies to `pfq`, from the briefing onward. What the user states is input to check, not a fact
to build on.

- **Check claims before the first question.** Anything the user states as fact about the code,
  the tooling or the outside world (a price, a limit, "X is called without Y", "nobody uses Z")
  is verified during **Understand** against the code or a primary source. Open the first
  interview round with what did not hold, each point with its evidence — before any question
  that depends on it.
- **Say so once when a request looks like a bad idea.** Name the concern, the reason, and a
  concrete alternative, before any plan is written. Agreeing in order to move on is the failure
  this section exists to prevent; "yes" is only an answer when it is also the assessment.
- **Then the user decides.** A request the user confirms after hearing the concern is planned as
  asked — no second objection, and never the alternative planned quietly in its place. Record
  the overruled concern as one line under `.batch-context.md`'s `## Decisions`.
- **A change requested to an already written plan is covered too.** It is made — after the same
  one-time objection, when there is one.

One objection per point, none repeated after a decision, and none without a reason that can be
checked.

## Active Interview Duty

`## Challenge Duty` above applies first — read it before this section. Before treating an open point as "routine" (`pfq`'s **Interview**) or answering the closing
"anything else open?" check (`pfq`'s **Closing Question**) as satisfied, explicitly enumerate
every decision made autonomously
during the session that involved a real trade-off — not a forced choice, but one where a
different, reasonable reading would produce materially different files or behavior (e.g.
hardcoding a value vs. adding a configurable setting, choosing a data shape, picking a default).
Surface at least those in one batched `AskUserQuestion` before writing anything; the list of
autonomous decisions goes into that question's text. Silently deciding
them and only asking "anything else?" afterward does not satisfy **Closing Question** — this section exists
specifically to prevent that.

This section covers decisions the *planner* made autonomously. `plan-for-queue`'s
**Self-Critique of the Phase Cut** and `<plugin-root>/references/plan-self-critique.md` cover the
mirror case — decisions the *user* made from the
planner's own option lists, re-examined before any phase file is written.

## Decision Question Context

Text written before an `AskUserQuestion` call cannot be read while the dialog is open, so every
fact the user needs to *decide* (not merely confirm) goes inside the dialog itself, in the user's
language, in user-visible terms (what the user sees or does), not code identifiers:

- **What it is about and the problem** — the feature or step, what happens today, what goes wrong
  or why a decision is needed: in the `question` text.
- **Options** — each option's concrete effect for the user and its downside: in that option's
  `description`. A list that is to be confirmed goes in the `question` text or a `preview`.
- **Recommendation** — marked in the first option's `label` (`(Recommended)`) and named with `➡️`
  in the `question` text.

Text before the call is allowed as a courtesy for readers of the scrollback, but is never the only
place a fact lives. Code names may appear in parentheses after the plain description, never
instead of it.

**Exempt:** `pfq`'s start block questions (**Start Block**), and pure confirmations whose options
are proceed/cancel (e.g. "delete this batch?").
