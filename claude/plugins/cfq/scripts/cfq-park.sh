#!/usr/bin/env bash
# Parks a batch directory: creates it, writes .priority/.dependsOn, ensures the local git-exclude
# entry, and registers the repo. Idempotent — safe to re-run with the same arguments. Does not
# write phase files; only the planning session that knows their content does that.
# Usage: cfq-park.sh <repo-root> <batch-dir-name> <high|normal> [<dependsOn-entry>...]
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-park.sh: jq is required" >&2; exit 1; }

repo_root="${1:?usage: cfq-park.sh <repo-root> <batch-dir-name> <high|normal> [<dependsOn-entry>...]}"
batch_name="${2:?usage: cfq-park.sh <repo-root> <batch-dir-name> <high|normal> [<dependsOn-entry>...]}"
priority="${3:?usage: cfq-park.sh <repo-root> <batch-dir-name> <high|normal> [<dependsOn-entry>...]}"
shift 3
depends=("$@")

case "$priority" in
  high|normal) : ;;
  *) echo "cfq-park.sh: priority must be high|normal, got '$priority'" >&2; exit 1 ;;
esac

dir="$repo_root/.claude/code-for-queue/impl/$batch_name"
mkdir -p "$dir"
# .planning is written on creation, idempotent (a re-run during the same pfq session refreshes
# the timestamp as a heartbeat), and removed by plan-for-queue's lint step once the batch is
# complete — this is what keeps ifq from picking up a batch pfq is still writing.
date -Iseconds > "$dir/.planning"

case "$priority" in
  high)   printf 'high\n' > "$dir/.priority" ;;
  normal) rm -f "$dir/.priority" ;;
esac

if [ "${#depends[@]}" -gt 0 ]; then
  printf '%s\n' "${depends[@]}" > "$dir/.dependsOn"
fi

if ! git -C "$repo_root" check-ignore -q .claude/code-for-queue/ 2>/dev/null; then
  exclude="$repo_root/.git/info/exclude"
  mkdir -p "$(dirname "$exclude")"
  grep -qxF '**/.claude/code-for-queue/' "$exclude" 2>/dev/null || \
    printf '**/.claude/code-for-queue/\n' >> "$exclude"
fi

"$(dirname "${BASH_SOURCE[0]}")/cfq-registry.sh" add "$repo_root" >/dev/null

printf '%s\n' "$dir"
