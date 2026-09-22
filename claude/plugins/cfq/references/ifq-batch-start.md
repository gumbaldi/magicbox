# ifq: Batch Selection, Briefing, Branch and Resume

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
step) — is never offered either, separately from the `dependsOn` wait list: for every name in
`selection.planning`, "Batch `<name>` is still being planned — try again once `/pfq` finishes."
One line per such batch, no more.

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
selectable (blocked, still planning, or unknown) — report why, from `selection`, and end; never
falls back to the ordered default. **Never two batches in the same session**, not even once the
first finishes and context is still free — different plans belong in separate context windows.

`selection.inProgress` non-null → that batch was auto-selected already (`batch`/`nextPhase`/
`branch`/`resume`/`contextGate` are already resolved for it) — straight to **Batch Briefing**.
`nextPhase: null` here means every phase already moved to `done/` but `bin/cfq finish` never ran —
**Batch Briefing** still acquires the lock and resolves the branch as usual, then skips ahead
straight to **Batch Done**. `status: "SELECT_UNAVAILABLE"` (arguments named a batch that isn't
selectable) → report why, from `selection` (blocked / still planning / not found), end — never
falls back to the ordered default. `selection.selectable` has **zero** entries and `status` isn't
`NO_BATCH`/`BLOCKED` → treat as `NO_BATCH`.

Print `Batch` in every outcome above that reaches **Batch Briefing** — the preflight's own
`statusLines` entry, already the right one of its four wordings (`--select` given, in-progress
resumed, the lone selectable batch, or the ordered pick among several), printed exactly as
returned — the distinguishing condition lives in the script, not here.

## Batch Briefing

`batch.briefText` in the preflight result already holds `bin/cfq brief`'s output for the resolved
batch — batch name, priority, phase count, then a `goal:` line from `.batch-context.md`'s
`## Goal` (cut at about 300 characters, on a word boundary) when the batch has one, `.dependsOn` if
present, then one line per phase (number and title, size in brackets, context excerpt). Present it
as-is, compactly: no prose around it, no repetition of the plan, no commentary on the phases. A
phase file without `## Size` counts as `M`; one without `## Context` shows its title alone — an
incomplete plan is worth showing, not worth aborting over. The `goal:` line is the batch summary,
shown as-is; a batch without `.batch-context.md` or without a `## Goal` renders exactly as before,
with no `goal:` line.

`bin/cfq brief <batch-dir> --overview` is the mode the start gate itself renders (wired in by a
later phase, not this reference) — the aligned-monospace batch-overview block: header, phase
count with done/red breakdown, the wrapped `## Goal` paragraph, then the phase table with a
`done`/`open`/`red` status column. `--with-done` stays exactly as described above for any caller
that still wants the old flat listing.

## Briefing Warnings

`contextGate.verdict` is `WARN` → print one warning line *above* the briefing, naming the reason in
the user's language and the concrete numbers from `contextGate.note` (e.g. the five-hour budget is
at 89% against a 70% threshold); state plainly that this is a budget warning, not a blocker, and
that the phase runs normally if started — wording per `<plugin-root>/references/ifq-phase.md`'s
**Phase Announcement**; `batch.consistency == "divergent"` adds one more such line naming the
repair command (`bin/cfq batch verify "<repo-root>"`), never blocking.

## Start Gate

Fires before the lock — a declined batch must leave nothing to release, not even a lock. What is
printed, in order: the briefing warnings **Briefing Warnings** already defines, then `bin/cfq
brief "<batch-dir>" --overview` (the aligned-monospace batch-overview block from **Batch
Briefing**), then `selection.queueText` (already resolved by the preflight, no new call), each
rendered exactly as returned — no rewording, nothing between them but a blank line.

**The question**, two-stage, because `AskUserQuestion` caps at four options and a repo may hold
more than two other open batches:

- First call, three options: **Start** (recommended, listed first) — proceed to **Lock
  Acquisition** for the batch just briefed; **Pick a different batch** — opens the second call
  below; **Cancel** — end the session, nothing touched, no lock taken, no branch checked out.
  Print `Start Gate` as `➖ cancelled by user` and stop.
