# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin, not an application: four skills (`skills/*/SKILL.md`), twenty-one bash scripts
(`scripts/`) plus one isolated migration utility (`scripts/migrations/`), eight TOML command aliases
(`commands/`). No build step, no package manager, no runtime other than `bash` and `jq` (every script
hard-fails without jq except `cfq-doctor.sh` itself, which is jq-free on purpose — see Architecture).

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
bash claude/plugins/cfq/tests/test-changelog.sh     # cfq-changelog.sh init/finish, prints PASS
bash claude/plugins/cfq/tests/test-brief-park.sh    # cfq-brief.sh + cfq-park.sh, prints PASS
bash claude/plugins/cfq/tests/test-branch.sh        # cfq-branch.sh mode/version/base, prints PASS
bash claude/plugins/cfq/tests/test-finish.sh        # cfq-finish.sh batch-done sequence, lock always released, prints PASS
bash claude/plugins/cfq/tests/test-ctx-usage.sh     # ctx-usage.sh gate mode boundary matrix, prints PASS
bash claude/plugins/cfq/tests/test-resume.sh        # cfq-resume.sh state reconstruction, prints PASS
bash claude/plugins/cfq/tests/test-runtime.sh       # cfq-runtime.sh transcript-path/context adapter, prints PASS
bash claude/plugins/cfq/tests/test-layout.sh        # cfq-paths.sh + cfq-layout.sh canonical layout/Git policy, prints PASS
bash claude/plugins/cfq/tests/test-layout-migration.sh  # scripts/migrations/cfq-layout-v1.sh, prints PASS
bash claude/plugins/cfq/tests/test-doctor.sh        # cfq-doctor.sh dependency checks, prints PASS
bash claude/plugins/cfq/tests/test-no-duplicate-defaults.sh  # no script hardcodes a copy of a schema default, prints PASS
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

