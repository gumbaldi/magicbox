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
`AskUserQuestion` with three options:

- **Quick interview** — a handful of targeted questions. Fits when the scope is manageable.
- **Thorough grilling** — a design tree, round by round, until nothing is left open. State the
  cost plainly: takes longer, costs noticeably more planning tokens; strongly recommended for
  complex reworks.
- **Grilling with docs** — the thorough grilling, plus a written paper trail: resolved domain terms go
  into a `CONTEXT.md` glossary at the repo root as they resolve, and decisions that are hard to reverse,
  surprising without context, and the result of a real trade-off become ADRs under `docs/adr/`. State
  the cost plainly: the most expensive of the three, and unlike the git-ignored queue folder it writes
  versioned files into the target repo. Recommend it only when the work introduces genuinely new domain
  vocabulary or architectural decisions someone will have to re-derive later.

Derive the recommendation from the scope of the request (number of components touched, how
unclear the requirement is, how far the consequences reach) and justify it in the option text —
don't always mark the same option.

On **Thorough** or **Grilling with docs**, read `references/grilling.md` and follow it — it covers
both paths.

## Step 2 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not.

## Step 3 — Plugin Boundaries

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planBlockedPlugins
```

Blocked plugins are used neither directly nor indirectly — and are not recommended in the phase
files this session produces either.

## Step 4 — Interview

Clarify open points as long as different readings would lead to materially different work.
Decide and name routine decisions yourself instead of asking.

## Step 5 — Queue Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh" | jq -c '.repos[] | select(.path == "<repo-root>") | .batches[] | select(.archived == false and .open > 0) | {name, priority, open, dependsOn}'
```

For every open batch found, read only the "Affected Files" section of its phase files — never
the whole file:

