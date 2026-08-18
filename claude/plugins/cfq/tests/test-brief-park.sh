#!/usr/bin/env bash
# Self-test for scripts/cfq-brief.sh and scripts/cfq-park.sh. No framework, no fixtures beyond
# what's built here — just `bash tests/test-brief-park.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
brief_sh="$repo_root/scripts/cfq-brief.sh"
park_sh="$repo_root/scripts/cfq-park.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# ============================================================ cfq-brief.sh ===========

batch="$tmp/2026-01-01-briefme"
mkdir -p "$batch"
echo high > "$batch/.priority"
echo 2026-01-02-otherbatch > "$batch/.dependsOn"

cat > "$batch/01-complete.md" <<'EOF'
# Complete phase

## Size

S

## Context

First context line.
Second context line.

## Affected Files
EOF

cat > "$batch/02-incomplete.md" <<'EOF'
# Incomplete phase

## Affected Files
EOF

out=$(bash "$brief_sh" "$batch")
printf '%s\n' "$out" | grep -qx '2026-01-01-briefme  priority=high  phases=2' \
  || { echo "FAIL: header line wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -qx 'dependsOn: 2026-01-02-otherbatch' \
  || { echo "FAIL: dependsOn line missing: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^01  Complete phase  \[S\]  First context line. Second context line. $' \
  || { echo "FAIL: complete phase line wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^02  Incomplete phase  \[M\]' \
  || { echo "FAIL: incomplete phase should default to [M]: $out"; exit 1; }

# unflagged batch (no .priority file): header line omits the priority clause entirely
unflagged="$tmp/2026-01-03-unflagged"
mkdir -p "$unflagged"
cat > "$unflagged/01-a.md" <<'EOF'
# A phase

## Affected Files
EOF
out=$(bash "$brief_sh" "$unflagged")
printf '%s\n' "$out" | grep -qx '2026-01-03-unflagged  phases=1' \
  || { echo "FAIL: unflagged header line wrong: $out"; exit 1; }

# ============================================================ cfq-park.sh ============

parkhome=$(mktemp -d)
parkrepo="$tmp/parkrepo"
mkdir -p "$parkrepo"
git init -q "$parkrepo"

d1=$(HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-01-test" high "2026-01-01-dep-a" "2026-01-01-dep-b")
batchdir="$parkrepo/.claude/code-for-queue/impl/2026-01-01-test"
[ "$d1" = "$batchdir" ] || { echo "FAIL: printed dir wrong: $d1"; exit 1; }
[ "$(cat "$batchdir/.priority")" = "high" ] || { echo "FAIL: .priority wrong"; exit 1; }
[ "$(cat "$batchdir/.dependsOn")" = "$(printf '2026-01-01-dep-a\n2026-01-01-dep-b')" ] \
  || { echo "FAIL: .dependsOn wrong: $(cat "$batchdir/.dependsOn")"; exit 1; }
grep -qxF '**/.claude/code-for-queue/' "$parkrepo/.git/info/exclude" \
  || { echo "FAIL: git exclude entry missing"; exit 1; }
grep -q "$parkrepo" "$parkhome/.claude/code-for-queue/repos.json" \
  || { echo "FAIL: repo not registered"; exit 1; }

# no dependsOn entries -> no file; normal priority -> no .priority file either
d2=$(HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-02-nodeps" normal)
[ ! -e "$parkrepo/.claude/code-for-queue/impl/2026-01-02-nodeps/.dependsOn" ] \
  || { echo "FAIL: .dependsOn should not exist when no entries were passed"; exit 1; }
[ ! -e "$parkrepo/.claude/code-for-queue/impl/2026-01-02-nodeps/.priority" ] \
  || { echo "FAIL: .priority should not exist for normal priority"; exit 1; }

# re-park an existing high batch as normal: .priority must be removed, not left stale
d1normal=$(HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-01-test" normal)
[ "$d1" = "$d1normal" ] || { echo "FAIL: re-park printed a different dir"; exit 1; }
[ ! -e "$batchdir/.priority" ] || { echo "FAIL: re-park to normal should remove .priority"; exit 1; }

# re-run with the same arguments: idempotent, no duplicate exclude line
before=$(cat "$parkrepo/.git/info/exclude")
d1again=$(HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-01-test" high "2026-01-01-dep-a" "2026-01-01-dep-b")
after=$(cat "$parkrepo/.git/info/exclude")
[ "$d1" = "$d1again" ] || { echo "FAIL: second run printed a different dir"; exit 1; }
[ "$before" = "$after" ] || { echo "FAIL: second run duplicated the exclude entry"; exit 1; }
[ "$(grep -c '^\*\*/\.claude/code-for-queue/$' "$parkrepo/.git/info/exclude")" = "1" ] \
  || { echo "FAIL: exclude entry not exactly once"; exit 1; }

# invalid priority -> exit != 0
if HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-03-bad" nope 2>/dev/null; then
  echo "FAIL: invalid priority should exit non-zero"; exit 1
fi

rm -rf "$parkhome"

echo PASS
