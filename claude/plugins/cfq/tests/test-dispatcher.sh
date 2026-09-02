#!/usr/bin/env bash
# Self-test for bin/cfq, the single entrypoint. The 21 scripts under scripts/ stay directly
# callable and unchanged (every other test-*.sh here still calls them that way) — this file only
# asserts the dispatcher routes to them correctly, one behaviour per case, all in one run.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cfq_bin="$repo_root/bin/cfq"
scripts_dir="$repo_root/scripts"

fixture_repo() {
  local d; d=$(mktemp -d)
  (cd "$d" && git init -q)
  printf '%s' "$d"
}

# 1. Routine: byte-identical stdout through the dispatcher and the direct script call, across
#    three different output shapes (JSON array, JSON object, plain text).
repo1=$(fixture_repo)
a=$("$cfq_bin" settings list --repo "$repo1" 2>&1)
b=$(bash "$scripts_dir/cfq-settings.sh" list --repo "$repo1" 2>&1)
[ "$a" = "$b" ] || { echo "FAIL: settings list differs between dispatcher and direct call"; exit 1; }

home1=$(mktemp -d)
a=$(HOME="$home1" CFQ_SCAN_ROOTS=/nonexistent-scan-root "$cfq_bin" scan 2>&1)
b=$(HOME="$home1" CFQ_SCAN_ROOTS=/nonexistent-scan-root bash "$scripts_dir/cfq-scan.sh" 2>&1)
[ "$a" = "$b" ] || { echo "FAIL: scan differs between dispatcher and direct call"; exit 1; }

home2=$(mktemp -d)
a=$(HOME="$home2" "$cfq_bin" doctor check 2>&1)
b=$(HOME="$home2" bash "$scripts_dir/cfq-doctor.sh" check 2>&1)
[ "$a" = "$b" ] || { echo "FAIL: doctor check differs between dispatcher and direct call"; exit 1; }

# 2. Argument passthrough: a value containing a space and a literal $ survives unmangled.
repo2=$(fixture_repo)
tricky='a value with a space and a $dollar sign'
"$cfq_bin" settings set --repo "$repo2" changelogFile "$tricky" >/dev/null
got=$("$cfq_bin" settings get --repo "$repo2" changelogFile)
[ "$got" = "$tricky" ] || { echo "FAIL: argument passthrough mangled the value: got '$got'"; exit 1; }

# 3. Exit codes: the underlying script's exit status propagates, not some dispatcher-invented one.
set +e
"$cfq_bin" batch allocate /no-such-repo-path 2>/dev/null
rc_dispatcher=$?
bash "$scripts_dir/cfq-batch-id.sh" allocate /no-such-repo-path >/dev/null 2>&1
rc_direct=$?
set -e
[ "$rc_dispatcher" -ne 0 ] || { echo "FAIL: dispatcher exit 0 on a failing subcommand"; exit 1; }
[ "$rc_dispatcher" = "$rc_direct" ] || { echo "FAIL: dispatcher exit ($rc_dispatcher) != direct exit ($rc_direct)"; exit 1; }

# 4. Edge - unknown noun: non-zero exit, noun list on stderr.
set +e
out=$("$cfq_bin" nosuchthing 2>&1 >/dev/null)
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: unknown noun exited 0"; exit 1; }
echo "$out" | grep -q 'nouns:' || { echo "FAIL: unknown noun did not print the noun list to stderr"; exit 1; }

# 5. Edge - no arguments: prints the noun list, exits non-zero (nothing is a sensible default).
set +e
out=$("$cfq_bin" 2>&1 >/dev/null)
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: no-args invocation exited 0"; exit 1; }
echo "$out" | grep -q 'nouns:' || { echo "FAIL: no-args invocation did not print the noun list"; exit 1; }

# 6. Fallback: `cfq --help` names every noun, `cfq <noun> --help` names that noun's verbs.
out=$("$cfq_bin" --help 2>&1)
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: cfq --help exit = $rc"; exit 1; }
echo "$out" | grep -q ' settings ' || { echo "FAIL: cfq --help does not name the settings noun"; exit 1; }

out=$("$cfq_bin" settings --help 2>&1)
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: cfq settings --help exit = $rc"; exit 1; }
echo "$out" | grep -qi 'list' || { echo "FAIL: cfq settings --help does not name its verbs"; exit 1; }

out=$("$cfq_bin" batch --help 2>&1)
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: cfq batch --help exit = $rc"; exit 1; }
echo "$out" | grep -qi 'allocate\|next' || { echo "FAIL: cfq batch --help (fallback path) does not name its verbs"; exit 1; }

# 7. Completeness: every scripts/*.sh except cfq-paths.sh (sourced, not run) is reachable through
#    exactly one noun. Extracted straight from bin/cfq's own table, not retyped here, so this stays
#    a structural check rather than a copy that can silently drift from the real map.
mapped=$(grep -oE '^\s*\[[a-z-]+\]=cfq-[a-z-]+\.sh$|^\s*\[[a-z-]+\]=ctx-usage\.sh$' "$cfq_bin" \
  | sed -E 's/^\s*\[[a-z-]+\]=//' | sort -u)
on_disk=$(cd "$scripts_dir" && ls *.sh | grep -v '^cfq-paths\.sh$' | sort -u)
[ "$mapped" = "$on_disk" ] || {
  echo "FAIL: dispatcher routing table and scripts/*.sh (minus cfq-paths.sh) disagree"
  diff <(echo "$on_disk") <(echo "$mapped")
  exit 1
}
# Exactly one noun per script (no script mapped twice).
dupe=$(grep -oE '^\s*\[[a-z-]+\]=cfq-[a-z-]+\.sh$|^\s*\[[a-z-]+\]=ctx-usage\.sh$' "$cfq_bin" \
  | sed -E 's/^\s*\[[a-z-]+\]=//' | sort | uniq -d)
[ -z "$dupe" ] || { echo "FAIL: script(s) mapped by more than one noun: $dupe"; exit 1; }

echo PASS
