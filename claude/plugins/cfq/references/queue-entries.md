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

## Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

Same call, `note todo`: H1 title, one or two sentences describing what to do, optionally a `check:
<shell-command>` line (exit `0` means done). For the merge case: `check: git branch --merged main
| grep -q <branch>`. Plus `## Origin`, same as above.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`, `<slug>` normalised by `note` itself. The headings
are always English; only the prose inside them follows `codeLanguage`.