- Second call, only when the user picked the middle option: one option per entry in
  `selection.selectable` other than the batch already briefed, each labelled with its number and
  slug and described with its `open` (phase count) and `goal`. Blocked and planning batches are
  **not** offered — they are already visible in `queueText` with their own reason and stay
  non-selectable. More than four such entries → offer the first three, in the same
  flagged-first-then-name order `selectable` already carries, and say in the question text that
  the rest are in the listing above and reachable by typing the number as free text. A free-text
  answer naming a batch that is not in `selection.selectable` is reported against `queueText`'s
  own reason for that batch and the question is asked once more; a second miss ends the session
  without touching anything, mirroring **Branch and Changelog on Go-Ahead**'s free-text
  resolution for the `ambiguous` base-branch question — point at that paragraph, don't repeat it.
- On a different batch being chosen, re-run `bin/cfq preflight-impl "<repo-root>" --select
  <batch>` and continue from **Batch Briefing** with the new result — the gate does not fire a
  second time for the freshly chosen batch, because choosing it *was* the confirmation.

**When it fires**: always. A resumed in-progress batch, a batch named explicitly as an argument,
and orchestrator mode are all included — one behaviour, no exception, even though each of the
three reads like a natural exemption.

**The one case it does not fire**: `selection.selectable` is empty and there is no in-progress
batch, i.e. the session is already ending via `NO_BATCH`/`BLOCKED`/`MULTIPLE_IN_PROGRESS`. Those
paths end before a batch is ever resolved, so there is nothing left to confirm.

Print `Start Gate` either way: `✅ confirmed · <batch>` (Start chosen), `✅ switched to <batch>`
(a different batch chosen on the second call), or `➖ cancelled by user` (Cancel, or a second
free-text miss on the second call).

## Lock Acquisition

Exit ≠ 0 (`LOCKED`) → **end immediately**, touch nothing, name holder/batch/time, note the
30-minute stale takeover; `TAKEOVER` → proceed, `Lock` carries that warning; else `Lock` is just
acquired.

## Branch and Changelog on Go-Ahead

The preflight's `branch` field (already computed pre-mutation — see **Resume Snapshot** below) is
the same JSON `bin/cfq branch plan "<repo-root>" "<batch>"` itself returns: `batch`/`batchNumber`
echo the batch's own stable identity (`batchNumber` is `null` for a legacy unnumbered batch);
`mode` says what to do. Always use the `branch` field directly for checkout — never reconstruct a
branch string from a number/slug:

`bin/cfq branch plan` is remote-aware: it fetches `origin` once (best-effort — no `origin`, or the
fetch fails offline/sandboxed, and everything falls back to local-only behavior unchanged) before
deciding, so a stale local `main`/branch never gets silently proposed as a base. On the `new` path,
`origin/*` is the source of truth for `candidates` — each is an object (`name`, `ref`,
`aheadOfMain`, `behindRemote`, `aheadRemote`, `localOnly`, `highestBatch`, `mergedIntoOriginMain`,
`lastCommit`), ranked by `lastCommit` descending, kept for the `ambiguous` fallback below and for
the free-text answer's resolution. `base`/`baseRef` are derived from the batch's own `.dependsOn`,
in a `baseSource` field:

