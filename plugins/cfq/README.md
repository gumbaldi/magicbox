# code-for-queue (cfq)

Plan with an expensive model, implement with a cheap one. Phased plans get parked as numbered
markdown files in a repo-local queue, then worked off one batch per session, phase by phase. A
dashboard shows every queue across every repo at a glance.

## Installation

```
/plugin marketplace add gumbaldi/gumbaclaude
/plugin install cfq@gumbaclaude
```

Then run `/cfq` once for first-time setup.

Upgrading from a `codeforqueue` marketplace install: the GitHub repo was renamed from
`gumbaldi/codeforqueue` to `gumbaldi/gumbaclaude` (it now hosts all of gumbaldi's Claude Code
plugins, not just this one), and the marketplace name changed to match. Remove the old marketplace
entry and reinstall: `/plugin marketplace remove codeforqueue`, then run the two commands above.
Settings and the repo registry live in `~/.claude/code-for-queue/` and are kept.

Upgrading from 0.1.x: the plugin itself was also renamed from `code-for-queue` to `cfq` so its skills
show up as `cfq:plan-for-queue`. Claude Code treats that as a different plugin, so remove the old one
once: `/plugin uninstall code-for-queue`, then install as above.

## The four commands

| Command | Long form | Purpose |
|---|---|---|
| `/pfq` | `/plan-for-queue` | Interview (quick, thorough, or thorough-with-docs), resolve open questions, park phased plans — no implementation |
| `/ifq` | `/implement-for-queue` | Work off one batch from the current repo's queue, phase by phase |
| `/cfq` | `/code-for-queue` | Cross-repo dashboard, repo-local queue management, settings |
| `/rfq` | `/report-for-queue` | Show implementation reports for finished batches — table and HTML |

## The workflow

1. `/pfq` in an expensive-model session (default: opus/fable) to plan. Output is plan files
   only — no code, no commits.
2. `/clear`, then `/model sonnet`.
3. `/ifq` to implement, one batch per session, phase by phase. `/ifq` briefs the chosen batch and
   waits for go-ahead before locking or writing anything. Every green phase is committed
   and pushed immediately. The session stops and hands off cleanly once the context window gets
   too full.

Never two batches in the same session, even if the first finishes early — different plans
belong in separate context windows. Only one `ifq` session works a given repo at a time: a
second one aborts with the name of the holder, unless that session has been silent for 30
minutes, in which case it's considered dead and taken over.

## Queue layout

```
<repo>/.claude/code-for-queue/
  <YYYY-MM-DD>-<topic>/
    01-first-phase.md
    02-second-phase.md
    .priority            # low | medium | high
    .dependsOn           # optional: one batch directory name per line
    report.json          # written by ifq, includes telemetry
    done/                # finished phases
  done/                  # finished batches
  telemetry.jsonl        # one record per planning session and per phase
  .lock                  # held by the running ifq session
```

The path is ignored locally via `.git/info/exclude` — deliberately not via the versioned
`.gitignore`, since the queue is local working state, not something to publish.

`.dependsOn` blocks a batch for as long as any batch it names hasn't landed in `done/` yet; a
name that resolves to neither an open nor a finished batch is deliberately never blocking —
it's flagged in the dashboard instead.

## Reports

Every phase `ifq` finishes — green or red — is recorded to `<batch-dir>/report.json`: which
phases went green, which failed, where the implementation departed from the plan, what broke,
which verification ran, and the commit SHA. It lives in the batch directory, so it travels with
the batch into `done/` and is covered by the same `.git/info/exclude` entry as the rest of the
queue.

Run `/rfq` for a compact terminal table across all repos, or drill into a single batch for the
detailed HTML report. The HTML is regenerated fresh on every request and can be deleted freely —
`report.json` is the source of truth.

## Telemetry

Every planning session and every implemented phase gets one record: turns, wallclock, and tokens
by kind, broken down by model, reasoning effort, skill, plugin, tool, and the subagent share —
plus the skills the plan recommended for that phase.

What's deliberately **not** recorded: no prompt text, no responses, no tool arguments, no file
contents. Numbers, timestamps and names only.

It's stored in the batch (`report.json`) and repo-locally (`telemetry.jsonl`), both covered by
the same `.git/info/exclude` line as the rest of the queue — nothing is written globally.
Optionally, point `telemetrySyncRepo` at a dedicated telemetry git repo: cfq then appends the new
lines to `<repo-name>.jsonl` there, commits and pushes, at the end of every planning or
implementation session. Failures there are never fatal.

