#!/usr/bin/env bash
# Self-test for scripts/cfq-runtime.sh. No framework, no fixtures directory — builds throwaway
# ~/.claude/.ctx/<sid>.json and ~/.claude/projects/<slug>/<sid>.jsonl files under a fresh $HOME
# per assertion group.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_sh="$repo_root/scripts/cfq-runtime.sh"

sid="sid1"
export CLAUDE_CODE_SESSION_ID="$sid"
slug="$(pwd | tr '/' '-')"

new_home() {
  local h; h=$(mktemp -d)
  mkdir -p "$h/.claude/.ctx" "$h/.claude/projects/$slug"
  printf '%s' "$h"
}

write_payload() {
  # $1: HOME, $2: raw payload content
  printf '%s' "$2" > "$1/.claude/.ctx/$sid.json"
}

write_transcript() {
  # $1: HOME, $2: model, $3: input, $4: cacheRead, $5: cacheCreate, $6: version, $7: usable(1/0)
  local h="$1" model="$2" input="$3" cr="$4" cc="$5" version="$6" usable="${7:-1}"
  local usage
  if [ "$usable" = "1" ]; then
    usage="{\"input_tokens\":$input,\"cache_read_input_tokens\":$cr,\"cache_creation_input_tokens\":$cc}"
  else
    usage="{}"
  fi
  printf '{"type":"assistant","isSidechain":false,"message":{"model":"%s","usage":%s},"version":"%s"}\n' \
    "$model" "$usage" "$version" > "$h/.claude/projects/$slug/$sid.jsonl"
}

fail() { echo "FAIL: $1"; exit 1; }

# 1. Valid statusline payload -> source: payload, correct pct
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":21,"context_window_size":200000,"current_usage":{"input":1,"creation":1,"read":1}}}'
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "ok" ] || fail "1 status: $out"
[ "$(jq -r '.source' <<<"$out")" = "payload" ] || fail "1 source: $out"
[ "$(jq -r '.pct' <<<"$out")" = "21" ] || fail "1 pct: $out"
rm -rf "$h"

# 2. Payload missing used_percentage but has current_usage.* -> computed correctly
h=$(new_home)
write_payload "$h" '{"context_window":{"context_window_size":200000,"current_usage":{"input":20000,"creation":10000,"read":12000}}}'
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.source' <<<"$out")" = "payload" ] || fail "2 source: $out"
[ "$(jq -r '.pct' <<<"$out")" = "21" ] || fail "2 pct: $out"
[ "$(jq -r '.used' <<<"$out")" = "42000" ] || fail "2 used: $out"
rm -rf "$h"

# 3. Payload present but stale (mtime >=600s) -> falls through to transcript
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":99,"context_window_size":200000,"current_usage":{"input":1,"creation":1,"read":1}}}'
touch -d '-700 seconds' "$h/.claude/.ctx/$sid.json"
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "ok" ] || fail "3 status: $out"
[ "$(jq -r '.source' <<<"$out")" = "transcript" ] || fail "3 source (stale must fall through): $out"
[ "$(jq -r '.code' <<<"$out")" = "null" ] || fail "3 code (staleness is not structural): $out"
rm -rf "$h"

# 4. Malformed payload JSON + healthy transcript fallback -> degraded, RUNTIME_PAYLOAD_INVALID
h=$(new_home)
write_payload "$h" 'not json'
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "degraded" ] || fail "4 status: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_PAYLOAD_INVALID" ] || fail "4 code: $out"
[ "$(jq -r '.pct' <<<"$out")" != "null" ] || fail "4 pct should be usable: $out"
[ "$(jq -r '.diagnostic.repairScope' <<<"$out")" = "cfq-runtime.sh" ] || fail "4 diagnostic.repairScope: $out"
rm -rf "$h"

