#!/usr/bin/env bash
# Self-test for scripts/cfq-changelog.sh. No framework, no fixtures — just `bash tests/test-changelog.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cl="$repo_root/scripts/cfq-changelog.sh"
settings="$repo_root/scripts/cfq-settings.sh"
layout="$repo_root/scripts/cfq-layout.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT
export HOME="$home"

repo="$tmp/repo"
mkdir -p "$repo"
target="$repo/.claude/cfq/changelog.yml"

# default path resolves to .claude/cfq/changelog.yml
resolved="$(bash "$settings" get changelogFile)"
[ "$resolved" = ".claude/cfq/changelog.yml" ] || { echo "FAIL: default changelogFile = $resolved, want .claude/cfq/changelog.yml"; exit 1; }

# init on a missing file creates it with exactly one block, status: in-progress, no version field,
# legacy detected from an unnumbered directory name
bash "$cl" init "$repo" v0.1 v0.1-example-topic main 2026-01-01-example-topic
[ -f "$target" ] || { echo "FAIL: init did not create the changelog file at $target"; exit 1; }
n=$(grep -c '^- batchNumber:' "$target")
[ "$n" = "1" ] || { echo "FAIL: init block count = $n, want 1"; exit 1; }
grep -q '^  status: in-progress$' "$target" || { echo "FAIL: init block missing status: in-progress"; exit 1; }
grep -q '^- batchNumber: null$' "$target" || { echo "FAIL: legacy init did not write batchNumber: null"; exit 1; }
grep -q '^  legacy: true$' "$target" || { echo "FAIL: legacy init did not write legacy: true"; exit 1; }
grep -q '^  version:' "$target" && { echo "FAIL: version field leaked into the new schema"; exit 1; }

# init twice appends, does not overwrite
bash "$cl" init "$repo" v0.2 v0.2-second-topic v0.1-example-topic 2026-01-02-second-topic
n=$(grep -c '^- batchNumber:' "$target")
[ "$n" = "2" ] || { echo "FAIL: after second init, block count = $n, want 2"; exit 1; }
grep -q '2026-01-01-example-topic' "$target" || { echo "FAIL: second init overwrote the first block"; exit 1; }

# finish turns the matching in-progress block into status: done with a finished date and phases
batch="$tmp/2026-01-02-second-topic"
mkdir -p "$batch"
cat >"$batch/report.json" <<'EOF'
{"started":"2026-01-02T09:00:00+01:00","phases":[
  {"phase":"01-first-step","status":"green","summary":"Added the setting and its test"},
  {"phase":"02-second-step","status":"green","summary":"Reworked the skill section"}
]}
EOF
bash "$cl" finish "$repo" v0.2-second-topic "$batch"
n=$(grep -c '^- batchNumber:' "$target")
[ "$n" = "2" ] || { echo "FAIL: finish changed the block count to $n, want 2"; exit 1; }
grep -q '^  status: done$' "$target" || { echo "FAIL: finish did not set status: done"; exit 1; }
grep -q '^  finished: ' "$target" || { echo "FAIL: finish did not add a finished date"; exit 1; }
[ "$(grep -c 'phase: "01-first-step"' "$target")" = "1" ] || { echo "FAIL: finish did not carry over phase 01"; exit 1; }
[ "$(grep -c 'phase: "02-second-step"' "$target")" = "1" ] || { echo "FAIL: finish did not carry over phase 02"; exit 1; }
grep -q '2026-01-01-example-topic' "$target" || { echo "FAIL: finish clobbered the first (unrelated) block"; exit 1; }

# finish for a branch with no matching in-progress block appends instead of corrupting the file
orphan="$tmp/2026-01-03-orphan-topic"
mkdir -p "$orphan"
cat >"$orphan/report.json" <<'EOF'
{"started":"2026-01-03T09:00:00+01:00","phases":[{"phase":"01-only-step","status":"red","summary":"failed"}]}
EOF
before_n=$(grep -c '^- batchNumber:' "$target")
bash "$cl" finish "$repo" v0.9-never-inited "$orphan"
after_n=$(grep -c '^- batchNumber:' "$target")
[ "$after_n" = "$((before_n + 1))" ] || { echo "FAIL: orphan finish block count = $after_n, want $((before_n + 1))"; exit 1; }
[ "$(grep -c '^  status: done$' "$target")" = "2" ] || { echo "FAIL: orphan finish must not turn the second-topic block into done again"; exit 1; }

