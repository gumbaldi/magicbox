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

Always answer in the user's language. The output of this session is plan files only — no code
edits, no builds, no commits, not even "just this one line." This holds even once a harness-level
plan-mode approval says "you can now start coding," and even with an autonomous/auto-run mode
active — that approval covers parking the plan, never implementing what it describes.
Implementation happens later, in a separate `implement-for-queue` session.

## Output Format

Progress is reported as status lines, not prose, one line per step, printed as soon as that step
is done. Section headers print once, on entering the section.

```
SECTION HEADER IN CAPS
<icon> <label padded to 16 chars><detail, one short clause>
```

Icons: `✅` done · `⚠️` warning/unavailable/degraded · `❌` failed · `➖` skipped/not applicable.
Rules: detail = what happened, not what happens next · a step that didn't run still gets its line
with `➖`/`⚠️` and the reason · sub-information → indented `   └ ` line, never the detail column ·
headers/labels/status lines are always English, interactive parts stay in the user's language ·
no commentary around the block.

## Step 0 — Inbox

List `"<repo-root>/.claude/cfq/plan"/*.md`, sorted by filename ascending (the
`<YYYY-MM-DD>-<slug>.md` naming already sorts oldest first). No entries → skip silently, no status
line, no mention. One or more entries → read `references/plan-inbox.md` and follow it.

## Step 1 — Interview Depth (unconditional, always, before anything else)

Print the `INTERVIEW` header on entering, then check the running model:
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planModels
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get allowAnyModel
```
`allowAnyModel: true` → skip, `Model Check` is `➖ allowAnyModel`. Otherwise substring-match the
running model (from the system prompt) against `planModels`, like `ifq`'s gate — no match → warn
naming the model and the list, and continue; this never blocks, unlike `ifq`. Print `Model Check`
either way. Ask this before anything else, every time, even for a small task or a familiar codebase
— never skip, never infer. One `AskUserQuestion` with three options, the recommendation derived
from scope (components touched, how unclear the requirement is, how far consequences reach) and
justified in the option text — don't always mark the same one:

- **Quick interview** — a handful of targeted questions; fits when the scope is manageable.
- **Thorough grilling** — a design tree, round by round, until nothing is left open. Costs
  noticeably more planning tokens; recommended for complex reworks.
- **Grilling with docs** — thorough grilling plus a paper trail: domain terms into a `CONTEXT.md`
  glossary, hard-to-reverse/surprising trade-off decisions into ADRs under `docs/adr/`. Most
  expensive; writes versioned files into the target repo — recommend only for genuinely new
  domain vocabulary or decisions someone would otherwise have to re-derive.

On **Thorough** or **Grilling with docs**, read `references/grilling.md` and follow it. Print the
`Interview Depth` status line once answered.

## Step 2 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not. For research spanning multiple files or unclear scope, delegate to
Explore agents instead of reading everything inline — one for a narrow, known area, up to three in
parallel for broad scope, each with a specific focus. Run them on
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planExploreModel` (default `haiku`), not this
session's own model — research is delegatable, the planning model is the expensive part.

## Step 3 — Plugin Boundaries

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get planBlockedPlugins`. Blocked plugins are
used neither directly nor indirectly, nor recommended in the phase files this session produces.
Print the `Plugin Boundaries` status line.

## Step 4 — Interview

Clarify open points as long as different readings would lead to materially different work.
Decide and name routine decisions yourself instead of asking.

## Step 5 — Queue Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-scan.sh" | jq -c '.repos[] | select(.path == "<repo-root>") | .batches[] | select(.archived == false and .open > 0) | {name, priority, open, dependsOn}'
```

Any batch found → read `references/queue-check.md` and follow it. No repo / no open batches →
skip the step without mentioning it. Either way, print the `Queue Check` status line — `➖` when
there was nothing to check.

## Step 6 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans: "Before I write the plans: is
there anything else we should discuss? Something I misunderstood, an edge case, a constraint?"
Proceed only once the user says no; if something comes up, work it in and ask again afterward.

## Step 7 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`; the confirmation dialogue stays prose.
Read once per session: `cfq-settings.sh get codeLanguage`, `docLanguages`, `docLevel`.
`codeLanguage` governs everything a phase specifies without exception — code, comments, commit
messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/` — and this session's own output
too: plan files, `## Decisions`, the batch directory name. A phase touching documentation → read
`references/language.md` and follow it. Print the `Language` status line once read. Propose a split
and get it confirmed — one phase = one self-testable, individually committable
unit; three honest phases beat seven artificial ones. For each phase, estimate **Size** `S`/`M`/`L`
(`S` one file and one test, `M` several files or a new script, `L` a new script **with** a new
test or a skill rework — steers whether `ifq` even starts a phase) and write it into that phase's
file as a `## Size` heading (structural markers are always English, independent of
`codeLanguage`) with the letter alone on the next non-empty line — this is what `cfq-brief.sh` and `ifq`'s size gate
parse; a missing or malformed heading silently degrades to `M`. Also add optional **Recommended
skills** (only where it helps, half-sentence reason each, never from `implBlockedPlugins`; no
recommendation is the normal case). Same confirmation also asks whether this batch should be
flagged high priority — flagged batches are picked first by `ifq`'s automatic ordering and marked
in the `/cfq` dashboard; not flagging is the normal case and needs no answer. Print the `Phases`
status line once confirmed — phase count and size mix.

