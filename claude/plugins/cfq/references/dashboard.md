# Dashboard Detail: Plugin Offer, Management Actions, Settings

## QUEUES Table and Reports (Step B)

The `QUEUES` table's columns are `Repo | Plan | Todo | Batches | Reports | Status`. `Reports`
counts the batch records (open and archived both) whose `report.json` exists — same `report` flag
`cfq_scan.py` already puts on every batch record, no new scan. Like `Plan`/`Todo`/`Batches`, a repo
with none prints a bare `0`, never a dash or blank.

The `ACTIONS` list gains a seventh, read-only entry — `view reports`, pointing at `/rfq`
(`report-for-queue`), the skill that lists and renders them, plus this repo's own report portal
path (`<repo>/.claude/cfq/reports/index.html`) for opening it directly. It needs no confirmation
and isn't one of Step C's six mutating actions below.

## Optional Third-Party Plugins and Ponytail Dormant-by-Default Offer

Moved into `<plugin-root>/references/setup-wizard.md`'s **Environment & Plugins** section (the
former Step A, first-time-setup only, is now the setup wizard's global part, run automatically the
first time and any time by name via `/cfq setup`).

## CONFIG Block: Full List and Global View (Step B)

On request, two extensions of the same block, same rendering:

- **Full list** — re-run `bin/cfq dash`'s settings call without the `marker != "D"` filter, so
  default-valued keys show too.
- **Global view** — `"<plugin-root>/bin/cfq" settings list --sources` without
  `--repo`, rendered identically (no `maskedValue`/`R` rows, since there is no repo tier here).

## Step C — Management, Six Actions (current repo only, always confirm before writing)

Every action follows the same shared flow: a deterministic check computes the proposed action
(file count, dependency existence, blocked status — already available from `.repos`/`.thisRepo`,
no new script needed for that part) → Claude presents it → the user confirms → the existing
mutation script executes → the structured result is shown. No new script per action.

1. **Flag/unflag high priority** — write or delete `.priority`.
2. **Delete a batch** — remove the directory. Name the batch and the number of files that will be
   lost beforehand, and get explicit confirmation.
3. **Archive a batch** — move to `<repo>/.claude/cfq/impl/done/<batch>/` without working it off.
   Open phases then count as done-but-not-implemented; say so in the confirmation text.
4. **Clean the registry** — `bin/cfq registry prune`, list the removed paths.
5. **Set/remove a dependency** — write or delete `.dependsOn` in the chosen batch. Before writing,
   check whether the named batch exists (open or in `done/`); if not, warn but write anyway on
   request — the edge is fail-soft by design.
6. **Work off todos**:
   1. Run `"<plugin-root>/bin/cfq" note sweep "<repo-root>" --text` and show its output — one line
      per card, green first, then unresolvable, then red oldest-first, then the ones with no
      `check:` line.
   2. On confirmation, run the same call with `--apply` and print one summary line under the
      `ACTION` header, e.g. `✅ Todos          3 checks green · moved to done · 44 still open`, not
      one line per card.
   3. A card without a `check:` line is never closed by `--apply`; closing one is an explicit act
      and goes through `note sweep "<repo-root>" --close <filename>`, one `--close` per card, after
      the user names it.
   4. Never create or edit an entry here — those are written by `ifq` at batch end. A red card
      simply stays open.

No pulling things back out of `done/` and no editing phase files — that's `pfq`'s job.

The confirmation question stays prose. After execution, print one line per action under an
`ACTION` header — the label names the action (`Priority`, `Registry`, `Dependency`, etc.), the
detail the before/after or a `⚠️` note:

```
ACTION
✅ Priority        2026-08-13-cfq-plugin: flagged high
✅ Registry        3 dead paths removed
⚠️ Dependency      2026-08-10-auth does not exist · edge written anyway
```

## Step D — Settings, Full Detail

The guided `/cfq settings` picker (`<plugin-root>/references/settings-menu.md`) navigates the same
schema this section describes and reuses everything below — scope inference, the global-only
rejection, the `env:repo-legacy` migration note — rather than duplicating it; a free-text change
request ("set stopUsed to 100000") keeps landing here directly. `ACTIONS`' two permanent rows,
`settings menu` (`/cfq settings`) and `setup wizard` (`/cfq setup`), point at the picker and at the
onboarding wizard respectively; both stay listed on every render, in a repo or outside one, rather
than only once during first-time setup.

Pair each `.settings` row with its explanation from `bin/cfq settings describe [<key>]` — that
schema call is the single source for per-key prose, not a hand-maintained table;
`<plugin-root>/references/settings-explain.md` adds only the nuance that doesn't reduce to
schema data.

**All** keys are changeable, including `planBlockedPlugins`/`implBlockedPlugins` (strict
prohibition) — there is no exception left. A key whose `scope` is global-only (`scanRoots`,
`securityTimeoutSeconds`, `securityFindingsCap`) rejects `--repo`; say so and fall back to a global
`set`. `0` is a valid, deliberate value for `stopUsed` meaning "hand off after every phase"; `-1` is
equally valid on `stopUsed`, `stopFiveHourPct` and `stopSevenDayPct` — on `stopUsed` it means "never
hand off for this reason", on the rate-limit pair it means "never emit a `WARN` for this reason" — none of
these is a misconfiguration, don't flag any of them.

Infer `--global` vs. `--repo` from the user's own phrasing where it's unambiguous ("for this repo",
"just here" → `--repo`; "everywhere", "by default" → global) — only ask via `AskUserQuestion` when
genuinely ambiguous, not on every request.

If any `.settings` entry has `source: "env:repo-legacy"` (the value comes from the old per-repo
`env` block in `<repo>/.claude/settings.json`, not a `CFQ_*` shell variable), print one note
pointing at `bin/cfq settings migrate <repo-root>` to carry that override into the repo settings
file — once per session, not once per key.

A rejected out-of-scope `--repo` attempt prints `❌ Setting  scanRoots is global-only, use set
scanRoots <value> without --repo`.
