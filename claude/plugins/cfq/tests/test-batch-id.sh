#!/usr/bin/env bash
# Self-test for scripts/cfq-batch-id.sh. No framework, no fixtures beyond plain temp dirs — just
# `bash tests/test-batch-id.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bi="$repo_root/scripts/cfq-batch-id.sh"
cl="$repo_root/scripts/cfq-changelog.sh"
layout="$repo_root/scripts/cfq-layout.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT
export HOME="$home"

status() { jq -r .status <<<"$1"; }

# empty repo/no ledger/no CFQ commit trailers -> bootstrap max 0, then 001-<date>-<slug>
repo1="$tmp/repo1"; mkdir -p "$repo1"
out="$(bash "$bi" next "$repo1" 2026-08-19 example)"
[ "$(status "$out")" = "OK" ] || { echo "FAIL: fresh repo next status = $(status "$out")"; exit 1; }
[ "$(jq -r .batch <<<"$out")" = "001-2026-08-19-example" ] || { echo "FAIL: fresh repo batch = $(jq -r .batch <<<"$out")"; exit 1; }
[ "$(jq -r .batchNumber <<<"$out")" = "1" ] || { echo "FAIL: fresh repo batchNumber != 1"; exit 1; }
[ "$(jq -r .width <<<"$out")" = "3" ] || { echo "FAIL: fresh repo width != 3"; exit 1; }

# missing ledger + highest valid commit trailer CFQ-Batch-Number: 42 -> next is 043, no second scan
repo2="$tmp/repo2"; mkdir -p "$repo2"
git -C "$repo2" init -q
git -C "$repo2" config user.email test@example.com
git -C "$repo2" config user.name Test
git -C "$repo2" commit -q --allow-empty -m "$(printf 'a\n\nCFQ-Batch-Number: 42\n')"
out="$(bash "$bi" next "$repo2" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "043" ] || { echo "FAIL: trailer bootstrap next = $(jq -r .formatted <<<"$out"), want 043"; exit 1; }
# a later, higher trailer must not leak in once the ledger exists — `next` never reserves, so the
# repeat call still reports the same unconsumed number, and only a rescan of Git history (which
# must not happen) could ever surface the 999 trailer here
git -C "$repo2" commit -q --allow-empty -m "$(printf 'b\n\nCFQ-Batch-Number: 999\n')"
out2="$(bash "$bi" next "$repo2" 2026-08-20 example2)"
[ "$(jq -r .formatted <<<"$out2")" = "043" ] || { echo "FAIL: ledger was rescanned from Git after bootstrap (got $(jq -r .formatted <<<"$out2"), want unchanged 043)"; exit 1; }

# 001, 002, 009 existing -> next is 010
repo3="$tmp/repo3"; mkdir -p "$repo3"
bash "$cl" reserve "$repo3" 1 001-2026-08-01-a
bash "$cl" reserve "$repo3" 2 002-2026-08-02-b
bash "$cl" reserve "$repo3" 9 009-2026-08-03-c
out="$(bash "$bi" next "$repo3" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "010" ] || { echo "FAIL: sequential reserve next = $(jq -r .formatted <<<"$out"), want 010"; exit 1; }

# gaps (001, 004) -> next is 005, never gap reuse
repo4="$tmp/repo4"; mkdir -p "$repo4"
bash "$cl" reserve "$repo4" 1 001-2026-08-01-a
bash "$cl" reserve "$repo4" 4 004-2026-08-02-b
out="$(bash "$bi" next "$repo4" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "005" ] || { echo "FAIL: gap next = $(jq -r .formatted <<<"$out"), want 005"; exit 1; }

# 099 -> 100
repo5="$tmp/repo5"; mkdir -p "$repo5"
bash "$cl" reserve "$repo5" 99 099-2026-08-01-a
out="$(bash "$bi" next "$repo5" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "100" ] || { echo "FAIL: 099 next = $(jq -r .formatted <<<"$out"), want 100"; exit 1; }

