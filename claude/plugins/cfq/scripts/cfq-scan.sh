#!/usr/bin/env bash
# The single source of numbers for the dashboard. No arguments needed.
# Prints one JSON object on stdout: { "repos": [ { "path", "plan", "todo", "batches": [
#   {name, priority, open, done, archived, report, dependsOn, blocked, unknownDeps, inProgress,
#    planning} ] } ] }
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-scan.sh: jq is required" >&2; exit 1; }

PLANNING_STALE_S=1800   # mirrors cfq-lock.sh's STALE_S — a .planning marker older than this is
                        # an abandoned pfq run, not a batch still being written

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

read_priority() {
  [ -f "$1/.priority" ] || return 0
  local p; p=$(trim "$1/.priority")
  [ "$p" = high ] && echo high
  return 0
}

read_deps() {
  [ -f "$1/.dependsOn" ] || return 0
  sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1/.dependsOn" \
    | sed '/^$/d' | paste -sd, -
}

records=$(mktemp)
counts=$(mktemp)
trap 'rm -f "$records" "$counts"' EXIT

while IFS= read -r repo; do
  [ -n "$repo" ] || continue
  qdir="$repo/.claude/code-for-queue"
  [ -d "$qdir" ] || continue

  plan=$(find "$qdir/plan" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l)
  todo=$(find "$qdir/todo" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l)
  printf '%s\t%s\t%s\n' "$repo" "$plan" "$todo" >>"$counts"

  for b in "$qdir/impl"/*/; do
    [ -d "$b" ] || continue
    name=$(basename "$b")
    [[ "$name" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-.+ ]] || continue
    open=$(find "$b" -maxdepth 1 -name '*.md' -type f | wc -l)
    donec=$(find "$b/done" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l)
    priority=$(read_priority "$b")
    report="false"; [ -f "$b/report.json" ] && report="true"
    deps=$(read_deps "$b")
    blocked="false"; unknown=""
    if [ -n "$deps" ]; then
      old_ifs=$IFS; IFS=','
      for d in $deps; do
        if [ -d "$qdir/impl/$d" ]; then
          blocked="true"                    # dependency exists and is not finished
        elif [ -d "$qdir/impl/done/$d" ]; then
          :                                 # finished — satisfied
        else
          unknown="${unknown:+$unknown,}$d" # unresolvable: reported, never blocking
        fi
      done
      IFS=$old_ifs
    fi
    planning="false"
    if [ -f "$b/.planning" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$b/.planning" 2>/dev/null || echo 0) ))
      [ "$age" -lt "$PLANNING_STALE_S" ] && planning="true"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$repo" "$name" "$priority" "$open" "$donec" "false" "$report" "$deps" "$blocked" "$unknown" "$planning" >>"$records"
  done

  if [ -d "$qdir/impl/done" ]; then
    for b in "$qdir/impl/done"/*/; do
      [ -d "$b" ] || continue
      name=$(basename "$b")
      [[ "$name" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-.+ ]] || continue
      donec=$(find "$b" -maxdepth 1 -name '*.md' -type f | wc -l)
      priority=$(read_priority "$b")
      report="false"; [ -f "$b/report.json" ] && report="true"
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$repo" "$name" "$priority" "0" "$donec" "true" "$report" "" "false" "" "false" >>"$records"
    done
  fi
done <<<"$candidates"

jq -n --rawfile recs "$records" --rawfile cnts "$counts" '
  def parse_tsv: split("\n") | map(select(length > 0)) | map(split("\t"));

  ($recs | parse_tsv | map({
    path: .[0], name: .[1], priority: .[2],
    open: (.[3] | tonumber), done: (.[4] | tonumber),
    archived: (.[5] == "true"), report: (.[6] == "true"),
    dependsOn:   (((.[7] // "") | select(. != "")) // "" | if . == "" then [] else split(",") end),
    blocked:     ((.[8] // "false") == "true"),
    unknownDeps: (((.[9] // "") | select(. != "")) // "" | if . == "" then [] else split(",") end),
    inProgress:  ((.[3] | tonumber) > 0 and (.[4] | tonumber) > 0),
    planning:    ((.[10] // "false") == "true")
  }) | group_by(.path)
     | map({key: .[0].path,
            value: map({name, priority, open, done, archived, report, dependsOn, blocked, unknownDeps, inProgress, planning})})
     | from_entries) as $batchmap
  |
  ($cnts | parse_tsv
     | map({key: .[0], value: {plan: (.[1] | tonumber), todo: (.[2] | tonumber)}})
     | from_entries) as $countmap
  |
  (($batchmap | keys) + ($countmap | keys) | unique) as $paths
  |
  { repos: [ $paths[] | . as $p | {
      path: $p,
      plan: ($countmap[$p].plan // 0),
      todo: ($countmap[$p].todo // 0),
      batches: ($batchmap[$p] // [])
    } ] }
'
