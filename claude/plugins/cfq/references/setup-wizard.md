# Setup Wizard: `/cfq setup`

cfq's onboarding wizard. This file's **Global Part** runs automatically the first time `/cfq` or
`/pfq` starts with `setupDone` still `false`, and any time by name via `/cfq setup` — the same
flow either way; `setupDone` only decides whether it opens on its own. `/ifq` never triggers or
offers it — it runs on the cheap model and stays out of onboarding entirely. Inside a repo, `/cfq
setup` continues into **Repo Part** once the global part finishes; outside a repo, the global part
is the whole wizard. `/pfq` triggers **Repo Part** on its own too, independently of `setupDone` —
see that section's own opening paragraph for when.

## Global Part

### Data

Nothing fetched beyond what the caller already has, plus one direct call for plugin install status
when the caller's own aggregator doesn't carry it:

- `code-for-queue`'s **Aggregate** (`bin/cfq dash`) already carries `.settings` (current
  value/source per key) and `.plugins` (installed + the two switches) — read both from there, no
  second call.
- `plan-for-queue`'s preflight carries `planningPolicy`/`language` but not plugin install status —
  call `"<plugin-root>/bin/cfq" runtime plugins` once for `.plugins`/`.ponytailMode` before the
  **Environment & Plugins** round.

Values shown as "current" throughout this file always come from one of those, never a fresh
`bin/cfq settings get` per question.

### Opening Question

One `AskUserQuestion`, three options, framed per
`<plugin-root>/references/interaction-policy.md`'s **Decision Question Context** in light form —
one plain sentence per area on what it covers, not the full three-part treatment:

- **Keep all defaults (recommended for a quick start)** — nothing is written, the wizard ends
  immediately at **Finish**.
- **Walk through the three areas** — Models, Language Defaults, Environment & Plugins, each its
  own `AskUserQuestion` round, in that order.
- **Pick areas** — a multi-select over the same three names; only the chosen ones run, still in
  the order above.

### Models

One `AskUserQuestion` call, up to 4 questions. Every question's first option is "keep current
(<value>)":

- **Plan models** (`planModels`) — the four known model families (`opus`, `sonnet`, `haiku`,
  `fable`) as options, multi-select; a selection replaces the list wholesale, it is never merged
  with the current one.
- **Implementation models** (`implModels`) — the same four families, multi-select, same
  replace-wholesale semantics.
- **Orchestrator mode** (`orchestratorMode`) — on (`/ifq` spawns one fresh worker sub-agent per
  phase) / off (the session implements every phase itself).

One plain sentence per question before asking: `planModels`/`implModels` gate which model `/pfq`/
`/ifq` are allowed to run under — a mismatch only warns for planning, but aborts implementation;
`orchestratorMode` decides whether `/ifq` hands each phase to a fresh sub-agent (no `/clear` needed
between phases) or keeps implementing in the same session.

### Language Defaults

One `AskUserQuestion` call, up to 4 questions, first option "keep current (<value>)":

- **Code language** (`codeLanguage`) — options: current value, `en`, the language this
  conversation is itself being held in (when it differs from both).
- **Doc languages** (`docLanguages`) — options: current value, "none" (empty list — documentation
  follows `codeLanguage` alone), free text via the question's own **Other**.
- **Doc level** (`docLevel`) — `minimal` (README only) / `standard`.

One plain sentence per question: `codeLanguage` governs everything read or executed as an
instruction — code, comments, commit messages, `README`, `CLAUDE.md`, `SKILL.md`; `docLanguages`
adds parallel `docs/<lang>/` trees on top of it; `docLevel` decides how much documentation a repo
keeps at all.

### Environment & Plugins

One `AskUserQuestion` call, up to 4 questions, first option "keep current (<value>)":

