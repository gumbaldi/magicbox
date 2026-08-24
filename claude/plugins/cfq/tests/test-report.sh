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

HOME="$home" bash "$rep" set-commit "$batch" "01-a" "def5678"
c=$(jq -r '.phases[] | select(.phase=="01-a") | .commit' "$batch/report.json")
[ "$c" = "def5678" ] || { echo "FAIL: set-commit did not update commit = $c"; exit 1; }

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

lf=$(bash "$rep" last-failure "$batch" "02-b")
[ "$(jq -r .found <<<"$lf")" = "true" ] || { echo "FAIL: last-failure should find 02-b's red entry: $lf"; exit 1; }
[ "$(jq -r .note <<<"$lf")" = "fehlgeschlagen" ] || { echo "FAIL: last-failure note: $lf"; exit 1; }

lf=$(bash "$rep" last-failure "$batch" "01-a")
[ "$(jq -r .found <<<"$lf")" = "false" ] || { echo "FAIL: 01-a is green, last-failure should be false: $lf"; exit 1; }

noreport="$tmp/2026-01-03-noreport"
mkdir -p "$noreport"
lf=$(bash "$rep" last-failure "$noreport" "01-a")
[ "$(jq -r .found <<<"$lf")" = "false" ] || { echo "FAIL: last-failure on missing report.json should be false, not crash: $lf"; exit 1; }

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

# --- index/detail (phase 6): 3 report-bearing batches across 2 repos ---

# repo-p: alpha (open, all-green) and beta (archived, red with no later retry)
mkdir -p "$tmp/repo-p/.claude/cfq/impl/2026-02-01-alpha" \
         "$tmp/repo-p/.claude/cfq/impl/done/2026-02-02-beta"
cat >"$tmp/repo-p/.claude/cfq/impl/2026-02-01-alpha/report.json" <<'JSON'
{"repo":"/repo-p","batch":"2026-02-01-alpha","started":"2026-02-01T09:00:00+01:00","phases":[
  {"phase":"01-a","status":"green","finished":"2026-02-01T10:00:00+01:00","summary":"ok","deviations":[],"errors":[],"verification":"tests -> PASS","commit":"aaa1111"},
  {"phase":"02-b","status":"green","finished":"2026-02-01T11:00:00+01:00","summary":"ok2","deviations":["dev1"],"errors":[],"verification":"tests -> PASS","commit":"aaa2222"}
]}
JSON
cat >"$tmp/repo-p/.claude/cfq/impl/done/2026-02-02-beta/report.json" <<'JSON'
{"repo":"/repo-p","batch":"2026-02-02-beta","started":"2026-02-02T08:00:00+01:00","phases":[
  {"phase":"01-a","status":"red","finished":"2026-02-02T09:00:00+01:00","summary":"boom","deviations":[],"errors":["stacktrace line"],"verification":"tests -> FAIL","commit":""}
]}
JSON

# repo-q: gamma (open, phase 01-a red then retried green -> MIXED)
mkdir -p "$tmp/repo-q/.claude/cfq/impl/2026-02-03-gamma"
cat >"$tmp/repo-q/.claude/cfq/impl/2026-02-03-gamma/report.json" <<'JSON'
{"repo":"/repo-q","batch":"2026-02-03-gamma","started":"2026-02-03T08:00:00+01:00","phases":[
  {"phase":"01-a","status":"red","finished":"2026-02-03T09:00:00+01:00","summary":"first try failed","deviations":[],"errors":["err"],"verification":"FAIL","commit":""},
  {"phase":"01-a","status":"green","finished":"2026-02-03T10:00:00+01:00","summary":"fixed","deviations":[],"errors":[],"verification":"PASS","commit":"ccc3333"}
]}
JSON

# Call-counting stub for the N+1-regression guard: index must call cfq-scan.sh exactly once,
# regardless of how many report-bearing batches exist.
scan_calls="$tmp/scan-call-count"
stub_dir="$tmp/stub-scripts"
mkdir -p "$stub_dir"
cp "$repo_root/scripts/cfq-report.sh" "$stub_dir/cfq-report.sh"
: >"$scan_calls"
cat >"$stub_dir/cfq-scan.sh" <<EOF
#!/usr/bin/env bash
echo x >>"$scan_calls"
exec bash "$repo_root/scripts/cfq-scan.sh" "\$@"
EOF
chmod +x "$stub_dir/cfq-scan.sh"

