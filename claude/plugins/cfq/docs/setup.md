# Setup

Install the `cfq` plugin marketplace and run first-time setup once per machine.

## Prerequisites

`bash`, `git` and `jq` on PATH — required, installing the plugin does not install them. Optional:
`gh` (GitHub) or `tea` (Gitea/Forgejo) for the security check, logged in to the forge cfq should
query; `npm` for `npm audit` on repos with a `package.json`.

Run `"${CLAUDE_PLUGIN_ROOT}/bin/cfq" doctor check` any time to see what's missing and how to
install it. The bundled `SessionStart` hook runs the same check automatically and stays silent on a
healthy host — it only speaks up when a required command is absent, and never installs anything
itself.

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
