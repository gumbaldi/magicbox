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

- `/tmp/example/foo.sh`
- `/tmp/example/bar.sh`

## Verification

```bash
bash tests/test-foo.sh
echo done
```
EOF

cat > "$batch/02-incomplete.md" <<'EOF'
# Incomplete phase

## Affected Files

- `/tmp/example/only.sh`
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

# regression guard: the two no-flag assertions above stay byte-identical to today's output;
# --phase is additive, tested separately below.

# ---- --phase <NN> announcement mode -------------------------------------------------

out=$(bash "$brief_sh" "$batch" --phase 01)
expected="PHASE 01 · Complete phase · Size S
  Goal     First context line. Second context line.
  Files    foo.sh, bar.sh
  Check    bash tests/test-foo.sh"
[ "$out" = "$expected" ] || { echo "FAIL: --phase 01 block wrong: $out"; exit 1; }

# edge: no ## Size -> falls back to M; no ## Verification -> Check line omitted entirely
out=$(bash "$brief_sh" "$batch" --phase 02)
printf '%s\n' "$out" | grep -qx 'PHASE 02 · Incomplete phase · Size M' \
  || { echo "FAIL: --phase 02 header wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -qx '  Files    only.sh' \
  || { echo "FAIL: --phase 02 files line wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^  Check' \
  && { echo "FAIL: --phase 02 should omit Check line entirely: $out"; exit 1; }

# edge: no such phase number -> non-zero exit, message on stderr, no partial block
errfile="$tmp/err99"
if out=$(bash "$brief_sh" "$batch" --phase 99 2>"$errfile"); then
  echo "FAIL: --phase 99 should exit non-zero"; exit 1
fi
[ -z "$out" ] || { echo "FAIL: --phase 99 should print no partial block: $out"; exit 1; }
[ -s "$errfile" ] || { echo "FAIL: --phase 99 should print a message on stderr"; exit 1; }

# edge: phase already moved to done/ -> found there too
mkdir -p "$batch/done"
mv "$batch/01-complete.md" "$batch/done/01-complete.md"
out=$(bash "$brief_sh" "$batch" --phase 01)
printf '%s\n' "$out" | grep -qx 'PHASE 01 · Complete phase · Size S' \
  || { echo "FAIL: --phase should find a phase already moved to done/: $out"; exit 1; }

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
batchdir="$parkrepo/.claude/cfq/impl/2026-01-01-test"
[ "$d1" = "$batchdir" ] || { echo "FAIL: printed dir wrong: $d1"; exit 1; }
[ "$(cat "$batchdir/.priority")" = "high" ] || { echo "FAIL: .priority wrong"; exit 1; }
[ "$(cat "$batchdir/.dependsOn")" = "$(printf '2026-01-01-dep-a\n2026-01-01-dep-b')" ] \
  || { echo "FAIL: .dependsOn wrong: $(cat "$batchdir/.dependsOn")"; exit 1; }
grep -qxF '.claude/cfq/impl/' "$parkrepo/.git/info/exclude" \
  || { echo "FAIL: git exclude entry missing"; exit 1; }
grep -q "$parkrepo" "$parkhome/.claude/code-for-queue/repos.json" \
  || { echo "FAIL: repo not registered"; exit 1; }

# no dependsOn entries -> no file; normal priority -> no .priority file either
d2=$(HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-02-nodeps" normal)
[ ! -e "$parkrepo/.claude/cfq/impl/2026-01-02-nodeps/.dependsOn" ] \
  || { echo "FAIL: .dependsOn should not exist when no entries were passed"; exit 1; }
[ ! -e "$parkrepo/.claude/cfq/impl/2026-01-02-nodeps/.priority" ] \
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
[ "$(grep -c '^# BEGIN cfq-managed' "$parkrepo/.git/info/exclude")" = "1" ] \
  || { echo "FAIL: exclude block not exactly once"; exit 1; }

# invalid priority -> exit != 0
if HOME="$parkhome" bash "$park_sh" "$parkrepo" "2026-01-03-bad" nope 2>/dev/null; then
  echo "FAIL: invalid priority should exit non-zero"; exit 1
fi

rm -rf "$parkhome"

echo PASS
