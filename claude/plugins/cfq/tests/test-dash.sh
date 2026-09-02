#!/usr/bin/env bash
# Self-test for scripts/cfq-dash.sh. No framework, no fixtures beyond throwaway repos — just
# `bash tests/test-dash.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dash="$repo_root/scripts/cfq-dash.sh"
settings_sh="$repo_root/scripts/cfq-settings.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# repo-a: registered, one open batch (high priority, 1 open + 1 done phase). A real git repo so
# cfq-dash.sh's git rev-parse resolves it as "this repo" when cwd is inside it.
mkdir -p "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done"
git -C "$tmp/repo-a" init -q
touch "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done/00-x.md"
echo high >"$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/.priority"

# repo-b: registered, no batches at all — the rollup must read OK, never crash on empty batches.
mkdir -p "$tmp/repo-b/.claude/cfq"
git -C "$tmp/repo-b" init -q

# 1. Two registered repos, one with an open batch -> .repos has exactly two entries, each
# appearing once, counters matching what was created on disk.
out=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$dash")
[ "$(jq -r '.status' <<<"$out")" = "OK" ] || { echo "FAIL: status = $(jq -r '.status' <<<"$out")"; exit 1; }
[ "$(jq '.repos | length' <<<"$out")" = "2" ] || { echo "FAIL: repos length = $(jq '.repos|length' <<<"$out")"; exit 1; }
a=$(jq -c --arg p "$tmp/repo-a" '[.repos[] | select(.path == $p)]' <<<"$out")
[ "$(jq 'length' <<<"$a")" = "1" ] || { echo "FAIL: repo-a should appear exactly once, got $a"; exit 1; }
[ "$(jq -c '.[0] | {open, done, status}' <<<"$a")" = '{"open":1,"done":0,"status":"IN_PROGRESS"}' ] \
  || { echo "FAIL: repo-a rollup = $(jq -c '.[0]' <<<"$a")"; exit 1; }
b=$(jq -c --arg p "$tmp/repo-b" '.repos[] | select(.path == $p) | {open, done, status}' <<<"$out")
[ "$b" = '{"open":0,"done":0,"status":"OK"}' ] || { echo "FAIL: repo-b rollup = $b"; exit 1; }

# 1b. `render` is additive, not a substitute: same fixture, JSON default above is untouched, and
# the terminal render mentions both repos. Deep render coverage (tables, MULTIPLE_IN_PROGRESS,
# equivalence, no-HTML-entity) lives in tests/test-render.sh, not duplicated here.
rendered=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$dash" render "$tmp")
echo "$rendered" | grep -qF 'repo-a' || { echo "FAIL: render output missing repo-a"; exit 1; }
echo "$rendered" | grep -qF 'repo-b' || { echo "FAIL: render output missing repo-b"; exit 1; }

# 2. Run from inside a registered repo -> .thisRepo.batches lists that repo's batches only.
out_inside=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash -c "cd '$tmp/repo-a' && bash '$dash'")
this=$(jq -c '.thisRepo.batches | map(.name)' <<<"$out_inside")
[ "$this" = '["2026-01-01-demo"]' ] || { echo "FAIL: thisRepo.batches = $this"; exit 1; }

# 3. Run from a directory that is not a registered repo -> .thisRepo is null, .repos still
# populated, status still OK.
outside=$(mktemp -d)
git -C "$outside" init -q
out_outside=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash -c "cd '$outside' && bash '$dash'")
[ "$(jq '.thisRepo' <<<"$out_outside")" = "null" ] \
  || { echo "FAIL: thisRepo should be null outside a registered repo"; exit 1; }
[ "$(jq '.repos | length' <<<"$out_outside")" = "2" ] || { echo "FAIL: repos should stay populated"; exit 1; }
[ "$(jq -r '.status' <<<"$out_outside")" = "OK" ] \
  || { echo "FAIL: status should stay OK, got $(jq -r '.status' <<<"$out_outside")"; exit 1; }
rm -rf "$outside"