# 5. Fresh valid payload, documented shape missing + healthy transcript fallback -> degraded,
# RUNTIME_SCHEMA_MISMATCH
h=$(new_home)
write_payload "$h" '{"foo":"bar"}'
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "degraded" ] || fail "5 status: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_SCHEMA_MISMATCH" ] || fail "5 code: $out"
[ "$(jq -r '.diagnostic.repairScope' <<<"$out")" = "cfq-runtime.sh" ] || fail "5 repairScope: $out"
[ -n "$(jq -r '.diagnostic.researchHint' <<<"$out")" ] || fail "5 researchHint empty: $out"
rm -rf "$h"

# 6. Missing/stale/not-yet-populated statusline + healthy transcript fallback -> usable pct,
# no false schema-mismatch classification
h=$(new_home)  # no payload file at all
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "ok" ] || fail "6a status: $out"
[ "$(jq -r '.code' <<<"$out")" = "null" ] || fail "6a code: $out"
rm -rf "$h"

h=$(new_home)
write_payload "$h" '{"context_window":{"context_window_size":0}}'
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "ok" ] || fail "6b status: $out"
[ "$(jq -r '.code' <<<"$out")" = "null" ] || fail "6b code: $out"
rm -rf "$h"

# 7. context_window_size <= 0 in payload -> falls through (already covered by 6b; also assert
# the select()-filtered value never leaks into the result)
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":50,"context_window_size":-1}}'
write_transcript "$h" claude-sonnet-5 40000 1000 1000 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.source' <<<"$out")" = "transcript" ] || fail "7 source: $out"
rm -rf "$h"

# 8. No .ctx payload and no transcript at all, no structural primary failure -> unavailable,
# pct:null, RUNTIME_SOURCE_MISSING
h=$(new_home)
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "unavailable" ] || fail "8 status: $out"
[ "$(jq -r '.pct' <<<"$out")" = "null" ] || fail "8 pct: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_SOURCE_MISSING" ] || fail "8 code: $out"
rm -rf "$h"

# 9. Transcript present, no usable usage fields, no structural primary failure -> unavailable,
# pct:null, FALLBACK_FAILED
h=$(new_home)
write_transcript "$h" claude-sonnet-5 0 0 0 2.1.0 0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "unavailable" ] || fail "9 status: $out"
[ "$(jq -r '.pct' <<<"$out")" = "null" ] || fail "9 pct: $out"
[ "$(jq -r '.code' <<<"$out")" = "FALLBACK_FAILED" ] || fail "9 code: $out"
rm -rf "$h"

# 10. Fresh payload schema mismatch + missing transcript -> unavailable, top-level code stays the
# primary code, diagnostic carries the fallback code/status. Same for RUNTIME_PAYLOAD_INVALID.
h=$(new_home)
write_payload "$h" '{"foo":"bar"}'
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "unavailable" ] || fail "10a status: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_SCHEMA_MISMATCH" ] || fail "10a code: $out"
[ "$(jq -r '.diagnostic.fallbackCode' <<<"$out")" = "RUNTIME_SOURCE_MISSING" ] || fail "10a fallbackCode: $out"
rm -rf "$h"

h=$(new_home)
write_payload "$h" 'not json'
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "unavailable" ] || fail "10b status: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_PAYLOAD_INVALID" ] || fail "10b code: $out"
[ "$(jq -r '.diagnostic.fallbackCode' <<<"$out")" = "RUNTIME_SOURCE_MISSING" ] || fail "10b fallbackCode: $out"
rm -rf "$h"

h=$(new_home)
write_payload "$h" '{"foo":"bar"}'
write_transcript "$h" claude-sonnet-5 0 0 0 2.1.0 0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "unavailable" ] || fail "10c status: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_SCHEMA_MISMATCH" ] || fail "10c code: $out"
[ "$(jq -r '.diagnostic.fallbackCode' <<<"$out")" = "FALLBACK_FAILED" ] || fail "10c fallbackCode: $out"
rm -rf "$h"

