#!/usr/bin/env bash
# Self-test for scripts/cfq-changelog.sh. No framework, no fixtures — just `bash tests/test-changelog.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cl="$repo_root/scripts/cfq-changelog.sh"
settings="$repo_root/scripts/cfq-settings.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

repo="$tmp/repo"
mkdir -p "$repo"
export HOME="$home"
target="$repo/cfq.changelog.yml"

# init on a missing file creates it with exactly one block, status: in-progress
bash "$cl" init "$repo" v0.1 v0.1-example-topic main 2026-01-01-example-topic
[ -f "$target" ] || { echo "FAIL: init did not create the changelog file"; exit 1; }
n=$(grep -c '^- version:' "$target")
[ "$n" = "1" ] || { echo "FAIL: init block count = $n, want 1"; exit 1; }
grep -q '^  status: in-progress$' "$target" || { echo "FAIL: init block missing status: in-progress"; exit 1; }

# init twice appends, does not overwrite
bash "$cl" init "$repo" v0.2 v0.2-second-topic v0.1-example-topic 2026-01-02-second-topic
n=$(grep -c '^- version:' "$target")
[ "$n" = "2" ] || { echo "FAIL: after second init, block count = $n, want 2"; exit 1; }
grep -q 'v0.1-example-topic' "$target" || { echo "FAIL: second init overwrote the first block"; exit 1; }

# finish turns the matching (last) block into status: done with a finished date and phases
batch="$tmp/2026-01-02-second-topic"
mkdir -p "$batch"
cat >"$batch/report.json" <<'EOF'
{"started":"2026-01-02T09:00:00+01:00","phases":[
  {"phase":"01-first-step","status":"green","summary":"Added the setting and its test"},
  {"phase":"02-second-step","status":"green","summary":"Reworked the skill section"}
]}
EOF
bash "$cl" finish "$repo" v0.2-second-topic "$batch"
n=$(grep -c '^- version:' "$target")
[ "$n" = "2" ] || { echo "FAIL: finish changed the block count to $n, want 2"; exit 1; }
grep -q '^  status: done$' "$target" || { echo "FAIL: finish did not set status: done"; exit 1; }
grep -q '^  finished: ' "$target" || { echo "FAIL: finish did not add a finished date"; exit 1; }
[ "$(grep -c 'phase: "01-first-step"' "$target")" = "1" ] || { echo "FAIL: finish did not carry over phase 01"; exit 1; }
[ "$(grep -c 'phase: "02-second-step"' "$target")" = "1" ] || { echo "FAIL: finish did not carry over phase 02"; exit 1; }
grep -q 'v0.1-example-topic' "$target" || { echo "FAIL: finish clobbered the first (unrelated) block"; exit 1; }

# finish for a branch that is not the last block appends instead of corrupting the file
orphan="$tmp/2026-01-03-orphan-topic"
mkdir -p "$orphan"
cat >"$orphan/report.json" <<'EOF'
{"started":"2026-01-03T09:00:00+01:00","phases":[{"phase":"01-only-step","status":"red","summary":"failed"}]}
EOF
before_n=$(grep -c '^- version:' "$target")
bash "$cl" finish "$repo" v0.9-never-inited "$orphan"
after_n=$(grep -c '^- version:' "$target")
[ "$after_n" = "$((before_n + 1))" ] || { echo "FAIL: orphan finish block count = $after_n, want $((before_n + 1))"; exit 1; }
grep -q '^  status: done$' "$target" || { echo "FAIL: orphan finish missing status: done"; exit 1; }
[ "$(grep -c '^  status: done$' "$target")" = "2" ] || { echo "FAIL: orphan finish must not turn the second-topic block into done again"; exit 1; }

# changelogFile set to the empty string makes both subcommands no-ops and leaves no file behind
empty_repo="$tmp/empty-repo"
mkdir -p "$empty_repo"
bash "$settings" set changelogFile ""
bash "$cl" init "$empty_repo" v0.1 v0.1-noop main 2026-01-01-noop
[ -f "$empty_repo/cfq.changelog.yml" ] && { echo "FAIL: init wrote a file despite empty changelogFile"; exit 1; }
noop_batch="$tmp/2026-01-04-noop"
mkdir -p "$noop_batch"
echo '{"phases":[]}' >"$noop_batch/report.json"
bash "$cl" finish "$empty_repo" v0.1-noop "$noop_batch"
[ -f "$empty_repo/cfq.changelog.yml" ] && { echo "FAIL: finish wrote a file despite empty changelogFile"; exit 1; }
bash "$settings" set changelogFile "cfq.changelog.yml"

# a summary containing a colon and a double quote survives a round trip through the file
quoty_repo="$tmp/quoty-repo"
mkdir -p "$quoty_repo"
bash "$cl" init "$quoty_repo" v0.1 v0.1-quoty main 2026-01-05-quoty
quoty_batch="$tmp/2026-01-05-quoty"
mkdir -p "$quoty_batch"
cat >"$quoty_batch/report.json" <<'EOF'
{"phases":[{"phase":"01-tricky","status":"green","summary":"said: \"hi\" # not a comment"}]}
EOF
bash "$cl" finish "$quoty_repo" v0.1-quoty "$quoty_batch"
# The emitted scalar is a double-quoted YAML string, which is also valid JSON — decode with jq
# rather than a scripting-language eval.
raw=$(sed -n 's/^      summary: //p' "$quoty_repo/cfq.changelog.yml" | head -1)
parsed=$(printf '%s' "$raw" | jq -r '.')
[ "$parsed" = 'said: "hi" # not a comment' ] || { echo "FAIL: summary did not survive the round trip, got: $parsed"; exit 1; }

echo PASS
