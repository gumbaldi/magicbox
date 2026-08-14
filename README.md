# gumbaclaude

gumbaldi's Claude Code plugins.

## Installation

```
/plugin marketplace add gumbaldi/gumbaclaude
```

Then install individual plugins from the table below.

## Plugins

| Plugin | Verzeichnis | Zweck |
|---|---|---|
| `cfq` | [`plugins/cfq/`](plugins/cfq/README.md) | Plan teuer, implementier billig — phasierte Pläne in einer repo-lokalen Queue |

## Struktur

Jedes Plugin liegt in `plugins/<name>/` mit eigener `.claude-plugin/plugin.json`; im Root steht nur
`.claude-plugin/marketplace.json`.

MIT licensed.
