#!/usr/bin/env bash
# Appends/completes entries in <repo-root>/<changelogFile>, one block per batch. No YAML parser
# (yq is not installed) — produced with printf/jq -r, parsed back with grep/sed/awk on fixed
# prefixes. Version-free schema: no batch ever carries a version/appVersion/cfqVersion field.
# Usage: cfq-changelog.sh init            <repo-root> <branch> <base> <batch>
#        cfq-changelog.sh finish          <repo-root> <branch> <batch-dir>
#        cfq-changelog.sh reserve         <repo-root> <batchNumber> <batch>
#        cfq-changelog.sh rename-batch    <repo-root> <old-batch> <new-batch>
#        cfq-changelog.sh branch-for      <repo-root> <batch>
#        cfq-changelog.sh commit-message  <repo-root> <batch> <phase> <status> <message-file>
#        cfq-changelog.sh ensure          <repo-root>
#        cfq-changelog.sh migrate         <repo-root>
#        cfq-changelog.sh max-batch-number <repo-root>
#
# batchNumber/legacy are derived from <batch>'s own name, never from a version. `commit-message`
# is the sole writer of `CFQ-*` Git trailers (scan_trailer_max/scan_trailer_batch_for_max below are
# the sole reader) — one owner for trailer rendering, one for parsing.
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-changelog.sh: jq is required" >&2; exit 1; }

here="$(dirname "${BASH_SOURCE[0]}")"
cfq="$here/../bin/cfq"

changelog_file() {
  local repo="$1" rel
  rel="$("$cfq" settings get changelogFile)"
  [ -n "$rel" ] || return 1
  printf '%s/%s\n' "$repo" "$rel"
}

