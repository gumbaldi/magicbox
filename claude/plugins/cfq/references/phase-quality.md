# Phase Quality: Test-First, Risk Flags, Bundled Verification

Read unconditionally in Step 7, before any phase's Changes and Verification text is written — not
only for a phase that moves, extracts, or reuses existing logic verbatim, or introduces non-trivial
logic of its own (a branch, a loop, a parser, a multi-step resolution chain, an adapter). Rules 1-4
name their own trigger condition inline; a phase outside that condition simply has nothing to apply
for that rule. This file governs what a phase's text must contain once it exists;
`references/plan-self-critique.md` (Step 7a) governs whether the phase should exist at all — keep
the two separate.

This file exists because one `/ifq` phase burned far more tokens than the task itself required —
not the logic, the debugging: a raw `bash -x` trace dumped whole into context, and a dozen one-off
shell smoke tests instead of one test file. The five rules below turn that incident into a
standing checkpoint, not a one-time lesson repeated only in a post-mortem.

## 1. Test-first, not shell exploration

A phase whose Changes move, extract, or otherwise touch non-trivial logic writes the test file
**before** the implementation file — always, not just when time allows. The phase's `Changes`
section states this order explicitly and names concrete fixture scenarios: the routine case, at
least one edge case, and at least one case that should fail or fall back. Exploring the behaviour
interactively in a shell first and writing the test afterward to match what was learned inverts the
guarantee a test is supposed to give — it ends up describing what the code does, not checking what
it must do.

## 2. Verbatim reuse is not automatically correct

Code a phase carries over unchanged from an existing file — "reuse as-is", "move as-is", "lift
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

---

None of this adds a new required heading. All five rules live inside a phase's existing `Changes`,
`Affected Files`/`Reuse`, and `Verification` prose — `bin/cfq lint`'s heading checks are unaffected.

## Phase File Structure

Unchanged from the template: Size (`S`/`M`/`L`, own heading) · Context · Affected Files (always
absolute paths) · Changes (copy-ready) · Reuse · Dependencies · Verification (with output
filtering). Conventions: absolute paths, no project-specific proper nouns in test data, token
hygiene in verification, and verification must check the real path the user actually takes.
`Reuse` entries that carry logic over verbatim, and `Verification`'s test-first/bundled-smoke/
sandboxed-debugging requirements are rules 2-4 above.