- `"dependsOn"` — the one unmerged dependency branch that contains every other unmerged one;
- `"ambiguous"` — no single dependency branch contains all the others (falls back to
  `candidates`' newest-`lastCommit` recommendation, unchanged);
- `"highestBatch"` — no unmerged dependency branch: the new batch chains onto the
  highest-numbered unmerged `cfq/<NNN>-…` branch (non-`cfq/` branches are never chosen here);
- `"newerCandidate"` — same base as `highestBatch`, but another unmerged `cfq/` branch that is
  not contained in it has a newer commit;
- `"main"` — bootstrap only: no unmerged numbered `cfq/` branch exists (`base: "main"`, `baseRef`
  pointing at `origin/main`).

Every response additionally carries `uncontained` — array of `{"name", "lastCommit", "newer"}`,
unmerged `cfq/` branches whose tip is not in the chosen base, empty unless `baseSource` is
`highestBatch`/`newerCandidate`, always `[]` on `continue`/`off` — plus `remoteChecked` (bool),
`remoteWarning` (string or `null`, set only when the chosen base — local `main` on `new`, the
persisted branch on `continue` — has commits `origin` doesn't and the gap can't be auto-resolved),
`remoteState` (`"synced"`/`"ahead"`/`"behind"`/`"diverged"`/`"unknown"` — the chosen base's own
relationship to its `origin` counterpart, `"unknown"` whenever `remoteChecked` is `false` or no
comparison was possible), `pushable` (bool, true only for `remoteState: "ahead"`), and `unpushed`
(array of `"<hash> <subject>"` lines, empty unless `pushable`) — so the caller never has to branch
on `mode` to read any of the three.

- **`off`** (`branchPerBatch` is `false`) → `Branch: ➖ branchPerBatch off`, skip everything below.
- **`continue`** (a branch for this batch already exists) → before resolving `remoteState`, its
  `dirty`/`changelogDirty` fields decide what happens to the changelog: `dirty: true` → the same
  error as `new`: report and end, nothing touched. `changelogDirty` alone (pfq's parked
  reservations, or a stray leftover from a previous session) → `git stash push -q --
  "<changelogFile>"` first, then resolve `remoteState` and run the checkout exactly as described
  below, `git stash pop -q` immediately after the checkout; a failing pop → report the conflict and
  name the kept stash, end without further action; a clean pop → `"<plugin-root>/bin/cfq" changelog
  commit "<repo-root>" "Record parked batch reservations in the changelog"`. On **Cancel** below
  (the `ahead`/`diverged` question), pop the stash back before ending so nothing is left changed.
  Neither flag set → resolve `remoteState` and checkout directly, no stash, no commit call.
  **`behind`**: not checked out → `update-ref` fast-forwards the local ref as before, then `git
  checkout "<branch>"`. Checked out with a clean tree → `git merge --ff-only
  "refs/remotes/origin/<branch>"` instead (the ref of the currently-checked-out branch can't move
  under `update-ref`). Checked out and dirty → nothing moves; `remoteWarning` names the dirty tree,
  and the `Branch` status line surfaces it as a `⚠️` note — `git checkout "<branch>"` still runs,
  a dirty tree here is otherwise the same error the **`new`** path already treats it as. **`ahead`**
  (`pushable: true`) → one `AskUserQuestion` before the checkout: **Push and continue**
  (recommended) runs `git push origin "<branch>"`, then proceeds; **Continue without pushing**
  proceeds and names the commits from `unpushed` that won't be in this batch's base; **Cancel**
  releases the lock and ends the session, nothing touched. **`diverged`** → the same three-option
  question minus the push option — `remoteWarning` explains why a push would be rejected.
  **`synced`**/**`unknown`** → plain `git checkout "<branch>"`, no question. Either way, don't write
  a new changelog entry — the batch is already recorded; only the stash/commit sequence above may
  touch the file's contents. The commit result (`committed`/`clean`/`ignored`/`off`, or `➖ no
  changelogDirty` when the sequence never ran) renders the same `   └ ` sub-line under `Branch` as
  the `new` path.
- **`new`** → `baseSource: "dependsOn"`, `"highestBatch"` or `"main"` resolves silently to the
  already-derived `base`/`baseRef`, no question — name `baseSource` in the `Branch` status line.
  When `uncontained` is non-empty on `baseSource: "highestBatch"`, add one `   └ ⚠️` sub-line under
  `Branch` per entry: "`<name>` has commits not in `<base>` (last commit `<lastCommit>`)" — an
  older, non-`newer` chain that never surfaces as a question. `baseSource: "newerCandidate"` → one
  `AskUserQuestion` naming that a newer unmerged `cfq/` branch exists than the highest batch
  number. Recommended (first, labelled `(Recommended)`): `base` — the highest-numbered branch
  itself, description naming its batch number. Then one option per `uncontained` entry with
  `newer: true`, description naming its `lastCommit` and its `aheadOfMain` (looked up from
  `candidates` by name); any `uncontained` entry that is not `newer` is named in the question text
  itself, not offered as its own option. The free-text answer (`AskUserQuestion`'s built-in
  "Other") and the `bin/cfq branch check` resolution follow the exact same rules the `ambiguous`
  question below already documents — point at that paragraph, don't repeat it. `baseSource:
  "ambiguous"` (no single dependency branch contains every other unmerged one — the exceptional
  case) → one `AskUserQuestion` listing every entry in `candidates` (already ranked), asking which
  one the new branch builds on. Recommended (first, labelled
  `(Recommended)`): `base` — the newest by `lastCommit`, never the checked-out branch. Each other
  option's description names its `aheadOfMain`, plus `local only` / `already contained in
  origin/main` / `behind origin by <behindRemote>` where applicable. The free-text answer
  (`AskUserQuestion`'s built-in "Other") is resolved with `bin/cfq branch check "<repo-root>"
  "<name>"`: `UNRESOLVED` → ask once more naming the unresolvable input; a second miss ends the
  session without touching anything, exactly like the dirty-tree rule below. On `OK`, surface both
  its warnings separately when they apply — "`<name>` is `<behind>` commit(s) behind
  `origin/<name>`" and "`<newerCandidate.name>` has a newer commit (`<newerCandidate.lastCommit>`)"
  — before the checkout runs, and use its `ref` as `<baseRef>` and `<name>` as `<base>` below. Then:

```bash
git checkout --no-track -b "<branch>" "<baseRef>"
"<plugin-root>/bin/cfq" changelog init "<repo-root>" "<branch>" "<base>" "<batch>"
"<plugin-root>/bin/cfq" changelog commit "<repo-root>" "Start <branch> batch in the changelog"
"<plugin-root>/bin/cfq" branch plan "<repo-root>" "<batch>"
```

`--no-track` matters: `<baseRef>` is a remote-tracking ref, and without it git's own
`branch.autoSetupMerge` default would set `<branch>`'s upstream to the *base* branch instead of
itself — the first `cfq phase commit` on this batch is what sets the upstream to
`origin/<branch>`, via its own `push -u` fallback.

`changelog init` keeps receiving `<base>` (the plain branch name), not `<baseRef>` — the changelog
records which branch the work builds on, not which ref was used to cut it. `changelog commit` is a
script verb, never model discretion — it stages and commits only the changelog file (never a bare
`git commit`), so a pfq reservation left dirty on the base branch rides along with the `checkout -b`
and lands in this one immediate commit together with the `init` block; no push here, the first
phase's Commit & Push step carries it.

The `new`-mode `bin/cfq branch plan` re-run above is the one and only place this batch's mutation
step calls it directly — solely to reconfirm the branch now exists post-checkout; `continue`/`off`
never call it again, the preflight's answer already stands. Its `dirty`/`changelogDirty` fields gate
this whole path: `dirty: true` (uncommitted changes other than the changelog file) → error, report
and end without touching anything; `changelogDirty` alone is expected here — it is exactly the pfq
reservation this section's `changelog commit` call above just cleared, so a second re-run reports
`changelogDirty: false` too. The commit result (`committed`/`clean`/`ignored`/`off`) is rendered as
an indented `   └ ` sub-line under the `Branch` status line, per **Output Format**'s sub-information
rule.

## Resume Snapshot

`bin/cfq preflight-impl`'s `resume` field carries what `bin/cfq resume` itself returns for the
resolved batch, minus its own `branch` sub-object (redundant with the preflight's top-level
`branch`, computed by that same underlying call — see the `resume` noun's own script header
comment for the full, still-current field-by-field contract: `phasesOpen`/`phasesDone`, `lastCommit`/
`lastCommitSource`, `deviations`, `redPhases`, `batchContext.exists`/`.path`). One JSON object,
deterministic — no summarization, only facts read from disk, `report.json`, and git. The script
itself is unchanged; only who calls it and what's kept from its output moved.
