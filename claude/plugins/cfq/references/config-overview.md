# Step 13: New Repo Config Overview

Only read when Step 13's registry check finds the repo genuinely new.

Show the full config:
run `bin/cfq settings list --repo <repo-root> --sources` alongside the per-key explanations from
`bin/cfq settings describe` and `<plugin-root>/references/settings-explain.md`. Most keys
have a per-repo override available (`scope` includes `repo` in the schema — only `scanRoots`,
`securityTimeoutSeconds` and `securityFindingsCap` are global-only); call out `codeLanguage`,
`docLanguages`, `docLevel` specifically since they matter most to a repo the user is newly working
in, and note whether `--sources` reports any of them as `env:repo-legacy` (an override still living
in the old `<repo-root>/.claude/settings.json` `env` block rather than the repo settings file).

One `AskUserQuestion`: keep the config as-is (default, fast path) vs. adjust something now.
Adjustments go through `bin/cfq settings set <key> <value>`, exactly as in `code-for-queue` Step D.
This step never blocks — either answer continues straight to Step 14.

Print the `Config` status line: `➖ known repo`, `⚠️ new repo · reviewed` (user kept defaults), or
`⚠️ new repo · adjusted <n>` (n = number of keys changed).
