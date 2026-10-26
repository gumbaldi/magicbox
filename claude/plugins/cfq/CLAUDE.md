# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin, not an application: three skills (`skills/*/SKILL.md`) whose implementations
live under `scripts/` — all of them stdlib Python (`cfq_settings.py`, `cfq_changelog.py`,
`cfq_report.py`, `cfq_doctor.py` ported as batch `014`; `cfq_layout.py`, `cfq_registry.py`,
`cfq_park.py` ported as batch `017` phase 01; `cfq_lock.py`, `cfq_maintenance.py` ported as batch
`017` phase 02; `cfq_runtime.py` ported as batch `017` phase 03; `ctx_usage.py`,
`cfq_telemetry.py` ported as batch `017` phase 04; `cfq_scan.py`, `cfq_queue_overlap.py` ported
as batch `017` phase 05; `cfq_batch_id.py` ported as batch `017` phase 06; `cfq_brief.py`,
`cfq_lint.py` ported as batch `017` phase 07; `cfq_lang.py`, `cfq_security.py` ported as batch
`017` phase 08; `cfq_branch.py` ported as batch `017` phase 09; `cfq_resume.py`, `cfq_finish.py`
ported as batch `017` phase 10; `cfq_pfq_preflight.py`, `cfq_ifq_preflight.py` ported as batch
`017` phase 11; `cfq_dash.py` ported as batch `017` phase 12; `cfq_trash.py` (plus the
CLI-less `cfq_lib/trash.py`) added as batch `019` phase 01; `cfq_phase.py` added as batch `019`
phase 02; `cfq_batch_id.py`'s `verify`/`recover` verbs (plus the CLI-less `cfq_lib/consistency.py`)
added as batch `019` phase 03; `cfq_note.py` (new), `cfq_batch_id.py`'s `ready` verb,
and `cfq_report.py`'s `skills` verb added as batch `019`
phase 04; `cfq_guard.py` (new) added as batch `019` phase 06; `cfq_portal.py` (new, plus the
CLI-less `cfq_lib/markdown.py`, split out of `cfq_report.py`) added as batch `040` phase 01;
the CLI-less `cfq_lib/flags.py` and `cfq_telemetry.py`'s `settle` verb added as batch `050`; the
CLI-less `cfq_lib/phase_state.py` and `cfq_phase.py`'s `skip`/`unskip` verbs added as batch `051`) —
`bin/cfq` itself stays shell by
design, see Commands — three Markdown command aliases (`commands/`: `cfq`, `pfq`, `ifq`), and `evals/`, on-demand behavioural cases for the skill prose. No build step, no package
manager; `bin/cfq doctor check` reports the host's dependency inventory (`bash`, `git` required,
a Python 3.8+ interpreter as `python3`/`python`/`py`) — see Architecture.

Reference files hold what would otherwise blow the size budget of a `SKILL.md` (see
Conventions): all of them live flat under `references/` (e.g. `doc-style.md`,
`ifq-phase.md`; `phase-template.md` is the skeleton of a phase file) — no per-skill `references/` directory, one path style everywhere
(`${CLAUDE_PLUGIN_ROOT}/references/<file>.md` from a `SKILL.md`, `<plugin-root>/references/<file>.md`
from inside another reference file, since the loader only expands `${CLAUDE_PLUGIN_ROOT}` in
`SKILL.md` itself). Reference files are loaded only on the path that actually needs them, not by
every session.

## Commands

```bash
python3 -m unittest discover -s claude/plugins/cfq/tests   # the whole suite
python3 -m unittest discover -s claude/plugins/cfq/tests -k settings   # one area
```

The test suite sets `CFQ_SETTINGS_AUTO_REPO=0` through `cfq_testlib.py`, so a settings read never
picks up this checkout's own settings file.

Tests are stdlib `unittest`, no installation needed. `pytest claude/plugins/cfq/tests` also works
if you have it, and gives better failure output — it is optional, never required.

```bash
claude plugin eval claude/plugins/cfq --case <name> --runs 1 --ablation none --scaffold --trust-plugin --no-publish
```

Behavioural eval cases for the skill prose live in `evals/`; this runs them on demand, never in CI,
and every run costs model usage — see `evals/README.md` for the full command and the sandbox facts.

Scripts write to `$HOME/.claude/cfq/`. Always run them against a throwaway HOME so the
user's real registry and settings stay untouched:

```bash
HOME=$(mktemp -d) claude/plugins/cfq/bin/cfq settings list
HOME=$(mktemp -d) CFQ_SCAN_ROOTS=/some/fixture claude/plugins/cfq/bin/cfq scan | python3 -m json.tool
claude/plugins/cfq/bin/cfq ctx        # read-only, safe as-is; must print PCT=<n> OK|STOP, never UNKNOWN
```

