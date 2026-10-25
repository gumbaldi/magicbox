# ifq: Arguments, Model Gate, Batch Selection and Gates

## Contents

- Arguments
- Model Gate Stop
- Batch Selection Rules
- Briefing Warnings
- Lint Gate

## Arguments

`$ARGUMENTS`, trimmed of surrounding whitespace and compared case-insensitively, maps onto flags
for the same `preflight-impl` call **Batch Selection** already makes — never a second call:

| Argument text | Flag(s) added | Meaning |
|---|---|---|
| `resume` | `--intent resume` | Continue the in-progress batch, skipping the start gate. Falls back to the normal gate (`startGate.reason: "resume-nothing-in-progress"`) when nothing is in progress — it never starts something new silently. |
| `start` | `--intent start` | Take the in-progress batch, or the ordered next selectable one, skipping the start gate. |
| `start <batch>` | `--intent start --select <batch>` | Same as `start`, naming which batch. |
| `skip <NN> [reason…]` | none | Skip phase `<NN>` of the selected batch, then continue as a normal session — see below. |
| `unskip <NN>` | none | Bring a skipped phase back, then continue as a normal session. |
| anything else | `--select <text>` (today's meaning, unchanged) | A hint that narrows batch selection, per **Batch Selection Rules** — not a keyword. |

`--intent resume` combined with `--select` is rejected by the preflight itself (`INVALID_ARGS`) —
`resume` always targets whichever batch is already in progress, never a chosen one; this parsing
never produces that combination, so it should never actually fire. `MULTIPLE_IN_PROGRESS`,
`BLOCKED`, `NO_BATCH` and `SELECT_UNAVAILABLE` stop exactly as they do without a keyword —
`startGate` comes back `null` on every one of those, so neither keyword has anything to skip.

**`skip` and `unskip`** pass no `--intent`. Run the preflight as usual; on `status: "OK"` call
`bin/cfq phase skip "<batch-dir>" <NN> --reason "<reason>"` (`phase unskip "<batch-dir>" <NN>` for
`unskip`; `--reason` only when text was given) for the batch the preflight resolved, print the
returned `statusLines` entry verbatim, re-run the preflight with `--select <batch>` and continue from
**Batch Briefing** as a normal session — briefing, start gate and the next phase follow. A non-`OK`
result of the verb is printed as `❌ Skip` with the returned detail and ends the session, nothing
else touched. Only the user skips, see `<plugin-root>/references/ifq-phase.md`'s **Skipping a
Phase**.

## Model Gate Stop

The running model's name is in your system prompt's environment block; `policy.allowAnyModel:
true` → skip this check, otherwise it must match one of `policy.implModels` (substring match:
`sonnet` matches `claude-sonnet-5`) — or, when `policy.orchestratorMode` is `true`,
`policy.orchestratorModels` instead (already carries the fallback to `implModels` when empty, no
extra logic here). No match → **stop immediately**, touch nothing, report the allowed models, that
`/model <x>` then `/ifq` is the way forward, and that `CFQ_IMPL_MODELS`/`cfq` changes the list.
Print `Model Gate` — the preflight's own `statusLines` entry — either way, before this check runs:
it already resolved which list applies (or that `allowAnyModel` skips the check entirely); the
actual match needs the running model's name, which only the session itself knows.

## Batch Selection Rules

`bin/cfq preflight-impl`'s `selection` object carries `blocked`, `planning`, `inProgress`, and
`multipleInProgress` — the filters and stop conditions applied before any picker runs. The
preflight itself already excludes blocked/planning/other-in-progress batches from
`selection.selectable`; this section only covers the wording each case needs.

`selection.queueText` is the aligned `QUEUE · <n> open` listing rendered from those same fields —
every open batch, selectable, blocked and planning alike, each row naming why a non-selectable one
can't be picked. It rides on every status this preflight can return, the four early-return ones
(`MULTIPLE_IN_PROGRESS`, `SELECT_UNAVAILABLE`, `BLOCKED`, `NO_BATCH`) included, `null` only when the
queue itself is empty. Print it exactly as returned — no rewording, no re-deriving it from the raw
`selectable`/`blocked`/`planning` arrays.

**Blocked** batches (`selection.blocked`, each `{name, dependsOn, unknownDeps}`) are never offered.
If `status` is `BLOCKED`, print the wait list (batch → waiting on `dependsOn`) and end — never fall
back to a blocked one. `unknownDeps` (an unresolvable `.dependsOn` name) is shown at selection time
with `⚠️` and the unresolvable name but doesn't block (`/cfq` fixes it) — one sentence, no more.

**Planning** — a batch `/pfq` is still writing (`.planning` marker not yet cleared by its lint
step) — is never offered either, separately from the `dependsOn` wait list. For every name in
`selection.review` (a batch held at its plan review gate, always also in `selection.planning`):
"Batch `<name>` is waiting for its plan review — run `/pfq` to continue the review, or release it
unreviewed with `bin/cfq batch ready "<batch-dir>"`." It never becomes selectable on its own. For
every other name in `selection.planning`: "Batch `<name>` is still being planned — try again once
`/pfq` finishes. If no `/pfq` session is still running for it, `bin/cfq batch ready "<batch-dir>"`
clears the marker; otherwise it becomes selectable on its own once the marker is older than
`sessionStaleSeconds`." One line per such batch, no more.

**In-progress invariant.** `status: "MULTIPLE_IN_PROGRESS"` (`selection.multipleInProgress`
non-empty) means more than one batch violates the one-in-progress-batch-per-repo invariant: **stop
immediately**, touch nothing, name every batch in the list, and say this must be resolved via
`/cfq` (archive or reprioritize one) before `/ifq` can proceed — never silently pick one, never
fall through to the picker. A batch that is both blocked and in-progress is excluded from this
check by the blocked filter (it doesn't reach `selection.selectable`/`.inProgress` at all) and
surfaces only through the wait-list path, like any other blocked batch. A non-archived batch with
no open phase but at least one done one (`bin/cfq finish` never ran for it) counts as in progress
too — it resumes straight into **Batch Done** instead of vanishing from selection, and participates
in this same `MULTIPLE_IN_PROGRESS` check like any other in-progress batch.

**Multiple selectable batches.** When `selection.inProgress` is `null` and `selection.selectable`
has more than one entry, the preflight already picked `selection.selectable[0]` (sorted
flagged-first-then-name) — `batch`/`nextPhase`/`branch`/`resume`/`contextGate` come back resolved
for it, no question. Arguments naming a specific batch re-run the preflight with `--select <batch>`
instead of taking the ordered default. `status: "SELECT_UNAVAILABLE"` means the named batch isn't
selectable (blocked, still planning, awaiting review, or unknown) — report why, from `selection`, and end; never
falls back to the ordered default. **Never two batches in the same session**, not even once the
first finishes and context is still free — different plans belong in separate context windows.

`selection.inProgress` non-null → that batch was auto-selected already (`batch`/`nextPhase`/
`branch`/`resume`/`contextGate` are already resolved for it) — straight to **Batch Briefing**.
`nextPhase: null` here means every phase already moved to `done/` but `bin/cfq finish` never ran —
**Batch Briefing** still acquires the lock and resolves the branch as usual, then skips ahead
straight to **Batch Done**. `status: "SELECT_UNAVAILABLE"` (arguments named a batch that isn't
selectable) → report why, from `selection` (blocked / still planning / awaiting review / not found), end — never
falls back to the ordered default. `selection.selectable` has **zero** entries and `status` isn't
`NO_BATCH`/`BLOCKED` → treat as `NO_BATCH`.

Print `Batch` in every outcome above that reaches **Batch Briefing** — the preflight's own
`statusLines` entry, already the right one of its four wordings (`--select` given, in-progress
resumed, the lone selectable batch, or the ordered pick among several), printed exactly as
returned — the distinguishing condition lives in the script, not here.

## Briefing Warnings

`contextGate.verdict` is `WARN` → print one warning line *above* the briefing, naming the reason in
the user's language and the concrete numbers from `contextGate.note` (e.g. the five-hour budget is
at 89% against a 70% threshold); state plainly that this is a budget warning, not a blocker, and
that the phase runs normally if started — wording per `<plugin-root>/references/ifq-phase.md`'s
**Phase Announcement**; `batch.consistency == "divergent"` adds one more such line naming the
repair command (`bin/cfq batch verify "<repo-root>"`), never blocking.

## Lint Gate

`lint` is the same `bin/cfq lint <batch-dir>` check `/pfq` already runs at Plan Lint, right before
handoff — run again here since a plan file is plain Markdown the user may edit by hand between
`/pfq` and `/ifq`, and a hand edit that breaks its structure would otherwise go unnoticed until a
later deterministic script misparses it mid-implementation. `lint.clean: false` → print `Lint` (its
`lint.findings` already rendered as `   └ ` sub-lines) and **end the session immediately** — before
the lock, the branch, or any file is touched — the user fixes the phase files by hand or re-plans
the batch with `/pfq`. Warnings never block and `lint.clean` stays `true` when `lint.warnings` is
non-empty; the preflight's `Lint` line lists every one of them as a sub-line and is printed as
returned. Typical warnings are an unresolvable `.dependsOn`, a `## Changes` section without
numbered steps, an unchecked `## Model` heading when `implModels` cannot be read, and `stale-new`
on the next pending phase's own `(new)` files, which means that phase was started before and
created them. The list is a set of examples, not a complete one. `lint.clean: true` → print `Lint`
and continue straight to lock acquisition.