idx=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$stub_dir/cfq-report.sh" index)
n=$(jq 'length' <<<"$idx")
[ "$n" = "3" ] || { echo "FAIL: index (no filter) length = $n"; exit 1; }

calls=$(wc -l <"$scan_calls")
[ "$calls" = "1" ] || { echo "FAIL: index should call cfq-scan.sh exactly once, got $calls"; exit 1; }

st_alpha=$(jq -r '.[] | select(.batch=="2026-02-01-alpha") | .status' <<<"$idx")
[ "$st_alpha" = "GREEN" ] || { echo "FAIL: alpha status = $st_alpha"; exit 1; }

st_beta=$(jq -r '.[] | select(.batch=="2026-02-02-beta") | .status' <<<"$idx")
[ "$st_beta" = "RED" ] || { echo "FAIL: beta status = $st_beta"; exit 1; }

st_gamma=$(jq -r '.[] | select(.batch=="2026-02-03-gamma") | .status' <<<"$idx")
[ "$st_gamma" = "MIXED" ] || { echo "FAIL: gamma status = $st_gamma"; exit 1; }

dev_alpha=$(jq -r '.[] | select(.batch=="2026-02-01-alpha") | .deviations' <<<"$idx")
[ "$dev_alpha" = "1" ] || { echo "FAIL: alpha deviations = $dev_alpha"; exit 1; }

first=$(jq -r '.[0].batch' <<<"$idx")
[ "$first" = "2026-02-03-gamma" ] || { echo "FAIL: index should sort newest-first, got $first first"; exit 1; }

idx_repo=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$stub_dir/cfq-report.sh" index --repo repo-q)
[ "$(jq 'length' <<<"$idx_repo")" = "1" ] || { echo "FAIL: --repo filter did not narrow to 1: $idx_repo"; exit 1; }
[ "$(jq -r '.[0].batch' <<<"$idx_repo")" = "2026-02-03-gamma" ] || { echo "FAIL: --repo filter wrong batch: $idx_repo"; exit 1; }

idx_batch=$(HOME="$home" CFQ_SCAN_ROOTS="$tmp" bash "$stub_dir/cfq-report.sh" index --batch alpha)
[ "$(jq 'length' <<<"$idx_batch")" = "1" ] || { echo "FAIL: --batch filter did not narrow to 1: $idx_batch"; exit 1; }
[ "$(jq -r '.[0].batch' <<<"$idx_batch")" = "2026-02-01-alpha" ] || { echo "FAIL: --batch filter wrong batch: $idx_batch"; exit 1; }

# detail on a batch with no report.json -> clear not-found result, no crash
noreport_batch="$tmp/repo-p/.claude/cfq/impl/nope"
mkdir -p "$noreport_batch"
det_missing=$(bash "$rep" detail "$noreport_batch")
[ "$(jq -r .found <<<"$det_missing")" = "false" ] || { echo "FAIL: detail on missing report.json should be found:false: $det_missing"; exit 1; }

# detail on gamma: overall status MIXED, both attempts present
det=$(bash "$rep" detail "$tmp/repo-q/.claude/cfq/impl/2026-02-03-gamma")
[ "$(jq -r .found <<<"$det")" = "true" ] || { echo "FAIL: detail found = false for gamma"; exit 1; }
[ "$(jq -r .status <<<"$det")" = "MIXED" ] || { echo "FAIL: detail status = $(jq -r .status <<<"$det")"; exit 1; }
[ "$(jq '.phases | length' <<<"$det")" = "2" ] || { echo "FAIL: detail phases length != 2"; exit 1; }

# detail's verification-excerpt bound: a long verification log must not be dumped in full
long_batch="$tmp/repo-p/.claude/cfq/impl/2026-02-04-longlog"
mkdir -p "$long_batch"
long_verification=$(awk 'BEGIN{for(i=0;i<200;i++) print "line " i}')
jq -n --arg v "$long_verification" \
  '{repo:"/repo-p",batch:"2026-02-04-longlog",started:"2026-02-04T08:00:00+01:00",phases:[
     {phase:"01-a",status:"green",finished:"2026-02-04T09:00:00+01:00",summary:"ok",deviations:[],errors:[],verification:$v,commit:"ddd4444"}
   ]}' >"$long_batch/report.json"
det_long=$(bash "$rep" detail "$long_batch")
vlines=$(jq -r '.phases[0].verification' <<<"$det_long" | wc -l)
[ "$vlines" -lt 200 ] || { echo "FAIL: detail should bound verification output, got $vlines lines"; exit 1; }

echo PASS