**`bin/cfq <noun> <verb>` is the entrypoint.** Skills call it as
`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" <noun> <verb>` — that variable only exists in an installed-plugin
session, so use a relative path (`claude/plugins/cfq/bin/cfq ...`) when testing from a checkout. The
scripts under `scripts/` are implementations, still directly runnable (`bash <script>.sh` or
`python3 <script>.py` — the test suite calls them that way on purpose, see Architecture) but no
longer the documented interface; add a new script's noun to `bin/cfq`'s routing table, not a new
call site naming the script. `bin/cfq` itself picks the interpreter by extension (`*.py` →
`python3`, guarded by a `require_python` check that exits 127 with a named message; anything else
→ direct exec) — implementations may be reimplemented in either language without any caller
noticing, which is the point.

Scripts call each other through `bin/cfq <noun>`, never by filename — the same rule that applies
to skills and references. `scripts/cfq_lib/` is the one exception — shared Python with no CLI and
no noun of its own, imported by `cfq_*.py` implementations (`cfq_lib/paths.py` holds the canonical
path helpers; `cfq_lib/proc.py` holds the shared `bin/cfq`/`git` subprocess helpers and `default_branch()`, the
one default-branch resolution every script uses; `cfq_lib/text.py`
holds the shared terminal-rendering helpers — padding, wrapping, aligned columns, icon lookup).
One further exception stays a direct filename call, commented at its call site:
- **Inner-loop calls** (`cfq_batch_id.py`'s per-pair rename and per-orphan reserve,
  `cfq_scan.py`'s per-repo registry-add and per-repo settings-get): a dispatcher exec resolves
  `../bin/cfq` fresh on every iteration, so the direct sibling call is the cheaper trade there.

Any test double that copies `scripts/` to intercept a sibling call by filename (e.g.
`tests/test_ifq_preflight.py`, `tests/test_pfq_preflight.py`) must copy `bin/` alongside it,
preserving the real `bin/../scripts` layout — `bin/cfq` resolves its routing table relative to its
own location, so the copy only routes to the shadowed sibling if both directories move together.

## Architecture

**Three skills, three roles, one shared data model.** `plan-for-queue` (expensive model) writes phase
plans and never edits code; `implement-for-queue` (cheap model) works exactly one batch per session and
hands off on the context gate — or, in orchestrator mode, drives one sub-agent per phase and hands off
on the rate-limit window instead; `code-for-queue` is the cross-repo dashboard plus settings.
The `implement-for-queue` `SKILL.md` carries only what both modes share, and each mode's per-phase
loop lives in its own reference file (`references/orchestrator.md`, `references/ifq-classic.md`).
Behaviour lives in the SKILL.md prose — the scripts only supply numbers and state.

**The queue is the filesystem, split into three queues** under `<repo>/.claude/cfq/` (canonical
path/layout helpers: `cfq_lib/paths.py` — pure path functions, no I/O — and `cfq_layout.py`, which
owns directory creation and the Git-state policy below):
`impl/` holds the phase-plan batches (`<YYYY-MM-DD>-<topic>/NN-slug.md`, `.priority`
(optional, present only when the batch is flagged and then contains exactly `high`), `.dependsOn`
(optional, one batch directory name per line — blocks this batch
until every named one is in `impl/done/`; an unresolvable name is reported, never blocking),
`report.json` (per-phase implementation report plus telemetry — a phase entry also carries
`diffstat` (`{files, insertions, deletions, paths}`, computed from the commit by `phase commit`) and
the optional model-written `observations`; the top level carries `planning` (the planning
session's telemetry), `finish` (the closing snapshot `cfq finish` takes), `notes` (the ledger of
`plan/`/`todo/` entries written during the batch, appended by `cfq note`) and `fromPlan` (the
`plan/` entries `park --from-plan` consumed) — closed onto the ledger together
with the file's move into `done/` and the phase's own Git commit by the single transactional call
`cfq phase commit <batch-dir> <phase-json-file> <message-file>` for green phases — commits
whatever is already staged (never runs `git add` itself), moves the `.md` file, appends the ledger
entry, backfills the commit SHA and pushes (a push failure stays non-fatal; a failure to record
after a successful commit is reported with the SHA instead, never reverting the commit); `cfq
phase record <batch-dir> <phase-json-file>` is the red-phase path (append the ledger entry only,
move nothing); `cfq phase reopen <batch-dir> <phase-slug>` is `record`'s inverse, moving a phase back
out of `done/` and marking the ledger entry `reopened` without touching `status`/`commit`; `cfq
phase skip <batch-dir> <NN|slug> [--reason <text>]` and `phase unskip` move a phase into and out of
`skipped/` and append the skip's own ledger entry; the append primitive itself lives on as
`cfq_report.append_phase()`, no longer exposed as its own `report append` CLI verb). `status.json`
(`{"schema": 1, "phases": {<slug>: {"status": "open"|"done"|"error"|"skipped", …}}}`) is the one
authority for phase state, read and written only through `cfq_lib/phase_state.py`, and no other
module globs phase files to decide a state; `done/` and `skipped/` mirror it (`open` and `error`
phases stay in the batch root), and when the two disagree `status.json` wins. A skipped entry also
carries `reason`, `previous` (the status `unskip` restores) and, once written, `inbox`. `cfq batch
verify [--batch <name>] [--json]` (read-only) and `cfq batch recover --batch <name> [--dry-run]`
(applies the repairs `verify` can name automatically) exist only to keep the mirror and the other
three sources that also record it — `report.json`, the `CFQ-Batch`/`CFQ-Phase`/`CFQ-Phase-Status`
Git commit trailers, and the changelog (`changelogFile`) — honest about what `status.json` says;
neither verb ever synthesizes plan **text** back from a changelog summary,
only a ledger entry (JSON) or a file `cfq trash` still holds (`cfq_lib/consistency.py`). `.planning`
(written by `cfq batch allocate` when the batch directory is created; `park` refreshes it on every
re-park during the same `plan-for-queue` session but only while it still exists, and never
re-creates it after `batch ready` has removed it — a re-park at that point warns on stderr instead;
removed only once `plan-for-queue`'s lint step goes clean — a batch younger than 30 minutes with
this marker still present is still being written and `implement-for-queue`
never offers it, mirroring `.lock`'s staleness window). `.review` replaces `.planning` when
`plan-for-queue` enters its review gate (`cfq batch review`), stores a per-file hash snapshot,
has no staleness window, and is removed only by `cfq batch ready`; `implement-for-queue` never
offers a batch that carries it. A batch has a `done/` for finished phases
and a sibling `impl/done/` for finished batches); `plan/` is the inbox of planning requests
(`<YYYY-MM-DD>-<slug>.md`, format in `claude/plugins/cfq/references/queue-entries.md`) that `implement-for-queue` drops for
follow-up work out of scope for the current phase, and `plan-for-queue` reads and parks into `done/`
(an entry whose fix landed incidentally, rather than through `park --from-plan`, is closed instead
via `cfq note close`, which appends a `## Closed` section and moves it into `plan/done/`);
`todo/` holds one-off follow-ups (`<YYYY-MM-DD>-<slug>.md`, optional `check: <shell-command>` line)
that `implement-for-queue` writes, `code-for-queue` works off through `cfq note sweep` (**Management**,
current repo only). `implement-for-queue` reads `impl/`, writes `plan/` and `todo/`;
`plan-for-queue` reads `plan/`, writes `impl/`. `.worker-brief.json` (written by `cfq worker brief`, read by the phase worker, replaced per phase)
may sit in a batch directory next to `status.json`. `.lock`, `telemetry.jsonl` (one line per planning
session and per phase) and `.maintenance` (the maintenance-run marker) stay at the queue root, not
inside any of the three subdirectories — `.lock` is held by the currently running
`implement-for-queue` session, liveness derived from the holder's transcript mtime. Apart from phase
state there is no index or bookkeeping file: `cfq_scan.py` counts batches, notes and the rest live
from disk every time, and phase counts from `status.json`; a batch whose `status.json` is missing or
unreadable is reported with all counts `0` and `consistency: "unknown"` and never offered. "Phase
finished" is the `status.json` write, with the `mv` into the batch's `done/` as its mirror.
Anything that changes the layout must change `cfq_scan.py` and `tests/test_scan.py` together — and,
for `report.json`, `tests/test_report.py` as well, for `status.json` `tests/test_phase_state.py`.
It also changes an external contract: `PreToolUse` hooks on `Write`/`Edit` outside this repository
key on these paths — see **Hook contract** in `README.md` before renaming anything here.

**Three state files, all outside any repo**, in `$HOME/.claude/cfq/` (the global store's own
path — same directory name as the repo-local `.claude/cfq/` layout above, rooted at `$HOME` rather
than inside any repo, and otherwise unrelated to it): `repos.json`
(registry of repos that ever had a queue, written by `cfq_registry.py add` from both worker skills),
`settings.json` (the global settings tier, `cfq_settings.py`), and `state.json` (schema-less runtime
state such as `setupDone`, `cfq_settings.py state get/set`). `cfq_scan.py` unions the registry with a
`find` over `scanRoots`, so a repo is discovered even if it was never registered.

**Settings precedence is env > repo `.claude/cfq/settings.json` > global `settings.json` >
default**, one schema in `cfq_settings.py` driving every tier generically. A read without a flag
uses the repository the shell stands in; a write without `--repo` always goes to the global file.
`settings get`/`list` take `--repo <path>`, `--global` (no repo tier) or `--default` (schema default
only), mutually exclusive: `merged_tiers()` layers
global-then-repo file overlays onto the schema `defaults`, `with_overrides()` then applies `CFQ_*`
env vars on top on read only — a `set` on an env-overridden key writes the file but stays invisible
until the variable is gone. Adding a setting means adding **one schema entry** — type, default,
scope (`global` and/or `repo`), optional `env` mapping, description — every subcommand
(`list`/`get`/`set`/`unset`/`describe`) and every precedence tier reads that one entry generically,
there is no second hand-written case arm or table to keep in sync. `migrate <repo-root>` copies
whatever the legacy per-repo `env` block (`<repo>/.claude/settings.json`) currently overrides into
the new repo-scoped file, so that mechanism doesn't have to live forever. `stopUsed`
is resolved by `ctx_usage.py` through `bin/cfq settings get stopUsed`, same precedence chain as
any other setting — anyone reworking that script breaks the precedence chain at exactly that
point. `preflight-impl` passes its repository with `--repo`; a bare `bin/cfq ctx` relies on the
working-directory lookup of `settings get`. The gate reports three verdicts and five reasons: capacity (`stopUsed`) always blocks
(`HANDOFF`/`STOP`); a rate limit (`stopFiveHourPct`/`stopSevenDayPct`) or an unresolvable context
reading only warns (`WARN`, advisory — the user decides whether to continue). All five reasons are
resolved through the same precedence chain, with three independent `-1` off switches. The rate
limit is still checked first, but capacity always wins the verdict when both fire — a full context
window must never be downgraded to a warning just because a rate-limit reason happened to be
evaluated first; the `stopUsed: 0` bypass suppresses only the capacity reason, never the
rate-limit `WARN`. `setupDone` is the
one exception that lives outside this schema entirely — it's runtime state, not policy, and goes
through `cfq_settings.py state get/set` against a separate schema-less store instead.

**`cfq_runtime.py` is the one Claude-Code-specific adapter.** Session id, transcript path, model
name and context usage each used to be resolved independently in `ctx_usage.py`, `cfq_lock.py` and
`cfq_telemetry.py`; all three now call `cfq_runtime.py transcript-path [--repo <path>] [--exact]`
and `cfq_runtime.py context` instead of re-deriving it. `context` prefers the statusline payload,
falls back to parsing the transcript directly, and returns `status: "degraded"` (primary diagnostic
preserved) rather than silently hiding it when the documented interface itself breaks structurally —
callers may still use the fallback value, but the breakage stays visible. `ctxWindowLimits` (the
model→context-window-size table) lives in the settings schema as data, not in this adapter, since
it's a retunable number rather than detection logic. Acceptance test: a
Claude Code runtime/statusline/plugin-cache representation change should only ever require editing
`cfq_runtime.py` (+ its tests/fixtures). If a change to any other aggregator is ever needed for
such a change, that is itself a regression to fix, not an accepted cost.

**`cfq_doctor.py` is the host dependency doctor**, deliberately dependency-light itself (it's the
one check every other script cannot perform on its own behalf) and reading a plain-text inventory
(`config/dependencies.txt`: required / alternative / optional) — a missing `python3` itself is
caught one layer down, by `bin/cfq`'s own `require_python` guard, since the doctor cannot report an
interpreter it needs to run. The bundled `SessionStart` hook (`bin/cfq doctor hook`) is silent on a
healthy host and warns both user and Claude only when a required command is missing — it never
installs anything itself.

**`cfq_guard.py` is the only script the runtime invokes rather than a skill.** Every other script
is called from `SKILL.md`/reference prose through `bin/cfq`; `cfq_guard.py pretooluse` is wired
directly into `hooks/hooks.json`'s `PreToolUse` entries and runs on every `Bash`/`Write`/`Edit`
call in the session, whether or not a cfq skill is active. It denies a raw shell mutation
(`rm`/`mv`/`cp`/`truncate`/`shred`/`dd`/`ln`/`install`/`sed -i`, a `>`/`>>` redirect, or
`find … -delete`) whose argument resolves — against the tool call's own `cwd`, not a literal-string
match — into `.claude/cfq`, and a `Write`/`Edit` landing directly in `impl/<batch>/done/**`,
`impl/<batch>/skipped/**` or on a batch's `status.json`. Its
fail-open behaviour (an internal exception allows the call and logs to stderr instead of denying)
is intentional, not an oversight: a guard that crashes closed would fail every `Bash` call in every
session, which is worse than the incident it exists to prevent now that phases 01-05 give every
legitimate mutation a deterministic `bin/cfq` subcommand to point to instead.

**Telemetry is metadata only.** `cfq_telemetry.py` derives everything from the running session's own
transcript (`cfq_runtime.py`'s path resolution, reused rather than reinvented) — never from a model's
own estimate of its token usage. Only numbers, timestamps and names are carried into a record;
`tests/test_telemetry.py` asserts this structurally (every leaf field name against a whitelist) so
that adding a field which happens to carry free text fails the test on purpose, not by omission.
A record's sub-agent turns are further split by the `WORKER_AGENT` attribution name into
`subagent_worker` and `subagent_explore` (the unchanged `subagent` field stays the sum of both), so
a phase-worker sub-agent's activity is never counted as an Explore agent's, or vice versa, by any
downstream aggregate that reads it — including `bin/cfq report summary`'s orchestrator/worker
split, and `bin/cfq telemetry show --session`'s `layers` object.

**Schema 3 counts per API response and records every sub-agent as its own node, grouped into four
cost layers.** Claude Code writes one transcript line per content block of a response, each
repeating that response's `message.id` and usage, so `collapse_responses()` reduces the lines to
one entry per `message.id` before anything is summed; a `turn` is a response, never a line. A
record written under the older per-line counting carries `schema` 1 or 2 and is about twice too
high. `by_agent`/`subagent`/`subagent_worker`/`subagent_explore` keep their existing meaning.
`agents` lists one entry per `agent-<id>.jsonl` attributed to the record
(`collect_agent_nodes()`): the agent's root (the depth-1 ancestor, walked via `parentAgentId`)
names its spawning `Agent` call by `toolUseId`, and the record owns the agent when the main
transcript's timestamp for that call is inside the record's `(since, upper]` span — the spawning
call, not the agent's own activity, decides which record an agent belongs to; only an agent
without a usable link falls back to its own first response. All responses of an attributed agent
count, never clipped by timestamp. Read together with its sibling `agent-<id>.meta.json`
(`agentType`, `description`, `spawnDepth`, `toolUseId`, `parentAgentId` at depth ≥ 2) — a missing
or unreadable meta falls back to depth 1, type from the turn's own `attributionAgent`, no parent.
Every node and every layer carries `by_model: {<model>: T}` next to its totals, which is what the
portal's cost-by-model views read. `layers` sums the nodes (plus the session's own transcript as
`main`) into the tree the report reads: `main` (the session), `main_explore` (sub-agents the
session spawned directly), `worker` (each `cfq:cfq-phase-worker` instance), `worker_explore`
(sub-agents a worker spawned — resolved by walking `parentAgentId` up through every meta file in
the directory, `_resolve_layer()`, not only the ones with turns in this window, so a depth-≥3
agent still resolves through an intermediate parent). Each layer carries `sums()`, `models`,
`efforts`, `by_model` and `count` (number of agents; always `1` for `main`). Invariant, asserted per
fixture in `tests/test_telemetry.py`: `main + main_explore + worker + worker_explore` == `totals +
subagent`, field by field — this holds structurally because every listed agent's turns land in
exactly one of the three non-`main` layers. Records are appended to `telemetry.jsonl` as before,
so `telemetry sync` carries the new fields into the telemetry repo without any change on its own
part; only a reader that cares needs to look at `schema`.

**Schema 3 records are provisional until their session has ended (`since`, `settled`, `rev`).**
`build_record()` writes `since`
(the window's lower bound), `settled: false` and `rev: 1`. The session goes on after the commit
(the worker's closing message, the orchestrator's summary), so `cfq telemetry settle <repo-root>`
recomputes each such record once its session is over — transcript and `subagents/` quiet for
`SETTLE_QUIET_SECONDS`, and not the running session — bounded above by the next record of the same
session (that record's `since`), and writes it back into its `report.json` as `settled: true`,
`rev: 2`; the new revision is appended to `telemetry.jsonl` next to the old one, and `telemetry show`
aggregates only the highest `rev` per `(session_id, kind, batch, phase, since)`. A vanished
transcript settles the record with its numbers unchanged. `cfq_lib/portal_hook.py`'s `sync()` runs
`settle` on every mutating verb, ahead of the portal sync and regardless of `htmlReport`
(`CFQ_PORTAL_SYNC=0` suppresses both); there is no hook of its own. Addressing an ended session by
id goes through `cfq_runtime.py transcript-path|subagent-dir --session <id>`.

**A subagent pays off only where the parent never needs the full raw result in its own context
afterward.** Two shapes qualify. The first is delegation: `plan-for-queue`'s **Understand** and
`implement-for-queue`'s classic **Implementation** step (`references/ifq-classic.md`) both delegate multi-file or unclear-scope research to Explore agents
(`planExploreModel` / `implExploreModel`), and `implement-for-queue` may additionally run a phase's
verification command through the same subagent to keep raw test/build log noise out of the
expensive model's context. Research fits, since the parent gets a distilled summary and stops
there; a **green** verification run fits the same way — pass/fail plus which command ran is
enough. A **red** run does not get filtered — the subagent returns the complete, unfiltered
failure output, because the implementing model needs the full error to fix it; summarizing a
failure is exactly the case where a cheaper model can lose the detail that matters.

The second is ownership, not delegation: `implement-for-queue`'s orchestrator mode spawns one
worker sub-agent per phase (`references/orchestrator.md`), and that worker implements, verifies
and commits its own phase completely — including the code, the tests and any documentation the
phase touches. The orchestrator reads only the worker's returned report, never the diff it
produced, so the same "parent doesn't need the raw result back" condition holds even though the
subagent's own work is implementation. This does not reopen delegation for a classic-mode session:
what still never fits, in either mode, is a fragment of work whose result the *parent itself* must
read back to finish — a *newly spawned* subagent starts cold and re-reads what the parent already
holds (a continued one, addressed via `SendMessage`, keeps its context instead — see
`claude/plugins/cfq/references/ifq-phase.md`'s "Reusing a Warm Explore Agent" for when that applies),
and the parent then reads the subagent's output again to verify it, two or three reads where a
direct read-and-edit would have been one.

That trade-off is measurable, not asserted: compare a subagent call's reported input-token count
(`cfq_telemetry.py`'s per-turn numbers) against the token cost of the parent reading and editing
the same files directly — for a fragment the parent must read back, the subagent path loses.
For the ownership case, `bin/cfq report summary <batch-dir>`'s orchestrator/worker split (its
additive TSV fields 12-15, populated whenever a phase actually ran as a worker) is the same
comparison already run per batch — read it before assuming the split still favors orchestrator
mode. Fields 12/13 are the `main` layer's own turns/output (the session itself) and 14/15 the
`worker` layer's, both read straight off `layers` (or derived the same way for an older record)
rather than by subtracting one pool from another; the invariant across the whole row is
`orchestrator_turns + worker_turns + explore_turns + worker_explore_turns` == the batch's whole
`total_turns` (and the same shape for output) — four disjoint layers summing to the total, never a
subtraction that could go negative. Anyone tempted to delegate anything beyond exploration,
verification execution, or a whole self-committing phase should re-run the relevant comparison
first, not take this paragraph on faith.

**`cfq_portal.py` is the data layer behind `<repo>/.claude/cfq/reports/index.html`**, and, since
batch `040` phase 05, the *only* HTML `report` produces — a `portal sync <repo-root> [--batch
<name>]...` / `portal rebuild <repo-root> [--migrate]` pair that writes into
`<repo>/.claude/cfq/reports/data/`: `site.js` (repo, commit URL, plugin version), `queue.js` (the
repo overview — totals, per-size baselines, calibration points, one row per batch and per entry),
`batch/<name>.js` (context, phases with their attempts, cost, notes, closing result, flags) and
`entry/<id>.js` (one per `todo`/`plan` entry, open and closed — the archive; `<id>` is
`<kind>-<file stem>`). Every data file registers a JSON payload on `window.CFQ_DATA["<key>"]`
rather than being `fetch()`-ed — a browser blocks `fetch()` of a local JSON file under `file://`,
but a `<script src>` tag still works — and **a file's path below `data/` is always its key plus
`.js`**, which is how the viewer finds it and how a file whose source is gone is recognized as
stale; a writer and a loader that disagree on that path produce a page that renders empty, which
is exactly what the pre-`050` viewer did. Payloads are deterministic (sorted object keys, no
timestamp beyond one already in the source data) and written only when their content changed
(`write_if_changed()`, the same tmp-file-plus-`os.replace` pattern as `cfq_lib.render.write_json`),
so a `sync` that changes nothing writes nothing and reports `{"written": [], "unchanged": <n>,
"removed": []}`. `sync` reuses `cfq_scan.scan_repo()` (the dashboard's own per-repo record builder)
for batch status/open/done/blocked/planning rather than re-deriving it, and
`cfq_report.phase_layer_sums()` (four-layer cost split, per-model split included) for every cost
total it writes; `merged` comes from Git: whether the batch's branch, or its last recorded commit, is reachable
from the default branch, two Git calls per `sync`. The Markdown subset renderer (`cfq_lib/markdown.py`: headings, lists nested
up to three levels, paragraphs, fenced and indented code blocks, block quotes, pipe tables, `---`
rules, `check:` lines, `**bold**`/`*emphasis*`/`` `code` ``; no links) produces the `…Html` fields,
the only values the viewer inserts as HTML — every other value reaches the DOM through
`textContent`. It is used by `cfq_portal.py` alone; `cfq_report.py`'s old Overview renderer was
deleted as dead code (batch 047 phase 03).

`cfq_lib/flags.py` derives the portal's flags (`warn`/`info`, thresholds as module constants, not
settings) and the per-size baselines and calibration points in `queue.js` as pure functions over the
batch payloads; `sync()` reads a batch outside the `--batch` filter back from its data file and only
recomputes its `flags`.

The viewer shell is every file in the plugin's `portal/` directory: `install_shell()` globs the
directory (`shell_files()` — `index.html` goes to the root, everything else to `assets/`), so a new
script needs no registration, and runs whenever `reports/.portal-version` differs from the running
plugin's own version. The same version change deletes what the new version no longer ships — files in
`assets/` that `portal/` lacks and the flat `<batch>.html` files the retired per-batch renderer left
under `reports/` (`remove_legacy_html()`) — and reports both in `removed`; an unchanged version
copies and removes nothing. The viewer is several plain scripts on one shared `CFQ` namespace
(`core.js` first, `app.js` last — router, route table and data-path rules; `overview.js` — KPI strip
and the sortable batch table; later views register through `CFQ.core.register(slot, item)` instead
of editing earlier files; `charts.js` draws the inline-SVG charts and `overview-charts.js`
registers the cost-per-batch and size-calibration `overviewPanel`s; `batch.js` draws the batch page
— header, tab bar, phase table with per-phase detail — and registers its own `batchTab`/`phaseTab`
items; `batch-cost.js`, `batch-notes.js` and `timeline.js` register the Cost tab and sub-tab, the
Notes and Closing tabs and the `batchPhasesTop` timeline; `entry.js` draws the todo-card/plan-entry
page and `repos.js` the cross-repo index of a `reportDir` mirror). `tests/js/*.test.mjs` run under
Node over a fake DOM (`tests/js/helpers.mjs`, which also holds the contract-shaped fixtures every
viewer test file shares); `tests/js/e2e.test.mjs` walks every view over the files a real `portal
sync` wrote; `tests/test_portal_viewer.py` runs them. No CDN, no build step, charts are hand-written
SVG.

With `reportDir` set, `sync()` additionally mirrors every data file into
`<reportDir>/<repo-basename>[-<hash>]/data/…`, writes `<reportDir>/data/repos.js` (the list of
mirrored repos) and installs one global viewer shell at `reportDir` itself (batch 040 phase 03);
every batch-affecting `bin/cfq` mutation (`park`, `phase` `record`/`commit`/`reopen`, `lock
acquire`, `finish`, `batch ready`, `trash put`/`restore`, `note`'s mutating verbs, `dash render`)
fires `cfq_lib/portal_hook.py`'s `sync()` as a side effect after its own mutation succeeds — first
`telemetry settle`, then the portal sync, the latter gated on `htmlReport` and neither touching
the triggering verb's own exit code or stdout. The portal is the only HTML cfq produces; on demand,
`bin/cfq portal sync <repo-root>` refreshes it. `portal rebuild <repo-root> --migrate` is the
one-time cleanup for a repo that still carries the old per-batch HTML
files — it deletes every stale `reports/*.html` (repo-local, and this repo's own mirror directory
under `reportDir` when set) whose name matches a batch's own shape, never touching `assets/`,
`data/`, or the portal's own `index.html`.

## Conventions

- Rationale and history for skill/reference/agent rules lives in `claude/plugins/cfq/docs/design-notes.md`,
  not in the skill text itself — new rationale goes there, never back into a `SKILL.md`, reference
  file, or agent definition.
- Commands are Markdown only (Claude Code loads no other format), one short alias per skill. No
  command may share a skill's name: the session's listing then shows the command's description
  instead of the skill's.
- Skill prose is English; every `SKILL.md` opens with "Always answer in the user's language" — the
  interview is the only part that runs in the user's language. Everything written into a repo (plan
  files, queue entries, batch directory names, commit messages, the changelog) follows `codeLanguage`,
  documentation additionally `docLanguages` — except structural markers, which are always English
  regardless of `codeLanguage`: headings in plan and queue files (`## Size`, `## Context`, …), the
  `(new)` marker, `.priority` values. Only the prose content inside those files follows
  `codeLanguage`.
- **Progress is reported as status lines, not prose.** The canonical `## Output Format` block
  (section header in caps, per step `<icon> <label padded to 16 chars> <detail>`, icons
  `✅ ⚠️ ❌ ➖`, printed live as each step completes) lives in
  `claude/plugins/cfq/references/output-format.md`, read by `implement-for-queue`,
  `plan-for-queue` and `code-for-queue`. A new skill points at the reference
  file rather than copying the block. `AskUserQuestion`, briefings, and data tables are exempt and stay prose.
- **16,000-character budget per `SKILL.md`, counted on the text as loaded** (each
  `${CLAUDE_PLUGIN_ROOT}` counted at its expanded installed-path length). Every session pays for a
  skill's size before anything happens, and Claude Code re-attaches only the first 5,000 tokens of
  a skill after a context compaction; a line count rewards long lines, so size is what is
  measured. Content needed only on some paths moves to `references/` and is loaded on that path
  only — pattern: `claude/plugins/cfq/references/grilling.md`. `tests/test_reference_paths.py`'s
  `check_skill_size_budget` enforces it — a `SKILL.md` over budget fails the suite. The working
  target is about 14,500 characters, so a small addition does not immediately break the build.
- **Deterministic work belongs in a script, not in prose.** Reading a marker, counting commits,
  diffing file lists: a script call costs about 20 tokens; the same instruction spelled out in
  prose costs that every session, even on the runs where the path never executes.
- **No skill or reference file instructs a shell mutation of anything under `.claude/cfq/`** —
  every such operation (`phase record`/`commit`/`reopen`, `trash put`, `note plan`/`todo`/`close`,
  `park --from-plan`, `batch ready`, …) is a `bin/cfq` subcommand, never a
  raw `rm`/`mv`/`mkdir`/`jq` written into the text. `tests/test_reference_paths.py` greps for this
  structurally.
- **Four prose rules for skill, reference and agent text.** (1) Every `references/*.md` is named
  directly, with its `${CLAUDE_PLUGIN_ROOT}/` or `<plugin-root>/` path, in at least one `SKILL.md`
  or agent definition. (2) A reference file over 100 lines opens with a `## Contents` section
  listing its other `## ` headings as bullets. (3) Text states what applies now, in the present
  tense — no "no longer", "as before", "since v0.2" and the like; history goes to `docs/design-notes.md`.
  (4) An item in `plan/` or `todo/` is an "entry", never a "card" or "queue note". A `description`
  in frontmatter holds neither `<` nor `>`. `tests/test_reference_paths.py` enforces all of them.
- The plugin must stay fully usable without `mattpocock-skills` and `ponytail`. Any path touching them
  needs a silent fallback, guarded by `useMattpocockGrilling` / `usePonytailAudit`.
- Python scripts are stdlib only; JSON is written via `cfq_lib.render.write_json` (tmp file +
  `os.replace`), never a raw file write.
- `bin/cfq` is the only shell file, Bash 3.2-compatible, logic-free — routing and interpreter
  discovery only.
- Bump `version` in `.claude-plugin/plugin.json` for user-visible changes. The plugin's `name` there is
  `cfq` (not `code-for-queue` — that was the pre-0.2 name), which is what Claude Code prefixes skill
  names with. Distribution is via the GitHub marketplace, which tracks this repo's default branch
  (`main`) — nothing reaches an installed plugin until the change is merged into `main`, not merely
  pushed to a feature branch.
- `.claude-plugin/plugin.json` is plugin-local (lives in `claude/plugins/cfq/.claude-plugin/`); the repo-level
  `.claude-plugin/marketplace.json` lives at the repo root and lists this plugin with
  `"source": "./claude/plugins/cfq"`.

## Status Vocabulary

Every read-only aggregator (`cfq_pfq_preflight.py`, `cfq_ifq_preflight.py`, `cfq_scan.py
--format=`, `cfq_runtime.py plugins`, and any future one) reports a
`status` field skills react to structurally, never by parsing prose. `status` is always exactly one
of:

- `OK` — normal result, no caller action needed beyond reading `data`.
- `NO_REPO` — target path is not a registered/valid repo.
- `NO_BATCH` — no batch matches the request (empty queue, or filter matched nothing).
- `MULTIPLE_IN_PROGRESS` — more than one batch has an active lock/in-progress marker (invariant
  violation, must be surfaced, never silently picked around).
- `BLOCKED` — batch exists but `.dependsOn` is unsatisfied.
- `PLANNING` — batch still has its `.planning` marker, or is held by `.review`; not
  implementation-ready. The `review` field carries the distinction, no new status string.
- `LOCKED` — another session holds the repo lock.
- `DIRTY` — repo has uncommitted changes where a clean tree was required.
- `UNKNOWN_CONTEXT` — context usage could not be resolved (mirrors `ctx_usage.py`'s existing
  `UNKNOWN`, not a new concept — just the field name aggregators use in JSON).
- `BATCH_WIDTH_MIGRATION_BLOCKED` — parking the next numbered batch would require a wider fixed
  width, but active CFQ queue work still exists. The batch-id helper's own action/detail is passed
  through; skills do not calculate widths themselves.
- `RUNTIME_DEGRADED` — `cfq_runtime.py` returned `status:"degraded"`: a usable fallback exists but
  the primary Claude-Code interface failed structurally. The aggregator passes the adapter's own
  code/hint through unmodified in a `runtimeDiagnostic` field, never re-derives or hides it.

Any additional detail goes in a `detail`/`note`/`runtimeDiagnostic` field, never folded into
`status` itself. The report-outcome vocabulary (`GREEN`/`RED`/`MIXED`, phase-level) is a
documented, additive extension for that one domain, not a conflicting scheme — it coexists with,
not replaces, the list above. The same goes for the phase states `open`/`done`/`error`/`skipped`
in `status.json`: a separate, additive vocabulary for phases, never an aggregator `status`, and no
new aggregator status was added for them. Don't invent parallel status strings elsewhere; reuse this list.
`MODE_MISMATCH` is the one token in this vocabulary that is never a JSON `status` value — it's
`cfq_brief.py`'s stderr/exit-2 refusal when `--phase` is called while `orchestratorMode` is on,
reported by exit code rather than by a field a caller parses.

## Self-hosting quirk

This repo drives its own development through its own queue: `<repo-root>/.claude/cfq/` holds
the plugin's phase plans and is ignored via the versioned `.gitignore` at the repo root, except
`changelog.yml` (and `settings.json`), which stay versioned (target repos use `.git/info/exclude`
instead, per `gitStatePolicy`, with the same carve-out). The queue lives in the **repo root**, not inside `claude/plugins/cfq/` — it
is not part of the plugin, it's this monorepo's own self-hosting state. `/ifq` sessions therefore run
against the repo root and, per the skill (and like every other repo since `branchPerBatch`), branch
to `cfq/<batch-directory-name>` per batch and record progress in `.claude/cfq/changelog.yml`
(`cfq_changelog.py`) rather than committing to `main` directly. Batches parked before the
numbered-identity refactor keep their legacy `vX.Y-<slug>` branch and `<YYYY-MM-DD>-<slug>` directory
name until they finish; only batches parked after cutover get a numbered
`<NNN>-<YYYY-MM-DD>-<slug>` identity and `cfq/`-prefixed branch. `changelog.yml` is kept newest-first
by every writing verb (`changelog normalize` is the idempotent re-sort) and is force-tracked even
if a repo's own ignore rule matches it. It is parsed
and written line-wise on purpose, never through a YAML library, so comments, field order and
layout survive a write untouched outside the lines actually changing; adding a YAML library here
would be a regression, not an upgrade.
