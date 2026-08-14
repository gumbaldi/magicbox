# gumbaclaude

gumbaldi's Claude Code plugins.

## Installation

```
/plugin marketplace add gumbaldi/gumbaclaude
```

Then install individual plugins from the table below.

## Plugins

| Plugin | Directory | Purpose |
|---|---|---|
| `cfq` | [`plugins/cfq/`](plugins/cfq/README.md) | Plan expensive, implement cheap — phased plans in a repo-local queue |

## Structure

Each plugin lives in `plugins/<name>/` with its own `.claude-plugin/plugin.json`; the root only
holds `.claude-plugin/marketplace.json`.

MIT licensed.
