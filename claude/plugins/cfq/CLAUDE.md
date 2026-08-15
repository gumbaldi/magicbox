# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin, not an application: four skills (`skills/*/SKILL.md`), eleven bash scripts
(`scripts/`), eight TOML command aliases (`commands/`). No build step, no package manager, no runtime
other than `bash` and `jq` (every script hard-fails without jq).

Reference files hold what would otherwise blow the 200-line budget of a `SKILL.md` (see
Conventions): plugin-level under `references/` (e.g. `doc-style.md`), or per-skill under
`skills/<name>/references/` (e.g. `implement-for-queue/references/queues.md`). Either way they're
loaded only on the path that actually needs them, not by every session.

## Commands

```bash
bash claude/plugins/cfq/tests/test-settings.sh      # cfq-settings.sh merge/precedence, prints PASS
bash claude/plugins/cfq/tests/test-scan.sh          # builds temp repos, asserts scan JSON, prints PASS
bash claude/plugins/cfq/tests/test-report.sh        # exercises cfq-report.sh append/summary/html, prints PASS
bash claude/plugins/cfq/tests/test-telemetry.sh     # cfq-telemetry.sh record/sync, prompt-leak whitelist, prints PASS
bash claude/plugins/cfq/tests/test-lock.sh          # cfq-lock.sh acquire/release/takeover, prints PASS
bash claude/plugins/cfq/tests/test-checks.sh        # cfq-lint.sh + cfq-security.sh, prints PASS
```

Scripts write to `$HOME/.claude/code-for-queue/`. Always run them against a throwaway HOME so the
user's real registry and settings stay untouched:

```bash
HOME=$(mktemp -d) bash claude/plugins/cfq/scripts/cfq-settings.sh list
HOME=$(mktemp -d) CFQ_SCAN_ROOTS=/some/fixture bash claude/plugins/cfq/scripts/cfq-scan.sh | jq .
bash claude/plugins/cfq/scripts/ctx-usage.sh        # read-only, safe as-is; must print PCT=<n> OK|STOP, never UNKNOWN
```

Skills call scripts as `"${CLAUDE_PLUGIN_ROOT}/scripts/<x>.sh"` — that variable only exists in an
installed-plugin session, so use relative paths (`claude/plugins/cfq/scripts/...`) when testing from a checkout.

## Architecture

**Four skills, four roles, one shared data model.** `plan-for-queue` (expensive model) writes phase
plans and never edits code; `implement-for-queue` (cheap model) works exactly one batch per session and
hands off on the context gate; `code-for-queue` is the cross-repo dashboard plus settings;
`report-for-queue` only reads, never writes — it surfaces the reports `implement-for-queue` produces.
Behaviour lives in the SKILL.md prose — the scripts only supply numbers and state.

**The queue is the filesystem, split into three queues** under `<repo>/.claude/code-for-queue/`:
`impl/` holds the phase-plan batches (`<YYYY-MM-DD>-<topic>/NN-slug.md`, `.priority`
(`low|medium|high`), `.dependsOn` (optional, one batch directory name per line — blocks this batch
until every named one is in `impl/done/`; an unresolvable name is reported, never blocking),
`report.json` (per-phase implementation report plus telemetry, appended by `implement-for-queue`
after every phase and travelling with the batch into `impl/done/`), a `done/` for finished phases
and a sibling `impl/done/` for finished batches); `plan/` is the inbox of planning requests
(`<YYYY-MM-DD>-<slug>.md`, format in `references/queues.md`) that `implement-for-queue` drops for
follow-up work out of scope for the current phase, and `plan-for-queue` reads and parks into `done/`;
`todo/` holds one-off follow-ups (`<YYYY-MM-DD>-<slug>.md`, optional `check: <shell-command>` line)
that `implement-for-queue` writes, `code-for-queue` works off (Step C, current repo only), and
`report-for-queue` only lists. `implement-for-queue` reads `impl/`, writes `plan/` and `todo/`;
`plan-for-queue` reads `plan/`, writes `impl/`. `.lock`, `telemetry.jsonl` (one line per planning
session and per phase) and `.maintenance` (the maintenance-run marker) stay at the queue root, not
inside any of the three subdirectories — `.lock` is held by the currently running
`implement-for-queue` session, liveness derived from the holder's transcript mtime. There is no
index or bookkeeping file: `cfq-scan.sh` counts live from disk every time, and "phase finished" *is*
the `mv` into `impl/done/`. Anything that changes the layout must change `cfq-scan.sh` and
`tests/test-scan.sh` together — and, for `report.json`, `tests/test-report.sh` as well.

**Two state files, both outside any repo**, in `$HOME/.claude/code-for-queue/`: `repos.json` (registry
of repos that ever had a queue, written by `cfq-registry.sh add` from both worker skills) and
`settings.json` (`cfq-settings.sh`). `cfq-scan.sh` unions the registry with a `find` over `scanRoots`,
so a repo is discovered even if it was never registered.

