# Queue Entry Formats

## Contents

- Batch Allocation Errors (`cfq batch allocate`)
- Plan Entry (`plan/<YYYY-MM-DD>-<slug>.md`)
- Closing a Plan Entry (`note close`)
- Parking Out-of-Scope Work
- Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

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

A `pfq` planning session writes findings the same way `ifq` does — see
`plan-for-queue/SKILL.md`'s opening paragraph: a finding is never an implementation step, no
matter which session writes it.

Pipe the body (H1 title, then the sections below) straight into `note plan` on stdin — no temp
file, so no write-guard hook that only allows writes under `.claude/cfq/` can ever block it:

```bash
"<plugin-root>/bin/cfq" note plan "<repo-root>" "<slug>" - <<'EOF'
# Title
…
EOF
```

`note plan`/`note todo` own the date and the target path, never an agent-composed filename, and
still accept a body-file path in place of `-` for the rare case a body already lives on disk. The
heredoc delimiter is always quoted (`<<'EOF'`, never `<<EOF`) — see README.md's Hook contract for
why an unquoted one matters. Written without asking, in both modes, so `## Why Not Here` must
always state plainly that a decision on the finding is still open:

- `## Finding` — what was noticed
- `## Location` — files and locations, absolute paths
- `## Why Not Here` — why it's out of scope for the current phase, and that a decision is still open
- `## Origin` — batch and phase it came from

A `security-findings` entry whose advisories a phase of the parked batch covers names that phase
under `## Why Not Here` instead, says the entry can be closed once it lands, and carries no
"decision still open" sentence.

A finding is a *framework* finding when it is about cfq itself — a cfq skill's or reference file's
behaviour, a `bin/cfq` script, the guard, the queue layout — rather than about the repo being
worked on; it stays a framework finding even when no file can be named, since the finding is about
behaviour. A finding about *this* repo's cfq settings (a wrong `codeLanguage`, a missing per-repo
override) is **not** a framework finding, it belongs to the repo. An ordinary finding uses the call
above; a framework finding adds the `--framework` flag right after `note plan` — the flag decides
routing, the caller never picks a target repo or path. A framework finding is never reported
through `SendFeedback` or any other product-feedback channel — that channel reaches Claude Code's
maintainers, not cfq's; `note plan --framework` is the only route, and this holds in a follow-up
conversation after a `pfq`/`ifq` run has ended just as much as mid-phase. `SendFeedback` stays
correct for a problem with Claude Code itself (a harness tool, the model's own behaviour) that is
not about cfq. A framework entry's `## Origin` additionally names the repo the finding was made
in, since the entry leaves that repo.

## Closing a Plan Entry (`note close`)

An entry whose fix landed incidentally, rather than through `pfq`'s `park --from-plan`, is closed
with:

```bash
"<plugin-root>/bin/cfq" note close "<repo-root>" "<entry>" [<entry>...] --reason "<text>"
```

`<entry>` is a filename or path inside `<repo-root>/.claude/cfq/plan/` — anything outside `plan/`
fails `INVALID_PATH`, a missing entry fails `NOT_FOUND`. It appends a `## Closed` section (date +
reason) to the entry and moves it into `plan/done/`, creating that directory if absent; repeated
`<entry>` arguments close several entries in one call, all with the same reason. It never touches
`todo/` — `note sweep --close` stays the only todo closer.
When `plan/done/` already holds a file of the same name, the entry is archived as `<name>-2.md`
(then `-3`, …); nothing in `plan/done/` is ever overwritten, and the same holds for
`park --from-plan`.

## Parking Out-of-Scope Work

Work found beyond this phase's scope is always parked, never asked about: write a `plan/` entry via
`note plan "<repo-root>" "<slug>" - <<'EOF' … EOF` (`--framework` for a cfq-itself finding, rule in
this file's **Plan Entry** section above), noting a decision is still open, and name it in the
phase summary — both modes, no `AskUserQuestion`, no second attempt. While the session holds the
repo lock, `note plan`/`note todo` record the entry in the running batch's `report.json` on their
own; pass `--batch <batch-name>` only once the lock is released.

## Follow-Up (`todo/<YYYY-MM-DD>-<slug>.md`)

Same call, `note todo`: H1 title, one or two sentences describing what to do, optionally a `check:
<shell-command>` line (exit `0` means done). `note todo` prints a non-fatal stderr warning when the
body carries no `check:` line — the entry is still written, the warning only names that `note sweep`
can never close it. Plus `## Origin`, same as above. `bin/cfq note sweep`
is what executes those `check:` lines and closes the green entries — never a hand-run shell command.
Write a `check:` that asserts the *outcome*, not a count of files that happen to hold it today: the
entry asserting that four `SKILL.md` files contain a clause has been unfalsifiably red since that
clause moved into `<plugin-root>/references/output-format.md`, even though the work is long done.

Merging a batch branch is the user's own step, and no `todo/` entry is written for it. A hand-written `todo/` entry may carry its own `check:` line.

Both formats: filename `<YYYY-MM-DD>-<slug>.md`, `<slug>` normalised by `note` itself. The headings
are always English; only the prose inside them follows `codeLanguage`.
