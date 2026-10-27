# ifq: Branch and Changelog

## Contents

- Branch and Changelog on Go-Ahead

## Branch and Changelog on Go-Ahead

The preflight's `branch` field (already computed pre-mutation — see **Resume Snapshot** in `implement-for-queue/SKILL.md`) is
the same JSON `bin/cfq branch plan "<repo-root>" "<batch>"` itself returns: `batch`/`batchNumber`
echo the batch's own stable identity (`batchNumber` is `null` for a legacy unnumbered batch);
`mode` says what to do. Always use the `branch` field directly for checkout — never reconstruct a
branch string from a number/slug:

`bin/cfq branch plan` is remote-aware: it fetches `origin` once (best-effort — no `origin`, or the
fetch fails offline/sandboxed, and everything falls back to local-only behavior unchanged)
before deciding, so a stale local branch never gets silently proposed as a base. On the `new`
path `origin/*` is the source of truth; a branch that exists only locally is still considered
and marked `localOnly`. `base`/`baseRef` are the recommendation — the batch's own `.dependsOn`
only gates *when* a batch is selectable (a blocked batch never reaches `/ifq` at all) and never
picks the base — with the reason in `baseSource`:

- `"highestBatch"` — the `cfq/<NNN>-…` branch with the highest batch number; no branch that is
  not a batch branch has a newer commit than its tip;
- `"newestBranch"` — a branch that is not a batch branch has a strictly newer commit than the
  highest batch branch, or no batch branch exists at all.

`options` is the complete, ordered list of branches the base question offers: the
recommendation (`role: "recommended"`), then `role: "highestBatch"` when the recommendation is
not a batch branch, then `role: "newestCommit"` — an older batch branch carrying a newer commit
that the highest one does not contain. Each entry has `name`, `ref`, `isCfq`, `isDefault`,
`localOnly`, `lastCommit`, `behindRemote`, `aheadRemote`, `containedInBase`, and its own
`uncontained`/`uncontainedCount`: the unmerged batch branches that entry does not contain — at
most five listed, highest batch number first, `uncontainedCount` the full number — with an
unmerged `.dependsOn` branch missing from it listed first as `dependency: true`.
`defaultBranch` names the repository's default branch.

Every response additionally carries top-level `uncontained`/`uncontainedCount` — the
recommendation's own, `[]`/`0` on `continue`/`off`, where `options` is `[]` as well —
plus `remoteChecked` (bool),
`remoteWarning` (string or `null`, set only when the chosen base — local `main` on `new`, the
persisted branch on `continue` — has commits `origin` doesn't and the gap can't be auto-resolved),
`remoteState` (`"synced"`/`"ahead"`/`"behind"`/`"diverged"`/`"unknown"` — the chosen base's own
relationship to its `origin` counterpart, `"unknown"` whenever `remoteChecked` is `false` or no
comparison was possible), `pushable` (bool, true only for `remoteState: "ahead"`), and `unpushed`
(array of `"<hash> <subject>"` lines, empty unless `pushable`) — so the caller never has to branch
on `mode` to read any of the three. `remoteState` and `pushable` describe the chosen base branch when the session started and say nothing about the batch branch afterwards.

