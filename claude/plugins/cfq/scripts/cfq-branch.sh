#!/usr/bin/env bash
# Computes the branch/version/base decision for a batch go-ahead as one JSON object. Read-only —
# never creates or checks out a branch itself; the caller acts on `mode`.
# Usage: cfq-branch.sh plan <repo-root> <batch-dir-name>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-branch.sh: jq is required" >&2; exit 1; }

cmd="${1:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
repo_root="${2:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
batch_name="${3:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
[ "$cmd" = "plan" ] || { echo "cfq-branch.sh: unknown command '$cmd'" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
slug=$(printf '%s' "$batch_name" | sed -E 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}-//')

branch_per_batch=$("$script_dir/cfq-settings.sh" get branchPerBatch)
if [ "$branch_per_batch" = "false" ]; then
  jq -n --arg slug "$slug" \
    '{mode: "off", slug: $slug, branch: null, version: null, base: null, candidates: []}'
  exit 0
fi

existing=$(git -C "$repo_root" branch -a --format='%(refname:short)' | sed 's#^origin/##' | sort -u \
  | grep -E -- "-${slug}\$" || true)
if [ -n "$existing" ]; then
  branch=$(printf '%s\n' "$existing" | head -1)
  jq -n --arg slug "$slug" --arg branch "$branch" \
    '{mode: "continue", slug: $slug, branch: $branch, version: null, base: null, candidates: []}'
  exit 0
fi

last=$(git -C "$repo_root" branch -a | grep -oE 'v[0-9]+\.[0-9]+' | sort -t. -k1,1V -k2,2n | tail -1)
if [ -z "$last" ]; then
  version="v0.1"
else
  version="${last%.*}.$(( ${last#*.} + 1 ))"
fi
branch="${version}-${slug}"

candidates=()
while IFS= read -r b; do
  [ -n "$b" ] && [ "$b" != main ] || continue
  cnt=$(git -C "$repo_root" rev-list --count main.."$b")
  [ "$cnt" -gt 0 ] && candidates+=("$b")
done < <(git -C "$repo_root" branch --format='%(refname:short)')

if [ "${#candidates[@]}" -eq 0 ]; then
  base_json='"main"'
else
  base_json='null'
fi
cand_json=$(printf '%s\n' "${candidates[@]:-}" | sed '/^$/d' | jq -R . | jq -s .)

jq -n --arg slug "$slug" --arg branch "$branch" --arg version "$version" \
  --argjson base "$base_json" --argjson candidates "$cand_json" \
  '{mode: "new", slug: $slug, branch: $branch, version: $version, base: $base, candidates: $candidates}'
