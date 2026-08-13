# code-for-queue (cfq)

Plan with an expensive model, implement with a cheap one. Phased plans get parked as numbered
markdown files in a repo-local queue, then worked off one batch per session, phase by phase. A
dashboard shows every queue across every repo at a glance.

## Installation

```
/plugin marketplace add gumbaldi/codeforqueue
/plugin install cfq@codeforqueue
```

Then run `/cfq` once for first-time setup.

Upgrading from 0.1.x: the plugin was renamed from `code-for-queue` to `cfq` so its skills show up as
`cfq:plan-for-queue`. Claude Code treats that as a different plugin, so remove the old one once:
`/plugin uninstall code-for-queue`, then install as above. Settings and the repo registry live in
`~/.claude/code-for-queue/` and are kept.

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
3. `/ifq` to implement, one batch per session, phase by phase. Every green phase is committed
   and pushed immediately. The session stops and hands off cleanly once the context window gets
   too full.

Never two batches in the same session, even if the first finishes early — different plans
belong in separate context windows.

## Queue layout

```
<repo>/.claude/code-for-queue/
  <YYYY-MM-DD>-<topic>/
    01-first-phase.md
    02-second-phase.md
    .priority            # low | medium | high
    done/                # finished phases
  done/                  # finished batches
```

The path is ignored locally via `.git/info/exclude` — deliberately not via the versioned
`.gitignore`, since the queue is local working state, not something to publish.

## Reports

Every phase `ifq` finishes — green or red — is recorded to `<batch-dir>/report.json`: which
phases went green, which failed, where the implementation departed from the plan, what broke,
which verification ran, and the commit SHA. It lives in the batch directory, so it travels with
the batch into `done/` and is covered by the same `.git/info/exclude` entry as the rest of the
queue.

Run `/rfq` for a compact terminal table across all repos, or drill into a single batch for the
detailed HTML report. The HTML is regenerated fresh on every request and can be deleted freely —
`report.json` is the source of truth.

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
| `planPreferredPlugins` | — | `[]` | **recommendation**: give these plugins extra consideration while planning |
| `planBlockedPlugins` | — | `superpowers` | **prohibition**: never used while planning |
| `implPreferredPlugins` | — | `[]` | recommendation for implementation |
| `implBlockedPlugins` | — | `superpowers` | prohibition for implementation |

Preferred and blocked are deliberately asymmetric: preferred is a hint, not a requirement —
nothing is forced if none of them fit. Blocked is strict and should be set sparingly, since it
also blocks indirect calls.

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
