#!/usr/bin/env bash
# Self-test for scripts/cfq-scan.sh. No framework, no fixtures — just `bash tests/test-scan.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scan="$repo_root/scripts/cfq-scan.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# repo-a: one open batch, 2 open phases + 1 done phase, priority hoch
mkdir -p "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/done"
echo hoch >"$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/.priority"
touch "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/02-b.md" \
      "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/done/00-x.md"

# repo-b: one batch fully moved to done/ (archived), no .priority
mkdir -p "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo"
touch "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo/01-a.md" \
      "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo/02-b.md"

# repo-c: no .claude/code-for-queue/ at all — must not show up
mkdir -p "$tmp/repo-c"

out=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan")

a=$(jq -c --arg p "$tmp/repo-a" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$a" = '[{"name":"2026-01-01-demo","priority":"hoch","open":2,"done":1,"archived":false}]' ] \
  || { echo "FAIL: repo-a batches = $a"; exit 1; }

b=$(jq -c --arg p "$tmp/repo-b" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$b" = '[{"name":"2026-01-02-demo","priority":"mittel","open":0,"done":2,"archived":true}]' ] \
  || { echo "FAIL: repo-b batches = $b"; exit 1; }

c=$(jq -c --arg p "$tmp/repo-c" '[.repos[] | select(.path == $p)]' <<<"$out")
[ "$c" = "[]" ] || { echo "FAIL: repo-c should not appear, got $c"; exit 1; }

echo PASS
