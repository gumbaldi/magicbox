#!/usr/bin/env bash
set -eu
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ctx="$repo_root/scripts/ctx-usage.sh"

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

home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT

# routine: used under stopUsed -> START/OK
out=$(HOME="$home" CFQ_CTX_TEST_USED=50000 CFQ_STOP_USED=100000 bash "$ctx" gate S)
[[ "$out" == *"USED=50000"*"SIZE=S"*"LIMIT=100000"*START* ]] || { echo "FAIL: under limit gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=50000 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=50000 OK (test override)" ] || { echo "FAIL: under limit no-arg -> $out"; exit 1; }

# boundary: exactly at stopUsed -> HANDOFF/STOP (>=, not >); note now names the fired reason
out=$(HOME="$home" CFQ_CTX_TEST_USED=100000 CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *"USED=100000"*HANDOFF* ]] || { echo "FAIL: boundary gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=100000 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=100000 STOP (test override, used 100000 >= 100000)" ] || { echo "FAIL: boundary no-arg -> $out"; exit 1; }

# one token over -> HANDOFF/STOP
out=$(HOME="$home" CFQ_CTX_TEST_USED=100001 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=100001 STOP (test override, used 100001 >= 100000)" ] || { echo "FAIL: over limit -> $out"; exit 1; }

# custom stopUsed
out=$(HOME="$home" CFQ_CTX_TEST_USED=19999 CFQ_STOP_USED=20000 bash "$ctx" gate L)
[[ "$out" == *"USED=19999"*"LIMIT=20000"*START* ]] || { echo "FAIL: custom limit start -> $out"; exit 1; }

# special value: stopUsed=0 -> gate always START (pre-phase bypass); no-arg always STOP
out=$(HOME="$home" CFQ_STOP_USED=0 bash "$ctx" gate S)
[[ "$out" == *"LIMIT=0"*START* ]] || { echo "FAIL: stopUsed=0 gate bypass -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=0 bash "$ctx")
[ "$out" = "USED=1 STOP (test override, used 1 >= 0)" ] || { echo "FAIL: stopUsed=0 no-arg always stop -> $out"; exit 1; }

# special value: stopUsed=-1 -> never stop for capacity, gate and no-arg both, even with a huge used
out=$(HOME="$home" CFQ_CTX_TEST_USED=99999999 CFQ_STOP_USED=-1 bash "$ctx" gate L)
[[ "$out" == *"LIMIT=-1"*START* ]] || { echo "FAIL: stopUsed=-1 gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=99999999 CFQ_STOP_USED=-1 bash "$ctx")
[[ "$out" == *OK* ]] || { echo "FAIL: stopUsed=-1 no-arg -> $out"; exit 1; }

# malformed/missing size still defaults to M (passthrough only, no effect on the decision)
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=100000 bash "$ctx" gate XL)
[[ "$out" == *"SIZE=M"* ]] || { echo "FAIL: malformed size -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=100000 bash "$ctx" gate)
[[ "$out" == *"SIZE=M"* ]] || { echo "FAIL: missing size -> $out"; exit 1; }

# unknown used (throwaway HOME, no transcript/session, no override) -> conservative HANDOFF/UNKNOWN
tmp_home=$(mktemp -d)
out=$(HOME="$tmp_home" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *"USED=?"*HANDOFF* ]] || { echo "FAIL: unknown used gate -> $out"; exit 1; }
out=$(HOME="$tmp_home" CFQ_STOP_USED=100000 bash "$ctx")
[[ "$out" == *"USED=?"*UNKNOWN* ]] || { echo "FAIL: unknown used no-arg -> $out"; exit 1; }
rm -rf "$tmp_home"

# malformed CFQ_STOP_USED env falls back to the schema default (100000)
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=abc bash "$ctx")
[ "$out" = "USED=1 OK (test override)" ] || { echo "FAIL: malformed stopUsed env fallback -> $out"; exit 1; }

# --- rate limits: written-payload fixtures, since CFQ_CTX_TEST_USED bypasses the payload entirely
# and rate limits have no such override. write_payload/new_home carried over from test-runtime.sh.

# five-hour over threshold, context far below stopUsed -> HANDOFF, note names 5h
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":1000,"cache_creation_input_tokens":1000,"cache_read_input_tokens":1000}},"rate_limits":{"five_hour":{"used_percentage":80},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *HANDOFF* ]] || { echo "FAIL: rate 5h over -> decision: $out"; exit 1; }
[[ "$out" == *"5h 80% >= 70"* ]] || { echo "FAIL: rate 5h over -> reason: $out"; exit 1; }
rm -rf "$h"

# seven-day over threshold, five-hour fine -> HANDOFF, note names 7d
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":1000,"cache_creation_input_tokens":1000,"cache_read_input_tokens":1000}},"rate_limits":{"five_hour":{"used_percentage":10},"seven_day":{"used_percentage":97}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *HANDOFF* ]] || { echo "FAIL: rate 7d over -> decision: $out"; exit 1; }
[[ "$out" == *"7d 97% >= 95"* ]] || { echo "FAIL: rate 7d over -> reason: $out"; exit 1; }
rm -rf "$h"

# both rate limits below threshold, context over stopUsed -> HANDOFF, note names used
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":50,"context_window_size":1000000,"current_usage":{"input_tokens":60000,"cache_creation_input_tokens":30000,"cache_read_input_tokens":20000}},"rate_limits":{"five_hour":{"used_percentage":10},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *HANDOFF* ]] || { echo "FAIL: capacity over -> decision: $out"; exit 1; }
[[ "$out" == *"used 110000 >= 100000"* ]] || { echo "FAIL: capacity over -> reason: $out"; exit 1; }
rm -rf "$h"

# rateLimits absent from the payload -> decision identical to today's context-only behaviour, no
# 5h/7d segment in the note
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":50,"context_window_size":1000000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":10000,"cache_read_input_tokens":10000}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *START* ]] || { echo "FAIL: no rate_limits -> decision: $out"; exit 1; }
[[ "$out" != *"5h"* ]] || { echo "FAIL: no rate_limits -> unexpected 5h segment: $out"; exit 1; }
[[ "$out" != *"7d"* ]] || { echo "FAIL: no rate_limits -> unexpected 7d segment: $out"; exit 1; }
rm -rf "$h"

