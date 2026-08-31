#!/usr/bin/env bash
# Self-test for scripts/cfq-scan.sh. No framework, no fixtures — just `bash tests/test-scan.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scan="$repo_root/scripts/cfq-scan.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# repo-a: one open batch, 2 open phases + 1 done phase, priority high
mkdir -p "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done"
echo high >"$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/.priority"
touch "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/01-a.md" \
      "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/02-b.md" \
      "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/done/00-x.md"
# a stray dotfile in the batch root must never be counted as an open phase (regression test)
touch "$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/.batch-context.md"

# repo-b: one batch fully moved to done/ (archived), no .priority
mkdir -p "$tmp/repo-b/.claude/cfq/impl/done/2026-01-02-demo"
touch "$tmp/repo-b/.claude/cfq/impl/done/2026-01-02-demo/01-a.md" \
      "$tmp/repo-b/.claude/cfq/impl/done/2026-01-02-demo/02-b.md"
touch "$tmp/repo-b/.claude/cfq/impl/done/2026-01-02-demo/.batch-context.md"

# repo-c: no .claude/cfq/impl/ at all — must not show up
mkdir -p "$tmp/repo-c"

# repo-a has a report.json — must not affect phase counts, only the report flag
echo '{"repo":"x","batch":"2026-01-01-demo","started":"t","phases":[]}' \
  >"$tmp/repo-a/.claude/cfq/impl/2026-01-01-demo/report.json"

# repo-e: dependsOn fixtures — target-open (still open) and target-done (archived) are the
# dependency targets; b-blocked/b-free/b-unknown are the batches exercising each outcome.
mkdir -p "$tmp/repo-e/.claude/cfq/impl/2026-01-10-target-open" \
         "$tmp/repo-e/.claude/cfq/impl/done/2026-01-10-target-done" \
         "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-blocked" \
         "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-free" \
         "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-unknown"
touch "$tmp/repo-e/.claude/cfq/impl/2026-01-10-target-open/01-a.md" \
      "$tmp/repo-e/.claude/cfq/impl/done/2026-01-10-target-done/01-a.md" \
      "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-blocked/01-a.md" \
      "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-free/01-a.md" \
      "$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-unknown/01-a.md"
echo 2026-01-10-target-open   >"$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-blocked/.dependsOn"
echo 2026-01-10-target-done   >"$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-free/.dependsOn"
echo gibtsnicht     >"$tmp/repo-e/.claude/cfq/impl/2026-01-10-b-unknown/.dependsOn"

# repo-f: no impl/ batches at all, only plan/ and todo/ orders — plan and todo must count only
# the open entries (2 and 1), never the ones already moved to their done/
mkdir -p "$tmp/repo-f/.claude/cfq/plan/done" "$tmp/repo-f/.claude/cfq/todo/done"
touch "$tmp/repo-f/.claude/cfq/plan/2026-01-04-a.md" \
      "$tmp/repo-f/.claude/cfq/plan/2026-01-05-b.md" \
      "$tmp/repo-f/.claude/cfq/plan/done/2026-01-01-old.md" \
      "$tmp/repo-f/.claude/cfq/todo/2026-01-06-c.md" \
      "$tmp/repo-f/.claude/cfq/todo/done/2026-01-02-old.md"

# repo-g: .planning fixtures — b-fresh has a just-written marker (planning:true), b-stale has
# one backdated past the 30-minute staleness threshold (planning:false)
mkdir -p "$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-fresh" \
         "$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-stale"
touch "$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-fresh/01-a.md" \
      "$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-stale/01-a.md"
date -Iseconds >"$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-fresh/.planning"
touch -d "@$(($(date +%s) - 3600))" "$tmp/repo-g/.claude/cfq/impl/2026-01-11-b-stale/.planning"

# repo-h: stale pre-476aa60 .priority value — must not crash the scan, must read back empty
mkdir -p "$tmp/repo-h/.claude/cfq/impl/2026-01-12-legacy"
touch "$tmp/repo-h/.claude/cfq/impl/2026-01-12-legacy/01-a.md"
echo medium >"$tmp/repo-h/.claude/cfq/impl/2026-01-12-legacy/.priority"

