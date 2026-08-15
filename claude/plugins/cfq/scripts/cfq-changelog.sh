#!/usr/bin/env bash
# Appends/completes entries in <repo-root>/<changelogFile>, one block per batch. No YAML parser
# (yq is not installed) — produced with printf/jq -r, parsed back with grep/sed on fixed prefixes.
# Usage: cfq-changelog.sh init   <repo-root> <version> <branch> <base> <batch>
#        cfq-changelog.sh finish <repo-root> <branch> <batch-dir>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-changelog.sh: jq is required" >&2; exit 1; }

here="$(dirname "${BASH_SOURCE[0]}")"

changelog_file() {
  local repo="$1" rel
  rel="$("$here/cfq-settings.sh" get changelogFile)"
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

cmd="${1:-}"
case "$cmd" in
  init)
    repo="${2:?usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch>}"
    version="${3:?usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch>}"
    branch="${4:?usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch>}"
    base="${5:?usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch>}"
    batch="${6:?usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch>}"
    target="$(changelog_file "$repo")" || exit 0
    {
      printf -- '- version: %s\n' "$version"
      printf '  branch: %s\n' "$branch"
      printf '  base: %s\n' "$base"
      printf '  batch: %s\n' "$batch"
      printf '  started: %s\n' "$(date -I)"
      printf '  status: in-progress\n'
    } >>"$target"
    ;;

  finish)
    repo="${2:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    branch="${3:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    batch_dir="${4:?usage: cfq-changelog.sh finish <repo-root> <branch> <batch-dir>}"
    target="$(changelog_file "$repo")" || exit 0
    batch="$(basename "$batch_dir")"
    report="$batch_dir/report.json"
    finished="$(date -I)"
    phases="$(phases_yaml "$report")"

    version="" base="" started=""
    [ -f "$report" ] && started="$(jq -r '.started // "" | .[0:10]' "$report" 2>/dev/null || true)"
    matched=0

    if [ -f "$target" ]; then
      # ponytail: assumes the in-progress block for a branch is always the file's last one — true
      # today because the repo lock allows exactly one running ifq session. Upgrade to a real YAML
      # parser if concurrent batches per repo ever become possible.
      lastline="$(grep -n '^- version:' "$target" | tail -1 | cut -d: -f1 || true)"
      if [ -n "${lastline:-}" ]; then
        block="$(tail -n "+$lastline" "$target")"
        blockbranch="$(printf '%s\n' "$block" | sed -n 's/^  branch: *//p' | head -1)"
        if [ "$blockbranch" = "$branch" ]; then
          version="$(printf '%s\n' "$block" | sed -n 's/^- version: *//p' | head -1)"
          base="$(printf '%s\n' "$block" | sed -n 's/^  base: *//p' | head -1)"
          started="$(printf '%s\n' "$block" | sed -n 's/^  started: *//p' | head -1)"
          head -n "$((lastline - 1))" "$target" >"$target.tmp"
          mv "$target.tmp" "$target"
          matched=1
        fi
      fi
    fi
    # No match (different branch last, malformed file, or missing file): fall through and append
    # a new entry instead — a changelog with a stray entry beats one that silently drops phases.
    [ "$matched" = 1 ] || : >>"$target"

    {
      printf -- '- version: %s\n' "$version"
      printf '  branch: %s\n' "$branch"
      printf '  base: %s\n' "$base"
      printf '  batch: %s\n' "$batch"
      printf '  started: %s\n' "$started"
      printf '  finished: %s\n' "$finished"
      printf '  status: done\n'
      if [ -n "$phases" ]; then
        printf '  phases:\n'
        printf '%s\n' "$phases"
      fi
    } >>"$target"
    ;;

  *)
    echo "usage: cfq-changelog.sh init <repo-root> <version> <branch> <base> <batch> | finish <repo-root> <branch> <batch-dir>" >&2
    exit 1
    ;;
esac
