# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin **marketplace**, `magicbox` — not application code, not a single plugin. The
root holds both marketplace manifests and monorepo-wide docs; below it, the CFQ package keeps
separate host instructions around one shared CLI.

## Layout rule

CFQ remains one physical package under `claude/plugins/cfq/` because both hosts run its shared
scripts against the same queue. Claude instructions live in `skills/`, `references/`, `commands/`
and `hooks/`; Codex instructions live in `codex/`. The separate plugin manifests select those
paths. Other provider-specific packages can use their own directory.

`.github/workflows/` at the repo root holds per-plugin CI, path-filtered so each plugin's workflow
only runs when that plugin's own files change.

Claude Code plugins live at `claude/plugins/<name>/`, one directory per plugin, each fully
self-contained with its own `.claude-plugin/plugin.json`, its own `README.md`, and its own
`CLAUDE.md`. The root `marketplace.json` lists each of them with
`"source": "./claude/plugins/<name>"`. Adding a new plugin: create the directory, add the
marketplace entry — nothing else changes at the root. Loose skills for other providers would live at
`<provider>/skills/`.

Plugin-specific conventions, commands, and architecture notes live in `claude/plugins/<name>/CLAUDE.md`,
not here.

## Self-hosting queue

`.claude/cfq/` at the repo root is this repo's own planning queue (used to drive development
of the `cfq` plugin itself via `/pfq` / `/ifq`) and is ignored via the versioned `.gitignore`. It is not
part of any plugin. Batches park under `.claude/cfq/impl/`, alongside the sibling `plan/`
and `todo/` queues — see "The queue is the filesystem" in `claude/plugins/cfq/CLAUDE.md` for what each
holds.
