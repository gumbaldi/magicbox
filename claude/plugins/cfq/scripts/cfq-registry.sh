#!/usr/bin/env bash
# Manages ~/.claude/code-for-queue/repos.json — the registry of known repos.
# Usage: cfq-registry.sh add <repo-root> | prune | list
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-registry.sh: jq is required" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=cfq-paths.sh
. "$script_dir/cfq-paths.sh"

dir="$HOME/.claude/code-for-queue"
reg="$dir/repos.json"

ensure() {
  mkdir -p "$dir"
  [ -f "$reg" ] || echo '{"repos":[]}' > "$reg"
}

write() {
  local tmp="$reg.tmp"
  cat > "$tmp"
  mv "$tmp" "$reg"
}

cmd="${1:-}"
case "$cmd" in
  add)
    repo="${2:?usage: cfq-registry.sh add <repo-root>}"
    ensure
    jq --arg r "$repo" '.repos = ((.repos + [$r]) | unique | sort)' "$reg" | write
    ;;
  prune)
    ensure
    removed=$(jq -r '.repos[]' "$reg" | while read -r r; do
      [ -d "$(cfq_repo_dir "$r")" ] || echo "$r"
    done)
    if [ -n "$removed" ]; then
      keep=$(jq -Rn '[inputs]' <<<"$removed")
      jq --argjson rm "$keep" '.repos = (.repos - $rm)' "$reg" | write
      printf '%s\n' "$removed"
    fi
    ;;
  list)
    ensure
    jq -r '.repos[]' "$reg"
    ;;
  *)
    echo "usage: cfq-registry.sh add <repo-root> | prune | list" >&2
    exit 1
    ;;
esac
