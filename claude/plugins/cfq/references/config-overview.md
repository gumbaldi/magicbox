# New Repo Config Overview

Only read when pfq's **Start Block** preflight has `repo.known: false` — shown right before its
`AskUserQuestion`; the config question below is one of that call's (up to three)
questions, not a separate call.

Show the full config:
run `bin/cfq settings list --repo <repo-root> --sources` alongside the per-key explanations from
`bin/cfq settings describe` and `<plugin-root>/references/settings-explain.md`. Most keys
have a per-repo override available (`scope` includes `repo` in the schema — only `scanRoots`,
`securityTimeoutSeconds` and `securityFindingsCap` are global-only); call out `codeLanguage`,
`docLanguages`, `docLevel` specifically since they matter most to a repo the user is newly working
in, and note whether `--sources` reports any of them as `env:repo-legacy` (an override still living
in the old `<repo-root>/.claude/settings.json` `env` block rather than the repo settings file).

## The Config Question

The third `AskUserQuestion` option (only when `repo.known` is `false`): keep the config as-is
(default, fast path) vs. adjust something now. Adjustments go through `bin/cfq settings set <key>
<value>`, exactly as in `code-for-queue`'s **Settings**, and run before **Start Block**'s write
probe. This never blocks — either answer continues straight through the rest of the start block.

Print the `Config` status line: `➖ known repo`, `⚠️ new repo · reviewed` (user kept defaults), or
`⚠️ new repo · adjusted <n>` (n = number of keys changed).