# 999 at width 3 -> BATCH_WIDTH_MIGRATION_REQUIRED, not malformed 1000 allocation
repo6="$tmp/repo6"; mkdir -p "$repo6"
bash "$cl" reserve "$repo6" 999 999-2026-08-01-a
out="$(bash "$bi" next "$repo6" 2026-08-19 example)" && { echo "FAIL: width-exhausted next exited 0"; exit 1; }
[ "$(status "$out")" = "BATCH_WIDTH_MIGRATION_REQUIRED" ] || { echo "FAIL: width-exhausted status = $(status "$out")"; exit 1; }

# numeric max beats lexicographic traps (9 vs 010: numeric max is 10, not lexicographic "9")
repo7="$tmp/repo7"; mkdir -p "$repo7"
bash "$cl" reserve "$repo7" 9 009-2026-08-01-a
bash "$cl" reserve "$repo7" 10 010-2026-08-02-b
out="$(bash "$bi" next "$repo7" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "011" ] || { echo "FAIL: numeric-max next = $(jq -r .formatted <<<"$out"), want 011"; exit 1; }

# legacy unnumbered batch directories do not influence the counter
repo8="$tmp/repo8"; mkdir -p "$repo8/.claude/cfq/impl/2026-08-01-legacy-topic"
bash "$cl" reserve "$repo8" 3 003-2026-08-01-a
out="$(bash "$bi" next "$repo8" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "004" ] || { echo "FAIL: legacy dir influenced next = $(jq -r .formatted <<<"$out"), want 004"; exit 1; }

# old v0.12-* branches and free-form commit prose do not influence the counter
repo9="$tmp/repo9"; mkdir -p "$repo9"
git -C "$repo9" init -q
git -C "$repo9" config user.email test@example.com
git -C "$repo9" config user.name Test
git -C "$repo9" commit -q --allow-empty -m "v0.12-some-old-topic: mentions CFQ-Batch-Number: 500 in prose, not a trailer"
git -C "$repo9" branch v0.12-some-old-topic
out="$(bash "$bi" next "$repo9" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "001" ] || { echo "FAIL: branch/prose influenced next = $(jq -r .formatted <<<"$out"), want 001"; exit 1; }

# changelog batch number higher than queue dirs wins
repo10="$tmp/repo10"; mkdir -p "$repo10/.claude/cfq/impl/002-2026-08-01-a"
bash "$cl" reserve "$repo10" 5 005-2026-08-02-b
out="$(bash "$bi" next "$repo10" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "006" ] || { echo "FAIL: changelog-higher next = $(jq -r .formatted <<<"$out"), want 006"; exit 1; }

# queue-only higher number -> BATCH_LEDGER_MISMATCH rather than risking reuse
repo11="$tmp/repo11"; mkdir -p "$repo11/.claude/cfq/impl/009-2026-08-01-a"
bash "$cl" reserve "$repo11" 5 005-2026-08-02-b
out="$(bash "$bi" next "$repo11" 2026-08-19 example)" && { echo "FAIL: queue-higher next exited 0"; exit 1; }
[ "$(status "$out")" = "BATCH_LEDGER_MISMATCH" ] || { echo "FAIL: queue-higher status = $(status "$out")"; exit 1; }

# allocation immediately creates one status: parked changelog reservation and the queue directory
repo12="$tmp/repo12"; mkdir -p "$repo12"
out="$(bash "$bi" allocate "$repo12" 2026-08-19 my-feature)"
[ "$(status "$out")" = "OK" ] || { echo "FAIL: allocate status = $(status "$out")"; exit 1; }
batch="$(jq -r .batch <<<"$out")"
[ "$batch" = "001-2026-08-19-my-feature" ] || { echo "FAIL: allocate batch = $batch"; exit 1; }
target="$repo12/.claude/cfq/changelog.yml"
[ "$(grep -c '^- batchNumber:' "$target")" = "1" ] || { echo "FAIL: allocate did not reserve exactly one changelog entry"; exit 1; }
grep -q '^  status: parked$' "$target" || { echo "FAIL: allocate did not write status: parked"; exit 1; }
[ -d "$repo12/.claude/cfq/impl/$batch" ] || { echo "FAIL: allocate did not create the queue directory"; exit 1; }

