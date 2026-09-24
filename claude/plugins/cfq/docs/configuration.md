# Configuration

How to view and change cfq's settings, globally or per repo, and what each one does.

## Precedence

**env var > repo `.claude/cfq/settings.json` > global `settings.json` > default.** Four tiers,
highest wins:

1. **Env var** (`CFQ_*`) — highest precedence, same variable works globally or per repo (see
   below).
2. **Repo settings** — `<repo>/.claude/cfq/settings.json`, written via `set --repo <path>`.
   Applies only to that repo, wherever it's cloned.
3. **Global settings** — `~/.claude/cfq/settings.json`, written via plain `set`.
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

## Settings menu

```
"${CLAUDE_PLUGIN_ROOT}/bin/cfq" settings menu [--repo <path>] [--group <id>] [--format text|json]
```

A grouped overview of the settings above — the eight group headings below, in that fixed order.
Without `--group`, each group prints its title plus up to two keys (non-default ones first) and a
`… +N` count for the rest; with `--group <id>`, every key of that one group, one line each: marker,
value, type, and its allowed values or range. Every line carries a one-letter marker for which tier
actually supplied the value — `[D]` default, `[G]` global, `[R]` repo, `[E]` env (env-shadowed, or
the legacy `env:repo-legacy` block, which additionally gets a trailing `(legacy env)` note).
Without `--repo`, the header reads `SETTINGS · global` and no key ever shows `[R]`; with `--repo`,
it shows that repo's effective values instead. `--format json` prints the same grouped data as
`{groups:[{id,title,keys:[{key,value,source,marker,type,values,min,scopes,default,description}]}]}`
— the shape `/cfq`'s own interactive navigation walks. `--group nope` (an id outside the eight
below) fails with `UNKNOWN_GROUP`.

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

Grouped exactly as `settings menu` groups them — same eight ids, same fixed order (the
`group` field on each schema entry is the single source both read).

### Models

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `planModels` | `CFQ_PLAN_MODELS` | `opus,fable` | global, repo | models allowed to plan; a mismatch only warns |
| `implModels` | `CFQ_IMPL_MODELS` | `sonnet` | global, repo | models allowed to implement; a mismatch aborts `ifq` |
| `orchestratorModels` | `CFQ_ORCHESTRATOR_MODELS` | `""` | global, repo | models the orchestrator session itself is allowed to run under; falls back to `implModels` when empty |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | global, repo | lifts both model checks above |
| `planExploreModel` | `CFQ_PLAN_EXPLORE_MODEL` | `haiku` | global, repo | model pfq's research subagents run on |
| `planExploreModelComplex` | `CFQ_PLAN_EXPLORE_MODEL_COMPLEX` | `sonnet` | global, repo | model for pfq's Explore agents whose task is to judge rather than to locate |
| `implExploreModel` | `CFQ_IMPL_EXPLORE_MODEL` | `haiku` | global, repo | model ifq's pre-implementation research and test-run subagents run on |
| `implExploreModelComplex` | `CFQ_IMPL_EXPLORE_MODEL_COMPLEX` | `sonnet` | global, repo | model for ifq's Explore agents whose task is to judge rather than to locate |

### Planning

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `grillMode` | `CFQ_GRILL_MODE` | `stepwise` | global, repo | `stepwise` = batched rounds of up to 4 questions; `classic` = delegates to `mattpocock-skills:grilling`'s own round format |
| `useMattpocockGrilling` | `CFQ_USE_MATTPOCOCK` | `true` | global, repo | allows `grillMode: classic` |
| `planBlockedPlugins` | — | `superpowers` | global, repo | prohibition: never used while planning, not even indirectly |

### Implementation

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `orchestratorMode` | `CFQ_ORCHESTRATOR_MODE` | `true` | global, repo | `ifq` runs each phase in its own sub-agent instead of implementing in the session itself |
| `onePhasePerSession` | `CFQ_ONE_PHASE_PER_SESSION` | `true` | global, repo | `ifq` always hands off after one phase instead of continuing automatically while the context gate allows it; no effect in orchestrator mode |
| `branchPerBatch` | — | `true` | global, repo | `ifq` creates one branch per batch right after the go-ahead |
| `implBlockedPlugins` | — | `superpowers` | global, repo | prohibition for implementation |

