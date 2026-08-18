#!/usr/bin/env bash
# Self-test for scripts/cfq-report.sh. No framework, no fixtures — just `bash tests/test-report.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rep="$repo_root/scripts/cfq-report.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

batch="$tmp/2026-01-01-demo"
mkdir -p "$batch"

# HOME isolated to an empty dir so `append`'s automatic telemetry call finds no transcript
# (fail-soft, no-op) — this batch stays a "report without telemetry" fixture on purpose.
HOME="$home" bash "$rep" append "$batch" '{"phase":"01-a","status":"green","finished":"2026-01-01T10:00:00+01:00","summary":"ok","deviations":["Plan sagte X, gebaut Y"],"errors":[],"verification":"tests -> PASS","commit":"abc1234"}'
HOME="$home" bash "$rep" append "$batch" '{"phase":"02-b","status":"red","finished":"2026-01-01T11:00:00+01:00","summary":"fehlgeschlagen","deviations":[],"errors":["Verifikation rot: 1 Test <failed>"],"verification":"tests -> FAIL","commit":""}'

s=$(bash "$rep" summary "$batch")
expected="$(basename "$batch")	2	1	1	1	2026-01-01T11:00:00+01:00	0	0	0		"
[ "$s" = "$expected" ] || { echo "FAIL: summary = $s"; exit 1; }

out=$(bash "$rep" html "$batch")
[ "$out" = "$batch/report.html" ] || { echo "FAIL: html path = $out"; exit 1; }
[ -f "$out" ] || { echo "FAIL: report.html not created"; exit 1; }

grep -q '01-a' "$out" || { echo "FAIL: report.html missing 01-a"; exit 1; }
grep -q '02-b' "$out" || { echo "FAIL: report.html missing 02-b"; exit 1; }

grep -q '1 Test &lt;failed&gt;' "$out" || { echo "FAIL: error text not HTML-escaped"; exit 1; }

grep -c 'class="telemetry"' "$out" >/dev/null 2>&1 && n=$(grep -c 'class="telemetry"' "$out") || n=0
[ "$n" = "0" ] || { echo "FAIL: report.html has telemetry markup despite no telemetry data ($n)"; exit 1; }

bash "$rep" security "$batch" '{"status":"ok","critical":0,"high":0}'
bash "$rep" security "$batch" '{"status":"ok","critical":0,"high":1}'
sec=$(jq '.security | length' "$batch/report.json")
[ "$sec" = "2" ] || { echo "FAIL: security snapshots = $sec, want 2"; exit 1; }

# security on a fresh batch must create report.json — this is the planning-time path, where no
# phase has been appended yet.
fresh="$tmp/2026-01-02-fresh"
mkdir -p "$fresh"
HOME="$home" bash "$rep" security "$fresh" '{"available":false,"counts":{}}'
[ -f "$fresh/report.json" ] || { echo "FAIL: security did not create report.json"; exit 1; }
n=$(jq '.security | length' "$fresh/report.json")
[ "$n" = "1" ] || { echo "FAIL: fresh security snapshots = $n, want 1"; exit 1; }
b=$(jq -r '.batch' "$fresh/report.json")
[ "$b" = "2026-01-02-fresh" ] || { echo "FAIL: batch = $b"; exit 1; }

echo PASS
