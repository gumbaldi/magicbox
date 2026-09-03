# Configuration

How to view and change cfq's settings, globally or per repo, and what each one does.

## Precedence

**env var > repo `.claude/cfq/settings.json` > global `settings.json` > default.** Four tiers,
highest wins:

1. **Env var** (`CFQ_*`) — highest precedence, same variable works globally or per repo (see
   below).
2. **Repo settings** — `<repo>/.claude/cfq/settings.json`, written via `set --repo <path>`.
   Applies only to that repo, wherever it's cloned.
3. **Global settings** — `~/.claude/code-for-queue/settings.json`, written via plain `set`.
   Applies to every repo unless a repo overrides the key.
4. **Default** — the schema's built-in value, used when nothing above sets the key.

A key not writable per repo (`scope` is `["global"]` in the schema — currently `scanRoots`,
`securityTimeoutSeconds`, `securityFindingsCap`) rejects a `set --repo` attempt outright.

The legacy `env` block in `<repo>/.claude/settings.json` still works and still sits at the top
tier — it's not the only per-repo mechanism anymore, just the oldest one:

```json
{ "env": { "CFQ_CODE_LANGUAGE": "en", "CFQ_DOC_LANGUAGES": "de", "CFQ_DOC_LEVEL": "standard" } }
```

`migrate <repo-root>` copies every key that legacy block currently overrides into the repo
settings file (tier 2), so the same override keeps working without depending on that `env` block
forever; the original file is left untouched.

## View settings

```
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings list [--repo <path>] [--sources]
```

`--repo` folds in that repo's tier-2 file. `--sources` adds, per key, which tier actually supplied
the value: `env:process`, `env:repo-legacy` (the legacy `env` block, not a `CFQ_*` var set in the
shell), `repo`, `global`, or `default`. Or run `/cfq` and pick the settings step — same data,
presented as a table.

## Change settings

```bash
# Global (tier 3)
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings set maintenanceEvery 25

# Repo-scoped (tier 2) — only for this clone's repo
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings set --repo "$(git rev-parse --show-toplevel)" docLevel standard

# Remove an override, falling back to the next tier
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings unset --repo "$(git rev-parse --show-toplevel)" docLevel
```

`get [--repo <path>] [--source] <key>` reads a single key the same way `list` does; `describe
[<key>]` prints type/default/scope/env/description for one key or the whole schema — the same
data this reference table below is generated from. `/cfq` offers the same `set` calls
interactively.