```bash
for f in <repo-root>/.claude/code-for-queue/<batch>/[0-9]*.md; do
  printf '%s\n' "== $f"
  sed -n '/^## \(Betroffene Dateien\|Affected Files\)/,/^## /p' "$f" | sed -n 's/^- `\([^`]*\)`.*/\1/p'
done
```

Intersect this path set against the files the new work will touch. Then:

- **No overlap** → one sentence, move on. No question.
- **Overlap** → name the affected paths and the batch, then ask **one** `AskUserQuestion` with the
  options: set `.dependsOn` on that batch · deliberately parallel (note that whichever batch runs
  first will change the file) · fold into the existing batch instead of creating a new one.
- The outcome is mentioned explicitly in the priority question's text (Step 9) — a batch waiting
  on another is rarely `high`.

No repo / no open batches → skip the step without mentioning it.

## Step 6 — Closing Question (mandatory)

Once nothing is left open, always check back once more before writing any plans — a short, open
question:

> "Before I write the plans: is there anything else we should discuss? Something I misunderstood,
> an edge case, a constraint?"

Only proceed once the user says no. If something comes up, work it in and ask the question again
afterward.

## Step 7 — Cut Phases

Propose a split and get it confirmed. Rule of thumb: one phase = one self-testable, individually
committable unit. Three honest phases beat seven artificial ones.

For each phase, additionally estimate:

- **Size** `S` / `M` / `L` — yardstick: `S` one file and one test, `M` several files or a new
  script, `L` a new script **with** a new test, or a skill rework. Size steers whether `ifq` even
  starts a phase.
- **Recommended skills** — optional, only where it actually helps, each with a half-sentence
  reason. Never a skill from `implBlockedPlugins`. No recommendation is the normal case and isn't
  commented on.

## Step 8 — Security Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-security.sh" "<repo-root>" > /tmp/cfq-sec.json
jq -c '{available, sources, counts, fixable}' /tmp/cfq-sec.json
```

- `available == false` → print the `hint` from the JSON **once**, never mention it again.
- Findings present → state the count per severity in one line.
- Only when `fixable.critical` or `fixable.high` is greater than 0: **one** `AskUserQuestion`
  asking whether a security phase should go into the batch (suggestion: as the first phase, since
  it's independent). Anything below that stays a warning line with no further planning — checking
  is cheap, planning is expensive.
- The snapshot is stored after parking, so `ifq` can diff it at the end of the batch:
  ```bash
  "${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" security "<batch-dir>" "$(cat /tmp/cfq-sec.json)"
  ```

## Step 9 — Priority (unconditional, always)

Ask this for every batch, every single time, even for a two-phase batch and even when the urgency
seems obvious from the conversation. Do not skip it, do not infer it from context, do not fold it into
another question. Exactly one `AskUserQuestion` with the three options `low`, `medium`, `high`.

`medium` is the default recommendation, but derive it honestly from what was discussed — a hotfix batch
is `high`, and saying so in the option text is better than a reflex `medium`. The answer is written to
`.priority` in Step 10; nothing is parked before it has been asked.

## Step 10 — Park

- Repo root: `git rev-parse --show-toplevel`. No repo → report and abort.
- Batch directory: `<repo-root>/.claude/code-for-queue/<YYYY-MM-DD>-<topic-slug>/`
- `NN-<slug>.md` per phase, numbered ascending
- `.priority` with a single line — the value chosen in Step 9, nothing else
- If Step 5 concluded a dependency, write `.dependsOn` in the batch directory — one batch
  directory name per line. No dependency decided → don't create the file at all.
- Make sure `**/.claude/code-for-queue/` is in `<repo-root>/.git/info/exclude` (ignored locally,
  **not** in the versioned `.gitignore`)
- `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" add "<repo-root>"`
- On the grilling path: write the decisions made as a `## Decisions` table into the **first**
  phase file. No separate ADR directory.

## Step 11 — Plan Lint

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lint.sh" "<batch-dir>"
```

Findings are fixed **immediately** and the lint re-run until it's clean. A batch never goes into
handoff with open lint findings. `warn:` lines (an unresolvable `.dependsOn` edge) are mentioned
but don't block.

## Step 12 — Optional Audit

First `cfq-settings.sh get ponytailAuditEvery`. `0` → the audit is disabled: don't ask, don't
check, don't touch the marker, skip this step without comment. This runs **before**
`usePonytailAudit`, so `0` stays the number-with-off-switch the user expects. Otherwise, as
before: only if `cfq-settings.sh get usePonytailAudit` is `true` **and** `ponytail:ponytail-audit`
is available. Due date works via the marker `<repo-root>/.claude/code-for-queue/.ponytail-audit`
(one line: `<YYYY-MM-DD> <commit-sha>`); due when the marker is missing, the SHA no longer
resolves, or `git rev-list --count "$sha..HEAD"` is ≥ the value just read. Keep the
`[ -n "$sha" ]` check — with an empty SHA, `git rev-list --count "..HEAD"` silently returns `0`
and would look like "just audited". If `usePonytailAudit` is `false`, neither ask nor check — the
skill works fully without ponytail.

The audit reports, it does not plan. Run it, then:

1. Present the findings as a list — one line each, nothing created yet.
2. Per finding, give an explicit recommendation (`queue it` / `fold into the current batch` /
   `ignore`) with a one-line reason, and offer details on any single finding: which files it touches,
   why it is ballast, what would stand there instead. Hand those over when asked, one finding at a time.
3. Only then one `AskUserQuestion` (multi-select) over which findings should be parked as a cleanup
   batch. No selection is a valid answer → no batch, accepted without comment or a second attempt.
4. A cleanup batch is created only for what was selected. Step 14 then lists it as a second batch.

## Step 13 — Telemetry and Sync

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" record "<batch-dir>" planning
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-telemetry.sh" sync "<repo-root>"
```

Failures of either call are non-fatal and get one line in the final report, not a comment.

## Step 14 — Final Report

Full format, kept short:

1. Batch path (absolute) and phase list in order, each with its size.
2. Priority and, if set, the `.dependsOn` edge with its reason.
3. Interview depth and planning cost from the telemetry record (turns, output tokens, model,
   effort) — one line.
4. Security in one line: the count, or "unavailable" with the hint, or "no findings".
5. Handoff: `/clear` → `/model <first model from implModels>` → `/ifq`.
6. If a cleanup batch came out of Step 12: list it as a second batch with a note that it can be
   worked off independently.

No repetition of the plan contents — that's what the files are for.

## Phase File Structure

Unchanged from the template: Context · Affected Files (always absolute paths) · Changes
(copy-ready) · Reuse · Dependencies · Verification (with output filtering). Plus the conventions:
absolute paths, no project-specific proper nouns in test data, token hygiene in the verification
section, and the verification must check the real path the user actually takes.
