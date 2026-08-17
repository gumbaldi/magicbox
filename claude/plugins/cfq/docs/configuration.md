# Configuration

How to view and change cfq's settings, globally or per repo, and what each one does.

## View settings

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" list
```

Or run `/cfq` and pick the settings step — same data, presented as a table.

## Change settings globally

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" set stopPct 25
```

Writes to `~/.claude/code-for-queue/settings.json`, read by every repo unless that repo overrides
the key (below). `/cfq` offers the same `set` calls interactively.

## Override per repo

Add an `env` block to `<repo>/.claude/settings.json` — it's versioned, so the override travels
with the repo:

```json
{ "env": { "CFQ_CODE_LANGUAGE": "en", "CFQ_DOC_LANGUAGES": "de", "CFQ_DOC_LEVEL": "standard" } }
```

Precedence is env var > `settings.json` > default.

## Settings reference

| Key | Env | Default | Meaning |
|---|---|---|---|
| `grillMode` | `CFQ_GRILL_MODE` | `stepwise` | `stepwise` = batched rounds of up to 4 questions; `classic` = delegates to `mattpocock-skills:grilling`'s own round format |
| `planModels` | `CFQ_PLAN_MODELS` | `opus,fable` | models allowed to plan; a mismatch only warns |
| `implModels` | `CFQ_IMPL_MODELS` | `sonnet` | models allowed to implement; a mismatch aborts `ifq` |
| `planExploreModel` | `CFQ_PLAN_EXPLORE_MODEL` | `haiku` | model pfq's research subagents run on |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | lifts both model checks above |
| `stopPct` | `CFQ_STOP_PCT` | `40` | context share at which `ifq` hands off the session; `0` hands off after every phase |
| `scanRoots` | `CFQ_SCAN_ROOTS` | `~/git` | roots for automatic queue discovery |
| `useMattpocockGrilling` | `CFQ_USE_MATTPOCOCK` | `false` | allows `grillMode: classic` |
| `usePonytailAudit` | `CFQ_USE_PONYTAIL` | `false` | enables the optional cleanup audit, one of several maintenance tasks gated by `maintenanceEvery` |
| `codeLanguage` | `CFQ_CODE_LANGUAGE` | `en` | language of everything executed or read as an instruction: code, comments, commit messages, `README`, `CLAUDE.md`, `SKILL.md` |
| `docLanguages` | `CFQ_DOC_LANGUAGES` | `""` | additional languages kept under `docs/<lang>/`; empty means documentation follows `codeLanguage` alone |
| `docLevel` | `CFQ_DOC_LEVEL` | `minimal` | how much documentation a repo keeps: `minimal` (`README` only), `standard` (`docs/` with setup, usage, configuration), `full` (additionally a reference page per module/script and an architecture overview) |
| `maintenanceEvery` | `CFQ_MAINTENANCE_EVERY` | `50` | commits since the last maintenance run before it's due again; `0` disables maintenance entirely |
| `branchPerBatch` | — | `true` | `ifq` creates one branch per batch right after the go-ahead |
| `changelogFile` | — | `cfq.changelog.yml` | path (repo-root-relative) `ifq` records batch progress to; empty disables the changelog |
| `htmlReport` | — | `false` | render the HTML report automatically at batch end; otherwise only on `/rfq` request |
| `planBlockedPlugins` | — | `superpowers` | prohibition: never used while planning, not even indirectly |
| `implBlockedPlugins` | — | `superpowers` | prohibition for implementation |
| `telemetrySyncRepo` | `CFQ_TELEMETRY_SYNC_REPO` | `""` | absolute path to a dedicated telemetry git repo; empty disables the sync |
| `setupDone` | — | `false` | internal marker: first-time setup (`/cfq`) has run |

The prohibition keys (`planBlockedPlugins`/`implBlockedPlugins`) are the only global-only settings
worth being conservative with — they also block indirect calls, so set them sparingly.

## Language and documentation

`codeLanguage` governs everything executable or read as an instruction — code, comments, commit
messages, `README`, `CLAUDE.md`, `SKILL.md`. `docs/` is the only multilingual area: each additional
language in `docLanguages` gets its own tree at `docs/<lang>/…`, mirroring the same files.
`docLevel` controls how much documentation a repo keeps at all (table above). Override any of the
three per repo via the `env` block shown above.

The documentation standard itself lives in `references/doc-style.md` (page structure, formatting,
translation rules); a repo overrides it by adding its own `docs/STYLE.md`, which wins whenever it
exists.

## See also

- [usage.md](usage.md) — what each setting actually changes in practice
- [setup.md](setup.md) — installation and first-time setup
