# Phase Quality: Test-First, Risk Flags, Bundled Verification

Read unconditionally in **Language and Cut Phases**, before any phase's Changes and Verification
text is written — not only for a phase that moves, extracts, or reuses existing logic verbatim, or
introduces non-trivial logic of its own (a branch, a loop, a parser, a multi-step resolution chain,
an adapter). Rules 1-4 name their own trigger condition inline, so a phase outside that condition
simply has nothing to apply for that rule; rule 5 steers the phase's `Size` letter; rules 6 and 7 apply
to every phase without exception; rule 8 is optional. This file governs what a phase's text must contain once it
exists; `<plugin-root>/references/plan-self-critique.md`'s **Self-Critique of the Phase Cut**
governs whether the phase should exist at all — keep the two separate.

The eight rules below are a standing checkpoint against runaway debugging tokens and untested
verbatim moves, not a one-time lesson repeated only in a post-mortem.

## Contents

- 1. Test-first, not shell exploration
- 2. Verbatim reuse is not automatically correct
- 3. Debugging stays out of the main context
- 4. Smoke tests are bundled, not serialized
- 5. Size reflects verify-the-reuse work, not just new lines
- 6. `## Affected Files` is the complete list
- 7. `## Changes` is a numbered step list
- 8. `## Model` names the smallest model that fits
- Phase File Structure

## 1. Test-first, not shell exploration

A phase whose Changes move, extract, or otherwise touch non-trivial logic writes the test file
**before** the implementation file — always, not just when time allows. The phase's `Changes`
section states this order explicitly and names concrete fixture scenarios: the routine case, at
least one edge case, and at least one case that should fail or fall back. Exploring the behaviour
interactively in a shell first and writing the test afterward to match what was learned inverts the
guarantee a test is supposed to give — it ends up describing what the code does, not checking what
it must do.

## 2. Verbatim reuse is not automatically correct

Code a phase copies without modification from an existing file — "reuse as-is", "move as-is", "lift
verbatim" — gets flagged, not waved through. In that phase's `Affected Files` or `Reuse` entry,
mark the carried-over block with a trailing `(verbatim)` marker — the same structural,
English-regardless-of-`codeLanguage` convention as the existing `(new)` marker. The phase's
`Verification` section then names one fixture-backed check that exercises that specific block in
its new location: moving code is a claim that its behaviour is preserved, and that claim is exactly
what an existing test suite may never have covered if it never exercised that path before.

## 3. Debugging stays out of the main context

A phase whose Verification involves exploring or debugging something with potentially large output
— a trace, a log, several iterative test runs — states the requirement generically: run it through
whatever sandboxed execution/processing tool is available in that future session rather than raw
`Bash`, so only the derived answer enters the conversation, not the raw bytes. No specific tool or
plugin is named here — whichever such tool exists at implementation time satisfies the rule. Where
no sandboxed tool is available, or a raw trace truly cannot be avoided (e.g. `bash -x` with nothing
else to run it through), the phase says to pipe it straight into a filter — `grep`, a line range, a
summarizing script — never to read the unfiltered output directly.

## 4. Smoke tests are bundled, not serialized

Any exploratory "does this work for case A, B, C" round belongs inside the test file as cases (or
one parametrized run), not as a series of separate manual shell invocations typed one at a time.
The phase's `Verification` section names one command that runs all of them together.

## 5. Size reflects verify-the-reuse work, not just new lines

The three letters: `S` one file and one test, `M` several files or a new script, `L` a new script
**with** a new test or a skill rework — this is what steers whether `ifq` even starts a phase.

A phase carrying `(verbatim)` blocks per rule 2 costs more than its new-code line count alone
suggests — writing the fixture, running it, and fixing whatever the move actually broke is real
work a pure-new-code phase of the same file count doesn't have. Bump the `Size` letter one step
above what raw file/line volume would otherwise suggest (`S` → `M`, `M` → `L`) for any phase where
this applies — decide it here, at planning time, not discover it mid-`ifq` as an underestimate.

Write the estimate into that phase's file as a `## Size` heading (structural markers are always
English, independent of `codeLanguage`) with the letter alone on the next non-empty line — this is
what `bin/cfq brief` and `ifq`'s size gate parse; a missing or malformed heading silently degrades
to `M`. Optionally add **Recommended skills** (half-sentence reason each, never from
`implBlockedPlugins`; usually omitted).