### Limits & handoff

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `stopUsed` | `CFQ_STOP_USED` | `125000` | global, repo | absolute context tokens at which `ifq` hands off instead of starting another phase; `0` hands off after every phase, `-1` never hands off for this reason |
| `stopFiveHourPct` | `CFQ_STOP_FIVE_HOUR_PCT` | `70` | global, repo | five-hour rate-limit usage in percent at which `ifq` emits a `WARN` before starting another phase, instead of continuing silently; `-1` disables the check |
| `stopSevenDayPct` | `CFQ_STOP_SEVEN_DAY_PCT` | `95` | global, repo | seven-day rate-limit usage in percent at which `ifq` emits a `WARN` before starting another phase, instead of continuing silently; `-1` disables the check |
| `ctxWindowLimits` | — | see `describe ctxWindowLimits` | global, repo | context-window size in tokens per model, keyed by whether the model gets the large window |
| `sessionStaleSeconds` | `CFQ_SESSION_STALE_SECONDS` | `1800` | global, repo | seconds since a session transcript was last touched before it's considered stale (lock takeover, resume staleness) |

### Language & docs

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `codeLanguage` | `CFQ_CODE_LANGUAGE` | `en` | global, repo | language of everything executed or read as an instruction: code, comments, commit messages, `README`, `CLAUDE.md`, `SKILL.md` |
| `docLanguages` | `CFQ_DOC_LANGUAGES` | `""` | global, repo | additional languages kept under `docs/<lang>/`; empty means documentation follows `codeLanguage` alone |
| `docLevel` | `CFQ_DOC_LEVEL` | `minimal` | global, repo | how much documentation a repo keeps: `minimal` (`README` only), `standard` (`docs/` with setup, usage, configuration) |
| `i18nExcludePatterns` | — | `*/locales/*, */locale/*, */i18n/*, */lang/*, */translations/*` | global, repo | Git pathspec exclusions applied to `ifq`'s language-prose sample — directories that intentionally hold multiple languages, never judged as a `codeLanguage` violation |

### Maintenance & security

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `maintenanceEvery` | `CFQ_MAINTENANCE_EVERY` | `50` | global, repo | commits since the last maintenance run before it's due again; `0` disables maintenance entirely |
| `usePonytailAudit` | `CFQ_USE_PONYTAIL` | `true` | global, repo | enables the optional cleanup audit (one of several maintenance tasks gated by `maintenanceEvery`) |
| `securityTimeoutSeconds` | — | `30` | global only | timeout in seconds for the batch-completion security scan |
| `securityFindingsCap` | — | `20` | global only | maximum number of security findings surfaced per batch-completion scan |

### Reports & telemetry

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `htmlReport` | — | `true` | global, repo | keep the report portal synced automatically at batch end; set false to sync only on `/rfq` request |
| `reportDir` | `CFQ_REPORT_DIR` | `""` | global, repo | additional copy of every repo's report portal plus a cross-repo index; empty = repo-local only — see layout below |
| `telemetrySyncRepo` | `CFQ_TELEMETRY_SYNC_REPO` | `""` | global, repo | absolute path to a dedicated telemetry git repo; empty disables the sync |
| `changelogFile` | — | `.claude/cfq/changelog.yml` | global, repo | path (repo-root-relative) `ifq` records batch progress to; also the repository-local batch-number allocation ledger; always versioned — never part of the `gitStatePolicy: local` exclude block; empty disables both the changelog and numbered-batch allocation |

### Repo & git

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
| `gitStatePolicy` | — | `local` | global, repo | `local` keeps repo-local cfq workflow state in that clone's Git `info/exclude`, leaving `.claude/cfq/settings.json` trackable; `trackable` removes only cfq's managed exclude block and leaves the rest to normal repository Git policy |
| `scanRoots` | `CFQ_SCAN_ROOTS` | `~/git` | global only | roots for automatic queue discovery |
| `frameworkRepo` | `CFQ_FRAMEWORK_REPO` | `""` | global only | absolute path of the local cfq source checkout; a `note plan --framework` finding about cfq itself always lands in the global framework inbox (`$HOME/.claude/cfq/framework-inbox/`) instead of the repo being worked on, unless the target repo *is* `frameworkRepo`; `note import <repo-root>` moves accumulated inbox entries into that repo's `plan/` and is a no-op for any other repo; empty means findings just accumulate in the inbox |

### Outside the schema

| Key | Env | Default | Scope | Meaning |
|---|---|---|---|---|
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