**Settings precedence is env > `settings.json` > default**, implemented in `cfq-settings.sh`:
`with_overrides()` applies the `CFQ_*` vars on read only — a `set` on an env-overridden key writes the
file but stays invisible until the variable is gone. Adding a setting means touching three places:
the `defaults` JSON, the validation `case` in `set` (unlisted keys fall through to a bare string
write), and the README table; plus `with_overrides()` if it gets an env var. Since v0.3, `merged()`
combines `defaults` with the file (`with_entries(select(.key | in($d)))`) before `list`/`get`/`set`
ever touch it, so a newly introduced key reaches existing installations automatically and a removed
one simply disappears — no migration step needed. `stopPct` is resolved by `ctx-usage.sh` through
`cfq-settings.sh get stopPct`, not read from the environment directly — anyone reworking that script
breaks the precedence chain at exactly that point. Four keys added or renamed since v0.4:
`codeLanguage`, `docLanguages`, `docLevel` (language and doc-tree settings, read by `cfq-lang.sh`)
and `maintenanceEvery` (renamed from the pre-v0.4 maintenance-interval setting, read by
`cfq-maintenance.sh`). The
language keys are global defaults; a repo overrides them per-repo via the `env` block in its own
`<repo>/.claude/settings.json` (`CFQ_CODE_LANGUAGE` etc.) — same precedence chain, just sourced
from the target repo instead of `~/.claude/code-for-queue/settings.json`.

**Telemetry is metadata only.** `cfq-telemetry.sh` derives everything from the running session's own
transcript (`ctx-usage.sh`'s path resolution, reused rather than reinvented) — never from a model's
own estimate of its token usage. Only numbers, timestamps and names are carried into a record;
`tests/test-telemetry.sh` asserts this structurally (every leaf field name against a whitelist) so
that adding a field which happens to carry free text fails the test on purpose, not by omission.

## Conventions

- Every command exists twice — short (`pfq.toml`) and long (`plan-for-queue.toml`) — with byte-identical
  `description`/`prompt`. Change one, change both.
- Skill prose is English; every `SKILL.md` opens with "Always answer in the user's language" — the
  interview is the only part that runs in the user's language. Everything written into a repo (plan
  files, queue cards, batch directory names, commit messages, the changelog) follows `codeLanguage`,
  documentation additionally `docLanguages`.
- **Progress is reported as status lines, not prose.** Every SKILL.md carries a word-for-word
  identical `## Output Format` block (section header in caps, per step `<icon> <label padded to
  16 chars> <detail>`, icons `✅ ⚠️ ❌ ➖`, printed live as each step completes). A new skill
  copies the block from `implement-for-queue/SKILL.md` and adds only its own `## Section Map`.
  `AskUserQuestion`, briefings, and data tables are exempt and stay prose. Change the block →
  change it in all four `SKILL.md` files. Two forms are in use — the full block (`code-for-queue`,
  `report-for-queue`) and a shortened one that says the same thing in fewer lines
  (`implement-for-queue`, `plan-for-queue`), needed to stay inside the 200-line budget below.
  Whichever form a skill uses, it must still be word-for-word identical across every skill using
  that form.
- **200-line budget per `SKILL.md`.** Every session pays for a skill's size before anything
  happens. Content that would push a file past that moves to `references/` and is loaded only on
  the path that needs it — pattern: `skills/plan-for-queue/references/grilling.md`.
- **Deterministic work belongs in a script, not in prose.** Reading a marker, counting commits,
  diffing file lists: a script call costs about 20 tokens; the same instruction spelled out in
  prose costs that every session, even on the runs where the path never executes.
- The plugin must stay fully usable without `mattpocock-skills` and `ponytail`. Any path touching them
  needs a silent fallback, guarded by `useMattpocockGrilling` / `usePonytailAudit`.
- Bash style throughout: `set -eu`, jq for all JSON, write-to-`.tmp`-then-`mv`, `mktemp` + `trap` cleanup.
- Bump `version` in `.claude-plugin/plugin.json` for user-visible changes. The plugin's `name` there is
  `cfq` (not `code-for-queue` — that was the pre-0.2 name), which is what Claude Code prefixes skill
  names with. Distribution is via the GitHub marketplace, which tracks this repo's default branch
  (`main`) — nothing reaches an installed plugin until the change is merged into `main`, not merely
  pushed to a feature branch.
- `.claude-plugin/plugin.json` is plugin-local (lives in `claude/plugins/cfq/.claude-plugin/`); the repo-level
  `.claude-plugin/marketplace.json` lives at the repo root and lists this plugin with
  `"source": "./claude/plugins/cfq"`.

## Self-hosting quirk

This repo drives its own development through its own queue: `<repo-root>/.claude/code-for-queue/` holds
the plugin's phase plans and is ignored via the versioned `.gitignore` at the repo root (target repos
use `.git/info/exclude` instead). The queue lives in the **repo root**, not inside `claude/plugins/cfq/` — it
is not part of the plugin, it's this monorepo's own self-hosting state. `/ifq` sessions therefore run
against the repo root and, per the skill, branch to `v0.<N+1>` rather than committing to `main`.
