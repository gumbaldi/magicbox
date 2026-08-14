# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin **marketplace**, `gumbaclaude` — not application code, not a single plugin. The
root holds only `.claude-plugin/marketplace.json` and monorepo-wide docs; every plugin lives fully
self-contained under `plugins/<name>/`.

## Layout rule

One plugin = one directory `plugins/<name>/`, with its own `.claude-plugin/plugin.json`, its own
`README.md`, and its own `CLAUDE.md`. The root `marketplace.json` lists each of them with
`"source": "./plugins/<name>"`. Adding a new plugin: create the directory, add the marketplace entry —
nothing else changes at the root.

Plugin-specific conventions, commands, and architecture notes live in `plugins/<name>/CLAUDE.md`, not
here.

## Self-hosting queue

`.claude/code-for-queue/` at the repo root is this repo's own planning queue (used to drive development
of the `cfq` plugin itself via `/pfq` / `/ifq`) and is ignored via the versioned `.gitignore`. It is not
part of any plugin.