# a second allocate call in the same repo advances past the first
out2="$(bash "$bi" allocate "$repo12" 2026-08-20 second-feature)"
[ "$(jq -r .batch <<<"$out2")" = "002-2026-08-20-second-feature" ] || { echo "FAIL: second allocate batch = $(jq -r .batch <<<"$out2")"; exit 1; }

# simulated failure after changelog reservation never allows the number to be reused: make the
# impl directory unwritable so allocate's own mkdir fails after the changelog reserve succeeds
repo13="$tmp/repo13"; mkdir -p "$repo13"
bash "$layout" ensure "$repo13" >/dev/null
chmod 555 "$repo13/.claude/cfq/impl"
out="$(bash "$bi" allocate "$repo13" 2026-08-19 blocked)" && { chmod 755 "$repo13/.claude/cfq/impl"; echo "FAIL: colliding allocate exited 0"; exit 1; }
chmod 755 "$repo13/.claude/cfq/impl"
[ "$(status "$out")" = "INTERNAL_ERROR" ] || { echo "FAIL: colliding allocate status = $(status "$out")"; exit 1; }
[ "$(bash "$cl" max-batch-number "$repo13")" = "1" ] || { echo "FAIL: failed allocate did not consume number 1"; exit 1; }
out2="$(bash "$bi" allocate "$repo13" 2026-08-19 retry)"
[ "$(jq -r .batch <<<"$out2")" = "002-2026-08-19-retry" ] || { echo "FAIL: retry after failed allocate reused number 1: $(jq -r .batch <<<"$out2")"; exit 1; }

# malformed numbered-looking directory is ignored, never partially parsed
repo14="$tmp/repo14"; mkdir -p "$repo14/.claude/cfq/impl/0ab-2026-08-19-bad"
bash "$cl" reserve "$repo14" 2 002-2026-08-01-a
out="$(bash "$bi" next "$repo14" 2026-08-19 example)"
[ "$(jq -r .formatted <<<"$out")" = "003" ] || { echo "FAIL: malformed dir influenced next = $(jq -r .formatted <<<"$out"), want 003"; exit 1; }

# two competing allocation attempts cannot reserve the same number/name
repo15="$tmp/repo15"; mkdir -p "$repo15"
bash "$bi" allocate "$repo15" 2026-08-19 first-race >"$tmp/race1.json" &
p1=$!
bash "$bi" allocate "$repo15" 2026-08-19 second-race >"$tmp/race2.json" &
p2=$!
wait "$p1"; wait "$p2"
b1="$(jq -r .batch <"$tmp/race1.json")"
b2="$(jq -r .batch <"$tmp/race2.json")"
[ "$b1" != "$b2" ] || { echo "FAIL: two concurrent allocations returned the same batch: $b1"; exit 1; }
n1="$(jq -r .batchNumber <"$tmp/race1.json")"
n2="$(jq -r .batchNumber <"$tmp/race2.json")"
[ "$(( n1 + n2 ))" = 3 ] || { echo "FAIL: concurrent allocation numbers were $n1 and $n2, want 1 and 2"; exit 1; }