cfq only collects this data — it doesn't analyze it.

## Security

`pfq` checks before the priority question, `ifq` checks again at the end of the batch. The forge
is detected from the origin remote; both common CLIs are supported:

| Forge | CLI | Source |
|---|---|---|
| GitHub | `gh` | Dependabot advisories and code-scanning alerts — SARIF results from a Checkmarx or CodeQL action land there too, so cfq needs no scanner CLI of its own |
| Gitea / Forgejo | `tea` | the forge has no security-alerts API; `tea` only confirms login and reachability, and that's reported openly |
| any | — | `npm audit` whenever a `package.json` exists, always in addition |

The host is checked explicitly against the CLI's own login list, since `tea` otherwise silently
falls back to a mismatched login and queries the wrong instance. A missing CLI or login produces
a hint naming the exact fix (`gh auth login` or `tea login add --url <host>`), never a generic one.

Only `critical`/`high` findings **with** an available fix get planned as a phase — everything else
stays a warning line.

## Configuration

Precedence: **env var > `settings.json` > default**. Change via `/cfq` or by editing
`~/.claude/code-for-queue/settings.json` directly.

| Key | Env | Default | Meaning |
|---|---|---|---|
| `grillMode` | `CFQ_GRILL_MODE` | `stepwise` | `stepwise` = one question per round; `classic` = the whole round at once (needs `mattpocock-skills`) |
| `planModels` | `CFQ_PLAN_MODELS` | `opus,fable` | models allowed to plan |
| `implModels` | `CFQ_IMPL_MODELS` | `sonnet` | models allowed to implement |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | lifts both model gates |
| `stopPct` | `CFQ_STOP_PCT` | `40` | context share at which `ifq` hands off the session; `0` hands off after every phase |
| `scanRoots` | `CFQ_SCAN_ROOTS` | `~/git` | roots for automatic queue discovery |
| `useMattpocockGrilling` | `CFQ_USE_MATTPOCOCK` | `false` | allows `grillMode: classic` |
| `usePonytailAudit` | `CFQ_USE_PONYTAIL` | `false` | enables the optional cleanup audit |
| `planBlockedPlugins` | — | `superpowers` | **prohibition**: never used while planning |
| `implBlockedPlugins` | — | `superpowers` | prohibition for implementation |
| `telemetrySyncRepo` | `CFQ_TELEMETRY_SYNC_REPO` | `""` | absolute path to a dedicated telemetry git repo; empty disables the sync |
| `setupDone` | — | `false` | internal marker: first-time setup (`/cfq` Step A) has run |

There's no global "preferred plugins" setting anymore — recommendations now live **per phase** in
the plan itself, since the planner knows what that specific phase needs. Only the prohibition
stays global, and it's strict: it should be set sparingly, since it also blocks indirect calls.

## Optional dependencies

- **`mattpocock-skills`** — powers `grillMode: classic`, the frontier-per-round interview mode, and
  the `mattpocock-skills:grilling` + `mattpocock-skills:domain-modeling` combination behind the
  "Grilling with docs" path. Install: `/plugin marketplace add anthropics/claude-plugins-official`,
  then `/plugin install mattpocock-skills@claude-plugins-official`.
- **`ponytail`** — powers the optional cleanup audit at the end of a planning session.
  Install: `/plugin marketplace add DietrichGebert/ponytail`, then
  `/plugin install ponytail@ponytail`.

Everything except classic grill mode and the cleanup audit works fully without either plugin —
"Grilling with docs" falls back to the same techniques in prose when `mattpocock-skills` is missing.

## Credits

Adapted from Matt Pocock's skills (MIT) — <https://github.com/mattpocock/skills>. The design-tree /
frontier model comes from `grilling`, the glossary-and-ADR discipline from `domain-modeling`, and the
combination of the two from `grill-with-docs`. cfq's own additions are the one-question-per-round
format, the select-box protocol, and the fallback that keeps all of it working without the plugin.

- Grilling: <https://aihero.dev/skills-grilling>
- Grill with docs: <https://aihero.dev/skills-grill-with-docs>
- Domain modeling: <https://aihero.dev/skills-domain-modeling>

MIT licensed.
