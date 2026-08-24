#!/usr/bin/env bash
set -eu
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
resume="$repo_root/scripts/cfq-resume.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git -C "$tmp" init -q -b main 2>/dev/null || (mkdir -p "$tmp" && git -C "$tmp" init -q -b main)
git -C "$tmp" -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m init

# Fresh batch: no report.json, no .batch-context.md, one open phase, branch doesn't exist yet.
batch="$tmp/.claude/cfq/impl/2026-01-01-fresh"
mkdir -p "$batch"
printf '# T\n\n## Size\n\nM\n' >"$batch/01-a.md"
out=$(bash "$resume" "$tmp" "$batch")
[ "$(jq -c '.phasesDone' <<<"$out")" = '[]' ] || { echo "FAIL: fresh phasesDone"; exit 1; }
[ "$(jq -r '.lastCommit' <<<"$out")" = "null" ] || { echo "FAIL: fresh lastCommit"; exit 1; }
[ "$(jq -r '.batchContext.exists' <<<"$out")" = "false" ] || { echo "FAIL: fresh batchContext"; exit 1; }
[ "$(jq -r '.branch.mode' <<<"$out")" = "new" ] || { echo "FAIL: fresh branch mode"; exit 1; }
[ "$(jq -r '.phasesOpen[0].size' <<<"$out")" = "M" ] || { echo "FAIL: fresh phase size"; exit 1; }

# Mid-flight batch: 01-a done with a green report entry carrying a commit, 02-b open with a red
# entry, a .batch-context.md present, a missing-Size open phase.
batch2="$tmp/.claude/cfq/impl/2026-01-02-midflight"
mkdir -p "$batch2/done"
mv "$batch/01-a.md" "$batch2/done/01-a.md" 2>/dev/null || cp "$batch/01-a.md" "$batch2/done/01-a.md"
printf '# T2\n' >"$batch2/02-b.md"
printf '# Batch Context\n\n## Goal\nx\n' >"$batch2/.batch-context.md"
git -C "$tmp" checkout -qb v0.1-midflight
git -C "$tmp" -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m "phase 1"
sha=$(git -C "$tmp" rev-parse HEAD)
cat >"$batch2/report.json" <<EOF
{"repo":"$tmp","batch":"2026-01-02-midflight","started":"2026-01-01T00:00:00+00:00","phases":[
  {"phase":"01-a","status":"green","finished":"2026-01-01T01:00:00+00:00","summary":"ok","deviations":["did X instead of Y"],"errors":[],"verification":"ok","commit":"$sha"},
  {"phase":"02-b","status":"red","finished":"2026-01-01T02:00:00+00:00","summary":"failed","deviations":[],"errors":["boom"],"verification":"fail","commit":""}
]}
EOF
out=$(bash "$resume" "$tmp" "$batch2")
[ "$(jq -r '.lastCommit' <<<"$out")" = "$sha" ] || { echo "FAIL: midflight lastCommit"; exit 1; }
[ "$(jq -r '.lastCommitSource' <<<"$out")" = "report" ] || { echo "FAIL: midflight source"; exit 1; }
[ "$(jq -c '.phasesDone[0]' <<<"$out")" = "{\"num\":\"01\",\"slug\":\"01-a\",\"commit\":\"$sha\"}" ] \
  || { echo "FAIL: midflight phasesDone"; exit 1; }
[ "$(jq -c '.deviations' <<<"$out")" = '[{"phase":"01-a","text":"did X instead of Y"}]' ] \
  || { echo "FAIL: midflight deviations"; exit 1; }
[ "$(jq -c '.redPhases' <<<"$out")" = '["02-b"]' ] || { echo "FAIL: midflight redPhases"; exit 1; }
[ "$(jq -r '.phasesOpen[0].size' <<<"$out")" = "M" ] || { echo "FAIL: midflight missing-size default"; exit 1; }
[ "$(jq -r '.batchContext.exists' <<<"$out")" = "true" ] || { echo "FAIL: midflight batchContext"; exit 1; }
[ "$(jq -r '.batchContext.path' <<<"$out")" = "$batch2/.batch-context.md" ] \
  || { echo "FAIL: midflight batchContext path"; exit 1; }

# Old-style green entry with an empty commit -> falls back to the branch tip.
batch3="$tmp/.claude/cfq/impl/2026-01-03-legacycommit"
mkdir -p "$batch3/done"
printf '# T3\n' >"$batch3/done/01-a.md"
git -C "$tmp" checkout -qb v0.1-legacycommit main
git -C "$tmp" -c user.email=t@example.com -c user.name=t commit -q --allow-empty -m "legacy phase"
tip=$(git -C "$tmp" rev-parse HEAD)
printf '{"repo":"%s","batch":"2026-01-03-legacycommit","started":"t","phases":[{"phase":"01-a","status":"green","finished":"t","summary":"ok","deviations":[],"errors":[],"verification":"ok","commit":""}]}' \
  "$tmp" >"$batch3/report.json"
out=$(bash "$resume" "$tmp" "$batch3")
[ "$(jq -r '.lastCommit' <<<"$out")" = "$tip" ] || { echo "FAIL: legacy lastCommit"; exit 1; }
[ "$(jq -r '.lastCommitSource' <<<"$out")" = "branch-tip" ] || { echo "FAIL: legacy source"; exit 1; }

echo PASS
