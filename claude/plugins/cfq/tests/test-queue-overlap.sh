#!/usr/bin/env bash
# Self-test for scripts/cfq-queue-overlap.sh. No framework, no fixtures — just
# `bash tests/test-queue-overlap.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
overlap="$repo_root/scripts/cfq-queue-overlap.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# batch-a and batch-b each have one open phase; both list shared.txt plus one path of their own.
mkdir -p "$tmp/.claude/cfq/impl/2026-01-01-batch-a" "$tmp/.claude/cfq/impl/2026-01-01-batch-b"
cat > "$tmp/.claude/cfq/impl/2026-01-01-batch-a/01-a.md" <<'EOF'
## Size
S

## Affected Files

- `/repo/shared.txt`
- `/repo/a-only.txt`

## Changes
EOF
cat > "$tmp/.claude/cfq/impl/2026-01-01-batch-b/01-b.md" <<'EOF'
## Size
S

## Affected Files

- `/repo/shared.txt`
- `/repo/b-only.txt`

## Changes
EOF

# batch-c has one open phase with no ## Affected Files section at all — must yield an empty
# files array, not an omitted batch entry.
mkdir -p "$tmp/.claude/cfq/impl/2026-01-01-batch-c"
cat > "$tmp/.claude/cfq/impl/2026-01-01-batch-c/01-c.md" <<'EOF'
## Size
S

## Changes
EOF

# a phase already moved to done/ must never be scanned (excluded by maxdepth 1)
mkdir -p "$tmp/.claude/cfq/impl/2026-01-01-batch-a/done"
cat > "$tmp/.claude/cfq/impl/2026-01-01-batch-a/done/00-old.md" <<'EOF'
## Affected Files

- `/repo/should-not-appear.txt`
EOF

out=$("$overlap" "$tmp")

got_a=$(jq -c '.batches[] | select(.batch == "2026-01-01-batch-a") | .files | sort' <<<"$out")
[ "$got_a" = '["/repo/a-only.txt","/repo/shared.txt"]' ] \
  || { echo "FAIL: batch-a files = $got_a"; exit 1; }

got_b=$(jq -c '.batches[] | select(.batch == "2026-01-01-batch-b") | .files | sort' <<<"$out")
[ "$got_b" = '["/repo/b-only.txt","/repo/shared.txt"]' ] \
  || { echo "FAIL: batch-b files = $got_b"; exit 1; }

got_c=$(jq -c '.batches[] | select(.batch == "2026-01-01-batch-c") | .files' <<<"$out")
[ "$got_c" = '[]' ] || { echo "FAIL: batch-c files = $got_c, want []"; exit 1; }

count=$(jq '.batches | length' <<<"$out")
[ "$count" = "3" ] || { echo "FAIL: batches count = $count, want 3"; exit 1; }

# an empty repo (no .claude/cfq/impl at all) must never fail, just report no batches
empty=$(mktemp -d)
out2=$("$overlap" "$empty")
[ "$(jq -c '.batches' <<<"$out2")" = "[]" ] || { echo "FAIL: empty repo batches = $out2"; exit 1; }
rm -rf "$empty"

echo PASS