# repo-i: a foreign directory under impl/ (not a YYYY-MM-DD-slug batch) must not be collected
mkdir -p "$tmp/repo-i/.claude/cfq/impl/todo" \
         "$tmp/repo-i/.claude/cfq/impl/2026-01-13-real-batch"
touch "$tmp/repo-i/.claude/cfq/impl/todo/leftover.md" \
      "$tmp/repo-i/.claude/cfq/impl/2026-01-13-real-batch/01-a.md"

# repo-j: numbered-format batch dir (new naming, digits precede the date) must be found too
mkdir -p "$tmp/repo-j/.claude/cfq/impl/001-2026-01-14-numbered"
touch "$tmp/repo-j/.claude/cfq/impl/001-2026-01-14-numbered/01-a.md"

out=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan")

# Regression: batches without .dependsOn get [] / false / [], never null.
a=$(jq -c --arg p "$tmp/repo-a" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$a" = '[{"name":"2026-01-01-demo","priority":"high","open":2,"done":1,"archived":false,"report":true,"dependsOn":[],"blocked":false,"unknownDeps":[],"inProgress":true,"planning":false}]' ] \
  || { echo "FAIL: repo-a batches = $a"; exit 1; }

b=$(jq -c --arg p "$tmp/repo-b" '[.repos[] | select(.path == $p)][0].batches' <<<"$out")
[ "$b" = '[{"name":"2026-01-02-demo","priority":"","open":0,"done":2,"archived":true,"report":false,"dependsOn":[],"blocked":false,"unknownDeps":[],"inProgress":false,"planning":false}]' ] \
  || { echo "FAIL: repo-b batches (unflagged -> empty priority) = $b"; exit 1; }

c=$(jq -c --arg p "$tmp/repo-c" '[.repos[] | select(.path == $p)]' <<<"$out")
[ "$c" = "[]" ] || { echo "FAIL: repo-c should not appear, got $c"; exit 1; }

e_blocked=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "2026-01-10-b-blocked") | {blocked, dependsOn}' <<<"$out")
[ "$e_blocked" = '{"blocked":true,"dependsOn":["2026-01-10-target-open"]}' ] \
  || { echo "FAIL: b-blocked = $e_blocked"; exit 1; }

e_free=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "2026-01-10-b-free") | {blocked, dependsOn}' <<<"$out")
[ "$e_free" = '{"blocked":false,"dependsOn":["2026-01-10-target-done"]}' ] \
  || { echo "FAIL: b-free = $e_free"; exit 1; }

e_unknown=$(jq -c --arg p "$tmp/repo-e" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "2026-01-10-b-unknown") | {blocked, unknownDeps}' <<<"$out")
[ "$e_unknown" = '{"blocked":false,"unknownDeps":["gibtsnicht"]}' ] \
  || { echo "FAIL: b-unknown = $e_unknown"; exit 1; }

f=$(jq -c --arg p "$tmp/repo-f" '[.repos[] | select(.path == $p)][0] | {plan, todo, batches}' <<<"$out")
[ "$f" = '{"plan":2,"todo":1,"batches":[]}' ] \
  || { echo "FAIL: repo-f plan/todo counts = $f"; exit 1; }

g_fresh=$(jq -c --arg p "$tmp/repo-g" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "2026-01-11-b-fresh") | .planning' <<<"$out")
[ "$g_fresh" = "true" ] || { echo "FAIL: b-fresh planning = $g_fresh"; exit 1; }

g_stale=$(jq -c --arg p "$tmp/repo-g" '[.repos[] | select(.path == $p)][0].batches[] | select(.name == "2026-01-11-b-stale") | .planning' <<<"$out")
[ "$g_stale" = "false" ] || { echo "FAIL: b-stale planning = $g_stale"; exit 1; }

h=$(jq -c --arg p "$tmp/repo-h" '[.repos[] | select(.path == $p)][0].batches[0].priority' <<<"$out")
[ "$h" = '""' ] || { echo "FAIL: repo-h legacy priority should read back empty, got $h"; exit 1; }

i=$(jq -c --arg p "$tmp/repo-i" '[.repos[] | select(.path == $p)][0].batches | map(.name)' <<<"$out")
[ "$i" = '["2026-01-13-real-batch"]' ] \
  || { echo "FAIL: repo-i batches should exclude non-date-prefixed dirs, got $i"; exit 1; }

