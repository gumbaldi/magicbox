# Language Rules for Planning

Only read when Step 7 finds a phase that touches documentation. `codeLanguage`, `docLanguages`,
and `docLevel` were already read in Step 7 — this file only covers the documentation-specific
consequences.

- List every language path under "Affected Files": `docs/<codeLanguage>/<path>` plus one
  `docs/<lang>/<path>` per `docLanguages` entry. These additional files count toward the phase's
  size estimate.
- `docLevel: minimal` → no `docs/` tree, `README` only, `docLanguages` is moot. Say so once as a
  hint, never a warning, and never repeat it for the rest of the session.
- Point the phase at `${CLAUDE_PLUGIN_ROOT}/references/doc-style.md`, or `<repo>/docs/STYLE.md` if
  that file exists in the target repo — either way, the file is loaded when that phase actually
  runs, not during this planning session.