- **Scan roots** (`scanRoots`) — current value, or free text (comma-separated root directories the
  dashboard's scan searches for repos with a queue).
- **Framework repo** (`frameworkRepo`) — current value (or "unset" when empty), "this repo" (only
  offered when the repo this session is running in is itself a cfq source checkout — a
  `claude/plugins/cfq` directory exists at its root), or free text.
- **Grill procedure** (`grillMode`) — `stepwise` (one question per round, works everywhere) /
  `classic` (a full round at once — needs `mattpocock-skills`, falls back to `stepwise` silently
  without it).

One plain sentence per question: `scanRoots` is where the dashboard looks for every repo with a
queue; `frameworkRepo` is where a finding about cfq itself gets parked instead of the repo under
work; `grillMode` picks `/pfq`'s thorough-interview round format.

Then, unchanged from what first-time setup always asked before this wizard existed, in order:

1. **Optional third-party plugins** — for each plugin `.plugins` reports not installed, offer it:
   what it does, what cfq uses it for, install command and docs. Agreement → hand the user the
   `/plugin` command to run and set the matching switch to `true`. Decline → the switch stays
   `false`; cfq must work fully without either plugin, no path may run into a dead end without
   them.

   | Plugin | What cfq uses it for | Installation | Docs |
   |---|---|---|---|
   | `mattpocock-skills` | classic grill mode (`grillMode: classic`) | `/plugin install mattpocock-skills@claude-plugins-official` — if the marketplace is missing: `/plugin marketplace add anthropics/claude-plugins-official` | `github.com/anthropics/claude-plugins-official`, locally the `SKILL.md` under `skills/productivity/grilling/` in the plugin cache |
   | `ponytail` | one one-shot use: an optional cleanup audit (one of several tasks in the maintenance run) | `/plugin marketplace add DietrichGebert/ponytail`, then `/plugin install ponytail@ponytail` | `github.com/DietrichGebert/ponytail`, at runtime `/ponytail-help` |

   An already-installed plugin starts enabled (its switch defaults to `true`) without asking here —
   only offer what `.plugins` reports missing.

2. **Ponytail dormant by default** — only when `.plugins` reports ponytail installed and
   `.ponytailMode` is not `off` — ponytail defaults to `full` mode itself when unconfigured, which
   loads it into every session including `pfq`/`ifq` and every Explore subagent. cfq uses ponytail
   for one one-shot skill invocation that never needs the persistent mode: the optional cleanup
   audit inside the maintenance run. State plainly, in order:

   - **What changes**: `~/.config/ponytail/config.json` gets `{"defaultMode": "off"}`, merged into
     whatever is already there (a user may already have `hideStatus` or `quietStartup` set) — never
     an overwrite. The directory is created if it doesn't exist yet.
   - **What it means**: ponytail stops loading into every session; `/ponytail full` (or any mode)
     still switches it on by hand at any time, and `ponytail:ponytail-audit` keeps working
     untouched either way — it doesn't depend on the persistent mode.
   - **Why cfq asks**: `pfq`'s plan detail and `ifq`'s scope fidelity both degrade under an
     always-on lazy mode — full mode's "does this need to exist at all?" can silently shrink a
     scope `pfq`'s interview already agreed on.
   - **Declining is fine and changes nothing** — no file is written, and this question isn't asked
     again this run. A session where ponytail gets installed or its mode changes after `setupDone`
     is already `true` relies on `cfq doctor check`'s advisory line (which already carries the fix
     command) instead of a second interactive ask.

### Finish

Write only the values the user actually changed, globally — never `--repo`, this is the global
wizard:

```bash
"<plugin-root>/bin/cfq" settings set <key> <value>
```

