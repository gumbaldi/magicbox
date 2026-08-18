# Settings Explanations

- `codeLanguage` — language of everything executed or read as an instruction: code, comments,
  commit messages, `README`, `CLAUDE.md`, `SKILL.md`.
- `docLanguages` — additional languages kept under `docs/<lang>/`; empty means documentation
  follows `codeLanguage` alone.
- `docLevel` — how much documentation a repo keeps: `minimal` (README only), `standard`, `full`.
- `maintenanceEvery` — commits since the last maintenance run before it's due again; `0` disables
  maintenance entirely.
- `usePonytailAudit` — gates only the optional cleanup audit, **one task among several** in the
  maintenance run; it is not the switch for the maintenance run itself, which is controlled by
  `maintenanceEvery`.

The language settings are global but a repo's own language can differ: it overrides them via
`"env"` in its versioned `<repo>/.claude/settings.json` (e.g. `CFQ_CODE_LANGUAGE`,
`CFQ_DOC_LANGUAGES`, `CFQ_DOC_LEVEL`), so the override travels with the repo rather than living in
global settings.