## Settings reference

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `grillMode` | `CFQ_GRILL_MODE` | `stepwise` | global, repo | `stepwise` = batched rounds of up to 4 questions; `classic` = delegates to `mattpocock-skills:grilling`'s own round format |
| `planModels` | `CFQ_PLAN_MODELS` | `opus,fable` | global, repo | models allowed to plan; a mismatch only warns |
| `implModels` | `CFQ_IMPL_MODELS` | `sonnet` | global, repo | models allowed to implement; a mismatch aborts `ifq` |
| `planExploreModel` | `CFQ_PLAN_EXPLORE_MODEL` | `haiku` | global, repo | model pfq's research subagents run on |
| `planExploreModelComplex` | `CFQ_PLAN_EXPLORE_MODEL_COMPLEX` | `sonnet` | global, repo | model for pfq's Explore agents whose task is to judge rather than to locate |
| `implExploreModel` | `CFQ_IMPL_EXPLORE_MODEL` | `haiku` | global, repo | model ifq's pre-implementation research and test-run subagents run on |
| `implExploreModelComplex` | `CFQ_IMPL_EXPLORE_MODEL_COMPLEX` | `sonnet` | global, repo | model for ifq's Explore agents whose task is to judge rather than to locate |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | global, repo | lifts both model checks above |
| `stopUsed` | `CFQ_STOP_USED` | `100000` | global, repo | absolute context tokens at which `ifq` hands off instead of starting another phase; `0` hands off after every phase, `-1` never hands off for this reason |
| `stopFiveHourPct` | `CFQ_STOP_FIVE_HOUR_PCT` | `70` | global, repo | five-hour rate-limit usage in percent at which `ifq` emits a `WARN` before starting another phase, instead of continuing silently; `-1` disables the check |
| `stopSevenDayPct` | `CFQ_STOP_SEVEN_DAY_PCT` | `95` | global, repo | seven-day rate-limit usage in percent at which `ifq` emits a `WARN` before starting another phase, instead of continuing silently; `-1` disables the check |
| `sessionStaleSeconds` | `CFQ_SESSION_STALE_SECONDS` | `1800` | global, repo | seconds since a session transcript was last touched before it's considered stale (lock takeover, resume staleness) |
| `ctxWindowLimits` | — | see `describe ctxWindowLimits` | global, repo | context-window size in tokens per model, keyed by whether the model gets the large window |
| `scanRoots` | `CFQ_SCAN_ROOTS` | `~/git` | global only | roots for automatic queue discovery |
| `useMattpocockGrilling` | `CFQ_USE_MATTPOCOCK` | `true` | global, repo | allows `grillMode: classic` |
| `usePonytailAudit` | `CFQ_USE_PONYTAIL` | `true` | global, repo | enables the optional cleanup audit, one of several maintenance tasks gated by `maintenanceEvery` |
| `codeLanguage` | `CFQ_CODE_LANGUAGE` | `en` | global, repo | language of everything executed or read as an instruction: code, comments, commit messages, `README`, `CLAUDE.md`, `SKILL.md` |
| `docLanguages` | `CFQ_DOC_LANGUAGES` | `""` | global, repo | additional languages kept under `docs/<lang>/`; empty means documentation follows `codeLanguage` alone |
| `docLevel` | `CFQ_DOC_LEVEL` | `minimal` | global, repo | how much documentation a repo keeps: `minimal` (`README` only), `standard` (`docs/` with setup, usage, configuration), `full` (additionally a reference page per module/script and an architecture overview) |
| `maintenanceEvery` | `CFQ_MAINTENANCE_EVERY` | `50` | global, repo | commits since the last maintenance run before it's due again; `0` disables maintenance entirely |
| `branchPerBatch` | — | `true` | global, repo | `ifq` creates one branch per batch right after the go-ahead |
| `changelogFile` | — | `.claude/cfq/changelog.yml` | global, repo | path (repo-root-relative) `ifq` records batch progress to; also the repository-local batch-number allocation ledger; empty disables both the changelog and numbered-batch allocation |
| `htmlReport` | — | `false` | global, repo | render the HTML report automatically at batch end; otherwise only on `/rfq` request |
| `reportDir` | `CFQ_REPORT_DIR` | `""` | global, repo | absolute path of the directory HTML reports are collected in; empty writes `report.html` into the batch directory instead — see layout below |
| `planBlockedPlugins` | — | `superpowers` | global, repo | prohibition: never used while planning, not even indirectly |
| `implBlockedPlugins` | — | `superpowers` | global, repo | prohibition for implementation |
| `telemetrySyncRepo` | `CFQ_TELEMETRY_SYNC_REPO` | `""` | global, repo | absolute path to a dedicated telemetry git repo; empty disables the sync |
| `securityTimeoutSeconds` | — | `30` | global only | timeout in seconds for the batch-completion security scan |
| `securityFindingsCap` | — | `20` | global only | maximum number of security findings surfaced per batch-completion scan |
| `gitStatePolicy` | — | `local` | global, repo | `local` keeps repo-local cfq workflow state in that clone's Git `info/exclude`, leaving `.claude/cfq/settings.json` trackable; `trackable` removes only cfq's managed exclude block and leaves the rest to normal repository Git policy |
| `setupDone` | — | `false` | state, not a setting | internal marker: first-time setup (`/cfq`) has run. Lives outside the settings schema — `bin/cfq settings state get/set setupDone` — since it's runtime state, not policy; a repo new to the registry separately gets a one-time config overview at park time (`pfq` Step 13) |

The prohibition keys (`planBlockedPlugins`/`implBlockedPlugins`) are worth being conservative with
even though they're repo-overridable like most others — they also block indirect calls, so set
them sparingly.

Adding a new setting means adding one schema entry inside the script behind `bin/cfq settings` —
`list`/`get`/`set`/`unset`/`describe` and every precedence tier read it generically, no second
place to touch.

## Explore model escalation

`planExploreModel`/`implExploreModel` and their `.Complex` counterparts aren't picked by mood —
both worker skills apply the same rule: the cheap model when the Explore agent's task is to
**locate** (find a file, list callers, check a naming convention, count occurrences), the
`.Complex` model when the task is to **judge** (compare two files for consistency, name the rule
behind a pattern, establish that something is *not* stated anywhere, weigh two implementations
against each other). A list-shaped answer stays on the cheap model; an assessment escalates.
Changing either `.Complex` model changes only the second kind of task — the everyday locate work
still runs on the cheap default.

## Report collection layout

