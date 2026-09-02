#!/usr/bin/env bash
# Static regression guards for the numbered-batch-identity model (docs/schema/interface level).
# Behavioral coverage for allocation, width migration and trailer rendering already lives in
# test-batch-id.sh, test-changelog.sh, test-branch.sh and test-layout.sh -- this file only guards
# against the four regressions Phase 5 exists to prevent: reintroduced version semantics,
# alphabetical-sort bugs, a second CFQ-imposed Git policy, and opaque/incomplete commit metadata.
# No framework, no fixtures -- just `bash tests/test-batch-identity.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scripts="$repo_root/scripts"
skills="$repo_root/skills"

fail() { echo "FAIL: $1"; exit 1; }

# --- no version-detection surface was reintroduced ---

[ ! -e "$scripts/cfq-version.sh" ] || fail "cfq-version.sh exists -- CFQ must not resolve application/plugin versions"

grep -qE '"(versionSource|appVersion|cfqVersion|versionDrift|batchSeq)":' "$scripts/cfq-settings.sh" \
  && fail "cfq-settings.sh schema defines a version-identity setting key" || true

# --- changelog entries never carry a version-shaped field ---

grep -qE "printf.*'  (version|appVersion|cfqVersion|versionSource): " "$scripts/cfq-changelog.sh" \
  && fail "cfq-changelog.sh renders a version-shaped changelog field" || true

# --- no second, ad-hoc branch-version-increment mechanism ---

grep -qE 'v\[0-9\]' "$scripts/cfq-branch.sh" \
  && fail "cfq-branch.sh still contains vX.Y-style version-increment matching" || true

# --- settings.json is never swept into the default local-state exclusion ---

grep -A10 'BLOCK_ENTRIES=(' "$scripts/cfq-layout.sh" | grep -qF 'settings.json' \
  && fail "cfq-layout.sh's managed exclude block includes settings.json" || true

# --- gitStatePolicy stays the single Git-state switch ---

grep -rlqE 'GIT_STATE_POLICY|GITPOLICY' "$scripts" \
  && fail "a second Git-state-policy mechanism exists alongside gitStatePolicy" || true

# --- history-wide trailer scans key off CFQ-Batch-Number only, never the padded CFQ-Batch value ---

while IFS= read -r line; do
  case "$line" in
    *--all*"trailers:key=CFQ-Batch,"*) fail "a history-wide scan keys off CFQ-Batch (human context) instead of CFQ-Batch-Number: $line" ;;
  esac
done < <(grep -n -- '--all' "$scripts/cfq-changelog.sh")

# --- every numbered phase commit gets the complete, required trailer set ---

trailer_block="$(awk '/interpret-trailers/{f=1} f{print} f&&/message_file"/{exit}' "$scripts/cfq-changelog.sh")"
for t in CFQ-Batch-Number CFQ-Batch CFQ-Phase CFQ-Phase-Status; do
  printf '%s\n' "$trailer_block" | grep -qF -- "--trailer \"$t=" \
    || fail "commit-message trailer rendering is missing $t"
done

# --- PFQ never hand-rolls batch-number padding/max arithmetic; it always calls the helper ---

grep -q 'bin/cfq" batch allocate' "$skills/plan-for-queue/SKILL.md" \
  || fail "plan-for-queue/SKILL.md no longer calls bin/cfq batch allocate"
grep -rqE "printf '%0[0-9]+d'|printf \"%0[0-9]+d\"" "$skills/plan-for-queue" \
  && fail "plan-for-queue hand-rolls zero-padding instead of delegating to the batch noun" || true

# --- fixed-width numbered names sort lexicographically in numeric order, by construction ---

sorted="$(printf '%s\n' 100-x 001-x 999-x 010-x | sort)"
expected="001-x
010-x
100-x
999-x"
[ "$sorted" = "$expected" ] || fail "fixed-width numbered identifiers do not sort in numeric order"

echo PASS
