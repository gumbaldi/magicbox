# Plan Review: The Gate Between a Written Plan and `/ifq`

Only read at pfq's **Review Gate** step, and at **Inbox** when a review is waiting
(**Resuming a Review**). The plan files are written and lint-clean by now; this file holds the batch
back until the user has seen what was planned and decided what happens to it. The gate is always
on — there is no setting that skips it.

## Entering the Gate

`bin/cfq batch review "<batch-dir>"` replaces `.planning` with `.review`: the batch stays held for
`/ifq`, and unlike `.planning` the marker never goes stale. Print the `REVIEW` section header, then
run `bin/cfq brief "<batch-dir>" --review --gate` and place its output exactly as returned — no
rewording, no translation, in the plan's own language — at the top of **The Question**'s `question`
text, followed by the four options. Text printed before the dialog is not visible while it is open,
so nothing of the gate goes before the question. The full digest is
`bin/cfq brief "<batch-dir>" --review`; run it only when the user asks to read it.

## The Question

One `AskUserQuestion`, in the user's language, four options, none labelled as recommended:

- **Release** — the batch becomes available to `/ifq`.
- **Request changes** — the user says what should differ, the planner edits the plan files.
- **I'll edit the files myself** — the planner waits.
- **Discard** — the batch goes to the cfq trash, restorable.

A free-text answer is a change request. The phase list at the top of the `question` text is the
question's context (`interaction-policy.md`'s **Decision Question Context**).

## Request Changes

Edit the phase files and `.batch-context.md` with `Write`/`Edit` — plan files only, never code.
Adding, dropping or reordering a phase keeps the numbering gapless and updates every
`## Dependencies` reference. A change the user asked for is made, not questioned — after the one-time objection of
`interaction-policy.md`'s **Challenge Duty**, when there is one — including
dropping a phase, which is then recorded with its reason in `.batch-context.md`'s `## Non-Goals`.
Then **Re-check**.

## I'll Edit the Files Myself

Print one line naming the batch directory and stating that every `NN-*.md` and `.batch-context.md`
in it may be edited, then end the turn with one sentence asking the user to say when they are done.
No `AskUserQuestion`, no polling. When the user returns: **Re-check**.

## Re-check

In this order:

1. `bin/cfq lint "<batch-dir>"` until clean — `warn: … changes-steps` lines included.
2. Any phase's `## Affected Files` changed → re-run `bin/cfq overlap "<repo-root>"` and `bin/cfq
   park` (idempotent) so `.dependsOn` matches.
3. Run `<plugin-root>/references/plan-self-critique.md`'s **The Post-Write Audit** again only when
   more than one phase changed, the phase order changed, or an `## Affected Files` list changed. A
   text change inside one phase gets lint only. The audit runs through its four steps — `batch audit
   start`, the Explore agent, the `⏳ Phase Audit` wait that ends the turn, then the fixes and `batch
   audit done` — and the re-check continues with step 4 once the result is in.
4. Run `bin/cfq brief "<batch-dir>" --review --gate --changed`.
5. `bin/cfq batch review "<batch-dir>"` to refresh the snapshot.
6. Ask **The Question** again, with step 4's output exactly as returned at the top of its
   `question` text.

## Release

`bin/cfq batch ready "<batch-dir>"`. Print `Review` as `✅ released`, plus `· <n> revisions` when
there was at least one round.

## Discard

`bin/cfq trash put "<repo-root>" "<batch-dir>" --reason "discarded at plan review"`. Print `Review`
as `➖ discarded · restorable via bin/cfq trash restore`. Skip `telemetry record` — the batch
directory is gone. **Final Report** then prints only `Batch` (the name), `Review` and — when `park
--from-plan` already consumed an inbox entry — that entry's path under `plan/done/`, so the user can
re-queue it.

## Resuming a Review

Read from **Inbox** when the preflight's `queue.awaitingReview` is non-empty and `/pfq` was invoked
without arguments. One `AskUserQuestion` before the inbox question: continue the review of the named
batch (the oldest when several wait; the others are named in the question text), or plan something
new.

- **Continue** — skip the interview and every planning step. An `awaitingReview` entry with
  `audit: true` (an interrupted audit) goes to **The Post-Write Audit** first — start again, wait,
  done — and then to **Entering the Gate**; any other entry goes straight to **Entering the Gate**
  for that batch (`batch review` keeps the marker's `since`). **Telemetry and Sync** is skipped — the
  planning record was written by the session that planned it. **Final Report** prints `Batch`,
  `Review` and `Handoff`.
- **Plan something new** — the waiting batch stays held, untouched.

## Leaving Without an Answer

Nothing to do: `.review` holds the batch until a later `/pfq` resumes the review or `bin/cfq batch
ready "<batch-dir>"` releases it by hand.