# invalid arguments are rejected cleanly
repo16="$tmp/repo16"; mkdir -p "$repo16"
out="$(bash "$bi" next "$repo16" not-a-date example)" && { echo "FAIL: bad date exited 0"; exit 1; }
[ "$(status "$out")" = "INVALID_ARGUMENT" ] || { echo "FAIL: bad date status = $(status "$out")"; exit 1; }
out="$(bash "$bi" next "$repo16" 2026-08-19 "Not_A_Slug")" && { echo "FAIL: bad slug exited 0"; exit 1; }
[ "$(status "$out")" = "INVALID_ARGUMENT" ] || { echo "FAIL: bad slug status = $(status "$out")"; exit 1; }

# helper never reads Claude runtime/session paths
grep -qE 'CLAUDE_|cfq-runtime' "$repo_root/scripts/cfq-batch-id.sh" && { echo "FAIL: cfq-batch-id.sh references Claude runtime/session state"; exit 1; }

# a disabled changelog refuses to allocate a numbered identity rather than silently no-op-ing
repo17="$tmp/repo17"; mkdir -p "$repo17"
"$repo_root/scripts/cfq-settings.sh" set changelogFile ""
out="$(bash "$bi" next "$repo17" 2026-08-19 example)" && { echo "FAIL: disabled changelog next exited 0"; exit 1; }
[ "$(status "$out")" = "BATCH_CHANGELOG_REQUIRED" ] || { echo "FAIL: disabled changelog status = $(status "$out")"; exit 1; }
"$repo_root/scripts/cfq-settings.sh" set changelogFile ".claude/cfq/changelog.yml"

# 999 -> 1000 while the active queue is non-empty -> BATCH_WIDTH_MIGRATION_BLOCKED, zero mutations
repo18="$tmp/repo18"; mkdir -p "$repo18/.claude/cfq/impl/2026-08-01-still-active"
bash "$cl" reserve "$repo18" 999 999-2026-08-01-a
mkdir -p "$repo18/.claude/cfq/impl/done/999-2026-08-01-a"
before_cl18="$(cat "$repo18/.claude/cfq/changelog.yml")"
out="$(bash "$bi" allocate "$repo18" 2026-08-19 blocked-test)" && { echo "FAIL: width-blocked allocate exited 0"; exit 1; }
[ "$(status "$out")" = "BATCH_WIDTH_MIGRATION_BLOCKED" ] || { echo "FAIL: width-blocked status = $(status "$out")"; exit 1; }
[ "$(jq -r .currentWidth <<<"$out")" = "3" ] || { echo "FAIL: width-blocked currentWidth = $(jq -r .currentWidth <<<"$out")"; exit 1; }
[ "$(jq -r .requiredWidth <<<"$out")" = "4" ] || { echo "FAIL: width-blocked requiredWidth = $(jq -r .requiredWidth <<<"$out")"; exit 1; }
[ "$(jq -r .nextNumber <<<"$out")" = "1000" ] || { echo "FAIL: width-blocked nextNumber = $(jq -r .nextNumber <<<"$out")"; exit 1; }
after_cl18="$(cat "$repo18/.claude/cfq/changelog.yml")"
[ "$before_cl18" = "$after_cl18" ] || { echo "FAIL: width-blocked mutated the changelog"; exit 1; }
[ -d "$repo18/.claude/cfq/impl/done/999-2026-08-01-a" ] || { echo "FAIL: width-blocked renamed the done directory"; exit 1; }
[ ! -e "$repo18/.claude/cfq/impl/done/0999-2026-08-01-a" ] || { echo "FAIL: width-blocked created a migrated destination"; exit 1; }
[ ! -e "$repo18/.claude/cfq/impl/1000-2026-08-19-blocked-test" ] || { echo "FAIL: width-blocked allocated a queue directory"; exit 1; }

