#!/usr/bin/env bash
# Computes the branch/batch-identity decision for a batch go-ahead as one JSON object. Read-only —
# never creates or checks out a branch itself; the caller acts on `mode`. New branches use the
# batch's own stable directory name directly (`cfq/<batch-directory-name>`) — no version scanning,
# no pseudo-version increment, no identity derived from Git branch history.
# Usage: cfq-branch.sh plan <repo-root> <batch-dir-name>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-branch.sh: jq is required" >&2; exit 1; }

cmd="${1:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
repo_root="${2:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
batch_name="${3:?usage: cfq-branch.sh plan <repo-root> <batch-dir-name>}"
[ "$cmd" = "plan" ] || { echo "cfq-branch.sh: unknown command '$cmd'" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# New-format batch directory names are <digits>-<YYYY-MM-DD>-<slug> (the number precedes the
# date); legacy names start directly with the date. Prints the plain integer (no leading zeros) on
# a match, nothing on no match — mirrors cfq-changelog.sh's own parse_batch_number.
parse_batch_number() {
  if [[ "$1" =~ ^([0-9]+)-[0-9]{4}-[0-9]{2}-[0-9]{2}- ]]; then
    printf '%d\n' "$((10#${BASH_REMATCH[1]}))"
  fi
}
number="$(parse_batch_number "$batch_name")"
number_json='null'; [ -n "$number" ] && number_json="$number"

slug=$(printf '%s' "$batch_name" | sed -E 's/^[0-9]+-[0-9]{4}-[0-9]{2}-[0-9]{2}-//; s/^[0-9]{4}-[0-9]{2}-[0-9]{2}-//')

branch_per_batch=$("$script_dir/cfq-settings.sh" get branchPerBatch)
if [ "$branch_per_batch" = "false" ]; then
  jq -n --arg batch "$batch_name" --argjson num "$number_json" \
    '{mode: "off", batch: $batch, batchNumber: $num, branch: null, base: null, candidates: []}'
  exit 0
fi

# Prefer the branch already persisted in the CFQ changelog for this exact batch — authoritative,
# since it is the branch that was actually checked out at init time — but only once it's confirmed
# to still exist; a deleted branch falls through to the suffix match below rather than being
# handed to the caller as an unresolvable "continue". Also falls through when the changelog
# doesn't know this batch yet, e.g. a batch parked before the changelog existed.
existing="$("$script_dir/cfq-changelog.sh" branch-for "$repo_root" "$batch_name" 2>/dev/null || true)"
if [ -n "$existing" ] && ! git -C "$repo_root" rev-parse --verify -q "refs/heads/$existing" >/dev/null 2>&1 \
  && ! git -C "$repo_root" rev-parse --verify -q "refs/remotes/origin/$existing" >/dev/null 2>&1; then
  existing=""
fi
if [ -z "$existing" ]; then
  existing=$(git -C "$repo_root" branch -a --format='%(refname:short)' | sed 's#^origin/##' | sort -u \
    | grep -E -- "-${slug}\$" || true)
  existing=$(printf '%s\n' "$existing" | head -1)
fi

if [ -n "$existing" ]; then
  jq -n --arg batch "$batch_name" --argjson num "$number_json" --arg branch "$existing" \
    '{mode: "continue", batch: $batch, batchNumber: $num, branch: $branch, base: null, candidates: []}'
  exit 0
fi

branch="cfq/${batch_name}"

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

jq -n --arg batch "$batch_name" --argjson num "$number_json" --arg branch "$branch" \
  --argjson base "$base_json" --argjson candidates "$cand_json" \
  '{mode: "new", batch: $batch, batchNumber: $num, branch: $branch, base: $base, candidates: $candidates}'
