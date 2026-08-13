# code-for-queue (cfq)

Plan with an expensive model, implement with a cheap one. Phased plans get parked as numbered
markdown files in a repo-local queue, then worked off one batch per session, phase by phase. A
dashboard shows every queue across every repo at a glance.

## Installation

```
/plugin marketplace add gumbaldi/codeforqueue
/plugin install code-for-queue@codeforqueue
```

Then run `/cfq` once for first-time setup.

## The three commands

| Command | Long form | Purpose |
|---|---|---|
| `/pfq` | `/plan-for-queue` | Interview, resolve open questions, park phased plans — no implementation |
| `/ifq` | `/implement-for-queue` | Work off one batch from the current repo's queue, phase by phase |
| `/cfq` | `/code-for-queue` | Cross-repo dashboard, repo-local queue management, settings |

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

## Configuration

Precedence: **env var > `settings.json` > default**. Change via `/cfq` or by editing
`~/.claude/code-for-queue/settings.json` directly.

| Key | Env | Default | Meaning |
|---|---|---|---|
| `grillMode` | `CFQ_GRILL_MODE` | `stepwise` | `stepwise` = one question per round; `classic` = the whole round at once (needs `mattpocock-skills`) |
| `planModels` | `CFQ_PLAN_MODELS` | `opus,fable` | models allowed to plan |
| `implModels` | `CFQ_IMPL_MODELS` | `sonnet` | models allowed to implement |
| `allowAnyModel` | `CFQ_ALLOW_ANY_MODEL` | `false` | lifts both model gates |
| `stopPct` | `CFQ_STOP_PCT` | `50` | context share at which `ifq` hands off the session |
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

- **`mattpocock-skills`** — powers `grillMode: classic`, the frontier-per-round interview mode.
  Install: `/plugin marketplace add anthropics/claude-plugins-official`, then
  `/plugin install mattpocock-skills@claude-plugins-official`.
- **`ponytail`** — powers the optional cleanup audit at the end of a planning session.
  Install: `/plugin marketplace add DietrichGebert/ponytail`, then
  `/plugin install ponytail@ponytail`.

Everything except classic grill mode and the cleanup audit works fully without either plugin.

## Credits

The grilling procedure builds on `mattpocock-skills:grilling` (MIT) — the design-tree/frontier
model is theirs; the one-question-per-round, select-box-with-recommendation format is cfq's
addition.

MIT licensed.
