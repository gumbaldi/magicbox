#!/usr/bin/env bash
# Self-test for scripts/cfq-scan.sh. No framework, no fixtures — just `bash tests/test-scan.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scan="$repo_root/scripts/cfq-scan.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# repo-a: one open batch, 2 open phases + 1 done phase, priority high
mkdir -p "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/done"
echo high >"$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/.priority"
touch "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/02-b.md" \
      "$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/done/00-x.md"

# repo-b: one batch fully moved to done/ (archived), no .priority
mkdir -p "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo"
touch "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo/01-a.md" \
      "$tmp/repo-b/.claude/code-for-queue/done/2026-01-02-demo/02-b.md"

# repo-c: no .claude/code-for-queue/ at all — must not show up
mkdir -p "$tmp/repo-c"

# repo-d: legacy German priority — must be mapped to the English value
mkdir -p "$tmp/repo-d/.claude/code-for-queue/2026-01-03-legacy"
echo hoch >"$tmp/repo-d/.claude/code-for-queue/2026-01-03-legacy/.priority"
touch "$tmp/repo-d/.claude/code-for-queue/2026-01-03-legacy/01-a.md"

# repo-a has a report.json — must not affect phase counts, only the report flag
echo '{"repo":"x","batch":"2026-01-01-demo","started":"t","phases":[]}' \
  >"$tmp/repo-a/.claude/code-for-queue/2026-01-01-demo/report.json"

# repo-e: dependsOn fixtures — target-open (still open) and target-done (archived) are the
# dependency targets; b-blocked/b-free/b-unknown are the batches exercising each outcome.
mkdir -p "$tmp/repo-e/.claude/code-for-queue/target-open" \
         "$tmp/repo-e/.claude/code-for-queue/done/target-done" \
         "$tmp/repo-e/.claude/code-for-queue/b-blocked" \
         "$tmp/repo-e/.claude/code-for-queue/b-free" \
         "$tmp/repo-e/.claude/code-for-queue/b-unknown"
touch "$tmp/repo-e/.claude/code-for-queue/target-open/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/done/target-done/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/b-blocked/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/b-free/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/b-unknown/01-a.md"
echo target-open   >"$tmp/repo-e/.claude/code-for-queue/b-blocked/.dependsOn"
echo target-done   >"$tmp/repo-e/.claude/code-for-queue/b-free/.dependsOn"
echo gibtsnicht     >"$tmp/repo-e/.claude/code-for-queue/b-unknown/.dependsOn"

out=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan")

# Regression: batches without .dependsOn get [] / false / [], never null.
a=$(jq -c --arg p "$tmp/repo-a" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$a" = '[{"name":"2026-01-01-demo","priority":"high","open":2,"done":1,"archived":false,"report":true,"dependsOn":[],"blocked":false,"unknownDeps":[]}]' ] \
  || { echo "FAIL: repo-a batches = $a"; exit 1; }

b=$(jq -c --arg p "$tmp/repo-b" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$b" = '[{"name":"2026-01-02-demo","priority":"medium","open":0,"done":2,"archived":true,"report":false,"dependsOn":[],"blocked":false,"unknownDeps":[]}]' ] \
  || { echo "FAIL: repo-b batches = $b"; exit 1; }

c=$(jq -c --arg p "$tmp/repo-c" '[.repos[] | select(.path == $p)]' <<<"$out")
[ "$c" = "[]" ] || { echo "FAIL: repo-c should not appear, got $c"; exit 1; }

d=$(jq -c --arg p "$tmp/repo-d" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$d" = '[{"name":"2026-01-03-legacy","priority":"high","open":1,"done":0,"archived":false,"report":false,"dependsOn":[],"blocked":false,"unknownDeps":[]}]' ] \
  || { echo "FAIL: repo-d legacy priority mapping = $d"; exit 1; }

e_blocked=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-blocked") | {blocked, dependsOn}' <<<"$out")
[ "$e_blocked" = '{"blocked":true,"dependsOn":["target-open"]}' ] \
  || { echo "FAIL: b-blocked = $e_blocked"; exit 1; }

e_free=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-free") | {blocked, dependsOn}' <<<"$out")
[ "$e_free" = '{"blocked":false,"dependsOn":["target-done"]}' ] \
  || { echo "FAIL: b-free = $e_free"; exit 1; }

e_unknown=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-unknown") | {blocked, unknownDeps}' <<<"$out")
[ "$e_unknown" = '{"blocked":false,"unknownDeps":["gibtsnicht"]}' ] \
  || { echo "FAIL: b-unknown = $e_unknown"; exit 1; }

echo PASS