# stopFiveHourPct: -1 with a five-hour value of 99 -> START (seven-day stays under its own threshold)
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":1000,"cache_creation_input_tokens":1000,"cache_read_input_tokens":1000}},"rate_limits":{"five_hour":{"used_percentage":99},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 CFQ_STOP_FIVE_HOUR_PCT=-1 bash "$ctx" gate M)
[[ "$out" == *START* ]] || { echo "FAIL: stopFiveHourPct=-1 -> decision: $out"; exit 1; }
rm -rf "$h"

# stopUsed: -1 with a five-hour value over threshold -> HANDOFF (the regression this phase's
# short-circuit rewrite exists for -- stopUsed=-1 alone must not silently disable the rate check)
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":1000,"cache_creation_input_tokens":1000,"cache_read_input_tokens":1000}},"rate_limits":{"five_hour":{"used_percentage":80},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=-1 bash "$ctx" gate M)
[[ "$out" == *"LIMIT=-1"* ]] || { echo "FAIL: stopUsed=-1 regression -> limit: $out"; exit 1; }
[[ "$out" == *HANDOFF* ]] || { echo "FAIL: stopUsed=-1 regression -> decision: $out"; exit 1; }
[[ "$out" == *"5h 80% >= 70"* ]] || { echo "FAIL: stopUsed=-1 regression -> reason: $out"; exit 1; }
rm -rf "$h"

# all three at -1 -> START without resolving anything (no payload/transcript needed)
out=$(HOME="$home" CFQ_STOP_USED=-1 CFQ_STOP_FIVE_HOUR_PCT=-1 CFQ_STOP_SEVEN_DAY_PCT=-1 bash "$ctx" gate M)
[[ "$out" == *"LIMIT=-1"*START* ]] || { echo "FAIL: all disabled gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_STOP_USED=-1 CFQ_STOP_FIVE_HOUR_PCT=-1 CFQ_STOP_SEVEN_DAY_PCT=-1 bash "$ctx")
[[ "$out" == *OK* ]] || { echo "FAIL: all disabled no-arg -> $out"; exit 1; }

# stopUsed: 0 gate bypass with a five-hour value over threshold -> HANDOFF, not the bypass (a
# rate-limit stop always wins over the capacity bypass)
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":1000,"cache_creation_input_tokens":1000,"cache_read_input_tokens":1000}},"rate_limits":{"five_hour":{"used_percentage":80},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=0 bash "$ctx" gate M)
[[ "$out" == *HANDOFF* ]] || { echo "FAIL: stopUsed=0 rate override -> decision: $out"; exit 1; }
[[ "$out" == *"5h 80% >= 70"* ]] || { echo "FAIL: stopUsed=0 rate override -> reason: $out"; exit 1; }
rm -rf "$h"

# cache share is display-only and appears even on a START decision
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":1,"context_window_size":1000000,"current_usage":{"input_tokens":2,"cache_creation_input_tokens":298,"cache_read_input_tokens":9700}},"rate_limits":{"five_hour":{"used_percentage":28},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *START* ]] || { echo "FAIL: cache display -> decision: $out"; exit 1; }
[[ "$out" == *"cache 97%"* ]] || { echo "FAIL: cache display -> cache pct: $out"; exit 1; }
[[ "$out" == *"5h 28%"* ]] || { echo "FAIL: cache display -> 5h pct: $out"; exit 1; }
[[ "$out" == *"7d 10%"* ]] || { echo "FAIL: cache display -> 7d pct: $out"; exit 1; }
rm -rf "$h"

# the emitted gate line matches cfq-ifq-preflight.sh's capture regex -- same jq capture(...)
# expression, copied from that script, so the two cannot drift
h=$(new_home)
write_payload "$h" '{"context_window":{"used_percentage":19,"context_window_size":1000000,"current_usage":{"input_tokens":2,"cache_creation_input_tokens":4000,"cache_read_input_tokens":180000}},"rate_limits":{"five_hour":{"used_percentage":28},"seven_day":{"used_percentage":10}}}'
out=$(HOME="$h" CFQ_STOP_USED=100000 bash "$ctx" gate M)
parsed=$(jq -cn --arg l "$out" '
  try ($l | capture("^USED=(?<used>[^ ]+) SIZE=(?<size>[A-Z]) LIMIT=(?<limit>-?[0-9]+) (?<verdict>START|HANDOFF) \\((?<note>.*)\\)$"))
  catch null')
[ "$parsed" != "null" ] || { echo "FAIL: gate line failed preflight capture regex -> $out"; exit 1; }
rm -rf "$h"

echo PASS
