#!/usr/bin/env bash
# Self-test for the render modes added in phase 03: scripts/cfq-dash.sh's `render` mode and
# scripts/cfq-report.sh's `index --text` mode. No framework — just `bash tests/test-render.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dash="$repo_root/scripts/cfq-dash.sh"
rep="$repo_root/scripts/cfq-report.sh"

# --- dash render: two repos, one with an open batch, one without -----------

tmp=$(mktemp -d)
home=$(mktemp -d)
mkdir -p "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done"
git -C "$tmp/repo-a" init -q
touch "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done/00-x.md"
mkdir -p "$tmp/repo-b/.claude/cfq"
git -C "$tmp/repo-b" init -q

json=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$dash" "$tmp")
text=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$dash" render "$tmp")

echo "$text" | grep -qF '| repo-a | 0 | 0 | 1/0 |' \
  || { echo "FAIL: repo-a row missing/wrong in QUEUES"; echo "$text"; exit 1; }
echo "$text" | grep -qF '| repo-b | 0 | 0 | 0/0 | OK |' \
  || { echo "FAIL: repo-b row missing/wrong in QUEUES"; echo "$text"; exit 1; }

# Equivalence: render and the JSON default agree on repo count for the same fixture.
[ "$(jq '.repos | length' <<<"$json")" = "2" ] || { echo "FAIL: JSON repos length"; exit 1; }
render_repo_lines=$(echo "$text" | grep -c '^| repo-')
[ "$render_repo_lines" = "2" ] || { echo "FAIL: render repo row count = $render_repo_lines"; exit 1; }
rm -rf "$tmp" "$home"

# --- dash render: empty registry -> plain sentence, no table ---------------

empty_home=$(mktemp -d); empty_root=$(mktemp -d)
empty_text=$(HOME="$empty_home" CFQ_SCAN_ROOTS="$empty_root" bash "$dash" render "$empty_root")
echo "$empty_text" | grep -qF "No repos with a queue yet." \
  || { echo "FAIL: empty registry sentence missing"; echo "$empty_text"; exit 1; }
if echo "$empty_text" | grep -qF '| Repo |'; then
  echo "FAIL: empty registry still rendered a table"; exit 1
fi
rm -rf "$empty_home" "$empty_root"

# --- dash render: MULTIPLE_IN_PROGRESS -> loud block, no row silently dropped

mip_tmp=$(mktemp -d); mip_home=$(mktemp -d)
mip_repo="$mip_tmp/repo-mip"
mkdir -p "$mip_repo/.claude/cfq/impl/2026-01-01-a/done" "$mip_repo/.claude/cfq/impl/2026-01-02-b/done"
git -C "$mip_repo" init -q
touch "$mip_repo/.claude/cfq/impl/2026-01-01-a/01-a.md" "$mip_repo/.claude/cfq/impl/2026-01-01-a/done/00-x.md"
touch "$mip_repo/.claude/cfq/impl/2026-01-02-b/01-a.md" "$mip_repo/.claude/cfq/impl/2026-01-02-b/done/00-x.md"
mip_text=$(HOME="$mip_home" CFQ_SCAN_ROOTS="$mip_tmp" bash "$dash" render "$mip_repo")
echo "$mip_text" | grep -qF 'MULTIPLE_IN_PROGRESS' \
  || { echo "FAIL: MULTIPLE_IN_PROGRESS not surfaced"; echo "$mip_text"; exit 1; }
echo "$mip_text" | grep -qF '2026-01-01-a' \
  || { echo "FAIL: batch a dropped from MULTIPLE_IN_PROGRESS render"; echo "$mip_text"; exit 1; }
echo "$mip_text" | grep -qF '2026-01-02-b' \
  || { echo "FAIL: batch b dropped from MULTIPLE_IN_PROGRESS render"; echo "$mip_text"; exit 1; }
rm -rf "$mip_tmp" "$mip_home"

# --- report index --text: a RED row, zero cost, equivalence with JSON ------

rep_tmp=$(mktemp -d); rep_home=$(mktemp -d)
rep_batch="$rep_tmp/repo-r/.claude/cfq/impl/2026-01-01-demo"
mkdir -p "$rep_batch"
git -C "$rep_tmp/repo-r" init -q
HOME="$rep_home" bash "$rep" append "$rep_batch" \
  '{"phase":"01-a","status":"red","finished":"2026-01-01T10:00:00+01:00","summary":"boom","deviations":[],"errors":["x"],"verification":"FAIL","commit":""}' >/dev/null

rep_json=$(HOME="$rep_home" CFQ_SCAN_ROOTS="$rep_tmp" bash "$rep" index)
rep_text=$(HOME="$rep_home" CFQ_SCAN_ROOTS="$rep_tmp" bash "$rep" index --text)

[ "$(jq 'length' <<<"$rep_json")" = "1" ] || { echo "FAIL: rep_json length"; exit 1; }
[ "$(jq -r '.[0].cost.outputTokens' <<<"$rep_json")" = "0" ] || { echo "FAIL: fixture cost not 0"; exit 1; }
echo "$rep_text" | grep -qF ' – |' || { echo "FAIL: zero cost did not render as –"; echo "$rep_text"; exit 1; }
if echo "$rep_text" | grep -qF '0k'; then
  echo "FAIL: zero cost rendered as 0k"; exit 1
fi
echo "$rep_text" | grep -qF '**RED**' || { echo "FAIL: RED row not visibly marked"; echo "$rep_text"; exit 1; }
echo "$rep_text" | grep -qF '2026-01-01-demo' || { echo "FAIL: batch missing from --text output"; exit 1; }
rm -rf "$rep_tmp" "$rep_home"

# --- report index --text: empty index -> plain sentence, not an empty table

empty_rep_home=$(mktemp -d); empty_rep_root=$(mktemp -d)
empty_rep_text=$(HOME="$empty_rep_home" CFQ_SCAN_ROOTS="$empty_rep_root" bash "$rep" index --text)
echo "$empty_rep_text" | grep -qF "v0.2" \
  || { echo "FAIL: empty index sentence missing"; echo "$empty_rep_text"; exit 1; }
rm -rf "$empty_rep_home" "$empty_rep_root"

# --- no HTML entity anywhere in any rendered terminal output ----------------

all_output="$text
$empty_text
$mip_text
$rep_text
$empty_rep_text"
if grep -qE '&nbsp;|&amp;|&#' <<<"$all_output"; then
  echo "FAIL: HTML entity found in rendered terminal output"; exit 1
fi

echo PASS