- **`off`** (`branchPerBatch` is `false`) → `Branch: ➖ branchPerBatch off`, skip everything below.
- **`continue`** (a branch for this batch already exists) → before resolving `remoteState`, its
  `dirty`/`changelogDirty` fields decide what happens to the changelog: `dirty: true` → the same
  error as `new`: release the lock, report and end, nothing else touched. `changelogDirty` alone (pfq's parked
  reservations, or a stray leftover from a previous session) → `git stash push -q --
  "<changelogFile>"` first, then resolve `remoteState` and run the checkout exactly as described
  below, `git stash pop -q` immediately after the checkout; a failing pop → report the conflict and
  name the kept stash, end without further action; a clean pop → `"<plugin-root>/bin/cfq" changelog
  commit "<repo-root>" "Record parked batch reservations in the changelog"`. On **Cancel** below
  (the `ahead`/`diverged` question), pop the stash back before ending so nothing is left changed.
  Neither flag set → resolve `remoteState` and checkout directly, no stash, no commit call.
  **`behind`**: not checked out → `update-ref` fast-forwards the local ref, then `git
  checkout "<branch>"`. Checked out with a clean tree → `git merge --ff-only
  "refs/remotes/origin/<branch>"` instead (the ref of the currently-checked-out branch can't move
  under `update-ref`). Checked out and dirty → nothing moves; `remoteWarning` names the dirty tree,
  and the `Branch` status line surfaces it as a `⚠️` note — `git checkout "<branch>"` still runs,
  a dirty tree here is otherwise the same error the **`new`** path already treats it as. **`ahead`**
  (`pushable: true`) → one `AskUserQuestion`, framed per `interaction-policy.md`'s **Decision
  Question Context**, before the checkout: **Push and continue**
  (recommended) runs `git push origin "<branch>"`, then proceeds; **Continue without pushing**
  proceeds and names the commits from `unpushed` that won't be in this batch's base; **Cancel**
  releases the lock and ends the session, nothing touched. **`diverged`** → the same three-option
  question minus the push option — `remoteWarning` explains why a push would be rejected.
  **`synced`**/**`unknown`** → plain `git checkout "<branch>"`, no question. Either way, don't write
  a new changelog entry — the batch is already recorded; only the stash/commit sequence above may
  touch the file's contents. The commit result (`committed`/`clean`/`forced`/`off`, or `➖ no
  changelogDirty` when the sequence never ran) renders the same `   └ ` sub-line under `Branch` as
  the `new` path.
- **`new`** → one `AskUserQuestion`, framed per `interaction-policy.md`'s **Decision Question
  Context**, fires for every new batch branch — the base never resolves silently. What it is
  about: a new branch `<branch>` is created for batch `<batch>`. The problem: which existing
  branch it builds on decides which earlier, unmerged work it contains. The options are exactly
  these, in this order — no branch is offered merely because it exists:
  - One option per `options` entry, in array order. The first is labelled `(Recommended)` and
    described by `baseSource`: `"highestBatch"` → "the newest batch branch"; `"newestBranch"`
    → "the newest branch — not a cfq batch branch", stated in the option's own description.
    `role: "highestBatch"` → "the newest cfq batch branch", plus "already contained in
    `<base>`" when `containedInBase` is true. `role: "newestCommit"` → "an older batch branch
    with a newer commit than `<base>`". Every description names `lastCommit`, adds `local
    only` / `behind origin by <behindRemote>` where they apply, and, when its
    `uncontainedCount` is above zero, names the unmerged batch branches it does not contain.
  - **Pick from list**, always last.

  `AskUserQuestion`'s built-in "Other" is the free-text field for typing a branch name
  directly. There is no `main` option, no further candidate and no Cancel option.

  When the recommendation itself is incomplete — its `uncontainedCount` is above zero, or a
  `newestCommit` option exists — the question text opens with that warning, one clause per
  `uncontained` entry: "`<name>` is a dependency of this batch and is not in `<base>`" for
  `dependency: true`, named first, else "`<name>` has commits not in `<base>` (last commit
  `<lastCommit>`)", and "and <n> more" when `uncontainedCount` exceeds the entries listed. A
  non-null `remoteWarning` is stated there too.

  **Pick from list** → `bin/cfq branch list "<repo-root>"`, print its `listText` exactly as
  returned, ask in plain prose, in the user's language, for a row number or a branch name,
  and end the turn — the user's next message is the answer. A number is the entry at that
  position in `names`; anything else is taken as a branch name. The list is never printed
  without this option having been chosen.

  A branch that did not come from `options` — typed into the free-text field or taken from
  the list — is resolved with `bin/cfq branch check "<repo-root>" "<name>" --batch "<batch>"`:
  `UNRESOLVED` → ask once more naming the unresolvable input; a second miss releases the lock
  (`bin/cfq lock release "<repo-root>" --batch "<batch>"`) and ends the session, nothing else
  touched. On `OK`, surface its two notes separately when they apply — "`<name>` is `<behind>`
  commit(s) behind `origin/<name>`" and "`<newerCandidate.name>` has a newer commit
  (`<newerCandidate.lastCommit>`)" — and use its `ref` as `<baseRef>` and `<name>` as `<base>`
  below. An `options` entry needs no such call: its `ref`, `uncontained` and
  `uncontainedCount` are already in the preflight result.

  **Confirmation.** The chosen branch is not the recommendation and its `uncontainedCount` is
  above zero → one more `AskUserQuestion` before anything is checked out, framed per
  **Decision Question Context**: building on `<chosen>` leaves these unmerged batch branches
  out of the new branch — its `uncontained` entries in the wording above, "and <n> more" past
  the five listed — which is rarely intended, since a new batch normally builds on every
  earlier one. Three options: **Use `<base>` instead** (recommended, listed first) → continue
  with the recommendation; **Build on `<chosen>` anyway** → continue with the chosen branch;
  **Cancel** → release the lock with the command above and end the session, nothing else
  touched. Choosing the recommendation never triggers this question — what it lacks was
  already stated in the first one.

  After the checkout, `Branch` names the base actually used and why — `baseSource` for the
  recommendation, `chosen` for anything else — with one `   └ ⚠️` sub-line per `uncontained`
  entry of that base, same wording, and a last "and <n> more" sub-line when the list was
  capped. Then:

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
records which branch the work builds on, not the ref it was cut from. `changelog commit` is a
script verb, never model discretion — it stages and commits only the changelog file (never a bare
`git commit`), so a pfq reservation left dirty on the base branch rides along with the `checkout -b`
and lands in this one immediate commit together with the `init` block; no push here, the first
phase's `phase commit` carries it.

The `new`-mode `bin/cfq branch plan` re-run above is the one and only place this batch's mutation
step calls it directly — solely to reconfirm the branch now exists post-checkout; `continue`/`off`
never call it again, the preflight's answer already stands. Its `dirty`/`changelogDirty` fields gate
this whole path: `dirty: true` (uncommitted changes other than the changelog file) → error: release the
lock (`bin/cfq lock release "<repo-root>" --batch "<batch>"`), report and end without touching
anything else; `changelogDirty` alone is expected here — it is exactly the pfq
reservation this section's `changelog commit` call above just cleared, so a second re-run reports
`changelogDirty: false` too. The commit result (`committed`/`clean`/`forced`/`off`; `forced` means the repo's own ignore rule covered the changelog and cfq tracked it anyway) is rendered as
an indented `   └ ` sub-line under the `Branch` status line, per **Output Format**'s sub-information
rule.
