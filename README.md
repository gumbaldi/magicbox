# magicbox

gumbaldi's plugins for Claude Code and Codex.

## Installation

Claude Code: `/plugin marketplace add gumbaldi/magicbox`, then install `cfq@magicbox`.

Codex: `codex plugin marketplace add ./` and `codex plugin add cfq@magicbox` from this checkout,
or install `cfq` from the Magicbox marketplace in the desktop plugin directory. The repo marketplace is
`.agents/plugins/marketplace.json`; the Codex skill and hook instructions are separate from the
Claude Code instructions.

## Plugins

| Plugin | Directory | Purpose |
|---|---|---|
| `cfq` | [`claude/plugins/cfq/`](claude/plugins/cfq/README.md) | Plan expensive, implement cheap — phased plans in a repo-local queue |

## Structure

The root holds both `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`.
CFQ lives once at `claude/plugins/cfq/`: the shared CLI and queue format stay there, while
`skills/` and `hooks/` serve Claude Code and `codex/skills/` and `codex/hooks/` serve Codex.
Each host loads only its own skill and hook paths.

MIT licensed.