j=$(jq -c --arg p "$tmp/repo-j" '[.repos[] | select(.path == $p)][0].batches | map(.name)' <<<"$out")
[ "$j" = '["001-2026-01-14-numbered"]' ] \
  || { echo "FAIL: repo-j numbered-format batch not found, got $j"; exit 1; }

# --format=json (explicit) must be byte-identical to the no-flag default — no regression for
# existing callers.
out_json_flag=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan" --format=json)
[ "$out_json_flag" = "$out" ] \
  || { echo "FAIL: --format=json must be byte-identical to no-flag output"; exit 1; }

# --format=md: valid Markdown table, one row per batch, Status reflects blocked/planning/inProgress.
out_md=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan" --format=md)
md_header=$(head -n1 <<<"$out_md")
[ "$md_header" = "| Repo | Batch | Priority | Open/Done | Status |" ] \
  || { echo "FAIL: md header = $md_header"; exit 1; }
md_rows=$(($(wc -l <<<"$out_md") - 2))
total_batches=$(jq '[.repos[].batches | length] | add' <<<"$out")
[ "$md_rows" = "$total_batches" ] \
  || { echo "FAIL: md row count $md_rows != total batches $total_batches"; exit 1; }
md_a_status=$(grep '2026-01-01-demo' <<<"$out_md" | awk -F'|' '{gsub(/ /,"",$6); print $6}')
[ "$md_a_status" = "IN_PROGRESS" ] \
  || { echo "FAIL: md status for repo-a's open+priority batch = $md_a_status"; exit 1; }
md_blocked_status=$(grep '2026-01-10-b-blocked' <<<"$out_md" | awk -F'|' '{gsub(/ /,"",$6); print $6}')
[ "$md_blocked_status" = "BLOCKED" ] \
  || { echo "FAIL: md status for b-blocked = $md_blocked_status"; exit 1; }
md_fresh_status=$(grep '2026-01-11-b-fresh' <<<"$out_md" | awk -F'|' '{gsub(/ /,"",$6); print $6}')
[ "$md_fresh_status" = "PLANNING" ] \
  || { echo "FAIL: md status for b-fresh = $md_fresh_status"; exit 1; }

# --format=tsv: same field set as md, tab-separated, one line per batch (no header).
out_tsv=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan" --format=tsv)
tsv_rows=$(wc -l <<<"$out_tsv")
[ "$tsv_rows" = "$total_batches" ] \
  || { echo "FAIL: tsv row count $tsv_rows != total batches $total_batches"; exit 1; }
tsv_fields=$(grep '2026-01-01-demo' <<<"$out_tsv" | awk -F'\t' '{print NF}')
[ "$tsv_fields" = "5" ] || { echo "FAIL: tsv field count = $tsv_fields"; exit 1; }

# --format=overview: one row per repo, Batches is open/done batch counts (not phase counts),
# Status the most severe status among that repo's own batches.
out_overview=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan" --format=overview)
ov_header=$(head -n1 <<<"$out_overview")
[ "$ov_header" = "| Repo | Plan | Todo | Batches | Status |" ] \
  || { echo "FAIL: overview header = $ov_header"; exit 1; }
ov_repo_a=$(grep '^| repo-a ' <<<"$out_overview" || true)
[ "$ov_repo_a" = "| repo-a | 0 | 0 | 1/0 | IN_PROGRESS |" ] \
  || { echo "FAIL: overview repo-a row = $ov_repo_a"; exit 1; }
ov_repo_f=$(grep '^| repo-f ' <<<"$out_overview" || true)
[ "$ov_repo_f" = "| repo-f | 2 | 1 | 0/0 | OK |" ] \
  || { echo "FAIL: overview repo-f row = $ov_repo_f"; exit 1; }

# Unknown --format value: clear error, exit 1.
err_file="$home/cfq-scan-format-err"
if HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$scan" --format=bogus >/dev/null 2>"$err_file"; then
  echo "FAIL: unknown --format value should exit non-zero"; exit 1
fi
grep -q "unknown --format value" "$err_file" \
  || { echo "FAIL: unknown --format value should print a clear error"; exit 1; }

echo PASS