# 4. No repos at all -> status NO_REPO, empty .repos, no crash.
empty_home=$(mktemp -d)
empty_root=$(mktemp -d)
out_empty=$(HOME="$empty_home" CFQ_SCAN_ROOTS="$empty_root" bash "$dash")
[ "$(jq -r '.status' <<<"$out_empty")" = "NO_REPO" ] \
  || { echo "FAIL: empty status = $(jq -r '.status' <<<"$out_empty")"; exit 1; }
[ "$(jq '.repos' <<<"$out_empty")" = "[]" ] || { echo "FAIL: empty repos = $(jq '.repos' <<<"$out_empty")"; exit 1; }
rm -rf "$empty_home" "$empty_root"

# 5. Marker mapping, one case per --sources value (default/global/repo/env:process), plus the
# env:process must-fall-back to the masked file value (not just the env value), plus
# env:repo-legacy.
mroot=$(mktemp -d)
mhome=$(mktemp -d)
mfixture="$mroot/mfixture"
mkdir -p "$mfixture/.claude/cfq"
git -C "$mfixture" init -q
run_dash() { HOME="$mhome" CFQ_SCAN_ROOTS="$mroot" bash -c "cd '$mfixture' && bash '$dash'"; }
key_row() { jq -c --arg k "$1" '.settings[] | select(.key == $k)' <<<"$2"; }

d=$(key_row maintenanceEvery "$(run_dash)")
[ "$(jq -r '.marker' <<<"$d")" = "D" ] || { echo "FAIL: default marker = $d"; exit 1; }

HOME="$mhome" bash "$settings_sh" set maintenanceEvery 20 >/dev/null
g=$(key_row maintenanceEvery "$(run_dash)")
[ "$(jq -r '.marker' <<<"$g")" = "G" ] || { echo "FAIL: global marker = $g"; exit 1; }

HOME="$mhome" bash "$settings_sh" set --repo "$mfixture" maintenanceEvery 5 >/dev/null
r=$(key_row maintenanceEvery "$(run_dash)")
[ "$(jq -r '.marker' <<<"$r")" = "R" ] || { echo "FAIL: repo marker = $r"; exit 1; }

envp=$(key_row maintenanceEvery "$(HOME="$mhome" CFQ_SCAN_ROOTS="$mroot" CFQ_MAINTENANCE_EVERY=99 \
  bash -c "cd '$mfixture' && bash '$dash'")")
[ "$(jq -r '.marker' <<<"$envp")" = "E" ] || { echo "FAIL: env:process marker = $envp"; exit 1; }

HOME="$mhome" bash "$settings_sh" set --repo "$mfixture" docLevel full >/dev/null
envd=$(key_row docLevel "$(HOME="$mhome" CFQ_SCAN_ROOTS="$mroot" CFQ_DOC_LEVEL=minimal \
  bash -c "cd '$mfixture' && bash '$dash'")")
[ "$(jq -r '.value' <<<"$envd")" = "minimal" ] || { echo "FAIL: docLevel effective value = $envd"; exit 1; }
[ "$(jq -r '.maskedValue' <<<"$envd")" = "full" ] \
  || { echo "FAIL: docLevel maskedValue must be the repo file value, not just the env value, got $envd"; exit 1; }
[ "$(jq -r '.maskedSource' <<<"$envd")" = "repo" ] || { echo "FAIL: docLevel maskedSource = $envd"; exit 1; }

echo '{"env":{"CFQ_DOC_LEVEL":"standard"}}' >"$mfixture/.claude/settings.json"
envl=$(key_row docLevel "$(HOME="$mhome" CFQ_SCAN_ROOTS="$mroot" CFQ_DOC_LEVEL=standard \
  bash -c "cd '$mfixture' && bash '$dash'")")
[ "$(jq -r '.marker' <<<"$envl")" = "E" ] || { echo "FAIL: env:repo-legacy marker = $envl"; exit 1; }
[ "$(jq -r '.source' <<<"$envl")" = "env:repo-legacy" ] \
  || { echo "FAIL: env:repo-legacy source = $envl"; exit 1; }
rm -rf "$mroot" "$mhome"

echo PASS