# 11. CFQ_CTX_TEST_PCT short-circuits before touching payload/transcript
h=$(new_home)  # no payload, no transcript at all
out=$(HOME="$h" CFQ_CTX_TEST_PCT=33 bash "$runtime_sh" context)
[ "$(jq -r '.status' <<<"$out")" = "ok" ] || fail "11 status: $out"
[ "$(jq -r '.source' <<<"$out")" = "test-override" ] || fail "11 source: $out"
[ "$(jq -r '.pct' <<<"$out")" = "33" ] || fail "11 pct: $out"
rm -rf "$h"

# 12. Model -> context-window size lookup, CFQ_CTX_LIMIT override
h=$(new_home)
write_transcript "$h" claude-opus-5 10000 0 0 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.windowSize' <<<"$out")" = "1000000" ] || fail "12a large-model windowSize: $out"
rm -rf "$h"

h=$(new_home)
write_transcript "$h" claude-unknown-model 10000 0 0 2.1.0
out=$(HOME="$h" bash "$runtime_sh" context)
[ "$(jq -r '.windowSize' <<<"$out")" = "200000" ] || fail "12b default windowSize: $out"
out=$(HOME="$h" CFQ_CTX_LIMIT=555555 bash "$runtime_sh" context)
[ "$(jq -r '.windowSize' <<<"$out")" = "555555" ] || fail "12c CFQ_CTX_LIMIT override: $out"
rm -rf "$h"

# 13. version reads .version from the last transcript line
h=$(new_home)
write_transcript "$h" claude-sonnet-5 10000 0 0 9.9.9
out=$(HOME="$h" bash "$runtime_sh" version)
[ "$out" = '"9.9.9"' ] || fail "13 version: $out"
rm -rf "$h"

# 14. jq unavailable -> DEPENDENCY_MISSING, exit 1, on every subcommand
nojq_dir=$(mktemp -d)
for b in bash git head ls date stat printf mkdir tr pwd sed grep cat dirname mv rm; do
  p=$(command -v "$b" 2>/dev/null) && ln -sf "$p" "$nojq_dir/"
done
nojq_home=$(mktemp -d)
for sub in session-id transcript-path context model version capabilities diagnose; do
  set +e
  out=$(PATH="$nojq_dir" HOME="$nojq_home" bash "$runtime_sh" "$sub" 2>&1)
  rc=$?
  set -e
  [ "$rc" -eq 1 ] || fail "14 $sub exit=$rc (want 1): $out"
  [[ "$out" == *DEPENDENCY_MISSING* ]] || fail "14 $sub message: $out"
done
rm -rf "$nojq_home"

# 15. diagnose always returns well-formed JSON, even total failure
h=$(new_home)
out=$(HOME="$h" bash "$runtime_sh" diagnose)
[ "$(jq -r '.sources | length' <<<"$out")" -ge 3 ] || fail "15 sources: $out"
[ "$(jq -e '.result' <<<"$out" >/dev/null; echo $?)" = "0" ] || fail "15 result missing: $out"
[ "$(jq -r '.code' <<<"$out")" = "RUNTIME_SOURCE_MISSING" ] || fail "15 code: $out"
rm -rf "$h"

# 16. transcript-path pwd-slug vs --repo path-slug
h=$(mktemp -d)
mkdir -p "$h/.claude/projects/$slug"
echo '{}' > "$h/.claude/projects/$slug/$sid.jsonl"
otherrepo=$(mktemp -d)
otherslug="$(printf '%s' "$otherrepo" | tr '/' '-')"
mkdir -p "$h/.claude/projects/$otherslug"
echo '{}' > "$h/.claude/projects/$otherslug/$sid.jsonl"

out=$(HOME="$h" bash "$runtime_sh" transcript-path)
[ "$out" = "$h/.claude/projects/$slug/$sid.jsonl" ] || fail "16a pwd-slug: $out"
out=$(HOME="$h" bash "$runtime_sh" transcript-path --repo "$otherrepo")
[ "$out" = "$h/.claude/projects/$otherslug/$sid.jsonl" ] || fail "16b repo-slug: $out"
rm -rf "$h" "$otherrepo"

echo PASS
