#!/usr/bin/env bash
# Self-test for scripts/cfq-branch.sh. No framework, no fixtures beyond what's built here — just
# `bash tests/test-branch.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
branch_sh="$repo_root/scripts/cfq-branch.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

repo="$tmp/repo"
mkdir -p "$repo"
git init -q -b main "$repo"
git -C "$repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init

run() { HOME="$home" bash "$branch_sh" plan "$repo" "$1"; }

# --- no branches beyond main -> new, v0.1, base main, no candidates ---
out=$(run "2026-01-01-mytopic")
printf '%s' "$out" | jq -e . >/dev/null || { echo "FAIL: not valid JSON: $out"; exit 1; }
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: mode -> $out"; exit 1; }
[ "$(jq -r '.version' <<<"$out")" = "v0.1" ] || { echo "FAIL: version -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "main" ] || { echo "FAIL: base -> $out"; exit 1; }
[ "$(jq -c '.candidates' <<<"$out")" = "[]" ] || { echo "FAIL: candidates -> $out"; exit 1; }

# --- lexical-sort trap: v0.9 and v0.10 present -> next is v0.11, not v0.10 ---
git -C "$repo" branch v0.9-a
git -C "$repo" branch v0.10-b
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.version' <<<"$out")" = "v0.11" ] || { echo "FAIL: lexical-sort trap: version -> $out"; exit 1; }

# --- v0.48 present -> v0.49 ---
git -C "$repo" branch v0.48-x
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.version' <<<"$out")" = "v0.49" ] || { echo "FAIL: version after v0.48 -> $out"; exit 1; }

# --- existing local branch for this slug -> continue, no version bump ---
git -C "$repo" branch v0.3-mytopic
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: continue mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "v0.3-mytopic" ] || { echo "FAIL: continue branch -> $out"; exit 1; }
[ "$(jq -r '.version' <<<"$out")" = "null" ] || { echo "FAIL: continue version should be null -> $out"; exit 1; }
git -C "$repo" branch -q -D v0.3-mytopic

# --- remote-only branch for the slug -> same continue result ---
remote="$tmp/remote.git"
git init -q --bare "$remote"
git -C "$repo" remote add origin "$remote"
git -C "$repo" push -q origin v0.48-x:v0.3-mytopic
git -C "$repo" fetch -q origin
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: remote continue mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "v0.3-mytopic" ] || { echo "FAIL: remote continue branch -> $out"; exit 1; }

# --- branchPerBatch=false -> off (no env var for this key, set it via settings.json) ---
mkdir -p "$home/.claude/code-for-queue"
echo '{"branchPerBatch": false}' > "$home/.claude/code-for-queue/settings.json"
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "off" ] || { echo "FAIL: off mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "null" ] || { echo "FAIL: off branch should be null -> $out"; exit 1; }
rm "$home/.claude/code-for-queue/settings.json"

# --- a branch ahead of main appears in candidates, base is null ---
git -C "$repo" checkout -q -b v0.50-ahead
git -C "$repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m ahead
git -C "$repo" checkout -q main
out=$(run "2026-01-02-newtopic")
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: candidates-case mode -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "null" ] || { echo "FAIL: base should be null with candidates -> $out"; exit 1; }
jq -e '.candidates | index("v0.50-ahead") != null' <<<"$out" >/dev/null \
  || { echo "FAIL: v0.50-ahead should be in candidates -> $out"; exit 1; }

echo PASS
