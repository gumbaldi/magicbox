# ifq: Batch Selection, Briefing, Branch and Resume

## Batch Selection Rules

`bin/cfq preflight-impl`'s `selection` object carries `blocked`, `planning`, `inProgress`, and
`multipleInProgress` — the filters and stop conditions applied before any picker runs. The
preflight itself already excludes blocked/planning/other-in-progress batches from
`selection.selectable`; this section only covers the wording each case needs.

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
for it, no question. Print `Batch` as `<name> · next in order · <n> phases` (prefix `high · ` when
flagged, suffix `⚠️ divergent` when `consistency` is `"divergent"`). Arguments naming a specific
batch re-run the preflight with `--select <batch>` instead of taking the ordered default.
`status: "SELECT_UNAVAILABLE"` means the named batch isn't selectable (blocked, still planning, or
unknown) — report why, from `selection`, and end; never falls back to the ordered default. **Never
two batches in the same session**, not even once the first finishes and context is still free —
different plans belong in separate context windows.

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
git checkout -b "<branch>" "<baseRef>"
"<plugin-root>/bin/cfq" changelog init "<repo-root>" "<branch>" "<base>" "<batch>"
"<plugin-root>/bin/cfq" changelog commit "<repo-root>" "Start <branch> batch in the changelog"
"<plugin-root>/bin/cfq" branch plan "<repo-root>" "<batch>"
```

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
