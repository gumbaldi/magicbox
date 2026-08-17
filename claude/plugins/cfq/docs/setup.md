# Setup

Install the `cfq` plugin marketplace and run first-time setup once per machine.

## Prerequisites

`bash` and `jq` on PATH. Optional: `gh` (GitHub) or `tea` (Gitea/Forgejo) for the security check,
logged in to the forge cfq should query.

## Install

```
/plugin marketplace add gumbaldi/magicbox
/plugin install cfq@magicbox
```

## First-time setup

Run `/cfq` once. It creates `~/.claude/code-for-queue/settings.json` with defaults and
`repos.json` (the cross-repo registry), and marks `setupDone` so this step only runs once.

## Upgrading

- From the `gumbaclaude` marketplace: it was renamed to `magicbox`. Remove the old entry
  (`/plugin marketplace remove gumbaclaude`) and reinstall as above — settings and the registry
  are kept.
- From `code-for-queue` 0.1.x: the plugin itself was renamed to `cfq`. Remove the old one
  (`/plugin uninstall code-for-queue`) and reinstall.

## See also

- [usage.md](usage.md) — what each skill does and how to run it
- [configuration.md](configuration.md) — every setting, global and per repo
