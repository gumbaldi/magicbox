#!/usr/bin/env bash
# Self-test for scripts/cfq-finish.sh. No framework, no fixtures beyond what's built here — just
# `bash tests/test-finish.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
finish_sh="$repo_root/scripts/cfq-finish.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

new_repo() {
  local r="$tmp/$1"
  mkdir -p "$r"
  git init -q -b main "$r"
  git -C "$r" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
  printf '%s' "$r"
}

new_batch() {
  # $1 = repo, $2 = batch name
  local dir="$1/.claude/cfq/impl/$2"
  mkdir -p "$dir/done"
  echo medium > "$dir/.priority"
  cat > "$dir/done/01-a.md" <<'EOF'
# A phase
EOF
  printf '%s' "$dir"
}

# ============================================================ happy path =============

home1=$(mktemp -d)
repo1=$(new_repo repo1)
batch1=$(new_batch "$repo1" "2026-01-01-happy")
HOME="$home1" bash "$repo_root/scripts/cfq-lock.sh" acquire "$repo1" "2026-01-01-happy" >/dev/null

out=$(HOME="$home1" bash "$finish_sh" "$repo1" "$batch1" "v0.1-happy")
printf '%s' "$out" | jq -e . >/dev/null || { echo "FAIL: output not valid JSON: $out"; exit 1; }
[ -d "$repo1/.claude/cfq/impl/done/2026-01-01-happy" ] \
  || { echo "FAIL: batch not moved into impl/done: $out"; exit 1; }
[ ! -d "$repo1/.claude/cfq/impl/2026-01-01-happy" ] \
  || { echo "FAIL: batch still present at its old location"; exit 1; }
[ "$(jq -r '.lock' <<<"$out")" = "released" ] || { echo "FAIL: lock field: $out"; exit 1; }
lockstatus=$(HOME="$home1" bash "$repo_root/scripts/cfq-lock.sh" status "$repo1")
[ "$lockstatus" = "FREE" ] || { echo "FAIL: lock not actually released: $lockstatus"; exit 1; }
rm -rf "$home1"

# ============================================================ mid-sequence failure ====

home2=$(mktemp -d)
repo2=$(new_repo repo2)
batch2=$(new_batch "$repo2" "2026-01-01-brokenchangelog")
HOME="$home2" bash "$repo_root/scripts/cfq-lock.sh" acquire "$repo2" "2026-01-01-brokenchangelog" >/dev/null

# Point changelogFile at a path inside a read-only directory — cfq-changelog.sh finish fails to
# write, cfq-finish.sh must still complete the rest of the sequence and release the lock.
mkdir -p "$home2/.claude/code-for-queue"
mkdir -p "$repo2/readonlydir"
echo '{"changelogFile": "readonlydir/changelog.yml"}' > "$home2/.claude/code-for-queue/settings.json"
chmod 555 "$repo2/readonlydir"

out=$(HOME="$home2" bash "$finish_sh" "$repo2" "$batch2" "v0.1-brokenchangelog")
chmod 755 "$repo2/readonlydir"

printf '%s' "$out" | jq -e . >/dev/null || { echo "FAIL: output not valid JSON: $out"; exit 1; }
[ -d "$repo2/.claude/cfq/impl/done/2026-01-01-brokenchangelog" ] \
  || { echo "FAIL: sequence did not complete the move: $out"; exit 1; }
[ "$(jq -r '.lock' <<<"$out")" = "released" ] || { echo "FAIL: lock field on failure path: $out"; exit 1; }
lockstatus=$(HOME="$home2" bash "$repo_root/scripts/cfq-lock.sh" status "$repo2")
[ "$lockstatus" = "FREE" ] || { echo "FAIL: lock not released after mid-sequence failure: $lockstatus"; exit 1; }
[ "$(jq '.errors | length' <<<"$out")" -gt 0 ] || { echo "FAIL: errors should be non-empty: $out"; exit 1; }
jq -e '.errors[] | select(startswith("changelog:"))' <<<"$out" >/dev/null \
  || { echo "FAIL: no changelog error recorded: $out"; exit 1; }
rm -rf "$home2"

# ============================================================ changelogFile empty =====

home3=$(mktemp -d)
repo3=$(new_repo repo3)
batch3=$(new_batch "$repo3" "2026-01-01-nochangelog")
HOME="$home3" bash "$repo_root/scripts/cfq-lock.sh" acquire "$repo3" "2026-01-01-nochangelog" >/dev/null
mkdir -p "$home3/.claude/code-for-queue"
echo '{"changelogFile": ""}' > "$home3/.claude/code-for-queue/settings.json"

out=$(HOME="$home3" bash "$finish_sh" "$repo3" "$batch3" "v0.1-nochangelog")
[ "$(jq -r '.changelog' <<<"$out")" = "changelogFile empty" ] \
  || { echo "FAIL: changelog field should say empty: $out"; exit 1; }
jq -e '.errors[] | select(startswith("changelog:"))' <<<"$out" >/dev/null \
  && { echo "FAIL: changelogFile empty must not be an error: $out"; exit 1; }
[ -d "$repo3/.claude/cfq/impl/done/2026-01-01-nochangelog" ] \
  || { echo "FAIL: sequence did not complete: $out"; exit 1; }
rm -rf "$home3"

# ============================================================ no planning snapshot ====

home4=$(mktemp -d)
repo4=$(new_repo repo4)
batch4=$(new_batch "$repo4" "2026-01-01-nosnapshot")
# No report.json at all — simulates a batch that predates the planning-time security snapshot.
HOME="$home4" bash "$repo_root/scripts/cfq-lock.sh" acquire "$repo4" "2026-01-01-nosnapshot" >/dev/null

out=$(HOME="$home4" bash "$finish_sh" "$repo4" "$batch4" "v0.1-nosnapshot")
[ "$(jq -c '.security.new' <<<"$out")" = "{}" ] \
  || { echo "FAIL: security.new should be empty without a planning snapshot: $out"; exit 1; }
jq -e '.errors[] | select(startswith("security:"))' <<<"$out" >/dev/null \
  && { echo "FAIL: missing planning snapshot must not be an error: $out"; exit 1; }
rm -rf "$home4"

echo PASS
