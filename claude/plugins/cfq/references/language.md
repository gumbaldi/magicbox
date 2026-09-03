# Language Rules for Planning

The general rule (Step 10): the interview runs in the user's language, everything written runs in
`codeLanguage`, documentation additionally in `docLanguages`. This file is only read when Step 10
finds a phase that touches documentation — `codeLanguage`, `docLanguages`, and `docLevel` were
already read in Step 10, so it only covers the documentation-specific consequences.

- List every language path under "Affected Files": `docs/<codeLanguage>/<path>` plus one
  `docs/<lang>/<path>` per `docLanguages` entry. These additional files count toward the phase's
  size estimate.
- `docLevel: minimal` → no `docs/` tree, `README` only, `docLanguages` is moot. Say so once as a
  hint, never a warning, and never repeat it for the rest of the session.
- Point the phase at `<plugin-root>/references/doc-style.md`, or `<repo>/docs/STYLE.md` if
  that file exists in the target repo — either way, the file is loaded when that phase actually
  runs, not during this planning session.
