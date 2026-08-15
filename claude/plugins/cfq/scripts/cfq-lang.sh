#!/usr/bin/env bash
# Language/doc-tree drift reporter for a target repo. Never writes, never fails: always prints one
# JSON object on stdout and exits 0 — the caller (a skill) decides what the numbers mean.
# Usage: cfq-lang.sh <repo-root> [--changed <ref>]
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-lang.sh: jq is required" >&2; exit 1; }

repo="${1:?usage: cfq-lang.sh <repo-root> [--changed <ref>]}"
shift || true
changed_ref=""
if [ "${1:-}" = "--changed" ]; then
  changed_ref="${2:?usage: cfq-lang.sh <repo-root> [--changed <ref>]}"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
settings_sh="$script_dir/cfq-settings.sh"

# Settings always via cfq-settings.sh, never from the environment directly — that's the only
# place the env > file > default precedence chain is implemented.
code_language=$("$settings_sh" get codeLanguage 2>/dev/null || echo en)
doc_languages_csv=$("$settings_sh" get docLanguages 2>/dev/null || true)
doc_level=$("$settings_sh" get docLevel 2>/dev/null || echo minimal)

if [ -z "$doc_languages_csv" ]; then
  doc_languages_json='[]'
else
  doc_languages_json=$(jq -Rc 'split(",")' <<<"$doc_languages_csv")
fi

scope="repo"
note=""
changed_set=""

if [ -n "$changed_ref" ]; then
  if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 \
     && git -C "$repo" rev-parse --verify "$changed_ref" >/dev/null 2>&1; then
    changed_set=$(git -C "$repo" diff --name-only "$changed_ref"...HEAD -- . 2>/dev/null || true)
    scope="changed"
  else
    note="no git repo or unknown ref '$changed_ref', falling back to repo scope"
  fi
fi

# Restricts a newline list of repo-relative paths to the changed set when scoped; passthrough
# otherwise.
scoped() {
  if [ "$scope" != "changed" ]; then
    cat
  else
    comm -12 <(sort -u) <(printf '%s\n' "$changed_set" | sort -u)
  fi
}

to_json_arr() {
  jq -R -s 'split("\n") | map(select(length > 0))'
}

missing_list=""
stray_list=""
unfiled_list=""

docs_dir="$repo/docs"

if [ "$doc_level" = "minimal" ] && [ ! -d "$docs_dir" ]; then
  note="docLevel=minimal, no docs tree expected"
elif [ -d "$docs_dir" ]; then
  all_md=$(cd "$repo" && find docs -type f -name '*.md' | sed 's#^\./##' | sort)

  unfiled_list=$( (printf '%s\n' "$all_md" | grep -E '^docs/[^/]+\.md$' || true) | scoped)

  code_files=$( (printf '%s\n' "$all_md" | grep -E "^docs/$code_language/" || true) | scoped)
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel="${f#docs/"$code_language"/}"
    for lang in $(jq -r '.[]' <<<"$doc_languages_json"); do
      counterpart="docs/$lang/$rel"
      [ -f "$repo/$counterpart" ] || missing_list="$missing_list
$counterpart"
    done
  done <<<"$code_files"

  for lang in $(jq -r '.[]' <<<"$doc_languages_json"); do
    lang_files=$( (printf '%s\n' "$all_md" | grep -E "^docs/$lang/" || true) | scoped)
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      rel="${f#docs/"$lang"/}"
      original="docs/$code_language/$rel"
      [ -f "$repo/$original" ] || stray_list="$stray_list
$f"
    done <<<"$lang_files"
  done
fi

missing_arr=$(to_json_arr <<<"$missing_list")
stray_arr=$(to_json_arr <<<"$stray_list")
unfiled_arr=$(to_json_arr <<<"$unfiled_list")

jq -n \
  --arg codeLanguage "$code_language" \
  --argjson docLanguages "$doc_languages_json" \
  --arg docLevel "$doc_level" \
  --arg scope "$scope" \
  --argjson missing "$missing_arr" \
  --argjson stray "$stray_arr" \
  --argjson unfiled "$unfiled_arr" \
  --arg note "$note" \
  '{codeLanguage: $codeLanguage, docLanguages: $docLanguages, docLevel: $docLevel, scope: $scope,
    missing: $missing, stray: $stray, unfiled: $unfiled, note: $note}'
