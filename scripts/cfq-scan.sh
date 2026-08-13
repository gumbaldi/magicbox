#!/usr/bin/env bash
# The single source of numbers for the dashboard. No arguments needed.
# Prints one JSON object on stdout: { "repos": [ { "path", "batches": [ {name, priority, open, done, archived, report} ] } ] }
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-scan.sh: jq is required" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
registry="$script_dir/cfq-registry.sh"

candidates=$("$registry" list 2>/dev/null || true)

IFS=':' read -ra roots <<<"${CFQ_SCAN_ROOTS:-$HOME/git}"
for root in "${roots[@]}"; do
  root="${root/#\~/$HOME}"
  [ -d "$root" ] || continue
  while IFS= read -r d; do
    candidates="$candidates
$(dirname "$(dirname "$d")")"
  done < <(find "$root" -mindepth 2 -maxdepth 4 -type d -path '*/.claude/code-for-queue' 2>/dev/null)
done

candidates=$(printf '%s\n' "$candidates" | sed '/^$/d' | sort -u)

for repo in $candidates; do
  "$registry" add "$repo" >/dev/null
done

trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1"; }

# Legacy queues wrote German priorities; map them so old batches keep sorting.
read_priority() {
  local p="medium"
  [ -f "$1/.priority" ] && p=$(trim "$1/.priority")
  case "$p" in
    niedrig) echo low ;;
    mittel)  echo medium ;;
    hoch)    echo high ;;
    *)       echo "$p" ;;
  esac
}

records=$(mktemp)
trap 'rm -f "$records"' EXIT

while IFS= read -r repo; do
  [ -n "$repo" ] || continue
  qdir="$repo/.claude/code-for-queue"
  [ -d "$qdir" ] || continue

  for b in "$qdir"/*/; do
    [ -d "$b" ] || continue
    name=$(basename "$b")
    [ "$name" = "done" ] && continue
    open=$(find "$b" -maxdepth 1 -name '*.md' -type f | wc -l)
    donec=$(find "$b/done" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l)
    priority=$(read_priority "$b")
    report="false"; [ -f "$b/report.json" ] && report="true"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$repo" "$name" "$priority" "$open" "$donec" "false" "$report" >>"$records"
  done

  if [ -d "$qdir/done" ]; then
    for b in "$qdir/done"/*/; do
      [ -d "$b" ] || continue
      name=$(basename "$b")
      donec=$(find "$b" -maxdepth 1 -name '*.md' -type f | wc -l)
      priority=$(read_priority "$b")
      report="false"; [ -f "$b/report.json" ] && report="true"
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$repo" "$name" "$priority" "0" "$donec" "true" "$report" >>"$records"
    done
  fi
done <<<"$candidates"

jq -R -s '
  split("\n") | map(select(length > 0)) | map(split("\t")) |
  map({
    path: .[0], name: .[1], priority: .[2],
    open: (.[3] | tonumber), done: (.[4] | tonumber),
    archived: (.[5] == "true"), report: (.[6] == "true")
  }) |
  group_by(.path) |
  map({ path: .[0].path, batches: map({name, priority, open, done, archived, report}) })
' "$records" | jq -c '{repos: .}'
