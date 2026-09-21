# Queue Entry Formats

## Batch Allocation Errors (`cfq batch allocate`)

`BATCH_LEDGER_MISMATCH` means a numbered queue directory exists with no matching ledger entry.
`allocate` cannot itself produce this state — it reserves the ledger entry before creating the
directory and never rolls the reservation back on a later failure, so the recoverable half (a
ledger entry with no directory) is the only one `allocate` can ever leave behind. The error's
`action` field already names the resolved `changelogFile` path and the repair, computed, never
hardcoded:

```bash
"<plugin-root>/bin/cfq" batch reconcile "<repo-root>"          # read-only, exits non-zero on a gap
"<plugin-root>/bin/cfq" batch reconcile "<repo-root>" --fix    # reserves every orphaned directory
```

`reconcile` never deletes anything and never touches a ledger entry with no directory — a reserved
number whose batch never got parked is a legitimate abandoned reservation, not a gap to close.

## Plan Entry (`plan/<YYYY-MM-DD>-<slug>.md`)

Write the body (H1 title, then the sections below) to a temp file, then
`"<plugin-root>/bin/cfq" note plan "<repo-root>" "<slug>" "<body-file>"` — it owns the date and the
target path, never an agent-composed filename. Written without asking, in both modes, so `## Why
Not Here` must always state plainly that a decision on the finding is still open:

- `## Finding` — what was noticed
- `## Location` — files and locations, absolute paths
- `## Why Not Here` — why it's out of scope for the current phase, and that a decision is still open
- `## Origin` — batch and phase it came from

A finding is a *framework* finding when it is about cfq itself — a cfq skill's or reference file's
behaviour, a `bin/cfq` script, the guard, the queue layout — rather than about the repo being
worked on; it stays a framework finding even when no file can be named, since the finding is about
behaviour. A finding about *this* repo's cfq settings (a wrong `codeLanguage`, a missing per-repo
override) is **not** a framework finding, it belongs to the repo. An ordinary finding uses the call
above; a framework finding adds the `--framework` flag right after `note plan` — the flag decides
routing, the caller never picks a target repo or path. A framework entry's `## Origin` additionally
names the repo the finding was made in, since the entry leaves that repo.

## Parking Out-of-Scope Work

Work found beyond this phase's scope is always parked, never asked about: write a `plan/` entry via
`bin/cfq note plan "<repo-root>" "<slug>" "<body-file>"` (`--framework` for a cfq-itself finding,
rule in this file's **Plan Entry** section above), noting a decision is still open, and name it in
the phase summary — both modes, no `AskUserQuestion`, no second attempt.

## Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

Same call, `note todo`: H1 title, one or two sentences describing what to do, optionally a `check:
<shell-command>` line (exit `0` means done). Plus `## Origin`, same as above. `bin/cfq note sweep`
is what executes those `check:` lines and closes the green cards — never a hand-run shell command.
Write a `check:` that asserts the *outcome*, not a count of files that happen to hold it today: the
card asserting that four `SKILL.md` files contain a clause has been unfalsifiably red since that
clause moved into `<plugin-root>/references/output-format.md`, even though the work is long done.

For the merge case, don't hand-compose the card: `"<plugin-root>/bin/cfq" note merge-todo
"<repo-root>" "<branch>"` writes it, title, ready-to-run merge command and `check:` line together,
so the line can never be left out. Its check resolves `origin/main` first and falls back to local
`main` (`git merge-base --is-ancestor <branch> origin/main 2>/dev/null || git merge-base
--is-ancestor <branch> main`) rather than `git branch --merged main | grep -q <branch>`, which
tests only the local `main` ref and can report a branch as unmerged when the local clone is simply
behind `origin/main`. A hand-written `todo/` card for anything else may still carry its own
`check:` line.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`, `<slug>` normalised by `note` itself. The headings
are always English; only the prose inside them follows `codeLanguage`.