# same boundary with the active queue empty -> every numbered historical identifier becomes width
# 4 (legacy unnumbered dirs untouched, sort order stays numeric), then 1000-... is allocated
repo19="$tmp/repo19"; mkdir -p "$repo19"
bash "$cl" reserve "$repo19" 1 001-2026-08-01-a
bash "$cl" reserve "$repo19" 99 099-2026-08-02-b
bash "$cl" reserve "$repo19" 999 999-2026-08-03-c
mkdir -p "$repo19/.claude/cfq/impl/done/001-2026-08-01-a" \
         "$repo19/.claude/cfq/impl/done/099-2026-08-02-b" \
         "$repo19/.claude/cfq/impl/done/999-2026-08-03-c" \
         "$repo19/.claude/cfq/impl/done/2026-08-01-legacy-topic"
out="$(bash "$bi" allocate "$repo19" 2026-08-19 new-batch)"
[ "$(status "$out")" = "OK" ] || { echo "FAIL: post-migration allocate status = $(status "$out")"; exit 1; }
[ "$(jq -r .batch <<<"$out")" = "1000-2026-08-19-new-batch" ] || { echo "FAIL: post-migration allocate batch = $(jq -r .batch <<<"$out")"; exit 1; }
[ "$(jq -r .width <<<"$out")" = "4" ] || { echo "FAIL: post-migration allocate width = $(jq -r .width <<<"$out")"; exit 1; }
target19="$repo19/.claude/cfq/changelog.yml"
grep -qxF '  batch: 0001-2026-08-01-a' "$target19" || { echo "FAIL: changelog batch 1 was not repadded"; exit 1; }
grep -qxF '  batch: 0099-2026-08-02-b' "$target19" || { echo "FAIL: changelog batch 99 was not repadded"; exit 1; }
grep -qxF '  batch: 0999-2026-08-03-c' "$target19" || { echo "FAIL: changelog batch 999 was not repadded"; exit 1; }
for d in 0001-2026-08-01-a 0099-2026-08-02-b 0999-2026-08-03-c; do
  [ -d "$repo19/.claude/cfq/impl/done/$d" ] || { echo "FAIL: done dir $d missing after migration"; exit 1; }
done
[ -d "$repo19/.claude/cfq/impl/done/2026-08-01-legacy-topic" ] || { echo "FAIL: legacy done dir was renamed"; exit 1; }
sorted19="$(cd "$repo19/.claude/cfq/impl/done" && ls -1 | grep -E '^[0-9]{4}-[0-9]{4}-[0-9]{2}-[0-9]{2}-' | sort)"
expected19="0001-2026-08-01-a
0099-2026-08-02-b
0999-2026-08-03-c"
[ "$sorted19" = "$expected19" ] || { echo "FAIL: alphabetical order after migration != numeric order"; exit 1; }

# second migration invocation is idempotent: nothing left to rename, no double-padding
out2="$(bash "$bi" migrate-width "$repo19")"
[ "$(status "$out2")" = "OK" ] || { echo "FAIL: idempotent migrate-width status = $(status "$out2")"; exit 1; }
[ "$(jq -r .migrated <<<"$out2")" = "0" ] || { echo "FAIL: idempotent migrate-width migrated $(jq -r .migrated <<<"$out2") entries, want 0"; exit 1; }
[ -d "$repo19/.claude/cfq/impl/done/0001-2026-08-01-a" ] || { echo "FAIL: idempotent migrate-width lost batch 1"; exit 1; }
[ ! -e "$repo19/.claude/cfq/impl/done/00001-2026-08-01-a" ] || { echo "FAIL: idempotent migrate-width double-padded batch 1"; exit 1; }

