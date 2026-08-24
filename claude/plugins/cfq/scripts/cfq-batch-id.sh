#!/usr/bin/env bash
# Repository-local CFQ batch-number allocation: a stable, version-free identity assigned once at
# PFQ park time. Never derives a number from a Git branch name or an application/package version;
# the only Git-history fallback is Phase 1's one-time trailer bootstrap inside cfq-changelog.sh
# ensure, for a ledger that does not exist yet. Width is an implementation invariant (see
# BATCH_WIDTH_MIGRATION_REQUIRED below), not a user-facing setting.
# Usage: cfq-batch-id.sh next     <repo-root> <YYYY-MM-DD> <slug>
#        cfq-batch-id.sh allocate <repo-root> <YYYY-MM-DD> <slug>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-batch-id.sh: jq is required" >&2; exit 1; }

here="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=cfq-paths.sh
. "$here/cfq-paths.sh"

# New-name grammar: <digits>-<YYYY-MM-DD>-<slug>, digits precede the date. A legacy
# <YYYY-MM-DD>-<slug> name never satisfies this (its own date would have to double as the digit
# run AND be immediately followed by another full date), so legacy directories are ignored, not
# specially cased.
NUMBERED_RE='^([0-9]{3,})-([0-9]{4}-[0-9]{2}-[0-9]{2})-([a-z0-9][a-z0-9-]*)$'
DEFAULT_WIDTH=3

err() { # status detail action
  jq -n --arg s "$1" --arg d "$2" --arg a "${3:-}" '{status:$s, detail:$d, action:$a}'
}

# Prints the digit-run width of a numbered identifier, nothing on no match. Never partially
# parses: a name either satisfies the full grammar or is ignored outright.
numbered_width() {
  [[ "$1" =~ $NUMBERED_RE ]] || return 1
  printf '%s\n' "${#BASH_REMATCH[1]}"
}

numbered_number() {
  [[ "$1" =~ $NUMBERED_RE ]] || return 1
  printf '%d\n' "$((10#${BASH_REMATCH[1]}))"
}

# Widths seen among existing numbered queue directories and changelog `batch:` entries, one per
# line, deduplicated by the caller. More than one distinct width is an unresolvable conflict.
observed_widths() {
  local repo="$1" d p name w target
  d="$(impl_dir "$repo")"
  if [ -d "$d" ]; then
    for p in "$d"/*/; do
      [ -d "$p" ] || continue
      name="$(basename "$p")"
      [ "$name" = "done" ] && continue
      if w="$(numbered_width "$name")"; then printf '%s\n' "$w"; fi
    done
  fi
  target="$(changelog_path "$repo" 2>/dev/null || true)"
  if [ -n "$target" ] && [ -f "$target" ]; then
    while IFS= read -r name; do
      if w="$(numbered_width "$name")"; then printf '%s\n' "$w"; fi
    done < <(grep '^  batch: ' "$target" | sed 's/^  batch: *//')
  fi
}

