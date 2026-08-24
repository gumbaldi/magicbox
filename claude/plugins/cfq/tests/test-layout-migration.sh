#!/usr/bin/env bash
# Self-test for scripts/migrations/cfq-layout-v1.sh. No framework, no fixtures.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mig_sh="$repo_root/scripts/migrations/cfq-layout-v1.sh"
registry_sh="$repo_root/scripts/cfq-registry.sh"
settings_sh="$repo_root/scripts/cfq-settings.sh"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

new_home() { mktemp -d -p "$work"; }
new_repo() { local d; d=$(mktemp -d -p "$work"); (cd "$d" && git init -q); printf '%s' "$d"; }

# 1. Old-root-only fixture migrates without data loss, old root removed
repo=$(new_repo); home=$(new_home)
mkdir -p "$repo/.claude/code-for-queue/impl/2026-01-01-a/done" "$repo/.claude/code-for-queue/plan" "$repo/.claude/code-for-queue/todo"
echo "phase-content" >"$repo/.claude/code-for-queue/impl/2026-01-01-a/01-x.md"
echo '{"a":1}' >"$repo/.claude/code-for-queue/telemetry.jsonl"
touch "$repo/.claude/code-for-queue/.maintenance"

out=$(HOME="$home" bash "$mig_sh" apply --all-known "$repo")
[ "$(jq -r '.repos[0].result' <<<"$out")" = "migrated" ] || { echo "FAIL: old-root-only result: $out"; exit 1; }
[ "$(cat "$repo/.claude/cfq/impl/2026-01-01-a/01-x.md")" = "phase-content" ] || { echo "FAIL: phase file bytes lost"; exit 1; }
[ -d "$repo/.claude/cfq/impl/2026-01-01-a/done" ] || { echo "FAIL: done/ subdir lost"; exit 1; }
[ -f "$repo/.claude/cfq/telemetry.jsonl" ] || { echo "FAIL: telemetry.jsonl not moved"; exit 1; }
[ -f "$repo/.claude/cfq/.maintenance" ] || { echo "FAIL: .maintenance not moved"; exit 1; }
[ -d "$repo/.claude/code-for-queue" ] && { echo "FAIL: old root not removed"; exit 1; }

# 2. Repeated migration is a no-op
out=$(HOME="$home" bash "$mig_sh" apply --all-known "$repo")
[ "$(jq -r '.repos[0].result' <<<"$out")" = "already-canonical" ] || { echo "FAIL: repeat migration not a no-op: $out"; exit 1; }

# 3. Both roots, non-conflicting entries merge deterministically
repo=$(new_repo); home=$(new_home)
mkdir -p "$repo/.claude/code-for-queue/impl/2026-01-01-a" "$repo/.claude/cfq/impl/2026-01-02-b" "$repo/.claude/cfq/impl/done"
echo old >"$repo/.claude/code-for-queue/impl/2026-01-01-a/01.md"
echo new >"$repo/.claude/cfq/impl/2026-01-02-b/01.md"
out=$(HOME="$home" bash "$mig_sh" apply --all-known "$repo")
[ "$(jq -r '.repos[0].result' <<<"$out")" = "migrated" ] || { echo "FAIL: merge result: $out"; exit 1; }
[ "$(cat "$repo/.claude/cfq/impl/2026-01-01-a/01.md")" = "old" ] || { echo "FAIL: merged old entry missing"; exit 1; }
[ "$(cat "$repo/.claude/cfq/impl/2026-01-02-b/01.md")" = "new" ] || { echo "FAIL: existing new entry disturbed"; exit 1; }
[ -d "$repo/.claude/code-for-queue" ] && { echo "FAIL: old root not removed after merge"; exit 1; }

# 4. Conflicting same-name content is reported, never overwritten
repo=$(new_repo); home=$(new_home)
mkdir -p "$repo/.claude/code-for-queue/impl/2026-01-01-a" "$repo/.claude/cfq/impl/2026-01-01-a"
echo old-version >"$repo/.claude/code-for-queue/impl/2026-01-01-a/01.md"
echo new-version >"$repo/.claude/cfq/impl/2026-01-01-a/01.md"

plan_out=$(HOME="$home" bash "$mig_sh" plan --all-known "$repo")
[ "$(jq -r '.repos[0].result' <<<"$plan_out")" = "conflict" ] || { echo "FAIL: plan should report conflict: $plan_out"; exit 1; }
[ "$(jq -r '.repos[0].code' <<<"$plan_out")" = "CFQ_LAYOUT_MIGRATION_CONFLICT" ] || { echo "FAIL: missing conflict code: $plan_out"; exit 1; }

apply_out=$(HOME="$home" bash "$mig_sh" apply --all-known "$repo")
[ "$(jq -r '.repos[0].result' <<<"$apply_out")" = "conflict" ] || { echo "FAIL: apply should report conflict: $apply_out"; exit 1; }
[ "$(cat "$repo/.claude/code-for-queue/impl/2026-01-01-a/01.md")" = "old-version" ] || { echo "FAIL: old content overwritten"; exit 1; }
[ "$(cat "$repo/.claude/cfq/impl/2026-01-01-a/01.md")" = "new-version" ] || { echo "FAIL: new content overwritten"; exit 1; }

# 5. Discovery: registry repos, current repo, and old-root repos beneath scanRoots
scanhome=$(new_home)
scanroot=$(mktemp -d -p "$work")
found=$(mktemp -d -p "$scanroot")
mkdir -p "$found/.claude/code-for-queue/plan"
HOME="$scanhome" bash "$settings_sh" set scanRoots "$scanroot" >/dev/null
reg_repo=$(new_repo)
HOME="$scanhome" bash "$registry_sh" add "$reg_repo" >/dev/null
current=$(new_repo)

disc=$(HOME="$scanhome" bash "$mig_sh" discover "$current")
grep -qxF "$found" <<<"$disc" || { echo "FAIL: scanRoots repo not discovered"; exit 1; }
grep -qxF "$reg_repo" <<<"$disc" || { echo "FAIL: registry repo not discovered"; exit 1; }
grep -qxF "$current" <<<"$disc" || { echo "FAIL: current repo not discovered"; exit 1; }

# 6. Stale registry entries are reported (and pruned) rather than retained as phantom repos
stalehome=$(new_home)
gone="$work/does-not-exist-$$"
HOME="$stalehome" bash "$registry_sh" add "$gone" >/dev/null
out=$(HOME="$stalehome" bash "$mig_sh" apply --all-known)
[ "$(jq -r '.repos[0].result' <<<"$out")" = "stale" ] || { echo "FAIL: stale registry entry not reported: $out"; exit 1; }
remaining=$(HOME="$stalehome" bash "$registry_sh" list)
[ -z "$remaining" ] || { echo "FAIL: stale entry not pruned from registry: $remaining"; exit 1; }

echo PASS