Every repo keeps its own report portal at `<repo>/.claude/cfq/reports/index.html` — a fixed viewer
shell (`index.html`, `assets/`) plus plain data files under `data/`, one per batch's plan and
implementation report and one per open `todo`/`plan` entry (`bin/cfq portal sync`/`rebuild`). It's
stable across archiving, since the batch name — not the batch's `impl/`-vs-`impl/done/` location —
is the only thing a batch's own data-file path depends on. With `reportDir` set to an absolute
path, every repo's sync additionally mirrors its own data into
`<reportDir>/<repo-basename>[-<hash>]/data/…` (a short hash suffix only on a name collision between
two different repos) and installs one global viewer shell at `<reportDir>/` itself, whose
`index.html` renders a cross-repo index over every mirrored repo instead of one repo's own overview
— a location reachable outside any one queue's own git-excluded directory and shared across repos,
a WSL user opening reports from Windows Explorer, for example. Either way, `bin/cfq report html
<batch-dir>` (`/rfq`'s own drill-down call) always syncs that one batch fresh and prints its
`file://` route; the portal itself keeps itself current automatically at every batch-affecting
`bin/cfq` mutation (park, phase commit, `finish`, …) by default — `htmlReport` (above) is the
switch that turns that automatic sync off, leaving it to `/rfq` on request.

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
- **`bin/cfq scan [--format=json|md|tsv|overview|next]`** — `json` (default): `{repos: [{path, plan,
  todo, batches: [{name, priority, open, done, archived, report, dependsOn, blocked, unknownDeps,
  inProgress, planning}]}]}`. `md`/`tsv`: one row per batch (Repo, Batch, Priority, Open/Done,
  Status), `Status` one of `BLOCKED`/`PLANNING`/`IN_PROGRESS`/`OK`. `overview`: one row per repo
  (Repo, Plan, Todo, Batches, Status) — `Batches` is the open/done batch counts, `Status` the most
  severe status among the repo's own batches. `next`: one object per repo — `{path, next, reason,
  blocked, planning}` — `next` is the batch name `ifq` would pick (`null` if none selectable),
  `reason` one of `inProgress`/`priority`/`order`/`multipleInProgress`/`null`; the one place the
  `ifq` selection ranking is decided, consumed rather than recomputed by `cfq_ifq_preflight.py`.
- **`bin/cfq phase commit <batch-dir> <phase-json-file> <message-file>`** — the green-phase path:
  commits whatever is already staged (never runs `git add` itself), moves the phase's `.md` file
  into `done/` and appends its `report.json` entry, backfills the commit SHA, pushes (`-u origin
  <branch>` on a first push, a plain `git push` after) and registers the repo — one call in place
  of the six a green phase used to issue one at a time. The phase JSON's `phase` field must be the
  full phase slug (`NN-slug`); a `status` other than `green` is rejected (`phase record` is the
  red-phase path). `<message-file>` is the human-written subject/body (plus `Co-Authored-By`); the
  `CFQ-*` trailers are added internally, the same way `changelog commit-message` adds them. Result:
  `{status: "OK", sha, pushed, branch, pushError?}` on success — a push failure is reported, not
  fatal — or `{status: "NOTHING_STAGED"}` / `{status: "COMMIT_FAILED", detail}` /
  `{status: "RECORD_FAILED", sha, detail}` on the ways it can stop, each with a non-zero exit. The
  general ledger-append primitive itself lives on as `cfq_report.append_phase()`, no longer exposed
  as its own `report append` CLI verb.
- **`bin/cfq report index [--repo <substr>] [--batch <substr>] [--any <substr>] [--text]`** —
  `[{batch, repo, date, status, deviations, cost: {outputTokens, turns}}, …]`, sorted newest-first.
  `status`: `GREEN`/`RED`/`MIXED`. `--any` matches a single argument against repo path or batch
  name and dedupes internally, for when the caller doesn't know which it names; `--repo`/`--batch`
  narrow independently (AND) when both are given. `--text` renders the same filtered rows as a
  terminal table plus one `file://` line per row instead of JSON.
- **`bin/cfq report detail <batch-dir>`** — `{found, batch, repo, started, status, deviationsTotal,
  cost: {outputTokens, turns}, phases: [{phase, status, summary, deviations, errors, verification,
  commit, telemetry}], todos: [{file, title}]}`. `found: false` (only) when the batch has no
  `report.json`.
- **`bin/cfq report set-commit <batch-dir> <phase-slug> <sha>`** — backfills the `commit` field of
  that phase's most recent entry. Exits non-zero when the batch has no entry for `<phase-slug>`; it
  never reports success without writing.
- **`bin/cfq report last-failure <batch-dir> <phase-slug>`** — `{found: false}` or `{found: true,
  phase, note, at}` for that phase's most recent red attempt, if any. `<phase-slug>` is the entry's
  `phase` field, i.e. the full phase slug.
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
