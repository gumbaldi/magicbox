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
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" list [--repo <path>] [--sources]
```

`--repo` folds in that repo's tier-2 file. `--sources` adds, per key, which tier actually supplied
the value: `env:process`, `env:repo-legacy` (the legacy `env` block, not a `CFQ_*` var set in the
shell), `repo`, `global`, or `default`. Or run `/cfq` and pick the settings step — same data,
presented as a table.

## Change settings

```bash
# Global (tier 3)
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" set maintenanceEvery 25

# Repo-scoped (tier 2) — only for this clone's repo
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" set --repo "$(git rev-parse --show-toplevel)" docLevel standard

# Remove an override, falling back to the next tier
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" unset --repo "$(git rev-parse --show-toplevel)" docLevel
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
| `implExploreModel` | `CFQ_IMPL_EXPLORE_MODEL` | `haiku` | global, repo | model ifq's pre-implementation research and test-run subagents run on |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | global, repo | lifts both model checks above |
| `stopPct` | `CFQ_STOP_PCT` | `60` | global, repo | context share at which `ifq` hands off the session; `0` hands off after every phase |
| `phaseContextGrowth` | — | `{S:7,M:15,L:25}` | global, repo | expected context-window growth percentage per phase size, used by the pre-phase size gate's projection |
| `sessionStaleSeconds` | `CFQ_SESSION_STALE_SECONDS` | `1800` | global, repo | seconds since a session transcript was last touched before it's considered stale (lock takeover, resume staleness) |
| `ctxWindowLimits` | — | see `describe ctxWindowLimits` | global, repo | context-window size in tokens per model, keyed by whether the model gets the large window |
| `scanRoots` | `CFQ_SCAN_ROOTS` | `~/git` | global only | roots for automatic queue discovery |
| `useMattpocockGrilling` | `CFQ_USE_MATTPOCOCK` | `false` | global, repo | allows `grillMode: classic` |
| `usePonytailAudit` | `CFQ_USE_PONYTAIL` | `false` | global, repo | enables the optional cleanup audit, one of several maintenance tasks gated by `maintenanceEvery` |
| `codeLanguage` | `CFQ_CODE_LANGUAGE` | `en` | global, repo | language of everything executed or read as an instruction: code, comments, commit messages, `README`, `CLAUDE.md`, `SKILL.md` |
| `docLanguages` | `CFQ_DOC_LANGUAGES` | `""` | global, repo | additional languages kept under `docs/<lang>/`; empty means documentation follows `codeLanguage` alone |
| `docLevel` | `CFQ_DOC_LEVEL` | `minimal` | global, repo | how much documentation a repo keeps: `minimal` (`README` only), `standard` (`docs/` with setup, usage, configuration), `full` (additionally a reference page per module/script and an architecture overview) |
| `maintenanceEvery` | `CFQ_MAINTENANCE_EVERY` | `50` | global, repo | commits since the last maintenance run before it's due again; `0` disables maintenance entirely |
| `branchPerBatch` | — | `true` | global, repo | `ifq` creates one branch per batch right after the go-ahead |
| `changelogFile` | — | `cfq.changelog.yml` | global, repo | path (repo-root-relative) `ifq` records batch progress to; empty disables the changelog |
| `htmlReport` | — | `false` | global, repo | render the HTML report automatically at batch end; otherwise only on `/rfq` request |
| `planBlockedPlugins` | — | `superpowers` | global, repo | prohibition: never used while planning, not even indirectly |
| `implBlockedPlugins` | — | `superpowers` | global, repo | prohibition for implementation |
| `telemetrySyncRepo` | `CFQ_TELEMETRY_SYNC_REPO` | `""` | global, repo | absolute path to a dedicated telemetry git repo; empty disables the sync |
| `securityTimeoutSeconds` | — | `30` | global only | timeout in seconds for the batch-completion security scan |
| `securityFindingsCap` | — | `20` | global only | maximum number of security findings surfaced per batch-completion scan |
| `gitStatePolicy` | — | `local` | global, repo | `local` keeps repo-local cfq workflow state in that clone's Git `info/exclude`, leaving `.claude/cfq/settings.json` trackable; `trackable` removes only cfq's managed exclude block and leaves the rest to normal repository Git policy |
| `setupDone` | — | `false` | state, not a setting | internal marker: first-time setup (`/cfq`) has run. Lives outside the settings schema — `cfq-settings.sh state get/set setupDone` — since it's runtime state, not policy; a repo new to the registry separately gets a one-time config overview at park time (`pfq` Step 10a) |

The prohibition keys (`planBlockedPlugins`/`implBlockedPlugins`) are worth being conservative with
even though they're repo-overridable like most others — they also block indirect calls, so set
them sparingly.

Adding a new setting means adding one schema entry to `cfq-settings.sh` — `list`/`get`/`set`/
`unset`/`describe` and every precedence tier read it generically, no second place to touch.

## Language and documentation

`codeLanguage` governs everything executable or read as an instruction — code, comments, commit
messages, `README`, `CLAUDE.md`, `SKILL.md`. `docs/` is the only multilingual area: each additional
language in `docLanguages` gets its own tree at `docs/<lang>/…`, mirroring the same files.
`docLevel` controls how much documentation a repo keeps at all (table above). Override any of the
three per repo via `set --repo` or the legacy `env` block shown above.

The documentation standard itself lives in `references/doc-style.md` (page structure, formatting,
translation rules); a repo overrides it by adding its own `docs/STYLE.md`, which wins whenever it
exists.

## See also

- [usage.md](usage.md) — what each setting actually changes in practice
- [setup.md](setup.md) — installation and first-time setup, including host dependencies