## 6. `## Affected Files` is the complete list

This rule applies to every phase, without exception — unlike rules 1-4, it names no trigger
condition because there isn't one.

`## Affected Files` names **every** file the phase will change or create — not the interesting
ones, not the ones the phase is "about". The implementer is measured against this list
(`<plugin-root>/references/ifq-phase.md`'s `## Stop Rule`), so an incomplete list is a planning
defect, not an implementation defect.

Before the list is considered done, walk it once against this checklist. Each item names what to
look for; a phase that legitimately has none of a category simply has nothing to add for it:

- the test file(s) that cover the changed code — new or existing
- the changelog, version, or release-notes file the repo maintains
- any registry, index, manifest, or dispatcher that has to learn about a new entry (in this repo:
  `bin/cfq`, `.claude-plugin/marketplace.json`)
- the README or documentation section that describes the behaviour being changed
- generated or derived files that have to be regenerated
- cross-references elsewhere that point at what is being renamed, renumbered, or moved

`(new)` marks a file on the phase that creates it, and only there. A later phase of the same batch
that extends the file, and a phase of a batch whose `.dependsOn` names the creating batch, list the
path bare. `bin/cfq lint` accepts a bare path that is not on disk while the creating phase is
pending, and reports `duplicate-new` when a second phase marks the same path. A bullet is never
reworded to keep a path out of lint: `bin/cfq overlap` reads the same bullets.

Only list what the phase demonstrably touches, never what it might touch. If the planner cannot
decide whether a file is in scope, that uncertainty is a research task for the planning session,
not a hedge in the plan — resolve it before parking: `bin/cfq overlap` intersects
these lists across open batches to derive conflicts and `.dependsOn` edges, and a wishlist entry
produces a phantom conflict that costs a real session.

## 7. `## Changes` is a numbered step list

This rule applies to every phase, without exception — like rule 6, it names no trigger condition.

Every phase's `## Changes` is a numbered list at column 0. Each step opens with one sentence that
stands on its own and says what changes and where; everything an implementer needs beyond that goes
into nested bullets or a fenced block below it. No prose before step 1 — a test-first order (rule 1)
is expressed by making the test step 1.

The review digest (`bin/cfq brief --review`) and `/ifq`'s phase announcement show exactly these
opening sentences, so they are what the user approves.

`bin/cfq lint` reports a missing numbered step as `warn: … changes-steps`, never as a finding, so an
older batch still starts.

## 8. `## Model` names the smallest model that fits

Optional. Without the heading a phase runs on the default implementation model. Write the heading
— `## Model`, then the model name alone on the next non-empty line, placed after `## Size` — only
to move a phase off that default, and only with a name from `planningPolicy.implModels`
(**Start Block**'s preflight result); `bin/cfq lint` rejects any other.

A smaller model than the default fits when all of these hold:

- Size is `S`.
- `## Changes` spells out every edit; no step asks the implementer to decide, design or choose.
- `## Verification` is one deterministic command with a stated expected result.
- No `(verbatim)` block, and no rework of skill, reference or agent prose.
- Apart from tests, the phase touches at most two files.

One condition failing means no heading. A larger model than the default is planned the same way,
for a phase whose `## Changes` cannot avoid a design decision. The first entry of `implModels` is
the default; when the list has one entry, never write the heading.

---

None of this adds a new required heading. Rules 1-7 live inside a phase's existing `Changes`,
`Affected Files`/`Reuse`, and `Verification` prose — `bin/cfq lint`'s heading checks are unaffected;
rule 8's heading is optional.

## Phase File Structure

Template: Size (`S`/`M`/`L`, own heading) · Model (optional, own heading) · Context · Affected Files (always
absolute paths) · Changes (copy-ready) · Reuse · Dependencies · Verification (with output
filtering). Conventions: absolute paths, no project-specific proper nouns in test data, token
hygiene in verification, and verification must check the real path the user actually takes.
`Reuse` entries that carry logic over verbatim, and `Verification`'s test-first/bundled-smoke/
sandboxed-debugging requirements are rules 2-4 above.
