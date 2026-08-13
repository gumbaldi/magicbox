# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin, not an application: three skills (`skills/*/SKILL.md`), four bash scripts
(`scripts/`), six TOML command aliases (`commands/`). No build step, no package manager, no runtime
other than `bash` and `jq` (every script hard-fails without jq).

## Commands

```bash
bash tests/test-scan.sh          # the only test — builds temp repos, asserts scan JSON, prints PASS
```

Scripts write to `$HOME/.claude/code-for-queue/`. Always run them against a throwaway HOME so the
user's real registry and settings stay untouched:

```bash
HOME=$(mktemp -d) bash scripts/cfq-settings.sh list
HOME=$(mktemp -d) CFQ_SCAN_ROOTS=/some/fixture bash scripts/cfq-scan.sh | jq .
bash scripts/ctx-usage.sh        # read-only, safe as-is; must print PCT=<n> OK|STOP, never UNKNOWN
```

Skills call scripts as `"${CLAUDE_PLUGIN_ROOT}/scripts/<x>.sh"` — that variable only exists in an
installed-plugin session, so use relative paths when testing from a checkout.

## Architecture

**Three skills, three roles, one shared data model.** `plan-for-queue` (expensive model) writes phase
plans and never edits code; `implement-for-queue` (cheap model) works exactly one batch per session and
hands off on the context gate; `code-for-queue` is the cross-repo dashboard plus settings. Behaviour
lives in the SKILL.md prose — the scripts only supply numbers and state.

**The queue is the filesystem.** `<repo>/.claude/code-for-queue/<YYYY-MM-DD>-<topic>/NN-slug.md`, with
`.priority` (`low|medium|high`), a `done/` for finished phases and a sibling `done/` for finished
batches. There is no index or bookkeeping file: `cfq-scan.sh` counts live from disk every time, and
"phase finished" *is* the `mv` into `done/`. Anything that changes the layout must change `cfq-scan.sh`
and `tests/test-scan.sh` together.

**Two state files, both outside any repo**, in `$HOME/.claude/code-for-queue/`: `repos.json` (registry
of repos that ever had a queue, written by `cfq-registry.sh add` from both worker skills) and
`settings.json` (`cfq-settings.sh`). `cfq-scan.sh` unions the registry with a `find` over `scanRoots`,
so a repo is discovered even if it was never registered.

**Settings precedence is env > `settings.json` > default**, implemented in `cfq-settings.sh`:
`with_overrides()` applies the `CFQ_*` vars on read only — a `set` on an env-overridden key writes the
file but stays invisible until the variable is gone. Adding a setting means touching three places:
the `defaults` JSON, the validation `case` in `set` (unlisted keys fall through to a bare string
write), and the README table; plus `with_overrides()` if it gets an env var.

## Conventions

- Every command exists twice — short (`pfq.toml`) and long (`plan-for-queue.toml`) — with byte-identical
  `description`/`prompt`. Change one, change both.
- Skill prose is English; every SKILL.md opens with "Always answer in the user's language", and the
  parked plan files in `.claude/code-for-queue/` are German. Match the language of the file you edit.
- The plugin must stay fully usable without `mattpocock-skills` and `ponytail`. Any path touching them
  needs a silent fallback, guarded by `useMattpocockGrilling` / `usePonytailAudit`.
- Bash style throughout: `set -eu`, jq for all JSON, write-to-`.tmp`-then-`mv`, `mktemp` + `trap` cleanup.
- Bump `version` in `.claude-plugin/plugin.json` for user-visible changes. Distribution is via the
  GitHub marketplace, so nothing reaches an installed plugin until it is pushed.

## Self-hosting quirk

This repo drives its own development through its own queue: `.claude/code-for-queue/` holds the plugin's
phase plans and is ignored via the versioned `.gitignore` here (target repos use `.git/info/exclude`
instead). `/ifq` sessions therefore run against this repo and, per the skill, branch to `v0.<N+1>`
rather than committing to `main`.
