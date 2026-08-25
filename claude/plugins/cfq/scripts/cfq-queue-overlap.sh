#!/usr/bin/env bash
# Bundles the "## Affected Files" extraction for every open phase across every open batch of a
# repo into one process invocation, replacing plan-for-queue's per-file sed loop
# (references/queue-check.md Step 5). Never fails, never writes: always prints one JSON object on
# stdout and exits 0 — the caller (a skill) decides what to do with the overlap.
# Usage: cfq-queue-overlap.sh <repo-root>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-queue-overlap.sh: jq is required" >&2; exit 1; }

repo="${1:?usage: cfq-queue-overlap.sh <repo-root>}"
impl_dir="$repo/.claude/cfq/impl"

result="[]"
if [ -d "$impl_dir" ]; then
  for b in "$impl_dir"/*/; do
    [ -d "$b" ] || continue
    name=$(basename "$b")
    [[ "$name" =~ ^([0-9]+-)?[0-9]{4}-[0-9]{2}-[0-9]{2}-.+ ]] || continue
    files_json=$(
      find "$b" -maxdepth 1 -name '[0-9][0-9]-*.md' -type f 2>/dev/null | sort | while IFS= read -r f; do
        sed -n '/^## Affected Files/,/^## /p' "$f" | sed -n 's/^- `\([^`]*\)`.*/\1/p'
      done | jq -R -s 'split("\n") | map(select(length > 0))'
    )
    result=$(jq -c --argjson r "$result" --arg batch "$name" --argjson files "$files_json" \
      '$r + [{batch: $batch, files: $files}]' <<<null)
  done
fi

jq -n --argjson batches "$result" '{batches: $batches}'
