#!/usr/bin/env bash
# Lints a parked batch of phase plans before pfq hands it off. Reports, never repairs, never
# aborts on soft findings (depends is warn-only and never affects the exit code).
# Usage: cfq-lint.sh <batch-dir>
set -eu

dir="${1:?usage: cfq-lint.sh <batch-dir>}"
[ -d "$dir" ] || { echo "cfq-lint.sh: no such batch directory: $dir" >&2; exit 1; }
dir="${dir%/}"
batch_name="$(basename "$dir")"

# Content rules (sections/abspath/missing/stale-new) only make sense pre-implementation, so they
# scan open phases only — a done phase's "(neu)" markers are stale by definition once the phase
# that created those files has been implemented. numbering is a structural, whole-batch
# invariant and always considers open + done together.
open_files=$(find "$dir" -maxdepth 1 -name '[0-9][0-9]-*.md' -type f 2>/dev/null | sort)
done_files=$(find "$dir/done" -maxdepth 1 -name '[0-9][0-9]-*.md' -type f 2>/dev/null | sort)
all_files=$(printf '%s\n%s\n' "$open_files" "$done_files" | sed '/^$/d')
n=$(printf '%s\n' "$all_files" | grep -c . || true)

findings=()
warn_findings=()

has_heading() {
  # $1 = file, $2 = German heading, $3 = English heading
  grep -qE "^## (${2}|${3})([[:space:]]|\$)" "$1"
}

extract_files_section() {
  sed -n '/^## \(Betroffene Dateien\|Affected Files\)/,/^## /p' "$1"
}

while IFS= read -r f; do
  [ -n "$f" ] || continue
  name="$(basename "$f")"

  has_heading "$f" "Kontext" "Context"                  || findings+=("$name: sections: missing Kontext/Context heading")
  has_heading "$f" "Betroffene Dateien" "Affected Files" || findings+=("$name: sections: missing Betroffene Dateien/Affected Files heading")
  has_heading "$f" "Änderungen" "Changes"                || findings+=("$name: sections: missing Änderungen/Changes heading")
  has_heading "$f" "Verifikation" "Verification"         || findings+=("$name: sections: missing Verifikation/Verification heading")

  while IFS= read -r line; do
    path=$(printf '%s' "$line" | sed -n 's/^- `\([^`]*\)`.*/\1/p')
    [ -n "$path" ] || continue
    case "$path" in
      /*)
        case "$line" in
          *'(neu)'*)
            [ -e "$path" ] && findings+=("$name: stale-new: $path already exists")
            ;;
          *)
            [ -e "$path" ] || findings+=("$name: missing: $path does not exist")
            ;;
        esac
        ;;
      *)
        findings+=("$name: abspath: $path is not absolute")
        ;;
    esac
  done < <(extract_files_section "$f" | grep -E '^- `' || true)
done <<<"$open_files"

# numbering: gapless from 01, no duplicates, open + done together
nums=$(printf '%s\n' "$all_files" | xargs -r -n1 basename | sed -n 's/^\([0-9][0-9]\)-.*/\1/p' | sort)
dups=$(printf '%s\n' "$nums" | uniq -d | tr '\n' ' ' | sed 's/ *$//')
[ -n "$dups" ] && findings+=("$batch_name: numbering: duplicate phase number(s): $dups")
expected=1
for cur in $(printf '%s\n' "$nums" | sort -u); do
  want=$(printf '%02d' "$expected")
  if [ "$cur" != "$want" ]; then
    findings+=("$batch_name: numbering: gap before $cur, expected $want")
    break
  fi
  expected=$((expected + 1))
done

# priority
if [ -f "$dir/.priority" ]; then
  p=$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$dir/.priority")
  case "$p" in
    low|medium|high) : ;;
    *) findings+=("$batch_name: priority: .priority is '$p', want low|medium|high") ;;
  esac
else
  findings+=("$batch_name: priority: .priority is missing")
fi

# depends (warn-only, never affects the exit code)
if [ -f "$dir/.dependsOn" ]; then
  repo_qdir="$(dirname "$dir")"
  deps=$(sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$dir/.dependsOn" | sed '/^$/d')
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    if [ ! -d "$repo_qdir/$d" ] && [ ! -d "$repo_qdir/done/$d" ]; then
      warn_findings+=("warn: $batch_name: depends: $d does not exist")
    fi
  done <<<"$deps"
fi

for line in "${findings[@]:-}"; do
  [ -n "$line" ] && echo "$line"
done
for line in "${warn_findings[@]:-}"; do
  [ -n "$line" ] && echo "$line"
done

if [ "${#findings[@]}" -eq 0 ]; then
  echo "OK $n Phasen"
  exit 0
fi
exit 1
