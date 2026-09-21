# Plan Security Check

Read at pfq's **Security Check** step, every session, unconditionally.

`security.available` (**Start Block**'s preflight, a `gh`/`tea` binary on `PATH`) is a capability
hint only — `false` means the forge-side check comes back empty, but a `package.json` repo still
gets a local `npm audit`, so the check always runs.

Read the `bin/cfq security` call's JSON fields directly (no `jq`, no `/tmp` file); `available ==
false` → print the `hint` once; findings present → state the count per severity.
`fixable.critical`/`fixable.high` > 0 → no `"<repo-root>/.claude/cfq/plan"/*-security-findings.md`
exists yet → write the `plan/` entry (body: counts per severity, the fixable advisories, a note
that a decision is still open); one already exists → write nothing, say so in the status line
instead. Never a question, never a phase in this batch.

Print `Security`: `⚠️` with the hint as detail when `available == false`, `⚠️` with the count per
severity (plus whether a `plan/` entry was written) when findings are present, or `➖ no findings`
when the scan ran clean.
