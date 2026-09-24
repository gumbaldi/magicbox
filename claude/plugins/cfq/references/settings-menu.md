# Settings Menu: `/cfq settings`

Guided navigation over the same settings schema `code-for-queue`'s Step D already changes via free
text — this is the picker version, entered when the skill's argument is `settings`. A free-text
change request ("set stopUsed to 100000") keeps going straight to Step D, unchanged; nothing below
replaces it.

## Data

One call, read once per scope choice, never re-run per navigation step:

```bash
"<plugin-root>/bin/cfq" settings menu [--repo <repo-root>] --format json
```

Returns `{groups:[{id,title,keys:[{key,value,source,marker,type,values,min,scopes,default,description}]}]}`
— the eight fixed groups (`models`, `planning`, `implementation`, `limits`, `language`,
`maintenance`, `reports`, `repo`), each already carrying every key's current value, source and
marker. **Group**, **Setting** and **Value** below all read from this one payload. Applying a
change (**Apply**) makes that one key's entry in the payload stale — re-fetch before offering the
same key again on a second pass through **Loop**, not before every unrelated navigation step.

Also print the text overview once, verbatim, as the flow's opening block, before the first
question:

```bash
"<plugin-root>/bin/cfq" settings menu [--repo <repo-root>]
```

This is the `SETTINGS · <repo-or-"global">` block with the four-letter legend and the eight group
previews — print it exactly as returned, no reformatting.

## Scope

Outside a repo (no repo root resolves), skip this question — everything is global, same as Step D.
Inside a repo, ask first, one `AskUserQuestion`, framed per
`<plugin-root>/references/interaction-policy.md`'s **Decision Question Context**:

- **global** — applies everywhere every repo reads cfq settings from.
- **this repo** — a repo-scoped override, applies only here.

A key whose `scopes` excludes `repo` can only ever be global (`<plugin-root>/references/dashboard.md`'s
**Step D — Settings, Full Detail** names the three: `scanRoots`, `securityTimeoutSeconds`,
`securityFindingsCap`). When scope is "this repo" and the key picked at **Setting** turns out to be
one of those, explain plainly at **Value** — the change applies everywhere, not just this repo —
and fall back to a global `set` rather than erroring the way a raw `settings set --repo` call does;
the menu already knows the key before it writes anything, so it can explain instead of reject.

## Group

One `AskUserQuestion`, at most 4 options, built from the `groups` list already in hand. Eight
groups always need paging: page 1 offers the first 3 groups plus a fourth **more…** option; page 2
(reached only via **more…**) offers the remaining 5, again capped at 4 — the first 3 plus
**more…**, then the last 2 directly on a third page. Each option's description previews that
group's 1-2 non-default keys (`[<marker>] <key> <value>`, the same preview the printed overview
block already showed); a group with nothing overridden says so plainly instead of an empty
description.

## Setting

One `AskUserQuestion` over the chosen group's `keys` list, same 4-option-plus-**more…** paging.
Each option names the key; its description carries the current value and source (`= 125000
(repo)`, `= 70 (default)`) plus, when scope is "this repo" and the key is global-only, a short note
that it applies everywhere regardless.

## Value

One `AskUserQuestion`:

- **bool** / **enum** — the type's own values as options (bool: `true`/`false`), the current one
  marked, plus **reset to default** always appended as a further option (→ `settings unset`).
  Paginate the same 3-plus-**more…** way if bool/enum values plus "reset to default" would ever
  exceed 4 options — nothing in the schema today needs a second page here (`docLevel`'s two values
  plus reset is 3), but a future enum that grows past it still pages the same way.
- **int** / **string** / **array** / **object** — no value options to enumerate. The question's own
  text carries the schema's `min`/`pattern` (from `describe`, the same source Step D already reads)
  and the current value; the answer comes back through the option list's own free-text **Other**
  rather than a value each. **reset to default** is still offered as an explicit option alongside
  **Other**.

Frame this question, like the two before it, per **Decision Question Context**: what the key does
today (its description), why a change might be wanted, and each offered value's concrete effect —
before asking.

## Apply

```bash
"<plugin-root>/bin/cfq" settings set [--repo <repo-root>] <key> <value>
"<plugin-root>/bin/cfq" settings unset [--repo <repo-root>] <key>          # reset to default
```

Print one status line, exactly Step D's own wording: `✅ Setting  <key>: <old> → <new>
(<scope>)`, or `⚠️ Setting  <key> set, but <ENV_VAR> overrides` when the key's `source` in the menu
JSON already started with `env` before this write — the write still happens, the note only warns
it stays invisible until the variable is gone.

## Loop

After the status line, one more `AskUserQuestion`: **change another setting** (back to **Group**,
same scope, data re-fetched) or **done** (return to the dashboard). Never re-ask **Scope** on a
repeat pass through the same flow — it was already answered.
