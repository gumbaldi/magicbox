---
name: plan-for-queue
description: >
  Interview the user, resolve open questions, and write detailed phase plans that get parked in
  the repo-local implementation queue — without implementing anything. Use whenever a feature, a
  series of bugs, a refactoring or a larger rework needs planning, and for "plan this", "how do
  we approach X", "/pfq", "/plan-for-queue". A separate cheaper session implements it later via
  implement-for-queue.
---

# Plan-for-Queue: Interview, Park, Hand Off

Always answer in the user's language.

The output of this session is plan files only — no code edits, no builds, no commits, not even
"just this one line."

## Step 1 — Interview Depth (unconditional, always, before anything else)

Ask this before anything else, every single time, even when the task looks small and even when
you already know the codebase. Do not skip it, do not infer the answer. Exactly one
`AskUserQuestion` with two options:

- **Quick interview** — a handful of targeted questions. Fits when the scope is manageable.
- **Thorough grilling** — a design tree, round by round, until nothing is left open. State the
  cost plainly: takes longer, costs noticeably more planning tokens; strongly recommended for
  complex reworks.

Derive the recommendation from the scope of the request (number of components touched, how
unclear the requirement is, how far the consequences reach) and justify it in the option text —
don't always mark the same option.

On **Thorough**, read `references/grilling.md` and follow it.

## Step 2 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not.

## Step 3 — Plugin Boundaries

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planBlockedPlugins
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planPreferredPlugins
```

Blocked plugins are used neither directly nor indirectly — and are not recommended in the phase
files this session produces either. Preferred plugins are checked for whether they'd help; if
not, they're left out without comment.

## Step 4 — Interview

Clarify open points as long as different readings would lead to materially different work.
Decide and name routine decisions yourself instead of asking.

## Step 5 — Closing Question (mandatory)

Once nothing is left open, always check back once more before writing any plans — a short, open
question:

> "Before I write the plans: is there anything else we should discuss? Something I misunderstood,
> an edge case, a constraint?"

Only proceed once the user says no. If something comes up, work it in and ask the question again
afterward.

## Step 6 — Cut Phases

Propose a split and get it confirmed. Rule of thumb: one phase = one self-testable, individually
committable unit. Three honest phases beat seven artificial ones.

## Step 7 — Park

- Repo root: `git rev-parse --show-toplevel`. No repo → report and abort.
- Batch directory: `<repo-root>/.claude/code-for-queue/<YYYY-MM-DD>-<topic-slug>/`
- `NN-<slug>.md` per phase, numbered ascending
- `.priority` with a single line (`low`|`medium`|`high`), asked via `AskUserQuestion`, with
  `medium` as the recommended option
- Make sure `**/.claude/code-for-queue/` is in `<repo-root>/.git/info/exclude` (ignored locally,
  **not** in the versioned `.gitignore`)
- `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"`
- On the grilling path: write the decisions made as a `## Decisions` table into the **first**
  phase file. No separate ADR directory.

## Step 8 — Optional Audit

Only if `cfq-settings.sh get usePonytailAudit` is `true` **and** `ponytail:ponytail-audit` is
available. Due date works as before, via the marker
`<repo-root>/.claude/code-for-queue/.ponytail-audit` (one line:
`<YYYY-MM-DD> <commit-sha>`); due when the marker is missing, the SHA no longer resolves, or
`git rev-list --count "$sha..HEAD"` is ≥ 50. Keep the `[ -n "$sha" ]` check — with an empty SHA,
`git rev-list --count "..HEAD"` silently returns `0` and would look like "just audited". If the
setting is `false`, neither ask nor check — the skill works fully without ponytail.

## Step 9 — Hand Off

Output exactly: the batch path (absolute), the phase list in order, then `/clear` →
`/model <first model from implModels>` → `/ifq`. If a cleanup batch was created, list it as a
second batch with a note that it can be worked off independently.

## Phase File Structure

Unchanged from the template: Context · Affected Files (always absolute paths) · Changes
(copy-ready) · Reuse · Dependencies · Verification (with output filtering). Plus the conventions:
absolute paths, no project-specific proper nouns in test data, token hygiene in the verification
section, and the verification must check the real path the user actually takes.