# phases[] from a batch's report.json, as indented double-quoted YAML scalars.
phases_yaml() {
  jq -r '
    .phases[] |
    "    - phase: " + (.phase // "" | tojson) +
    "\n      status: " + (.status // "" | tojson) +
    "\n      summary: " + (.summary // "" | tojson)
  ' "$1" 2>/dev/null || true
}

# New-format batch directory names are <digits>-<YYYY-MM-DD>-<slug> (the number precedes the
# date); legacy names start directly with the date. Prints the plain integer (no leading zeros)
# on a match, nothing on no match — never guesses from a version tag or branch name.
parse_batch_number() {
  local batch="$1"
  if [[ "$batch" =~ ^([0-9]+)-[0-9]{4}-[0-9]{2}-[0-9]{2}- ]]; then
    printf '%d\n' "$((10#${BASH_REMATCH[1]}))"
  fi
}

# Renders one changelog block. Args: number batch branch base started status legacy finished phases
render_block() {
  local number="$1" batch="$2" branch="$3" base="$4" started="$5" status="$6" legacy="$7" finished="$8" phases="$9"
  printf -- '- batchNumber: %s\n' "$number"
  printf '  batch: %s\n' "$batch"
  [ -n "$branch" ] && printf '  branch: %s\n' "$branch"
  [ -n "$base" ] && printf '  base: %s\n' "$base"
  [ -n "$started" ] && printf '  started: %s\n' "$started"
  printf '  status: %s\n' "$status"
  printf '  legacy: %s\n' "$legacy"
  [ -n "$finished" ] && printf '  finished: %s\n' "$finished"
  if [ -n "$phases" ]; then
    printf '  phases:\n'
    printf '%s\n' "$phases"
  fi
}

block_starts() { grep -n '^- batchNumber:' "$1" 2>/dev/null | cut -d: -f1 || true; }

# Exclusive end line of the block starting at $2 (next block start - 1, or EOF).
block_end_line() {
  local file="$1" start="$2" next
  next=$(awk -v s="$start" '/^- batchNumber:/ && NR>s {print NR; exit}' "$file")
  if [ -n "$next" ]; then printf '%s\n' "$((next - 1))"; else wc -l <"$file"; fi
}

block_text() { sed -n "${2},$(block_end_line "$1" "$2")p" "$1"; }

# block_field <block-text> '<field-prefix, e.g. "  batch:" or "- batchNumber:">'
block_field() { printf '%s\n' "$1" | sed -n "s/^$2 *//p" | head -1; }

# find_block_start <file> <field-prefix> <value> [want-status] — last matching block's start line.
find_block_start() {
  local file="$1" field="$2" value="$3" want_status="${4:-}" start block fval sval hit=""
  for start in $(block_starts "$file"); do
    block="$(block_text "$file" "$start")"
    fval="$(block_field "$block" "$field")"
    [ "$fval" = "$value" ] || continue
    if [ -n "$want_status" ]; then
      sval="$(block_field "$block" '  status:')"
      [ "$sval" = "$want_status" ] || continue
    fi
    hit="$start"
  done
  [ -n "$hit" ] && printf '%s\n' "$hit"
}

replace_block() {
  local file="$1" start="$2" new="$3" end
  end="$(block_end_line "$file" "$start")"
  { head -n "$((start - 1))" "$file"; printf '%s\n' "$new"; tail -n "+$((end + 1))" "$file"; } >"$file.tmp"
  mv "$file.tmp" "$file"
}

# Highest CFQ-Batch-Number trailer reachable in repo history; 0 if none/not a git repo. Uses
# Git's own trailer-aware formatting, never free-text grep, so a stray "CFQ-Batch-Number" in a
# commit body/subject can't be mistaken for a real trailer.
scan_trailer_max() {
  git -C "$1" log --all --no-color --pretty='format:%(trailers:key=CFQ-Batch-Number,valueonly)' 2>/dev/null \
    | awk '/^[0-9]+$/ && $1+0>0 { if ($1+0>m) m=$1+0 } END { print m+0 }'
}

# Human-readable CFQ-Batch trailer of the (first, newest-first) commit that carries the given max
# CFQ-Batch-Number. One `%(trailers:...)` placeholder per format string only — combining two in a
# single line is ambiguous, since each placeholder appends its own trailing newline.
scan_trailer_batch_for_max() {
  local repo="$1" max="$2" h val
  for h in $(git -C "$repo" log --all --format='%H' 2>/dev/null); do
    val="$(git -C "$repo" log -1 --format='%(trailers:key=CFQ-Batch-Number,valueonly)' "$h" 2>/dev/null | tr -d '\n')"
    if [ "$val" = "$max" ]; then
      git -C "$repo" log -1 --format='%(trailers:key=CFQ-Batch,valueonly)' "$h" 2>/dev/null | tr -d '\n'
      return 0
    fi
  done
}

cmd="${1:-}"
case "$cmd" in
  init)
    repo="${2:?usage: cfq-changelog.sh init <repo-root> <branch> <base> <batch>}"
    branch="${3:?usage: cfq-changelog.sh init <repo-root> <branch> <base> <batch>}"
    base="${4:?usage: cfq-changelog.sh init <repo-root> <branch> <base> <batch>}"
    batch="${5:?usage: cfq-changelog.sh init <repo-root> <branch> <base> <batch>}"
    target="$(changelog_file "$repo")" || exit 0
    mkdir -p "$(dirname "$target")"

    number="$(parse_batch_number "$batch")"
    legacy=true; [ -n "$number" ] && legacy=false
    [ -n "$number" ] || number=null

    started="$(date -I)"
    reserved_start=""
    [ -f "$target" ] && reserved_start="$(find_block_start "$target" '  batch:' "$batch" parked || true)"

    new_block="$(render_block "$number" "$batch" "$branch" "$base" "$started" in-progress "$legacy" "" "")"
    if [ -n "$reserved_start" ]; then
      replace_block "$target" "$reserved_start" "$new_block"
    else
      printf '%s\n' "$new_block" >>"$target"
    fi
    ;;

  finish)
    repo="${2:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    branch="${3:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    batch_dir="${4:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    target="$(changelog_file "$repo")" || exit 0
    mkdir -p "$(dirname "$target")"
    batch="$(basename "$batch_dir")"
    report="$batch_dir/report.json"
    finished="$(date -I)"
    phases="$(phases_yaml "$report")"

    matched_start=""
    [ -f "$target" ] && matched_start="$(find_block_start "$target" '  branch:' "$branch" in-progress || true)"

    if [ -n "$matched_start" ]; then
      block="$(block_text "$target" "$matched_start")"
      number="$(block_field "$block" '- batchNumber:')"; [ -n "$number" ] || number=null
      batchname="$(block_field "$block" '  batch:')"; [ -n "$batchname" ] && batch="$batchname"
      base="$(block_field "$block" '  base:')"
      started="$(block_field "$block" '  started:')"
      legacy="$(block_field "$block" '  legacy:')"; [ -n "$legacy" ] || legacy=true
      new_block="$(render_block "$number" "$batch" "$branch" "$base" "$started" done "$legacy" "$finished" "$phases")"
      replace_block "$target" "$matched_start" "$new_block"
    else
      # No matching in-progress block (different branch last, malformed file, missing file, or an
      # init that never ran): append a new done entry — a stray extra entry beats one that
      # silently drops phases.
      number="$(parse_batch_number "$batch")"
      legacy=true; [ -n "$number" ] && legacy=false
      [ -n "$number" ] || number=null
      started=""
      [ -f "$report" ] && started="$(jq -r '.started // "" | .[0:10]' "$report" 2>/dev/null || true)"
      render_block "$number" "$batch" "$branch" "" "$started" done "$legacy" "$finished" "$phases" >>"$target"
    fi
    ;;

  reserve)
    repo="${2:?usage: cfq-changelog.sh reserve <repo-root> <batchNumber> <batch>}"
    number="${3:?usage: cfq-changelog.sh reserve <repo-root> <batchNumber> <batch>}"
    batch="${4:?usage: cfq-changelog.sh reserve <repo-root> <batchNumber> <batch>}"
    case "$number" in (*[!0-9]*|'') echo "cfq-changelog.sh reserve: batchNumber must be a positive integer, got '$number'" >&2; exit 1 ;; esac
    target="$(changelog_file "$repo")" || { echo "cfq-changelog.sh reserve: changelogFile is disabled, cannot reserve a numbered batch" >&2; exit 1; }
    mkdir -p "$(dirname "$target")"
    if [ -f "$target" ] && { grep -qxF -- "- batchNumber: $number" "$target" || grep -qxF -- "  batch: $batch" "$target"; }; then
      echo "cfq-changelog.sh reserve: duplicate batchNumber/batch identity: $number/$batch" >&2
      exit 1
    fi
    {
      printf -- '- batchNumber: %s\n' "$number"
      printf '  batch: %s\n' "$batch"
      printf '  status: parked\n'
    } >>"$target"
    ;;

  rename-batch)
    # Narrow width-migration helper: rewrites only the `batch:` field of the block currently
    # matching <old-batch>. A no-op (exit 0) when the changelog is disabled, missing, or no block
    # matches -- the caller (cfq-batch-id.sh migrate_width) re-derives its rewrite set from current
    # state, so an already-renamed entry harmlessly matching nothing here is expected, not an error.
    repo="${2:?usage: cfq-changelog.sh rename-batch <repo-root> <old-batch> <new-batch>}"
    old="${3:?usage: cfq-changelog.sh rename-batch <repo-root> <old-batch> <new-batch>}"
    new="${4:?usage: cfq-changelog.sh rename-batch <repo-root> <old-batch> <new-batch>}"
    target="$(changelog_file "$repo")" || exit 0
    [ -f "$target" ] || exit 0
    start="$(find_block_start "$target" '  batch:' "$old" || true)"
    [ -n "$start" ] || exit 0
    block="$(block_text "$target" "$start")"
    new_block="$(printf '%s\n' "$block" | sed "s|^  batch: .*|  batch: $new|")"
    replace_block "$target" "$start" "$new_block"
    ;;

  branch-for)
    # Read-only: the branch persisted for <batch> in the ledger (any status), empty on no match,
    # missing file or disabled changelog. Authoritative source for cfq-branch.sh's continue-mode
    # check — more precise than re-deriving a branch from a slug suffix match against Git.
    repo="${2:?usage: cfq-changelog.sh branch-for <repo-root> <batch>}"
    batch="${3:?usage: cfq-changelog.sh branch-for <repo-root> <batch>}"
    target="$(changelog_file "$repo")" || exit 0
    [ -f "$target" ] || exit 0
    start="$(find_block_start "$target" '  batch:' "$batch" || true)"
    [ -n "$start" ] || exit 0
    block="$(block_text "$target" "$start")"
    block_field "$block" '  branch:'
    ;;

  commit-message)
    # Appends the standard CFQ-* trailer block to a numbered batch's phase-commit message via
    # git interpret-trailers, so the trailers land in the same trailing block as any existing
    # trailer (e.g. Co-Authored-By) rather than a second machine section, and a stray mention of
    # "CFQ-Batch-Number" in prose can never be mistaken for a real trailer. Legacy (unnumbered)
    # batches pass the message through unchanged -- no number is ever invented for them.
    repo="${2:?usage: cfq-changelog.sh commit-message <repo-root> <batch> <phase> <status> <message-file>}"
    batch="${3:?usage: cfq-changelog.sh commit-message <repo-root> <batch> <phase> <status> <message-file>}"
    phase="${4:?usage: cfq-changelog.sh commit-message <repo-root> <batch> <phase> <status> <message-file>}"
    status="${5:?usage: cfq-changelog.sh commit-message <repo-root> <batch> <phase> <status> <message-file>}"
    message_file="${6:?usage: cfq-changelog.sh commit-message <repo-root> <batch> <phase> <status> <message-file>}"
    [ "$status" = green ] || { echo "cfq-changelog.sh commit-message: status must be 'green', got '$status'" >&2; exit 1; }
    number="$(parse_batch_number "$batch")"
    if [ -n "$number" ]; then
      git -C "$repo" interpret-trailers --trim-empty \
        --trailer "CFQ-Batch-Number=${number}" \
        --trailer "CFQ-Batch=${batch}" \
        --trailer "CFQ-Phase=${phase}" \
        --trailer "CFQ-Phase-Status=${status}" \
        "$message_file"
    else
      cat "$message_file"
    fi
    ;;

  ensure)
    repo="${2:?usage: cfq-changelog.sh ensure <repo-root>}"
    target="$(changelog_file "$repo")" || { jq -n '{source:"disabled",max:0,path:null}'; exit 0; }
    if [ -f "$target" ]; then
      jq -n --arg path "$target" '{source:"exists",max:null,path:$path}'
      exit 0
    fi
    mkdir -p "$(dirname "$target")"
    max=0 source=empty batchctx=""
    if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
      scanned="$(scan_trailer_max "$repo")"
      if [ -n "$scanned" ] && [ "$scanned" -gt 0 ] 2>/dev/null; then
        max="$scanned"
        source=git-trailer
        batchctx="$(scan_trailer_batch_for_max "$repo" "$max")"
      fi
    fi
    if [ "$source" = git-trailer ]; then
      {
        printf -- '- batchNumber: %s\n' "$max"
        [ -n "$batchctx" ] && printf '  batch: %s\n' "$batchctx"
        printf '  status: recovered\n'
      } >"$target"
    else
      : >"$target"
    fi
    jq -n --arg source "$source" --argjson max "$max" --arg path "$target" '{source:$source,max:$max,path:$path}'
    ;;

  migrate)
    repo="${2:?usage: cfq-changelog.sh migrate <repo-root>}"
    # Deliberately not resolved via changelogFile: this is the old, no-longer-configurable
    # root-level default (predates the .claude/cfq/ relocation), not a copy of the current schema
    # default — test-no-duplicate-defaults.sh's guard is about settings-read fallbacks, not this.
    old="$repo/cfq.changelog.yml"
    target="$(changelog_file "$repo")" || exit 0
    [ -f "$old" ] || exit 0
    mkdir -p "$(dirname "$target")"
    touch "$target"

    existing_batches="$(grep '^  batch: ' "$target" 2>/dev/null | sed 's/^  batch: *//' || true)"

    for start in $(grep -n '^- version:' "$old" 2>/dev/null | cut -d: -f1 || true); do
      next=$(awk -v s="$start" '/^- version:/ && NR>s {print NR; exit}' "$old")
      if [ -n "$next" ]; then block=$(sed -n "${start},$((next - 1))p" "$old"); else block=$(sed -n "${start},\$p" "$old"); fi

      obatch="$(printf '%s\n' "$block" | sed -n 's/^  batch: *//p' | head -1)"
      [ -n "$obatch" ] || continue
      printf '%s\n' "$existing_batches" | grep -qxF "$obatch" && continue

      obranch="$(printf '%s\n' "$block" | sed -n 's/^  branch: *//p' | head -1)"
      obase="$(printf '%s\n' "$block" | sed -n 's/^  base: *//p' | head -1)"
      ostarted="$(printf '%s\n' "$block" | sed -n 's/^  started: *//p' | head -1)"
      ofinished="$(printf '%s\n' "$block" | sed -n 's/^  finished: *//p' | head -1)"
      ostatus="$(printf '%s\n' "$block" | sed -n 's/^  status: *//p' | head -1)"
      ophases="$(printf '%s\n' "$block" | awk '/^  phases:/{f=1;next} f')"

      render_block null "$obatch" "$obranch" "$obase" "$ostarted" "${ostatus:-done}" true "$ofinished" "$ophases" >>"$target"
    done
    ;;

  max-batch-number)
    repo="${2:?usage: cfq-changelog.sh max-batch-number <repo-root>}"
    target="$(changelog_file "$repo")" || { echo 0; exit 0; }
    [ -f "$target" ] || { echo 0; exit 0; }
    awk '
      /^- batchNumber: / {
        v=$0; sub(/^- batchNumber: /,"",v)
        if (v ~ /^[0-9]+$/ && v+0>m) m=v+0
      }
      END { print m+0 }
    ' "$target"
    ;;

  *)
    echo "usage: cfq-changelog.sh init <repo-root> <branch> <base> <batch> | finish <repo-root> <branch> <batch-dir> | reserve <repo-root> <batchNumber> <batch> | rename-batch <repo-root> <old-batch> <new-batch> | branch-for <repo-root> <batch> | commit-message <repo-root> <batch> <phase> <status> <message-file> | ensure <repo-root> | migrate <repo-root> | max-batch-number <repo-root>" >&2
    exit 1
    ;;
esac