# changelogFile set to the empty string makes init/finish no-ops and leaves no file behind
empty_repo="$tmp/empty-repo"
mkdir -p "$empty_repo"
bash "$settings" set changelogFile ""
bash "$cl" init "$empty_repo" v0.1 v0.1-noop main 2026-01-01-noop
[ -f "$empty_repo/.claude/cfq/changelog.yml" ] && { echo "FAIL: init wrote a file despite empty changelogFile"; exit 1; }
noop_batch="$tmp/2026-01-04-noop"
mkdir -p "$noop_batch"
echo '{"phases":[]}' >"$noop_batch/report.json"
bash "$cl" finish "$empty_repo" v0.1-noop "$noop_batch"
[ -f "$empty_repo/.claude/cfq/changelog.yml" ] && { echo "FAIL: finish wrote a file despite empty changelogFile"; exit 1; }
# reserve must refuse to silently no-op: a disabled changelog can't back numbered allocation
bash "$cl" reserve "$empty_repo" 1 001-2026-01-01-noop 2>/dev/null && { echo "FAIL: reserve succeeded despite empty changelogFile"; exit 1; }
bash "$settings" set changelogFile ".claude/cfq/changelog.yml"

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
raw=$(sed -n 's/^      summary: //p' "$quoty_repo/.claude/cfq/changelog.yml" | head -1)
parsed=$(printf '%s' "$raw" | jq -r '.')
[ "$parsed" = 'said: "hi" # not a comment' ] || { echo "FAIL: summary did not survive the round trip, got: $parsed"; exit 1; }

# fresh numbered reserve -> init -> finish transitions ONE entry through parked/in-progress/done,
# writes no version-related fields, and derives batchNumber/legacy from the numbered name
numbered_repo="$tmp/numbered-repo"
mkdir -p "$numbered_repo"
numbered_target="$numbered_repo/.claude/cfq/changelog.yml"
numbered_batch="001-2026-02-01-example"
bash "$cl" reserve "$numbered_repo" 1 "$numbered_batch"
[ "$(grep -c '^- batchNumber:' "$numbered_target")" = "1" ] || { echo "FAIL: reserve did not create exactly one block"; exit 1; }
grep -q '^  status: parked$' "$numbered_target" || { echo "FAIL: reserve did not write status: parked"; exit 1; }

bash "$cl" init "$numbered_repo" ignored "cfq/$numbered_batch" main "$numbered_batch"
[ "$(grep -c '^- batchNumber:' "$numbered_target")" = "1" ] || { echo "FAIL: init on a reserved batch created a duplicate block instead of transitioning it"; exit 1; }
grep -q '^- batchNumber: 1$' "$numbered_target" || { echo "FAIL: init did not preserve the reserved batchNumber"; exit 1; }
grep -q '^  status: in-progress$' "$numbered_target" || { echo "FAIL: init did not transition parked -> in-progress"; exit 1; }
grep -q '^  legacy: false$' "$numbered_target" || { echo "FAIL: numbered batch was not marked legacy: false"; exit 1; }

numbered_batch_dir="$tmp/$numbered_batch"
mkdir -p "$numbered_batch_dir"
echo '{"phases":[]}' >"$numbered_batch_dir/report.json"
bash "$cl" finish "$numbered_repo" "cfq/$numbered_batch" "$numbered_batch_dir"
[ "$(grep -c '^- batchNumber:' "$numbered_target")" = "1" ] || { echo "FAIL: finish on a numbered batch created a duplicate block instead of transitioning it"; exit 1; }
grep -q '^- batchNumber: 1$' "$numbered_target" || { echo "FAIL: finish did not preserve the batchNumber through to done"; exit 1; }
grep -q '^  status: done$' "$numbered_target" || { echo "FAIL: finish did not set status: done on the numbered batch"; exit 1; }
grep -q '^  version:' "$numbered_target" && { echo "FAIL: version field leaked into the numbered workflow"; exit 1; }

