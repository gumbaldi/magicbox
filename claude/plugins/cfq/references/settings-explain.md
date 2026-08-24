# Settings Explanations

Per-key one-line explanations come from `cfq-settings.sh describe [<key>]` — this file only holds
nuance that doesn't reduce to schema data.

- `usePonytailAudit` — gates only the optional cleanup audit, **one task among several** in the
  maintenance run; it is not the switch for the maintenance run itself, which is controlled by
  `maintenanceEvery`.
- `stopPct` / `phaseContextGrowth` — `stopPct` compares against actual context usage after every
  phase; `phaseContextGrowth` is only a *projection* used by the pre-phase size gate to predict
  whether the next phase would cross `stopPct`, not a second measurement of the same thing. `0`
  for `stopPct` means "hand off after every phase," a deliberate value, not an error.
- `codeLanguage` / `docLanguages` / `docLevel` — global defaults, but a repo's own language can
  differ: override them per repo via `cfq-settings.sh set --repo` or the legacy `env` block in
  `<repo>/.claude/settings.json` (`CFQ_CODE_LANGUAGE` etc.), so the override travels with the repo
  rather than living in global settings.
- `gitStatePolicy` — controls only cfq's own managed block in Git's local `info/exclude`; it never
  touches a repo's versioned `.gitignore` and never overrides normal repository tracking decisions.