With `reportDir` set, `bin/cfq report html <batch-dir>` writes into
`<reportDir>/<repo-basename>/<batch>.html` instead of the batch directory, and regenerates
`<reportDir>/index.html` alongside it — one page linking every report-bearing batch across every
repo (`bin/cfq report index`'s own data), grouped by repo, newest first. A batch `index` reports
that has no HTML rendered yet is listed without a link rather than omitted. Leaving `reportDir`
empty keeps today's behavior: `report.html` next to `report.json` in the batch directory, no
`index.html`. This is meant for a location reachable outside the queue's own git-excluded
directory — a WSL user opening reports from Windows Explorer, for example — `htmlReport` (above)
controls whether it renders automatically at batch completion.

## Script Output Reference

The canonical JSON shape for every read-only aggregator a skill calls, so no `SKILL.md` needs to
restate a field list inline — read the field here, then read it back from the call's own output.
`status` values follow CLAUDE.md's Status Vocabulary.

- **`bin/cfq preflight-plan <repo-root>`** — `{status, repo: {root, known}, planningPolicy:
  {planModels, allowAnyModel, planExploreModel, planExploreModelComplex, planBlockedPlugins,
  grillMode, useMattpocockGrilling, usePonytailAudit}, language: {codeLanguage, docLanguages,
  docLevel}, queue: {openBatches: [{name, priority, open, dependsOn}]}, maintenance: {status, n},
  security: {available}, reporting: {reportDir, htmlReport}}`. `status`: `OK` or `NO_REPO` (only
  `repo.root`/`.known` set then).
- **`bin/cfq preflight-impl <repo-root> [--select <batch>]`** — `{status, repo: {root}, policy:
  {implModels, allowAnyModel, implBlockedPlugins, onePhasePerSession, implExploreModel,
  implExploreModelComplex}, reporting: {reportDir, htmlReport}, selection: {selectable: [{name,
  priority, open, done}], blocked: [{name, dependsOn, unknownDeps}], planning: [name, …],
  inProgress, multipleInProgress}, batch: {name, priority, phaseCount, dependsOn, briefText} |
  null, nextPhase: {num, slug, size, failedAttempt} | null, branch: {…`bin/cfq branch plan`'s shape}
  | null, resume: {…`bin/cfq resume`'s shape minus `branch`} | null, contextGate: {used, size,
  limit, verdict, reason, note} | null}`. `status`: `OK`, `NO_REPO`,
  `MULTIPLE_IN_PROGRESS`, `BLOCKED`, or `NO_BATCH`.
- **`bin/cfq scan [--format=json|md|tsv]`** — `json` (default): `{repos: [{path, plan, todo,
  batches: [{name, priority, open, done, archived, report, dependsOn, blocked, unknownDeps,
  inProgress, planning}]}]}`. `md`/`tsv`: one row per batch (Repo, Batch, Priority, Open/Done,
  Status), `Status` one of `BLOCKED`/`PLANNING`/`IN_PROGRESS`/`OK`.
- **`bin/cfq report index [--repo <substr>] [--batch <substr>]`** — `[{batch, repo, date, status,
  deviations, cost: {outputTokens, turns}}, …]`, sorted newest-first. `status`: `GREEN`/`RED`/
  `MIXED`.
- **`bin/cfq report detail <batch-dir>`** — `{found, batch, repo, started, status, deviationsTotal,
  cost: {outputTokens, turns}, phases: [{phase, status, summary, deviations, errors, verification,
  commit, telemetry}], todos: [{file, title}]}`. `found: false` (only) when the batch has no
  `report.json`.
- **`bin/cfq report last-failure <batch-dir> <phase-slug>`** — `{found: false}` or `{found: true,
  phase, note, at}` for that phase's most recent red attempt, if any.
- **`bin/cfq runtime plugins`** — `{status: "OK", plugins: [name, …]}`.
- **`bin/cfq runtime plugin-installed <name>`** — `{installed: boolean}`.

## Language and documentation

`codeLanguage` governs everything executable or read as an instruction — code, comments, commit
messages, `README`, `CLAUDE.md`, `SKILL.md`. `docs/` is the only multilingual area: each additional
language in `docLanguages` gets its own tree at `docs/<lang>/…`, mirroring the same files.
`docLevel` controls how much documentation a repo keeps at all (table above). Override any of the
three per repo via `set --repo` or the legacy `env` block shown above.

The documentation standard itself lives in `claude/plugins/cfq/references/doc-style.md` (page structure, formatting,
translation rules); a repo overrides it by adding its own `docs/STYLE.md`, which wins whenever it
exists.

## See also

- [usage.md](usage.md) — what each setting actually changes in practice
- [setup.md](setup.md) — installation and first-time setup, including host dependencies