# reserve rejects duplicate batchNumber/batch identities
dup_repo="$tmp/dup-repo"
mkdir -p "$dup_repo"
bash "$cl" reserve "$dup_repo" 5 002-2026-02-02-dup
bash "$cl" reserve "$dup_repo" 5 003-2026-02-03-other 2>/dev/null && { echo "FAIL: reserve accepted a duplicate batchNumber"; exit 1; }
bash "$cl" reserve "$dup_repo" 6 002-2026-02-02-dup 2>/dev/null && { echo "FAIL: reserve accepted a duplicate batch"; exit 1; }

# max-batch-number ignores legacy/null entries and returns the numeric max, not lexicographic max
maxnum_repo="$tmp/maxnum-repo"
mkdir -p "$maxnum_repo"
bash "$cl" reserve "$maxnum_repo" 2 001-2026-03-01-a
bash "$cl" reserve "$maxnum_repo" 9 002-2026-03-02-b
bash "$cl" init "$maxnum_repo" ignored branch-x main 2026-03-03-legacy-c
got_max="$(bash "$cl" max-batch-number "$maxnum_repo")"
[ "$got_max" = "9" ] || { echo "FAIL: max-batch-number = $got_max, want 9"; exit 1; }
empty_max_repo="$tmp/empty-max-repo"
mkdir -p "$empty_max_repo"
got_empty_max="$(bash "$cl" max-batch-number "$empty_max_repo")"
[ "$got_empty_max" = "0" ] || { echo "FAIL: max-batch-number on a missing ledger = $got_empty_max, want 0"; exit 1; }

# missing ledger + commits with valid CFQ-Batch-Number trailers -> one-time bootstrap recovers the
# numeric max; a matching CFQ-Batch trailer is retained only as recovery context
git_repo="$tmp/git-repo"
mkdir -p "$git_repo"
git -C "$git_repo" init -q
git -C "$git_repo" config user.email test@example.com
git -C "$git_repo" config user.name Test
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'first\n\nCFQ-Batch-Number: 7\nCFQ-Batch: 007-2026-01-01-a\n')"
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'second\n\nCFQ-Batch-Number: 42\nCFQ-Batch: 042-2026-01-02-b\n')"
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'third\n\nCFQ-Batch-Number: 9\nCFQ-Batch: 009-2026-01-03-c\n')"
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'noise\n\nCFQ-Batch-Number: not-a-number\n')"
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'zero\n\nCFQ-Batch-Number: 0\n')"
ensure_out="$(bash "$cl" ensure "$git_repo")"
[ "$(jq -r .source <<<"$ensure_out")" = "git-trailer" ] || { echo "FAIL: ensure source = $(jq -r .source <<<"$ensure_out"), want git-trailer"; exit 1; }
[ "$(jq -r .max <<<"$ensure_out")" = "42" ] || { echo "FAIL: ensure recovered max = $(jq -r .max <<<"$ensure_out"), want 42"; exit 1; }
recovered_max="$(bash "$cl" max-batch-number "$git_repo")"
[ "$recovered_max" = "42" ] || { echo "FAIL: max-batch-number after bootstrap = $recovered_max, want 42"; exit 1; }
grep -q '042-2026-01-02-b' "$git_repo/.claude/cfq/changelog.yml" || { echo "FAIL: recovered entry did not retain the matching CFQ-Batch as context"; exit 1; }

# existing ledger -> ensure performs zero Git-history scans even if newer-looking trailers exist
git -C "$git_repo" commit -q --allow-empty -m "$(printf 'later\n\nCFQ-Batch-Number: 999\n')"
ensure_again="$(bash "$cl" ensure "$git_repo")"
[ "$(jq -r .source <<<"$ensure_again")" = "exists" ] || { echo "FAIL: second ensure did not report source: exists"; exit 1; }
still_max="$(bash "$cl" max-batch-number "$git_repo")"
[ "$still_max" = "42" ] || { echo "FAIL: second ensure rescanned Git history (max = $still_max, want unchanged 42)"; exit 1; }

