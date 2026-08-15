#!/usr/bin/env bash
# One lock per repo: only one implement-for-queue session may work a repo at a time.
# Liveness comes from the holder's transcript mtime, not from a fixed expiry.
# Usage: cfq-lock.sh acquire <repo-root> <batch> | release <repo-root> | status <repo-root>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-lock.sh: jq is required" >&2; exit 1; }

STALE_S=1800   # 30 min without a transcript write counts as dead

lockfile() { printf '%s/.claude/code-for-queue/.lock' "$1"; }

mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }

# Prints "alive" or "dead" for the lock content on stdin.
liveness() {
  local t at age now
  now=$(date +%s)
  t=$(jq -r '.transcript // ""')
  if [ -n "$t" ] && [ -f "$t" ]; then
    age=$(( now - $(mtime "$t") ))
  else
    at=$(printf '%s' "$1")
    age=$(( now - at ))
  fi
  [ "$age" -lt "$STALE_S" ] && echo alive || echo dead
}

cmd="${1:-}"
case "$cmd" in
  acquire)
    repo="${2:?usage: cfq-lock.sh acquire <repo-root> <batch>}"
    batch="${3:?usage: cfq-lock.sh acquire <repo-root> <batch>}"
    f="$(lockfile "$repo")"
    mkdir -p "$(dirname "$f")"
    sid="${CLAUDE_CODE_SESSION_ID:-unknown}"
    slug="$(printf '%s' "$repo" | tr '/' '-')"
    tpath="$HOME/.claude/projects/$slug/$sid.jsonl"

    if [ -f "$f" ]; then
      holder=$(jq -r '.session_id // ""' "$f" 2>/dev/null || true)
      hbatch=$(jq -r '.batch // ""' "$f" 2>/dev/null || true)
      hepoch=$(jq -r '.epoch // 0' "$f" 2>/dev/null || echo 0)
      if [ "$holder" = "$sid" ]; then
        echo "OK $hbatch (already held by this session)"; exit 0
      fi
      state=$(jq -c . "$f" | liveness "$hepoch")
      if [ "$state" = "alive" ]; then
        echo "LOCKED $holder $hbatch $(jq -r '.at // "?"' "$f")" >&2
        exit 1
      fi
      echo "TAKEOVER $holder $hbatch (stale)" >&2
    fi

    jq -n --arg s "$sid" --arg b "$batch" --arg t "$tpath" \
          --arg at "$(date -Iseconds)" --argjson e "$(date +%s)" \
          '{session_id: $s, batch: $b, transcript: $t, at: $at, epoch: $e}' >"$f.tmp"
    mv "$f.tmp" "$f"
    echo "OK $batch"
    ;;

  release)
    repo="${2:?usage: cfq-lock.sh release <repo-root>}"
    f="$(lockfile "$repo")"
    [ -f "$f" ] || { echo "FREE"; exit 0; }
    holder=$(jq -r '.session_id // ""' "$f" 2>/dev/null || true)
    sid="${CLAUDE_CODE_SESSION_ID:-unknown}"
    if [ "$holder" != "$sid" ]; then
      echo "cfq-lock.sh: lock held by $holder, not releasing" >&2
      exit 1
    fi
    rm -f "$f"
    echo "FREE"
    ;;

  status)
    repo="${2:?usage: cfq-lock.sh status <repo-root>}"
    f="$(lockfile "$repo")"
    [ -f "$f" ] || { echo "FREE"; exit 0; }
    hepoch=$(jq -r '.epoch // 0' "$f")
    state=$(jq -c . "$f" | liveness "$hepoch")
    jq -r --arg st "$state" '"\($st | ascii_upcase) \(.session_id) \(.batch) \(.at)"' "$f"
    ;;

  *)
    echo "usage: cfq-lock.sh acquire <repo-root> <batch> | release <repo-root> | status <repo-root>" >&2
    exit 1
    ;;
esac
