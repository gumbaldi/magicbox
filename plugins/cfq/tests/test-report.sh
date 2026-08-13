#!/usr/bin/env bash
# Self-test for scripts/cfq-report.sh. No framework, no fixtures — just `bash tests/test-report.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rep="$repo_root/scripts/cfq-report.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

batch="$tmp/2026-01-01-demo"
mkdir -p "$batch"

bash "$rep" append "$batch" '{"phase":"01-a","status":"green","finished":"2026-01-01T10:00:00+01:00","summary":"ok","deviations":["Plan sagte X, gebaut Y"],"errors":[],"verification":"tests -> PASS","commit":"abc1234"}'
bash "$rep" append "$batch" '{"phase":"02-b","status":"red","finished":"2026-01-01T11:00:00+01:00","summary":"fehlgeschlagen","deviations":[],"errors":["Verifikation rot: 1 Test <failed>"],"verification":"tests -> FAIL","commit":""}'

s=$(bash "$rep" summary "$batch")
expected="$(basename "$batch")	2	1	1	1	2026-01-01T11:00:00+01:00"
[ "$s" = "$expected" ] || { echo "FAIL: summary = $s"; exit 1; }

out=$(bash "$rep" html "$batch")
[ "$out" = "$batch/report.html" ] || { echo "FAIL: html path = $out"; exit 1; }
[ -f "$out" ] || { echo "FAIL: report.html not created"; exit 1; }

grep -q '01-a' "$out" || { echo "FAIL: report.html missing 01-a"; exit 1; }
grep -q '02-b' "$out" || { echo "FAIL: report.html missing 02-b"; exit 1; }

grep -q '1 Test &lt;failed&gt;' "$out" || { echo "FAIL: error text not HTML-escaped"; exit 1; }

echo PASS