# Highest number among numbered queue directories only (never legacy ones), 0 if none.
queue_max() {
  local repo="$1" d p name n max=0
  d="$(impl_dir "$repo")"
  if [ -d "$d" ]; then
    for p in "$d"/*/; do
      [ -d "$p" ] || continue
      name="$(basename "$p")"
      [ "$name" = "done" ] && continue
      if n="$(numbered_number "$name")" && [ "$n" -gt "$max" ]; then max="$n"; fi
    done
  fi
  printf '%s\n' "$max"
}

changelog_path() {
  local repo="$1" rel
  rel="$("$here/cfq-settings.sh" get changelogFile)"
  [ -n "$rel" ] || return 1
  printf '%s/%s\n' "$repo" "$rel"
}

# Computes the next identity. Prints the full {status, ...} result and returns 0 for OK, 1 for any
# structured non-OK status (BATCH_CHANGELOG_REQUIRED / BATCH_LEDGER_MISMATCH /
# BATCH_WIDTH_MIGRATION_REQUIRED). Read-only except for cfq-changelog.sh's own one-time missing-
# ledger bootstrap, which must run before any number can be computed at all.
compute_next() {
  local repo="$1" date="$2" slug="$3" cf changelog_max qmax widths n_widths width next digits formatted

  cf="$("$here/cfq-settings.sh" get changelogFile)"
  if [ -z "$cf" ]; then
    err BATCH_CHANGELOG_REQUIRED "changelogFile is disabled; numbered batch identity needs the CFQ workflow changelog" "set changelogFile before allocating a numbered batch"
    return 1
  fi

  "$here/cfq-changelog.sh" ensure "$repo" >/dev/null
  changelog_max="$("$here/cfq-changelog.sh" max-batch-number "$repo")"
  qmax="$(queue_max "$repo")"

  if [ "$qmax" -gt "$changelog_max" ]; then
    err BATCH_LEDGER_MISMATCH "queue directory number $qmax exceeds changelog max $changelog_max" "reconcile .claude/cfq/impl/ against .claude/cfq/changelog.yml before allocating"
    return 1
  fi

  widths="$(observed_widths "$repo" | sort -u)"
  n_widths="$(printf '%s\n' "$widths" | grep -c . || true)"
  if [ "$n_widths" -gt 1 ]; then
    err BATCH_LEDGER_MISMATCH "numbered batch identifiers disagree on width: $(printf '%s' "$widths" | tr '\n' ' ')" "run the width migration before allocating"
    return 1
  fi
  width="$widths"
  [ -n "$width" ] || width="$DEFAULT_WIDTH"

  next=$((changelog_max + 1))
  digits=${#next}
  if [ "$digits" -gt "$width" ]; then
    err BATCH_WIDTH_MIGRATION_REQUIRED "next batch number $next needs $digits digits, current width is $width" "run the width migration first, then allocate again"
    return 1
  fi

  formatted="$(printf "%0${width}d" "$next")"
  jq -n --argjson n "$next" --argjson w "$width" --arg f "$formatted" --arg date "$date" --arg slug "$slug" \
    '{status:"OK", batchNumber:$n, width:$w, formatted:$f, date:$date, slug:$slug, batch: ($f + "-" + $date + "-" + $slug)}'
}

validate_args() {
  local date="$1" slug="$2"
  if [[ ! "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    err INVALID_ARGUMENT "date must be YYYY-MM-DD, got '$date'" ""
    return 1
  fi
  if [[ ! "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    err INVALID_ARGUMENT "slug must match [a-z0-9][a-z0-9-]*, got '$slug'" ""
    return 1
  fi
}

# mkdir-based mutex, same staleness spirit as cfq-lock.sh: a lock older than lock_stale_s is
# presumed abandoned (crashed holder) and reclaimed rather than waited on forever. Allocation is
# fast, so a short stale window is enough — this is not a long-lived session lock.
lock_stale_s=10
alloc_lockdir() { printf '%s/.batch-id.lock' "$(cfq_repo_dir "$1")"; }

acquire_alloc_lock() {
  local repo="$1" lockdir age tries=0
  lockdir="$(alloc_lockdir "$repo")"
  mkdir -p "$(dirname "$lockdir")"
  while ! mkdir "$lockdir" 2>/dev/null; do
    age=$(( $(date +%s) - $(stat -c %Y "$lockdir" 2>/dev/null || echo 0) ))
    if [ "$age" -gt "$lock_stale_s" ]; then
      rmdir "$lockdir" 2>/dev/null || true
      continue
    fi
    tries=$((tries + 1))
    [ "$tries" -le 200 ] || return 1
    sleep 0.05
  done
}

release_alloc_lock() { rmdir "$(alloc_lockdir "$1")" 2>/dev/null || true; }

cmd="${1:-}"
case "$cmd" in
  next)
    repo="${2:?usage: cfq-batch-id.sh next <repo-root> <YYYY-MM-DD> <slug>}"
    date="${3:?usage: cfq-batch-id.sh next <repo-root> <YYYY-MM-DD> <slug>}"
    slug="${4:?usage: cfq-batch-id.sh next <repo-root> <YYYY-MM-DD> <slug>}"
    validate_args "$date" "$slug"
    compute_next "$repo" "$date" "$slug"
    ;;

  allocate)
    repo="${2:?usage: cfq-batch-id.sh allocate <repo-root> <YYYY-MM-DD> <slug>}"
    date="${3:?usage: cfq-batch-id.sh allocate <repo-root> <YYYY-MM-DD> <slug>}"
    slug="${4:?usage: cfq-batch-id.sh allocate <repo-root> <YYYY-MM-DD> <slug>}"
    validate_args "$date" "$slug"

    "$here/cfq-layout.sh" ensure "$repo" >/dev/null

    if ! acquire_alloc_lock "$repo"; then
      err INTERNAL_ERROR "could not acquire the allocation lock" "retry once the concurrent allocation finishes"
      exit 1
    fi
    trap 'release_alloc_lock "'"$repo"'"' EXIT

    if ! result="$(compute_next "$repo" "$date" "$slug")"; then
      printf '%s\n' "$result"
      exit 1
    fi

    number="$(jq -r .batchNumber <<<"$result")"
    batch="$(jq -r .batch <<<"$result")"

    if ! reserve_out="$("$here/cfq-changelog.sh" reserve "$repo" "$number" "$batch" 2>&1)"; then
      err BATCH_ID_CONFLICT "changelog reservation for $batch failed: $reserve_out" "retry; the failed number stays consumed and is never reused"
      exit 1
    fi

    target_dir="$(impl_dir "$repo")/$batch"
    if ! mkdir "$target_dir" 2>/dev/null; then
      err INTERNAL_ERROR "changelog reserved $batch but the queue directory could not be created; the number stays consumed" "inspect $target_dir and .claude/cfq/changelog.yml manually, then park under a new slug/date"
      exit 1
    fi

    printf '%s\n' "$result"
    ;;

  *)
    echo "usage: cfq-batch-id.sh next <repo-root> <YYYY-MM-DD> <slug> | allocate <repo-root> <YYYY-MM-DD> <slug>" >&2
    exit 1
    ;;
esac
