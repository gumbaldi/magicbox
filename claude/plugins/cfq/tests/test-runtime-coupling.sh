#!/usr/bin/env bash
# Regression guard: the cross-skill-preflight batch's own new/modified scripts must never read
# Claude-Code-runtime state directly — everything Claude-Code-specific goes through
# cfq-runtime.sh. Scoped to this batch's own files only, not the whole codebase.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# cfq-runtime.sh itself is the one allowed adapter and is deliberately excluded here.
files=(
  "$repo_root/scripts/cfq-pfq-preflight.sh"
  "$repo_root/scripts/cfq-ifq-preflight.sh"
  "$repo_root/scripts/cfq-report.sh"
  "$repo_root/scripts/cfq-scan.sh"
)

forbidden='CLAUDE_CODE_SESSION_ID|\.claude/\.ctx|\.claude/projects'

fail=0
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  hits=$(grep -nE "$forbidden" "$f" || true)
  if [ -n "$hits" ]; then
    echo "FAIL: runtime-coupling literal found in $f:" >&2
    echo "$hits" >&2
    fail=1
  fi
done

[ "$fail" = "0" ] || exit 1
echo PASS