# generic 4 -> 5 fixture works without code changes specific to 3 digits
repo20="$tmp/repo20"; mkdir -p "$repo20"
bash "$cl" reserve "$repo20" 9999 9999-2026-08-01-a
mkdir -p "$repo20/.claude/cfq/impl/done/9999-2026-08-01-a"
out="$(bash "$bi" migrate-width "$repo20")"
[ "$(status "$out")" = "OK" ] || { echo "FAIL: 4->5 migrate-width status = $(status "$out")"; exit 1; }
[ "$(jq -r .width <<<"$out")" = "5" ] || { echo "FAIL: 4->5 migrate-width width = $(jq -r .width <<<"$out")"; exit 1; }
target20="$repo20/.claude/cfq/changelog.yml"
grep -qxF '  batch: 09999-2026-08-01-a' "$target20" || { echo "FAIL: 4->5 changelog batch was not repadded"; exit 1; }
[ -d "$repo20/.claude/cfq/impl/done/09999-2026-08-01-a" ] || { echo "FAIL: 4->5 done dir was not renamed"; exit 1; }
out2="$(bash "$bi" allocate "$repo20" 2026-08-19 next-after-5)"
[ "$(jq -r .batch <<<"$out2")" = "10000-2026-08-19-next-after-5" ] || { echo "FAIL: 4->5 allocate after migration = $(jq -r .batch <<<"$out2")"; exit 1; }

# simulated destination collision -> fail before any rename
repo21="$tmp/repo21"; mkdir -p "$repo21/.claude/cfq/impl/done/0999-2026-08-01-a"
bash "$cl" reserve "$repo21" 999 999-2026-08-01-a
before_cl21="$(cat "$repo21/.claude/cfq/changelog.yml")"
out="$(bash "$bi" allocate "$repo21" 2026-08-19 collide)" && { echo "FAIL: collision allocate exited 0"; exit 1; }
[ "$(status "$out")" = "BATCH_WIDTH_MIGRATION_COLLISION" ] || { echo "FAIL: collision status = $(status "$out")"; exit 1; }
after_cl21="$(cat "$repo21/.claude/cfq/changelog.yml")"
[ "$before_cl21" = "$after_cl21" ] || { echo "FAIL: collision mutated the changelog"; exit 1; }
[ ! -e "$repo21/.claude/cfq/impl/done/999-2026-08-01-a" ] || { echo "FAIL: collision unexpectedly created a 999 done dir"; exit 1; }
[ -d "$repo21/.claude/cfq/impl/done/0999-2026-08-01-a" ] || { echo "FAIL: collision removed the pre-existing destination"; exit 1; }

# simulated interrupted migration (one entry already at the new width, one still at the old one)
# recovers deterministically: the already-migrated entry is left alone, the other catches up
repo22="$tmp/repo22"; mkdir -p "$repo22"
bash "$cl" reserve "$repo22" 1 0001-2026-08-01-a
bash "$cl" reserve "$repo22" 2 002-2026-08-02-b
mkdir -p "$repo22/.claude/cfq/impl/done/0001-2026-08-01-a" "$repo22/.claude/cfq/impl/done/002-2026-08-02-b"
out="$(bash "$bi" migrate-width "$repo22")"
[ "$(status "$out")" = "OK" ] || { echo "FAIL: interrupted-recovery migrate-width status = $(status "$out")"; exit 1; }
target22="$repo22/.claude/cfq/changelog.yml"
grep -qxF '  batch: 0002-2026-08-02-b' "$target22" || { echo "FAIL: interrupted-recovery did not repad the still-old entry"; exit 1; }
grep -qxF '  batch: 0001-2026-08-01-a' "$target22" || { echo "FAIL: interrupted-recovery lost the already-migrated entry"; exit 1; }
[ -d "$repo22/.claude/cfq/impl/done/0002-2026-08-02-b" ] || { echo "FAIL: interrupted-recovery did not rename the still-old done dir"; exit 1; }
[ -d "$repo22/.claude/cfq/impl/done/0001-2026-08-01-a" ] || { echo "FAIL: interrupted-recovery lost the already-migrated done dir"; exit 1; }

# width migration never touches Git: no history rewrite, no branch/version scanning
grep -qE '(^|[^A-Za-z])git([^A-Za-z]|$)' "$repo_root/scripts/cfq-batch-id.sh" && { echo "FAIL: cfq-batch-id.sh performs Git operations (width migration must never touch Git)"; exit 1; }

echo PASS
