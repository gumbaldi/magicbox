# Dashboard Detail: Plugin Offer, Management Actions, Settings

## Optional Third-Party Plugins (Step A)

| Plugin | What cfq uses it for | Installation | Docs |
|---|---|---|---|
| `mattpocock-skills` | classic grill mode (`grillMode: classic`) | `/plugin install mattpocock-skills@claude-plugins-official` — if the marketplace is missing: `/plugin marketplace add anthropics/claude-plugins-official` | `github.com/anthropics/claude-plugins-official`, locally the `SKILL.md` under `skills/productivity/grilling/` in the plugin cache |
| `ponytail` | one of several tasks in the maintenance run: an optional cleanup audit | `/plugin marketplace add DietrichGebert/ponytail`, then `/plugin install ponytail@ponytail` | `github.com/DietrichGebert/ponytail`, at runtime `/ponytail-help` |

An already-installed plugin starts enabled (its switch defaults to `true`) without asking here —
only offer what `.plugins` reports missing.

## CONFIG Block: Full List and Global View (Step B)

On request, two extensions of the same block, same rendering:

- **Full list** — re-run `cfq-dash.sh`'s settings call without the `marker != "D"` filter, so
  default-valued keys show too.
- **Global view** — `"<plugin-root>/scripts/cfq-settings.sh" list --sources` without
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
4. **Clean the registry** — `cfq-registry.sh prune`, list the removed paths.
5. **Set/remove a dependency** — write or delete `.dependsOn` in the chosen batch. Before writing,
   check whether the named batch exists (open or in `done/`); if not, warn but write anyway on
   request — the edge is fail-soft by design.
6. **Work off todos**:
   1. List every entry under `todo/*.md`: title plus the one or two sentences describing what to
      do.
   2. For an entry with a `check:` line, **show** the command, then run it. Exit `0` → done, move
      the file to `todo/done/`, and print a status line under the `ACTION` header naming the
      reason (`✅ Todo   merge-v0.2: check green · moved to done`). Exit ≠ 0 → the entry stays
      open, with one line explaining why.
   3. Entries without a `check:` line are only shown, and only checked off on explicit
      confirmation.
   4. Never create or edit an entry here — those are written by `ifq` (P6).

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

Pair each `.settings` row with its explanation from `cfq-settings.sh describe [<key>]` — that
schema call is the single source for per-key prose, not a hand-maintained table;
`<plugin-root>/references/settings-explain.md` adds only the nuance that doesn't reduce to
schema data.

**All** keys are changeable, including `planBlockedPlugins`/`implBlockedPlugins` (strict
prohibition) — there is no exception left. A key whose `scope` is global-only (`scanRoots`,
`securityTimeoutSeconds`, `securityFindingsCap`) rejects `--repo`; say so and fall back to a global
`set`. `0` is a valid, deliberate value for `stopUsed` meaning "hand off after every phase"; `-1`
is equally valid, meaning "never hand off for this reason" — neither is a misconfiguration, don't
flag either.

Infer `--global` vs. `--repo` from the user's own phrasing where it's unambiguous ("for this repo",
"just here" → `--repo`; "everywhere", "by default" → global) — only ask via `AskUserQuestion` when
genuinely ambiguous, not on every request.

If any `.settings` entry has `source: "env:repo-legacy"` (the value comes from the old per-repo
`env` block in `<repo>/.claude/settings.json`, not a `CFQ_*` shell variable), print one note
pointing at `cfq-settings.sh migrate <repo-root>` to carry that override into the repo settings
file — once per session, not once per key.

A rejected out-of-scope `--repo` attempt prints `❌ Setting  scanRoots is global-only, use set
scanRoots <value> without --repo`.
