#!/usr/bin/env bash
# Self-test for scripts/cfq-scan.sh. No framework, no fixtures — just `bash tests/test-scan.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scan="$repo_root/scripts/cfq-scan.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# repo-a: one open batch, 2 open phases + 1 done phase, priority high
mkdir -p "$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/done"
echo high >"$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/.priority"
touch "$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/02-b.md" \
      "$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/done/00-x.md"

# repo-b: one batch fully moved to done/ (archived), no .priority
mkdir -p "$tmp/repo-b/.claude/code-for-queue/impl/done/2026-01-02-demo"
touch "$tmp/repo-b/.claude/code-for-queue/impl/done/2026-01-02-demo/01-a.md" \
      "$tmp/repo-b/.claude/code-for-queue/impl/done/2026-01-02-demo/02-b.md"

# repo-c: no .claude/code-for-queue/impl/ at all — must not show up
mkdir -p "$tmp/repo-c"

# repo-a has a report.json — must not affect phase counts, only the report flag
echo '{"repo":"x","batch":"2026-01-01-demo","started":"t","phases":[]}' \
  >"$tmp/repo-a/.claude/code-for-queue/impl/2026-01-01-demo/report.json"

# repo-e: dependsOn fixtures — target-open (still open) and target-done (archived) are the
# dependency targets; b-blocked/b-free/b-unknown are the batches exercising each outcome.
mkdir -p "$tmp/repo-e/.claude/code-for-queue/impl/target-open" \
         "$tmp/repo-e/.claude/code-for-queue/impl/done/target-done" \
         "$tmp/repo-e/.claude/code-for-queue/impl/b-blocked" \
         "$tmp/repo-e/.claude/code-for-queue/impl/b-free" \
         "$tmp/repo-e/.claude/code-for-queue/impl/b-unknown"
touch "$tmp/repo-e/.claude/code-for-queue/impl/target-open/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/impl/done/target-done/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/impl/b-blocked/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/impl/b-free/01-a.md" \
      "$tmp/repo-e/.claude/code-for-queue/impl/b-unknown/01-a.md"
echo target-open   >"$tmp/repo-e/.claude/code-for-queue/impl/b-blocked/.dependsOn"
echo target-done   >"$tmp/repo-e/.claude/code-for-queue/impl/b-free/.dependsOn"
echo gibtsnicht     >"$tmp/repo-e/.claude/code-for-queue/impl/b-unknown/.dependsOn"

# repo-f: no impl/ batches at all, only plan/ and todo/ orders — plan and todo must count only
# the open entries (2 and 1), never the ones already moved to their done/
mkdir -p "$tmp/repo-f/.claude/code-for-queue/plan/done" "$tmp/repo-f/.claude/code-for-queue/todo/done"
touch "$tmp/repo-f/.claude/code-for-queue/plan/2026-01-04-a.md" \
      "$tmp/repo-f/.claude/code-for-queue/plan/2026-01-05-b.md" \
      "$tmp/repo-f/.claude/code-for-queue/plan/done/2026-01-01-old.md" \
      "$tmp/repo-f/.claude/code-for-queue/todo/2026-01-06-c.md" \
      "$tmp/repo-f/.claude/code-for-queue/todo/done/2026-01-02-old.md"

# repo-g: .planning fixtures — b-fresh has a just-written marker (planning:true), b-stale has
# one backdated past the 30-minute staleness threshold (planning:false)
mkdir -p "$tmp/repo-g/.claude/code-for-queue/impl/b-fresh" \
         "$tmp/repo-g/.claude/code-for-queue/impl/b-stale"
touch "$tmp/repo-g/.claude/code-for-queue/impl/b-fresh/01-a.md" \
      "$tmp/repo-g/.claude/code-for-queue/impl/b-stale/01-a.md"
date -Iseconds >"$tmp/repo-g/.claude/code-for-queue/impl/b-fresh/.planning"
touch -d "@$(($(date +%s) - 3600))" "$tmp/repo-g/.claude/code-for-queue/impl/b-stale/.planning"

out=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan")

# Regression: batches without .dependsOn get [] / false / [], never null.
a=$(jq -c --arg p "$tmp/repo-a" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$a" = '[{"name":"2026-01-01-demo","priority":"high","open":2,"done":1,"archived":false,"report":true,"dependsOn":[],"blocked":false,"unknownDeps":[],"inProgress":true,"planning":false}]' ] \
  || { echo "FAIL: repo-a batches = $a"; exit 1; }

b=$(jq -c --arg p "$tmp/repo-b" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$b" = '[{"name":"2026-01-02-demo","priority":"","open":0,"done":2,"archived":true,"report":false,"dependsOn":[],"blocked":false,"unknownDeps":[],"inProgress":false,"planning":false}]' ] \
  || { echo "FAIL: repo-b batches (unflagged -> empty priority) = $b"; exit 1; }

c=$(jq -c --arg p "$tmp/repo-c" '[.repos[] | select(.path == $p)]' <<<"$out")
[ "$c" = "[]" ] || { echo "FAIL: repo-c should not appear, got $c"; exit 1; }

e_blocked=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-blocked") | {blocked, dependsOn}' <<<"$out")
[ "$e_blocked" = '{"blocked":true,"dependsOn":["target-open"]}' ] \
  || { echo "FAIL: b-blocked = $e_blocked"; exit 1; }

e_free=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-free") | {blocked, dependsOn}' <<<"$out")
[ "$e_free" = '{"blocked":false,"dependsOn":["target-done"]}' ] \
  || { echo "FAIL: b-free = $e_free"; exit 1; }

e_unknown=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-unknown") | {blocked, unknownDeps}' <<<"$out")
[ "$e_unknown" = '{"blocked":false,"unknownDeps":["gibtsnicht"]}' ] \
  || { echo "FAIL: b-unknown = $e_unknown"; exit 1; }

f=$(jq -c --arg p "$tmp/repo-f" '[.repos[] | select(.path == $p)][0] | {plan, todo, batches}' <<<"$out")
[ "$f" = '{"plan":2,"todo":1,"batches":[]}' ] \
  || { echo "FAIL: repo-f plan/todo counts = $f"; exit 1; }

g_fresh=$(jq -c --arg p "$tmp/repo-g" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-fresh") | .planning' <<<"$out")
[ "$g_fresh" = "true" ] || { echo "FAIL: b-fresh planning = $g_fresh"; exit 1; }

g_stale=$(jq -c --arg p "$tmp/repo-g" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "b-stale") | .planning' <<<"$out")
[ "$g_stale" = "false" ] || { echo "FAIL: b-stale planning = $g_stale"; exit 1; }

echo PASS
