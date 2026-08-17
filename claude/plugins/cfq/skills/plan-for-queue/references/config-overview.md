# Step 10a: New Repo Config Overview

Only read when Step 10a's registry check finds the repo genuinely new.

After Step 10's three status lines print, show the full config:
run `cfq-settings.sh list` alongside the per-key explanations from
`${CLAUDE_PLUGIN_ROOT}/references/settings-explain.md`. Explicitly mark `codeLanguage`,
`docLanguages`, `docLevel` as the three keys with a per-repo override available — they matter most
to a repo the user is newly working in — and note whether this repo's own
`<repo-root>/.claude/settings.json` already carries an `env` override for any of them.

One `AskUserQuestion`: keep the config as-is (default, fast path) vs. adjust something now.
Adjustments go through `cfq-settings.sh set <key> <value>`, exactly as in `code-for-queue` Step D.
This step never blocks — either answer continues straight to Step 11.

Print the `Config` status line: `➖ known repo`, `⚠️ new repo · reviewed` (user kept defaults), or
`⚠️ new repo · adjusted <n>` (n = number of keys changed).