# missing ledger + no valid CFQ trailers -> empty bootstrap, max 0
no_trailer_repo="$tmp/no-trailer-repo"
mkdir -p "$no_trailer_repo"
git -C "$no_trailer_repo" init -q
git -C "$no_trailer_repo" config user.email test@example.com
git -C "$no_trailer_repo" config user.name Test
git -C "$no_trailer_repo" commit -q --allow-empty -m "plain commit, no trailers"
empty_ensure_out="$(bash "$cl" ensure "$no_trailer_repo")"
[ "$(jq -r .source <<<"$empty_ensure_out")" = "empty" ] || { echo "FAIL: ensure with no trailers reported source $(jq -r .source <<<"$empty_ensure_out"), want empty"; exit 1; }
[ "$(jq -r .max <<<"$empty_ensure_out")" = "0" ] || { echo "FAIL: ensure with no trailers reported nonzero max"; exit 1; }

# old root file only -> migration creates the new local file, old file stays byte-identical
migrate_repo="$tmp/migrate-repo"
mkdir -p "$migrate_repo"
old_file="$migrate_repo/cfq.changelog.yml"
cat >"$old_file" <<'EOF'
- version: v0.5
  branch: v0.5-old-topic
  base: main
  batch: 2025-12-01-old-topic
  started: 2025-12-01
  finished: 2025-12-02
  status: done
  phases:
    - phase: "01-step"
      status: "green"
      summary: "did the thing"
EOF
old_before="$(cat "$old_file")"
bash "$cl" migrate "$migrate_repo"
new_file="$migrate_repo/.claude/cfq/changelog.yml"
[ -f "$new_file" ] || { echo "FAIL: migrate did not create the new local changelog"; exit 1; }
[ "$(cat "$old_file")" = "$old_before" ] || { echo "FAIL: migrate modified the old root file"; exit 1; }
grep -q '2025-12-01-old-topic' "$new_file" || { echo "FAIL: migrate did not carry over the batch identity"; exit 1; }
grep -q '^  legacy: true$' "$new_file" || { echo "FAIL: migrated entry was not marked legacy: true"; exit 1; }
grep -q '^- batchNumber: null$' "$new_file" || { echo "FAIL: migrated entry was not given batchNumber: null"; exit 1; }
grep -q '^  version:' "$new_file" && { echo "FAIL: migrated version: v0.5 survived into the new schema"; exit 1; }
grep -q 'phase: "01-step"' "$new_file" || { echo "FAIL: migrate dropped the phases array"; exit 1; }

# old + new file -> no duplicate entries; repeated migration is idempotent (byte-identical)
after_first_migrate="$(cat "$new_file")"
bash "$cl" migrate "$migrate_repo"
[ "$(grep -c '^- batchNumber:' "$new_file")" = "1" ] || { echo "FAIL: repeated migration created a duplicate entry"; exit 1; }
[ "$(cat "$new_file")" = "$after_first_migrate" ] || { echo "FAIL: repeated migration was not byte-identical"; exit 1; }

# gitStatePolicy=local keeps the ledger in the CFQ-managed local exclusion; settings.json stays trackable
policy_repo="$tmp/policy-repo"
mkdir -p "$policy_repo"
git -C "$policy_repo" init -q
bash "$layout" ensure "$policy_repo" >/dev/null
exclude_file="$policy_repo/.git/info/exclude"
grep -qxF ".claude/cfq/changelog.yml" "$exclude_file" || { echo "FAIL: gitStatePolicy=local did not exclude changelog.yml"; exit 1; }
grep -qxF ".claude/cfq/settings.json" "$exclude_file" && { echo "FAIL: gitStatePolicy=local must not exclude settings.json"; exit 1; }

# gitStatePolicy=trackable removes the managed exclusion
bash "$settings" set --repo "$policy_repo" gitStatePolicy trackable
bash "$layout" sync-git-policy "$policy_repo" >/dev/null
grep -qxF ".claude/cfq/changelog.yml" "$exclude_file" && { echo "FAIL: gitStatePolicy=trackable did not remove the managed exclusion"; exit 1; }

echo PASS
