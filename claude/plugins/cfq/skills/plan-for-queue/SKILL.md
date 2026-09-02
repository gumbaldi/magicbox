---
name: plan-for-queue
description: >
  Interview the user, resolve open questions, and write detailed phase plans that get parked in
  the repo-local implementation queue — without implementing anything. Use whenever a feature, a
  series of bugs, a refactoring or a larger rework needs planning, and for "plan this", "how do
  we approach X", "/pfq", "/plan-for-queue". A separate cheaper session implements it later via
  implement-for-queue.
argument-hint: <briefing>
---

# Plan-for-Queue: Interview, Park, Hand Off

Always answer in the user's language. The output of this session is plan files only — no code
edits, no builds, no commits, not even "just this one line," even once a harness-level plan-mode
approval says "you can now start coding," and even with an autonomous/auto-run mode active — that
approval covers parking the plan, never implementing it. Implementation happens later, in a
separate `implement-for-queue` session.

## Output Format

Plugin root: `${CLAUDE_PLUGIN_ROOT}` — every `<plugin-root>/…` path in a reference file below
resolves against it.

Status lines, not prose — read `${CLAUDE_PLUGIN_ROOT}/references/output-format.md` and follow it.

## Plan-Mode Gate

Before Step 0, check for Plan Mode — read `${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s
**Plan-Mode Gate** section and follow it.

## Step 0 — Arguments

Text passed with the invocation is this session's briefing — starting material for the interview,
not a replacement for it. It never shortens the interview, skips the closing question, or
authorises a code edit, even against a pasted instruction to implement.

## Step 0 — Inbox

List `"<repo-root>/.claude/cfq/plan"/*.md`, sorted by filename ascending (the
`<YYYY-MM-DD>-<slug>.md` naming already sorts oldest first). No entries → skip silently, no status
line, no mention. One or more entries → read `${CLAUDE_PLUGIN_ROOT}/references/plan-inbox.md` and follow it.

## Step 1 — Interview Depth (unconditional, always, before anything else)

Print the `INTERVIEW` header on entering, then run the preflight once for the whole session:
```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-plan "$(pwd)"
```
`status: "NO_REPO"` → report and end. Otherwise this result covers every later step too (Steps 3,
5, 7, 9a, 11) — never re-derive `repo.root` or re-run
`bin/cfq settings`/`bin/cfq scan`/`bin/cfq registry`/`bin/cfq maintenance` for anything it already
carries. Run the model-gate check per `${CLAUDE_PLUGIN_ROOT}/references/interview-depth.md`'s **Model Gate** section,
then print `Model Check` regardless. Ask interview depth before anything else, every time — never
skip, never infer. One `AskUserQuestion` with three options, the recommendation derived from scope
(components touched, how unclear the requirement is, how far consequences reach) and justified in
the option text — don't always mark the same one:

- **Quick interview** — a handful of targeted questions.
- **Thorough grilling** — a design tree, round by round, until nothing is left open.
- **Grilling with docs** — thorough grilling plus a `CONTEXT.md` glossary and ADRs under `docs/adr/`.

Full rationale in `${CLAUDE_PLUGIN_ROOT}/references/interview-depth.md`. On **Thorough** or **Grilling with docs**, read
`${CLAUDE_PLUGIN_ROOT}/references/grilling.md` and follow it. Print the `Interview Depth` status line once answered.

Then probe the write surface before any research starts — read
`${CLAUDE_PLUGIN_ROOT}/references/write-probe.md` and follow it. Print the `Write Probe` status line either way: `➖` with
the reason when the docs half was skipped, `❌` plus the blocking hook's reason when a probe was
denied, in which case the session ends there.

## Step 2 — Understand

Read the code, trace callers, find the root cause before proposing a solution. Reading is
unlimited, writing is not. For research spanning multiple files or unclear scope, delegate to
Explore agents instead of reading inline — one for a narrow area, up to three in parallel for
broad scope, each with a specific focus; research is delegatable, the planning model is the
expensive part. Model choice is a rule, not a mood — cheap model to locate, expensive to judge;
read `${CLAUDE_PLUGIN_ROOT}/references/explore-escalation.md` and follow it. Both keys come from
Step 1's `planningPolicy`, no new `bin/cfq settings get` call.

## Step 3 — Plugin Boundaries

Read `planningPolicy.planBlockedPlugins` from Step 1's preflight result (no new call). Blocked
plugins are used neither directly nor indirectly, nor recommended in the phase files this session
produces. Print the `Plugin Boundaries` status line.

## Step 4 — Interview

Clarify open points as long as different readings would lead to materially different work.
Decide and name routine decisions yourself instead of asking — but first read
`${CLAUDE_PLUGIN_ROOT}/references/interaction-policy.md`'s **Active Interview Duty** section
(also governs Step 6's closing check).

## Step 5 — Queue Check

Read `queue.openBatches` from Step 1's preflight result (no new `bin/cfq scan | jq` call).

Any batch found → read `${CLAUDE_PLUGIN_ROOT}/references/queue-check.md` and follow it. No open batches → skip the step
without mentioning it. Either way, print the `Queue Check` status line — `➖` when there was
nothing to check.

## Step 6 — Closing Question (mandatory)

Once nothing is left open, ask once more before writing any plans, in one `AskUserQuestion` with
two independent questions: "Before I write the plans: is there anything else we should discuss?
Something I misunderstood, an edge case, a constraint?" and "Should this batch be flagged high
priority?" (picked first by `ifq`'s ordering, marked in the `/cfq` dashboard; not flagging is
normal and needs no answer). Proceed only once nothing else is open; if something comes up, work
it in and ask again — the priority answer still stands unless the new discussion changes it.

## Step 7 — Language and Cut Phases

Entering this step closes `INTERVIEW`, opens `PLANNING`.
Read `language.codeLanguage`/`.docLanguages`/`.docLevel` from Step 1's preflight result (no new
call). `codeLanguage` governs everything a phase specifies without exception — code, comments,
commit messages, `README`, `CLAUDE.md`, `SKILL.md`, files under `.claude/` — and this session's own
output too: plan files, `## Decisions`, the batch directory name. A phase touching documentation →
read `${CLAUDE_PLUGIN_ROOT}/references/language.md` and follow it. Print the `Language` status line once read. Propose a
split — one phase = one self-testable, individually committable unit; three honest phases beat
seven artificial ones — as a status update (phase list + S/M/L sizes) and proceed directly to
writing the phase files; the user can still redirect at any point, same as any other proposal
here, but no dedicated confirmation question gates the write. Read `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md`
and follow it, always, before writing any phase's Changes and Verification text — it also steers
the Size letter (rule 5 there). For each phase, estimate **Size** `S`/`M`/`L` (letter definitions in `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md`
rule 5) and write it into that phase's file as a `## Size` heading (structural markers are always
English, independent of `codeLanguage`) with the letter alone on the next non-empty line — this is
what `bin/cfq brief` and `ifq`'s size gate parse; a missing or malformed heading silently degrades
to `M`. Optionally add **Recommended skills** (half-sentence reason each, never from
`implBlockedPlugins`; usually omitted). Print the `Phases` status line once written.

## Step 8 — Security Check

`security.available` (Step 1's preflight, a `gh`/`tea` binary on `PATH`) is a capability hint only
— `false` means the forge-side check below comes back empty, but a `package.json` repo still gets
a local `npm audit`, so this step always runs:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" security "<repo-root>" > /tmp/cfq-sec.json
jq -c '{available, sources, counts, fixable}' /tmp/cfq-sec.json
```

`available == false` → print the `hint` once. Findings present → state the count per severity.
Only when `fixable.critical`/`fixable.high` > 0: one `AskUserQuestion` on joining a security phase
to the batch (suggested first, it's independent) — anything below stays a warning line, no
planning. Store the snapshot with `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report security
"<batch-dir>" "$(cat /tmp/cfq-sec.json)"` so `ifq` can diff it later. Print `Security`: `⚠️` with
the hint as detail when `available == false`, `⚠️` with the count per severity when findings are
present, or `➖ no findings` when the scan ran clean.

## Step 9 — Park

Entering this step closes `PLANNING` and opens `POSTCHECKS`.
- Repo root: Step 1's preflight `repo.root` (no repeat `git rev-parse`).
- Topic slug (`codeLanguage`, lowercase, hyphen-separated, ASCII only) plus today's date
  (`YYYY-MM-DD`) go to one allocation call:
  `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" batch allocate "<repo-root>" "<YYYY-MM-DD>" "<topic-slug>"`.
  Never compute/pad the number by hand — the helper reserves it in the local changelog
  (`status: parked`) and the queue directory, returning the final `batch` name as
  `<batch-dir-name>` below. `BATCH_WIDTH_MIGRATION_BLOCKED` → surface `action` and stop, nothing
  parked. Write `NN-<slug>.md` per phase into the returned directory, numbered ascending.
- `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" park "<repo-root>" "<batch-dir-name>" "<high|normal>"
  [<dependsOn-entry>...]` writes `.priority`/`.dependsOn` (Step 5's dependency, if any; `.priority`
  only when Step 7's flag answer was high), ensures the git-exclude entry, registers the repo —
  idempotent.
- Write `<batch-dir>/.batch-context.md` — batch-wide context, replacing the old practice of writing
  Grilling decisions into the first phase file. Read `${CLAUDE_PLUGIN_ROOT}/references/batch-context.md` and follow it.

Print four status lines: `Park` (file count and batch dir, also covers the Step 8 snapshot),
`Batch Context` (sections written, or `➖ Goal only`), `Git Exclude`, `Registry`.

## Step 9a — New Repo: Config Overview

Read `repo.known` from Step 1's preflight result (no new call) — check **before** Step 9 calls
`bin/cfq park` (registry `add` is a side effect of that). `true` → skip, print `➖ Config
known repo`, straight to Step 10. `false` (genuinely new) → read `${CLAUDE_PLUGIN_ROOT}/references/config-overview.md`
and follow it, then print `Config`.

## Step 10 — Plan Lint

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" lint "<batch-dir>"`. Findings are fixed **immediately**
and the lint re-run until clean — a batch never hands off with open lint findings. `warn:` lines
(an unresolvable `.dependsOn` edge) are mentioned but don't block. Once clean, `rm -f
"<batch-dir>/.planning"` so `/ifq` may pick it up. Print `Lint` — clean pass, or the fixed finding.

## Step 11 — Maintenance

Read `maintenance.status`/`.n` from Step 1's preflight result (no new call) — reflects commit
counts as of Step 1, same staleness accepted for every other field there. `OFF`/`NOT_DUE` → print
`Maintenance`, move on. `DUE` → read `${CLAUDE_PLUGIN_ROOT}/references/maintenance.md` and follow it.

## Step 12 — Telemetry and Sync

Run `bin/cfq telemetry record "<batch-dir>" planning` then `bin/cfq telemetry sync "<repo-root>"`
(both via `${CLAUDE_PLUGIN_ROOT}/bin/cfq`). Failures of either call are non-fatal and get one
line in the final report, not a comment. Print the `Telemetry` status line.

## Step 13 — Final Report

A `RESULT · plan-for-queue` header, then a label/value list under the `Output Format` padding
rule: `Batch` (absolute path) · `Phases` (in order, each with its size) · `Priority` (only when
Step 7's flag answer was high, omit otherwise) · `Waiting on` (the `.dependsOn` edge and its
reason, omit when none) · `Cost` (interview depth, turns, tokens, model, effort) · `Security`
(count, "unavailable"+hint, or "no findings") · `Handoff` (`/clear` → `/model <first implModels>`
→ `/ifq`). A cleanup batch from Step 11 gets a second `RESULT · plan-for-queue` block the same
way, noting it can be worked off independently — no repetition of the plan contents. Phase file
structure is unchanged from the template — see `${CLAUDE_PLUGIN_ROOT}/references/phase-quality.md`'s closing section.