**The queue is the filesystem, split into three queues** under `<repo>/.claude/cfq/` (canonical
path/layout helpers: `cfq-paths.sh` — pure path functions, no I/O — and `cfq-layout.sh`, which owns
directory creation and the Git-state policy below; the previous repo-local layout is understood only
by the isolated `scripts/migrations/cfq-layout-v1.sh` upgrade utility):
`impl/` holds the phase-plan batches (`<YYYY-MM-DD>-<topic>/NN-slug.md`, `.priority`
(optional, present only when the batch is flagged and then contains exactly `high`), `.dependsOn`
(optional, one batch directory name per line — blocks this batch
until every named one is in `impl/done/`; an unresolvable name is reported, never blocking),
`report.json` (per-phase implementation report plus telemetry, appended by `implement-for-queue`
after every phase and travelling with the batch into `impl/done/`), `.planning` (written by
`cfq-park.sh` when the batch directory is created, refreshed on every re-park during the same
`plan-for-queue` session, removed only once `plan-for-queue`'s lint step goes clean — a batch
younger than 30 minutes with this marker still present is still being written and `implement-for-queue`
never offers it, mirroring `.lock`'s staleness window), a `done/` for finished phases
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

**Three state files, all outside any repo**, in `$HOME/.claude/code-for-queue/` (the global store's
own path — unrelated to and not renamed by the repo-local `.claude/cfq/` layout above): `repos.json`
(registry of repos that ever had a queue, written by `cfq-registry.sh add` from both worker skills),
`settings.json` (the global settings tier, `cfq-settings.sh`), and `state.json` (schema-less runtime
state such as `setupDone`, `cfq-settings.sh state get/set`). `cfq-scan.sh` unions the registry with a
`find` over `scanRoots`, so a repo is discovered even if it was never registered.

**Settings precedence is env > repo `.claude/cfq/settings.json` > global `settings.json` >
default**, one schema in `cfq-settings.sh` driving every tier generically: `merged_tiers()` layers
global-then-repo file overlays onto the schema `defaults`, `with_overrides()` then applies `CFQ_*`
env vars on top on read only — a `set` on an env-overridden key writes the file but stays invisible
until the variable is gone. Adding a setting means adding **one schema entry** — type, default,
scope (`global` and/or `repo`), optional `env` mapping, description — every subcommand
(`list`/`get`/`set`/`unset`/`describe`) and every precedence tier reads that one entry generically,
there is no second hand-written case arm or table to keep in sync. `migrate <repo-root>` copies
whatever the legacy per-repo `env` block (`<repo>/.claude/settings.json`) currently overrides into
the new repo-scoped file, so that mechanism doesn't have to live forever. `stopPct` is a normal
schema key like any other — no special env-only case remains; it and `phaseContextGrowth` are
resolved by `ctx-usage.sh` through `cfq-settings.sh get`, not read from the environment directly —
anyone reworking that script breaks the precedence chain at exactly that point. `setupDone` is the
one exception that lives outside this schema entirely — it's runtime state, not policy, and goes
through `cfq-settings.sh state get/set` against a separate schema-less store instead.

**`cfq-runtime.sh` is the one Claude-Code-specific adapter.** Session id, transcript path, model
name and context usage each used to be resolved independently in `ctx-usage.sh`, `cfq-lock.sh` and
`cfq-telemetry.sh`; all three now call `cfq-runtime.sh transcript-path [--repo <path>] [--exact]`
and `cfq-runtime.sh context` instead of re-deriving it. `context` prefers the statusline payload,
falls back to parsing the transcript directly, and returns `status: "degraded"` (primary diagnostic
preserved) rather than silently hiding it when the documented interface itself breaks structurally —
callers may still use the fallback value, but the breakage stays visible. `ctxWindowLimits` (the
model→context-window-size table) and `phaseContextGrowth` live in the settings schema as data, not
in this adapter, since they're retunable numbers rather than detection logic. A future Claude Code
runtime change should only ever touch this one file.

**`cfq-doctor.sh` is the host dependency doctor**, deliberately jq-free (it's the one check every
other script cannot perform on its own behalf) and reading a plain-text inventory
(`config/dependencies.txt`: required / alternative / optional). The bundled `SessionStart` hook
(`cfq-doctor.sh hook`) is silent on a healthy host and warns both user and Claude only when a
required command is missing — it never installs anything itself.

**Telemetry is metadata only.** `cfq-telemetry.sh` derives everything from the running session's own
transcript (`cfq-runtime.sh`'s path resolution, reused rather than reinvented) — never from a model's
own estimate of its token usage. Only numbers, timestamps and names are carried into a record;
`tests/test-telemetry.sh` asserts this structurally (every leaf field name against a whitelist) so
that adding a field which happens to carry free text fails the test on purpose, not by omission.

**Subagents are for exploration and mechanical test execution, never for content the parent must
own.** `plan-for-queue` Step 2 and `implement-for-queue` Step 4 both delegate multi-file or
unclear-scope research to Explore agents (`planExploreModel` / `implExploreModel`), and
`implement-for-queue` may additionally run a phase's verification command through the same
subagent to keep raw test/build log noise out of the expensive model's context. A subagent pays
off only where the parent doesn't need the full raw result in its own context afterward: research
fits, since the parent gets a distilled summary and stops there; a **green** verification run fits
the same way — pass/fail plus which command ran is enough. A **red** run does not get filtered —
the subagent returns the complete, unfiltered failure output, because the implementing model needs
the full error to fix it; summarizing a failure is exactly the case where a cheaper model can lose
the detail that matters. Implementation, test writing and documentation stay off subagents
entirely — the subagent starts cold, re-reads what the parent already holds, and the parent then
reads the subagent's output again to verify it, two or three reads where a direct read-and-edit
would have been one. That trade-off is measurable, not asserted: compare a subagent call's reported
input-token count (`cfq-telemetry.sh`'s per-turn numbers) against the token cost of the parent
reading and editing the same files directly — for implementation, test writing and documentation
the subagent path loses. Anyone tempted to delegate anything beyond exploration or verification
execution should re-run that comparison first, not take this paragraph on faith.

## Conventions

- Every command exists twice — short (`pfq.toml`) and long (`plan-for-queue.toml`) — with byte-identical
  `description`/`prompt`. Change one, change both.
- Skill prose is English; every `SKILL.md` opens with "Always answer in the user's language" — the
  interview is the only part that runs in the user's language. Everything written into a repo (plan
  files, queue cards, batch directory names, commit messages, the changelog) follows `codeLanguage`,
  documentation additionally `docLanguages` — except structural markers, which are always English
  regardless of `codeLanguage`: headings in plan and queue files (`## Size`, `## Context`, …), the
  `(new)` marker, `.priority` values. Only the prose content inside those files follows
  `codeLanguage`.
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

This repo drives its own development through its own queue: `<repo-root>/.claude/cfq/` holds
the plugin's phase plans and is ignored via the versioned `.gitignore` at the repo root (target repos
use `.git/info/exclude` instead, per `gitStatePolicy`). The queue lives in the **repo root**, not inside `claude/plugins/cfq/` — it
is not part of the plugin, it's this monorepo's own self-hosting state. `/ifq` sessions therefore run
against the repo root and, per the skill (and like every other repo since `branchPerBatch`), branch
to `cfq/<batch-directory-name>` per batch and record progress in `.claude/cfq/changelog.yml`
(`cfq-changelog.sh`) rather than committing to `main` directly. Batches parked before the
numbered-identity refactor keep their legacy `vX.Y-<slug>` branch and `<YYYY-MM-DD>-<slug>` directory
name until they finish; only batches parked after cutover get a numbered
`<NNN>-<YYYY-MM-DD>-<slug>` identity and `cfq/`-prefixed branch.