## Step 8 — Security Check

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-security.sh" "<repo-root>" > /tmp/cfq-sec.json
jq -c '{available, sources, counts, fixable}' /tmp/cfq-sec.json
```

`available == false` → print the `hint` once, never mention it again. Findings present → state the
count per severity. Only when `fixable.critical`/`fixable.high` > 0: one `AskUserQuestion` asking
whether a security phase should join the batch (suggested first, since it's independent).
Anything below that stays a warning line, no further planning. Store the snapshot after parking
with `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-report.sh" security "<batch-dir>" "$(cat
/tmp/cfq-sec.json)"` so `ifq` can diff it later. Print the `Security` status line — count per
severity, or `➖ no findings`.

## Step 10 — Park

Entering this step closes `PLANNING` and opens `POSTCHECKS`.
- Repo root: `git rev-parse --show-toplevel`. No repo → report and abort.
- Batch directory name `<YYYY-MM-DD>-<topic-slug>` (slug in `codeLanguage`, lowercase, hyphen-separated,
  ASCII only — no umlauts, it becomes a git branch name); write `NN-<slug>.md` per phase into it, numbered
  ascending.
- `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-park.sh" "<repo-root>" "<batch-dir-name>" "<high|normal>"
  [<dependsOn-entry>...]` creates the directory, writes `.priority`/`.dependsOn` (Step 5's dependency, if
  any; `.priority` only when Step 7's flag answer was high), ensures the local git-exclude entry, and
  registers the repo — idempotent, safe to re-run.
- Write `<batch-dir>/.batch-context.md` — batch-wide context, replacing the old practice of writing
  Grilling decisions into the first phase file. Read `references/batch-context.md` and follow it.

Print four status lines: `Park` (file count and batch dir, also covers the Step 8 snapshot),
`Batch Context` (sections written, or `➖ Goal only`), `Git Exclude`, `Registry`.

## Step 10a — New Repo: Config Overview

Determine this **before** Step 10 calls `cfq-park.sh` (registry `add` is a side effect of that):
`"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-registry.sh" list | grep -qxF "<repo-root>"`. A match (already
known) → skip, print `➖ Config          known repo`, straight to Step 11. No match (genuinely new)
→ read `references/config-overview.md` and follow it, then print the `Config` status line.

## Step 11 — Plan Lint

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-lint.sh" "<batch-dir>"`. Findings are fixed
**immediately** and the lint re-run until it's clean — a batch never goes into handoff with open
lint findings. `warn:` lines (an unresolvable `.dependsOn` edge) are mentioned but don't block.
Once clean, `rm -f "<batch-dir>/.planning"` — the batch is now complete and consistent, so `/ifq`
may pick it up. Print the `Lint` status line — clean pass, or the fixed finding on re-check.

## Step 12 — Maintenance

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-maintenance.sh" due "<repo-root>"`. `OFF` or `NOT_DUE <n>`
→ print the `Maintenance` status line and move on, nothing is loaded. `DUE <n>` → read
`references/maintenance.md` and follow it.

## Step 13 — Telemetry and Sync

Run `cfq-telemetry.sh record "<batch-dir>" planning` then `cfq-telemetry.sh sync "<repo-root>"`
(both via `${CLAUDE_PLUGIN_ROOT}/scripts/`). Failures of either call are non-fatal and get one
line in the final report, not a comment. Print the `Telemetry` status line.

## Step 14 — Final Report

A `RESULT · plan-for-queue` header, then a label/value list under the `Output Format` padding rule: `Batch`
(absolute path) · `Phases` (in order, each with its size) · `Priority` (only when Step 7's flag
answer was high, omit the line entirely otherwise) ·
`Waiting on` (the `.dependsOn` edge and its reason, omit the line entirely when there is none) ·
`Cost` (interview depth, turns, tokens, model, effort) · `Security` (count, "unavailable"+hint, or
"no findings") · `Handoff` (`/clear` → `/model <first implModels>` → `/ifq`). If a cleanup batch
came out of Step 12, print a second `RESULT · plan-for-queue` block the same way, noting it can be
worked off independently — no repetition of the plan contents, that's what the files are for.

## Phase File Structure

Unchanged from the template: Size (`S`/`M`/`L`, own heading) · Context · Affected Files (always
absolute paths) · Changes (copy-ready) · Reuse · Dependencies · Verification (with output
filtering). Plus the conventions:
absolute paths, no project-specific proper nouns in test data, token hygiene in the verification
section, and the verification must check the real path the user actually takes.
