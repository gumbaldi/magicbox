# Settings Explanations

Per-key one-line explanations come from `cfq-settings.sh describe [<key>]` — this file only holds
nuance that doesn't reduce to schema data.

- `usePonytailAudit` — gates only the optional cleanup audit, **one task among several** in the
  maintenance run; it is not the switch for the maintenance run itself, which is controlled by
  `maintenanceEvery`.
- `stopUsed` — absolute context-token ceiling; `0` hands off after every phase, `-1` disables this
  gate entirely. Normal global/repo setting like any other.
- `codeLanguage` / `docLanguages` / `docLevel` — global defaults, but a repo's own language can
  differ: override them per repo via `cfq-settings.sh set --repo` or the legacy `env` block in
  `<repo>/.claude/settings.json` (`CFQ_CODE_LANGUAGE` etc.), so the override travels with the repo
  rather than living in global settings.
- `gitStatePolicy` — controls only cfq's own managed block in Git's local `info/exclude`; it never
  touches a repo's versioned `.gitignore` and never overrides normal repository tracking decisions.
