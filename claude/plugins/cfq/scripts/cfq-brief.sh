#!/usr/bin/env bash
# Prints the batch briefing block shown before a batch is offered for implementation. Read-only.
# Usage: cfq-brief.sh <batch-dir>
set -eu

dir="${1:?usage: cfq-brief.sh <batch-dir>}"
dir="${dir%/}"
[ -d "$dir" ] || { echo "cfq-brief.sh: no such batch directory: $dir" >&2; exit 1; }

name="$(basename "$dir")"
priority=$(cat "$dir/.priority" 2>/dev/null || echo medium)

shopt -s nullglob
files=("$dir"/[0-9][0-9]-*.md)
shopt -u nullglob

printf '%s  priority=%s  phases=%s\n' "$name" "$priority" "${#files[@]}"

if [ -f "$dir/.dependsOn" ]; then
  while IFS= read -r d; do
    [ -n "$d" ] && printf 'dependsOn: %s\n' "$d"
  done < "$dir/.dependsOn"
fi

for f in "${files[@]}"; do
  num=$(basename "$f" | sed -n 's/^\([0-9][0-9]\)-.*/\1/p')
  awk -v num="$num" '
    /^# / && !t            { sub(/^# +/, ""); t = $0; next }
    /^## Size/             { g = 1; next }
    g && NF                { size = $1; g = 0; next }
    /^## Context/          { k = 1; next }
    k && NF                { ctx = ctx $0 " "; if (++n >= 2) k = 0; next }
    END { printf "%s  %s  [%s]  %s\n", num, t, (size ? size : "M"), substr(ctx, 1, 220) }
  ' "$f"
done