Print one status line per change, same wording as `code-for-queue`'s **Step D**: `✅ Setting  <key>:
<old> → <new> (global)`. Then mark the wizard done:

```bash
"<plugin-root>/bin/cfq" settings state set setupDone true
```

Print the closing status line: `Setup  ✅ done · <n> changed` — `<n>` is the number of keys
actually written (`0` on the keep-all fast path, which reaches this line without running any area
above).

## Repo Part

Runs automatically the first time `/pfq` starts inside a repo with `repo.known: false` — right
before its own **Start Block** `AskUserQuestion`, replacing the old **Config** question that used
to be one of that call's options — and as the second half of `/cfq setup` inside a repo,
immediately after the **Global Part** above finishes. `/ifq` never triggers or offers it, same as
the global part.

### Data

One call, read once for the whole flow — never re-fetch per area or per question:

```bash
"<plugin-root>/bin/cfq" settings menu --repo <repo-root> --format json
```

Read `codeLanguage`/`docLanguages`/`docLevel` (group `language`), `branchPerBatch` (group
`implementation`), `gitStatePolicy` (group `repo`), `maintenanceEvery` (group `maintenance`), and
`htmlReport`/`reportDir` (group `reports`) from the returned groups — each entry's own
`value`/`source`/`marker` is "current" throughout this section, never a fresh `bin/cfq settings get`
per question. Any of those eight keys reporting `source: "env:repo-legacy"` (an override still
living in `<repo-root>/.claude/settings.json`'s `env` block rather than the repo settings file) →
note it once, before the **Opening Question**, naming the affected key(s) and pointing at `bin/cfq
settings migrate <repo-root>`.

### Opening Question

One `AskUserQuestion`, three options, framed per
`<plugin-root>/references/interaction-policy.md`'s **Decision Question Context** in light form —
one plain sentence per area on what it covers, not the full three-part treatment. Every option's
description ends with the current effective values in one compact line, e.g. `code en · docs
minimal · branch per batch on · maintenance 50 · report on`:

- **Keep the global values for this repo (recommended when unsure)** — nothing is written, the
  wizard ends immediately at **Finish**.
- **Walk through the four areas** — Language & docs, Git, Maintenance, Reports, each its own
  `AskUserQuestion` round, in that order.
- **Pick areas** — a multi-select over the same four names; only the chosen ones run, still in the
  order above.

### Language & docs

One `AskUserQuestion` call, up to 4 questions. Every question's first option is "keep (<effective
value>, from <global|default>)":

- **Code language** (`codeLanguage`) — options: the effective value, the language this conversation
  is itself being held in (when it differs), free text via the question's own **Other**.
- **Doc languages** (`docLanguages`) — options: the effective value, "none" (empty list —
  documentation follows `codeLanguage` alone), free text via **Other**.
- **Doc level** (`docLevel`) — `minimal` (README only) / `standard`.

One plain sentence per question — the same wording the global wizard's **Language Defaults** round
uses for the same three keys.

### Git

One `AskUserQuestion` call, up to 2 questions, first option "keep (<effective value>, from
<global|default>)":

- **Branch per batch** (`branchPerBatch`) — on (`ifq` creates one branch per batch right after the
  go-ahead) / off (implementation happens on whatever branch is already checked out).
- **Git state policy** (`gitStatePolicy`) — `local` (cfq files stay out of git — a per-clone `git
  info/exclude` block) / `trackable` (cfq files can be committed — only cfq's own managed exclude
  block is removed, the rest follows normal repository Git policy).

### Maintenance

One `AskUserQuestion` call, one question, first option "keep (<effective value>, from
<global|default>)":

- **Maintenance every** (`maintenanceEvery`) — the effective value / another number via **Other** /
  off (`0`, disables maintenance entirely for this repo).

### Reports

One `AskUserQuestion` call, up to 2 questions, first option "keep (<effective value>, from
<global|default>)":

- **Report portal** (`htmlReport`) — on (the report portal stays synced automatically at every
  batch-affecting mutation) / off (synced only on `/rfq` request).
- **Report directory** (`reportDir`) — the effective value (or "unset" when empty), free text via
  **Other** (an additional copy of this repo's report portal, mirrored outside its own
  `.claude/cfq/`).

### Finish

Apply only the values the user actually changed, scoped to this repo — never global, this is the
repo wizard:

```bash
"<plugin-root>/bin/cfq" settings set --repo <repo-root> <key> <value>
```

Print one status line per change, same wording as `code-for-queue`'s **Step D**: `✅ Setting  <key>:
<old> → <new> (repo)`. Then print the `Config` status line, reused unchanged from what `pfq`'s start
block always printed for a new repo before this wizard existed: `⚠️ new repo · reviewed` (the user
kept every value, including the keep-all fast path) or `⚠️ new repo · adjusted <n>` (`<n>` = number
of keys actually written).
