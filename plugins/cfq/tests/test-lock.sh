#!/usr/bin/env bash
# Self-test for scripts/cfq-lock.sh. No framework, no fixtures — just `bash tests/test-lock.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock_sh="$repo_root/scripts/cfq-lock.sh"

repo=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$repo" "$home"' EXIT

lock="$repo/.claude/code-for-queue/.lock"
slug="$(printf '%s' "$repo" | tr '/' '-')"
tdir="$home/.claude/projects/$slug"

# 1. Fresh acquire
out=$(CLAUDE_CODE_SESSION_ID=sidA HOME="$home" bash "$lock_sh" acquire "$repo" batchA)
[ "$out" = "OK batchA" ] || { echo "FAIL: fresh acquire = $out"; exit 1; }
[ -f "$lock" ] || { echo "FAIL: lock file not created"; exit 1; }

# 2. Foreign session, still fresh (epoch just written) -> rejected
if out=$(CLAUDE_CODE_SESSION_ID=sidB HOME="$home" bash "$lock_sh" acquire "$repo" batchB 2>&1); then
  echo "FAIL: foreign acquire on a fresh lock should fail, got: $out"; exit 1
fi
[[ "$out" == LOCKED* ]] || { echo "FAIL: rejection message = $out"; exit 1; }

# 3. Same session again -> idempotent OK
out=$(CLAUDE_CODE_SESSION_ID=sidA HOME="$home" bash "$lock_sh" acquire "$repo" batchA)
[ "$out" = "OK batchA (already held by this session)" ] || { echo "FAIL: idempotent acquire = $out"; exit 1; }

# 4. Holder's transcript exists but is stale (40 min old) -> foreign takeover succeeds
mkdir -p "$tdir"
touch "$tdir/sidA.jsonl"
touch -d '-40 minutes' "$tdir/sidA.jsonl"
out=$(CLAUDE_CODE_SESSION_ID=sidB HOME="$home" bash "$lock_sh" acquire "$repo" batchB 2>&1)
[[ "$out" == *TAKEOVER* ]] || { echo "FAIL: expected TAKEOVER, got: $out"; exit 1; }
holder=$(jq -r '.session_id' "$lock")
[ "$holder" = "sidB" ] || { echo "FAIL: holder after takeover = $holder, want sidB"; exit 1; }

# 5. New holder's transcript freshly written -> foreign acquire rejected again
touch "$tdir/sidB.jsonl"
if out=$(CLAUDE_CODE_SESSION_ID=sidC HOME="$home" bash "$lock_sh" acquire "$repo" batchC 2>&1); then
  echo "FAIL: acquire against a fresh transcript should fail, got: $out"; exit 1
fi
[[ "$out" == LOCKED* ]] || { echo "FAIL: rejection message = $out"; exit 1; }

# Reset for the fallback case: release as the current holder (sidB)
CLAUDE_CODE_SESSION_ID=sidB HOME="$home" bash "$lock_sh" release "$repo" >/dev/null

# 6. No transcript on disk at all, epoch forced stale -> fallback to epoch age -> TAKEOVER
CLAUDE_CODE_SESSION_ID=sidD HOME="$home" bash "$lock_sh" acquire "$repo" batchD >/dev/null
jq '.epoch -= 3000' "$lock" >"$lock.tmp" && mv "$lock.tmp" "$lock"
out=$(CLAUDE_CODE_SESSION_ID=sidE HOME="$home" bash "$lock_sh" acquire "$repo" batchE 2>&1)
[[ "$out" == *TAKEOVER* ]] || { echo "FAIL: expected fallback TAKEOVER, got: $out"; exit 1; }
holder=$(jq -r '.session_id' "$lock")
[ "$holder" = "sidE" ] || { echo "FAIL: holder after fallback takeover = $holder, want sidE"; exit 1; }

# 7. Foreign release rejected, holder release frees it
if out=$(CLAUDE_CODE_SESSION_ID=sidF HOME="$home" bash "$lock_sh" release "$repo" 2>&1); then
  echo "FAIL: foreign release should fail, got: $out"; exit 1
fi
[ -f "$lock" ] || { echo "FAIL: lock removed by a foreign release"; exit 1; }
out=$(CLAUDE_CODE_SESSION_ID=sidE HOME="$home" bash "$lock_sh" release "$repo")
[ "$out" = "FREE" ] || { echo "FAIL: holder release = $out"; exit 1; }
[ -f "$lock" ] && { echo "FAIL: lock file still present after release"; exit 1; }

# 8. status: FREE, then ALIVE right after acquiring, then DEAD once stale
out=$(HOME="$home" bash "$lock_sh" status "$repo")
[ "$out" = "FREE" ] || { echo "FAIL: status on unlocked repo = $out"; exit 1; }

CLAUDE_CODE_SESSION_ID=sidG HOME="$home" bash "$lock_sh" acquire "$repo" batchG >/dev/null
out=$(HOME="$home" bash "$lock_sh" status "$repo")
[[ "$out" == "ALIVE sidG batchG "* ]] || { echo "FAIL: status after acquire = $out"; exit 1; }

jq '.epoch -= 3000' "$lock" >"$lock.tmp" && mv "$lock.tmp" "$lock"
out=$(HOME="$home" bash "$lock_sh" status "$repo")
[[ "$out" == "DEAD sidG batchG "* ]] || { echo "FAIL: status once stale = $out"; exit 1; }

CLAUDE_CODE_SESSION_ID=sidG HOME="$home" bash "$lock_sh" release "$repo" >/dev/null

echo PASS
