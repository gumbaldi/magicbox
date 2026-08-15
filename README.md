# magicbox

gumbaldi's Claude Code plugins, plus, later, skills for other AI providers.

## Installation

```
/plugin marketplace add gumbaldi/magicbox
```

Then install individual plugins from the table below.

## Plugins

| Plugin | Directory | Purpose |
|---|---|---|
| `cfq` | [`claude/plugins/cfq/`](claude/plugins/cfq/README.md) | Plan expensive, implement cheap — phased plans in a repo-local queue |

## Structure

The root holds `.claude-plugin/marketplace.json` and monorepo-wide docs; below it, one directory per
AI provider — `claude/` for Claude Code, `codex/` for Codex/GPT, `generic/` for provider-neutral
skill sources adapted by hand when adopted for a provider. Only directories with content exist.
Claude Code plugins live at `claude/plugins/<name>/`, each with its own `.claude-plugin/plugin.json`.

MIT licensed.
